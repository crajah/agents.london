"""An agent can actually call the tools its version pinned.

It could not. `call_model` sent a system prompt and a user turn and no tools at
all, so an agent's `tools` — resolved at registration, inside its content hash,
and refused by Rule 3.5 if unpublished — were decorative. A published agent
holding a search tool could not search; it could only describe not being able
to, which is what produced refusals like "web search is not granted to this
realm" from an agent that had been given web search.
"""
from __future__ import annotations

import json

import pytest

import execution


class FakeRouter:
    """A model router that asks for tools, then answers."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.seen = []

    async def __call__(self, base, body):
        self.seen.append(body)
        return self.rounds.pop(0)


def answer(text, prompt_tokens=10, completion_tokens=5):
    return {"choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens}}


def asks_for(tool_id, arguments, call_id="call_1"):
    return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": call_id, "type": "function",
                                "function": {"name": tool_id,
                                             "arguments": json.dumps(arguments)}}]}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8}}


RECORD = {"agent_id": "agt_x", "system_prompt": "you are a researcher",
          "model": {"name": "m"}, "tools": ["mcp-web-search"]}

OFFERED = [{"tool_id": "mcp-web-search", "name": "Web search",
            "description": "Search the public web.", "side_effects": "external",
            "input_schema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}}]


@pytest.fixture
def wiring(monkeypatch):
    """Stand in for the tool registry, and record what was asked of it."""
    calls = []

    async def usable(org_id, project_id, tool_ids):
        return [t for t in OFFERED if t["tool_id"] in set(tool_ids)]

    async def invoke(tool_id, arguments, org_id, project_id, caller=None,
                     version=None, idempotency_key=None):
        calls.append({"tool_id": tool_id, "arguments": arguments,
                      "org_id": org_id, "project_id": project_id,
                      "caller": caller, "idempotency_key": idempotency_key})
        return {"ok": True, "result": {"results": [{"title": "A real page"}]}}

    import tool_client
    monkeypatch.setattr(tool_client, "usable", usable)
    monkeypatch.setattr(tool_client, "invoke", invoke)
    return calls


async def test_a_pinned_tool_is_offered_to_the_model(monkeypatch, wiring):
    router = FakeRouter(answer("done"))
    monkeypatch.setattr(execution, "_chat", router)

    await execution.call_model(RECORD, "find something", org_id="org",
                               project_id="proj", agent_id="agt_x")

    offered = router.seen[0]["tools"]
    assert [t["function"]["name"] for t in offered] == ["mcp-web-search"]
    # The declared schema travels, or the model cannot form a valid call.
    assert offered[0]["function"]["parameters"]["required"] == ["query"]


async def test_the_model_asking_for_a_tool_really_calls_it(monkeypatch, wiring):
    router = FakeRouter(asks_for("mcp-web-search", {"query": "electric vans"}),
                        answer("Here is what I found."))
    monkeypatch.setattr(execution, "_chat", router)

    out = await execution.call_model(RECORD, "research electric vans",
                                     org_id="org", project_id="proj",
                                     agent_id="agt_x")

    assert len(wiring) == 1
    assert wiring[0]["tool_id"] == "mcp-web-search"
    assert wiring[0]["arguments"] == {"query": "electric vans"}
    # The tenancy travels, or the call lands in the wrong realm.
    assert wiring[0]["org_id"] == "org"
    assert wiring[0]["project_id"] == "proj"
    assert out["result"] == "Here is what I found."


async def test_the_real_result_is_handed_back_to_the_model(monkeypatch, wiring):
    router = FakeRouter(asks_for("mcp-web-search", {"query": "q"}),
                        answer("summarised"))
    monkeypatch.setattr(execution, "_chat", router)

    await execution.call_model(RECORD, "go", org_id="org", project_id="proj",
                               agent_id="agt_x")

    second = router.seen[1]["messages"]
    tool_turn = [m for m in second if m["role"] == "tool"]
    assert len(tool_turn) == 1
    assert "A real page" in tool_turn[0]["content"]


async def test_a_side_effecting_call_carries_an_idempotency_key(monkeypatch, wiring):
    """At-least-once delivery over a writing tool repeats the effect (Rule 6.2)."""
    router = FakeRouter(asks_for("mcp-web-search", {"query": "q"}, call_id="abc"),
                        answer("ok"))
    monkeypatch.setattr(execution, "_chat", router)

    await execution.call_model(RECORD, "go", org_id="org", project_id="proj",
                               agent_id="agt_x")

    assert wiring[0]["idempotency_key"] == "agt_x:abc"


async def test_a_failed_tool_call_is_reported_not_invented(monkeypatch):
    """A model cannot tell a fabricated tool result from a real one."""
    async def usable(org_id, project_id, tool_ids):
        return OFFERED

    async def invoke(tool_id, arguments, org_id, project_id, caller=None,
                     version=None, idempotency_key=None):
        return {"ok": False, "error": "mcp-web-search failed (503): unconfigured"}

    import tool_client
    monkeypatch.setattr(tool_client, "usable", usable)
    monkeypatch.setattr(tool_client, "invoke", invoke)

    router = FakeRouter(asks_for("mcp-web-search", {"query": "q"}),
                        answer("I could not search."))
    monkeypatch.setattr(execution, "_chat", router)

    await execution.call_model(RECORD, "go", org_id="org", project_id="proj",
                               agent_id="agt_x")

    tool_turn = [m for m in router.seen[1]["messages"] if m["role"] == "tool"][0]
    assert tool_turn["content"].startswith("ERROR:")
    assert "503" in tool_turn["content"]
    assert "unconfigured" in tool_turn["content"]


async def test_usage_is_summed_across_every_round(monkeypatch, wiring):
    """A tool round is a real model call and is charged for."""
    router = FakeRouter(asks_for("mcp-web-search", {"query": "q"}),
                        answer("done", prompt_tokens=30, completion_tokens=12))
    monkeypatch.setattr(execution, "_chat", router)

    out = await execution.call_model(RECORD, "go", org_id="org",
                                     project_id="proj", agent_id="agt_x")

    assert out["usage"] == {"input_tokens": 20 + 30, "output_tokens": 8 + 12}


async def test_an_agent_with_no_tools_is_offered_none(monkeypatch):
    router = FakeRouter(answer("plain"))
    monkeypatch.setattr(execution, "_chat", router)

    await execution.call_model({"system_prompt": "s", "model": {"name": "m"}},
                               "hello", org_id="org", project_id="proj")

    assert "tools" not in router.seen[0]


async def test_the_loop_is_bounded(monkeypatch, wiring):
    """A model that keeps calling tools is a cost with no ceiling."""
    monkeypatch.setattr(execution, "MAX_TOOL_ROUNDS", 2)
    router = FakeRouter(asks_for("mcp-web-search", {"query": "1"}, "a"),
                        asks_for("mcp-web-search", {"query": "2"}, "b"),
                        answer("forced to answer"))
    monkeypatch.setattr(execution, "_chat", router)

    out = await execution.call_model(RECORD, "go", org_id="org",
                                     project_id="proj", agent_id="agt_x")

    # The final round withdraws the tools, so the model has to answer.
    assert "tools" not in router.seen[-1]
    assert out["result"] == "forced to answer"


async def test_an_unreachable_tool_registry_does_not_stop_the_agent(monkeypatch):
    """It answers without tools, and its prompt still forbids inventing results."""
    async def broken(org_id, project_id, tool_ids):
        raise RuntimeError("tool registry unreachable")

    import tool_client
    monkeypatch.setattr(tool_client, "usable", broken)

    router = FakeRouter(answer("answered from what I know"))
    monkeypatch.setattr(execution, "_chat", router)

    out = await execution.call_model(RECORD, "go", org_id="org",
                                     project_id="proj", agent_id="agt_x")

    assert "tools" not in router.seen[0]
    assert out["result"] == "answered from what I know"


async def test_a_tool_call_with_unparseable_arguments_is_reported(monkeypatch, wiring):
    router = FakeRouter(
        {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "x", "type": "function",
             "function": {"name": "mcp-web-search", "arguments": "{not json"}}]}}],
         "usage": {}},
        answer("recovered"))
    monkeypatch.setattr(execution, "_chat", router)

    out = await execution.call_model(RECORD, "go", org_id="org",
                                     project_id="proj", agent_id="agt_x")

    tool_turn = [m for m in router.seen[1]["messages"] if m["role"] == "tool"][0]
    assert tool_turn["content"].startswith("ERROR:")
    assert wiring == [], "an unparseable call must not reach the registry"
    assert out["result"] == "recovered"
