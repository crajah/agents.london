"""Web search, through the router's grounding.

The Custom Search route closed: Google withdrew "search the entire web" for new
Programmable Search engines on 20 January 2026 and ends it for existing ones on
1 January 2027. These hold the replacement to the same standard the old one was
held to — above all, that it never returns something it did not obtain.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

import app as tool_app


def grounded(summary, citations):
    return {"choices": [{"message": {
        "content": summary,
        "annotations": [{"type": "url_citation", "url_citation": c}
                        for c in citations]}}]}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, url=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.url = url
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def router(monkeypatch):
    """Stand in for the model router and for redirect resolution."""
    state = {"body": None, "reply": None, "resolve": {}}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            state["body"] = json
            reply = state["reply"]
            if isinstance(reply, Exception):
                raise reply
            return reply

        async def head(self, url, follow_redirects=True, timeout=None):
            if url in state["resolve"]:
                return FakeResponse(url=state["resolve"][url])
            raise httpx.ConnectError("cannot resolve")

    monkeypatch.setattr(tool_app.httpx, "AsyncClient", FakeClient)
    return state


async def test_a_search_returns_its_sources(router, monkeypatch):
    monkeypatch.setattr(tool_app, "RESOLVE_CITATIONS", False)
    router["reply"] = FakeResponse(200, grounded(
        "Reykjavik has 139,804 residents as of January 2026.",
        [{"title": "hagstofa.is", "url": "https://redirect/abc",
          "start_index": 0, "end_index": 51}]))

    out = await tool_app.execute_web_search(
        tool_app.WebSearchRequest(query="population of Reykjavik"))

    assert out["status"] == "success"
    assert out["source"] == "gemini_search_grounding"
    assert out["count"] == 1
    assert out["results"][0]["title"] == "hagstofa.is"
    # The snippet is the span this source actually supports, not a slice of
    # the answer taken from somewhere else.
    assert out["results"][0]["snippet"] == "Reykjavik has 139,804 residents as of January 2026."


async def test_the_grounding_tool_is_actually_requested(router, monkeypatch):
    monkeypatch.setattr(tool_app, "RESOLVE_CITATIONS", False)
    router["reply"] = FakeResponse(200, grounded(
        "x", [{"title": "t", "url": "https://redirect/1"}]))

    await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    # Without this the model answers from training data, which is the one thing
    # a search tool must never silently do.
    assert router["body"]["tools"] == [{"googleSearch": {}}]


async def test_an_answer_with_no_sources_is_not_a_search_result(router):
    """The failure that matters: the model answering from memory."""
    router["reply"] = FakeResponse(200, {"choices": [{"message": {
        "content": "I believe the population is around 140,000.",
        "annotations": []}}]})

    with pytest.raises(HTTPException) as raised:
        await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    assert raised.value.status_code == 502
    assert "no sources" in raised.value.detail
    assert "not a search result" in raised.value.detail


async def test_an_unreachable_router_raises_rather_than_inventing(router):
    router["reply"] = httpx.ConnectError("router down")

    with pytest.raises(HTTPException) as raised:
        await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    assert raised.value.status_code == 502
    assert "unreachable" in raised.value.detail


async def test_an_upstream_error_is_reported(router):
    router["reply"] = FakeResponse(429, {"error": "rate limited"})

    with pytest.raises(HTTPException) as raised:
        await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    assert raised.value.status_code == 502
    assert "429" in raised.value.detail


async def test_disabling_search_is_reported_as_disabled(router, monkeypatch):
    monkeypatch.setattr(tool_app, "WEB_SEARCH_MODEL", "")

    with pytest.raises(HTTPException) as raised:
        await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    assert raised.value.status_code == 503
    assert "disabled" in raised.value.detail


async def test_a_redirect_is_resolved_to_where_the_claim_came_from(router, monkeypatch):
    """A citation that records where Google sent you is not a citation."""
    monkeypatch.setattr(tool_app, "RESOLVE_CITATIONS", True)
    router["resolve"] = {"https://vertexaisearch.example/redirect/xyz":
                         "https://hagstofa.is/statistics/population"}
    router["reply"] = FakeResponse(200, grounded(
        "A claim.", [{"title": "hagstofa.is",
                      "url": "https://vertexaisearch.example/redirect/xyz"}]))

    out = await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    assert out["results"][0]["link"] == "https://hagstofa.is/statistics/population"
    # The opaque original is kept, so the resolution can be audited.
    assert out["results"][0]["redirect"] == "https://vertexaisearch.example/redirect/xyz"
    assert out["citations_resolved"] is True


async def test_an_unresolvable_redirect_is_kept_not_dropped(router, monkeypatch):
    """An opaque link is worse than a real one and better than none."""
    monkeypatch.setattr(tool_app, "RESOLVE_CITATIONS", True)
    router["resolve"] = {}
    router["reply"] = FakeResponse(200, grounded(
        "A claim.", [{"title": "somewhere", "url": "https://redirect/unresolvable"}]))

    out = await tool_app.execute_web_search(tool_app.WebSearchRequest(query="q"))

    assert out["count"] == 1
    assert out["results"][0]["link"] == "https://redirect/unresolvable"
