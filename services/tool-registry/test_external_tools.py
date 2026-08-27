"""Tavily key rotation, Serper, and the RapidAPI service tools.

The standard these are held to is the one Rule 7.2 sets and the old search
endpoint failed: a call that did not obtain a result must not produce one. The
rotation tests exist because the failure mode they guard against — a revoked
key silently taking a fixed share of every search — is invisible from the
caller's side, which sees an intermittently failing tool and no reason why.
"""
from __future__ import annotations

import pytest

import external_tools as ext


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Stand in for httpx.AsyncClient, recording each request."""
    state = {"calls": [], "replies": []}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def _record(self, method, url, **kw):
            state["calls"].append({"method": method, "url": url, **kw})
            reply = state["replies"].pop(0) if state["replies"] else FakeResponse()
            if isinstance(reply, Exception):
                raise reply
            return reply

        async def post(self, url, **kw):
            return await self._record("POST", url, **kw)

        async def get(self, url, **kw):
            return await self._record("GET", url, **kw)

    monkeypatch.setattr(ext.httpx, "AsyncClient", FakeClient)
    return state


def ring(*names):
    return ext.TavilyKeyRing([(n, f"value-of-{n}") for n in names])


def tavily_ok(n=1):
    return FakeResponse(200, {"answer": "an answer",
                              "results": [{"title": "t", "content": "c",
                                           "url": "https://e.example", "score": 0.5}] * n})


# ------------------------------------------------------------- key discovery

def test_keys_are_collected_from_the_numbered_variables(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "base")
    monkeypatch.setenv("TAVILY_API_KEY_1", "one")
    monkeypatch.setenv("TAVILY_API_KEY_2", "two")
    monkeypatch.delenv("TAVILY_API_KEY_3", raising=False)
    names = [n for n, _ in ext._collect_tavily_keys()]
    assert names == ["TAVILY_API_KEY", "TAVILY_API_KEY_1", "TAVILY_API_KEY_2"]


def test_the_same_key_under_two_names_is_one_key(monkeypatch):
    """Rotating between aliases would look like spreading load across two
    quotas while actually spending one twice as fast."""
    monkeypatch.setenv("TAVILY_API_KEY", "same")
    monkeypatch.setenv("TAVILY_API_KEY_1", "same")
    monkeypatch.delenv("TAVILY_API_KEY_2", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY_3", raising=False)
    assert len(ext._collect_tavily_keys()) == 1


# ----------------------------------------------------------------- rotation

@pytest.mark.asyncio
async def test_each_call_starts_at_the_next_key(http):
    keys = ring("K1", "K2", "K3")
    http["replies"] = [tavily_ok(), tavily_ok(), tavily_ok()]
    used = []
    for _ in range(3):
        used.append((await ext.tavily_search(keys, "q"))["key_used"])
    assert used == ["K1", "K2", "K3"], "load is not being spread across the pool"


@pytest.mark.asyncio
async def test_a_rejected_key_is_stepped_over_within_the_same_call(http):
    keys = ring("K1", "K2")
    http["replies"] = [FakeResponse(401, text="unauthorized"), tavily_ok()]
    result = await ext.tavily_search(keys, "q")
    assert result["key_used"] == "K2"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_a_revoked_key_leaves_the_rotation_permanently(http):
    """Otherwise a dead key keeps taking its turn and fails 1-in-N searches."""
    keys = ring("K1", "K2")
    http["replies"] = [FakeResponse(401, text="unauthorized"), tavily_ok(), tavily_ok()]
    await ext.tavily_search(keys, "q")
    assert [k["state"] for k in keys.status() if k["name"] == "K1"] == ["quarantined"]
    # The next call must not spend an attempt on it.
    assert (await ext.tavily_search(keys, "q"))["key_used"] == "K2"


@pytest.mark.asyncio
async def test_an_over_quota_key_is_benched_not_quarantined(http):
    """Quota recovers on the provider's clock; a revoked key never does."""
    keys = ring("K1", "K2")
    http["replies"] = [FakeResponse(432, text="plan limit"), tavily_ok()]
    await ext.tavily_search(keys, "q")
    k1 = [k for k in keys.status() if k["name"] == "K1"][0]
    assert k1["state"] == "cooling"
    assert k1["reason"] is None
    assert k1["cooldown_secs_remaining"] > 0


@pytest.mark.asyncio
async def test_every_key_failing_raises_rather_than_returning_nothing(http):
    keys = ring("K1", "K2")
    http["replies"] = [FakeResponse(401, text="no"), FakeResponse(401, text="no")]
    with pytest.raises(ext.ProviderError) as e:
        await ext.tavily_search(keys, "q")
    assert e.value.status_code in (502, 503)


@pytest.mark.asyncio
async def test_no_keys_configured_is_reported_as_unconfigured(http):
    with pytest.raises(ext.NotConfigured) as e:
        await ext.tavily_search(ring(), "q")
    assert e.value.status_code == 503
    assert "TAVILY_API_KEY" in str(e.value)


@pytest.mark.asyncio
async def test_a_provider_error_is_not_retried_on_every_key(http):
    """A 500 is the provider failing, not this key being wrong. Burning the
    whole pool on it would quarantine nothing and just cost N calls."""
    keys = ring("K1", "K2", "K3")
    http["replies"] = [FakeResponse(500, text="boom")]
    with pytest.raises(ext.ProviderError):
        await ext.tavily_search(keys, "q")
    assert len(http["calls"]) == 1


@pytest.mark.asyncio
async def test_the_key_value_is_never_returned(http):
    keys = ring("K1")
    http["replies"] = [tavily_ok()]
    result = await ext.tavily_search(keys, "q")
    assert result["key_used"] == "K1"
    assert "value-of-K1" not in str(result)


def test_key_health_never_exposes_a_value():
    assert "value-of-K1" not in str(ring("K1", "K2").status())


# ------------------------------------------------------------------- Serper

@pytest.mark.asyncio
async def test_serper_returns_organic_results(http, monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    http["replies"] = [FakeResponse(200, {
        "organic": [{"title": "T", "snippet": "S", "link": "https://e.example",
                     "position": 1}],
        "answerBox": {"answer": "42"}, "credits": 1})]
    out = await ext.serper_search("q")
    assert out["count"] == 1 and out["answer"] == "42"
    assert out["results"][0]["link"] == "https://e.example"


@pytest.mark.asyncio
async def test_serper_without_a_key_is_unconfigured(http, monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_KEY", raising=False)
    with pytest.raises(ext.NotConfigured) as e:
        await ext.serper_search("q")
    assert "SERPER_API_KEY" in str(e.value)


@pytest.mark.asyncio
async def test_serper_upstream_failure_raises(http, monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    http["replies"] = [FakeResponse(500, text="boom")]
    with pytest.raises(ext.ProviderError):
        await ext.serper_search("q")


# ----------------------------------------------------------------- RapidAPI

def service(slug="deezer"):
    return ext.RAPIDAPI_BY_SLUG[slug]


@pytest.mark.asyncio
async def test_rapidapi_sends_the_declared_parameters(http, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    http["replies"] = [FakeResponse(200, {"data": [{"title": "Song"}]})]
    out = await ext.rapidapi_call(service("deezer"), {"query": "daft punk"})
    call = http["calls"][0]
    assert call["params"] == {"q": "daft punk"}
    assert call["headers"]["X-RapidAPI-Host"] == "deezerdevs-deezer.p.rapidapi.com"
    assert out["service"] == "deezer"


@pytest.mark.asyncio
async def test_rapidapi_fixed_parameters_are_applied(http, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    http["replies"] = [FakeResponse(200, {"body": {}})]
    await ext.rapidapi_call(service("yahoo-finance"), {"ticker": "AAPL"})
    assert http["calls"][0]["params"] == {"type": "STOCKS", "ticker": "AAPL"}


@pytest.mark.asyncio
async def test_a_retired_upstream_answering_200_is_not_a_result(http, monkeypatch):
    """linkedin-api8 answers HTTP 200 with {"success": false, "message": "This
    service is no longer available at this location"}. Passing that on as data
    is exactly the fabricated-evidence failure Rule 7.2 forbids."""
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    http["replies"] = [FakeResponse(200, {"success": False,
                                          "message": "no longer available"})]
    with pytest.raises(ext.ProviderError) as e:
        await ext.rapidapi_call(service("deezer"), {"query": "x"})
    assert "no longer available" in str(e.value)


@pytest.mark.asyncio
async def test_a_403_does_not_claim_to_know_which_cause(http, monkeypatch):
    """RapidAPI returns the same 403 for an invalid key and for a valid key
    that is not subscribed, so the message must not pick one."""
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    http["replies"] = [FakeResponse(403, {"message": "You are not subscribed to this API."})]
    with pytest.raises(ext.ProviderError) as e:
        await ext.rapidapi_call(service("deezer"), {"query": "x"})
    message = str(e.value)
    assert "invalid" in message and "not subscribed" in message


@pytest.mark.asyncio
async def test_rapidapi_without_a_key_is_unconfigured(http, monkeypatch):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    with pytest.raises(ext.NotConfigured) as e:
        await ext.rapidapi_call(service("deezer"), {"query": "x"})
    assert "RAPIDAPI_KEY" in str(e.value)


@pytest.mark.asyncio
async def test_a_missing_required_argument_is_rejected_before_the_call(http, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    with pytest.raises(ext.ProviderError) as e:
        await ext.rapidapi_call(service("deezer"), {})
    assert e.value.status_code == 400
    assert not http["calls"], "a call was made without its required argument"


def test_every_catalogued_service_has_a_schema_for_each_required_argument():
    """Rule 3.2: the input schema is what the model is shown. A required
    argument with no description is one the model has to guess."""
    for svc in ext.RAPIDAPI_SERVICES:
        for name in svc.required:
            assert name in svc.schema_properties, f"{svc.slug}: {name} undocumented"
            assert svc.schema_properties[name].get("description")
            assert name in svc.params, f"{svc.slug}: {name} maps to no query parameter"


def test_service_slugs_are_unique():
    slugs = [s.slug for s in ext.RAPIDAPI_SERVICES]
    assert len(slugs) == len(set(slugs))
