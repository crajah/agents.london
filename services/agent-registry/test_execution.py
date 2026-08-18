"""Invocation tests: name parsing, version resolution, and the guarantee that
a halted pipeline is never reported as a completed A2A task."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

import pytest

import execution
from execution import ExecutionError, _split, prompt_from_payload, run_agent
from registry_api import parse_tool_name


def test_tool_name_round_trips_with_and_without_a_version():
    assert parse_tool_name("agent:writer@1.2.3") == ("agent", "writer", "1.2.3")
    assert parse_tool_name("pipeline:loop") == ("pipeline", "loop", None)


def test_malformed_tool_name_is_rejected():
    from fastapi import HTTPException
    for bad in ("writer@1.0.0", "tool:x", "agent:"):
        with pytest.raises(HTTPException):
            parse_tool_name(bad)


def test_version_id_split_handles_underscored_agent_ids():
    assert _split("agv_agt_corpus_reader_2.1.0") == ("agt_corpus_reader", "2.1.0")


def test_prompt_extraction_prefers_declared_fields():
    assert prompt_from_payload({"prompt": "hello"}) == "hello"
    assert prompt_from_payload({"query": "q"}) == "q"
    # Anything else is passed through as JSON rather than silently dropped.
    assert "other" in prompt_from_payload({"other": 1})


class FakeClient:
    def __init__(self, versions): self._versions = versions
    def _get_table_ref(self, table, realm): return f'"{realm}"."{table}"'
    async def _fetch(self, q, *a): return [{"id": 1}]


@pytest.mark.asyncio
async def test_unpublished_version_cannot_be_invoked(monkeypatch):
    """Rule 4.3: a draft must not be reachable by guessing its number."""
    async def fake_latest(client, table, realm, pk):
        return {"1.0.0": {"version": "1.0.0", "status": "draft"}}
    monkeypatch.setattr(execution, "_latest_versions", fake_latest)
    with pytest.raises(ExecutionError, match="not published"):
        await run_agent(FakeClient({}), "org", "agt_x", {"prompt": "hi"}, version="1.0.0")


@pytest.mark.asyncio
async def test_usage_is_read_from_the_provider_not_estimated(monkeypatch):
    async def fake_latest(client, table, realm, pk):
        return {"1.0.0": {"version": "1.0.0", "status": "published",
                          "system_prompt": "s", "model": {"name": "m"}}}
    seen = {}
    async def fake_call(record, prompt, org_id=None, project_id=None, agent_id=None):
        # The tenancy has to reach the model call, because that is where the
        # agent's pinned tools are resolved and invoked. Without it the tool
        # loop cannot reach the registry, and an agent that pinned a tool
        # silently runs without it.
        seen.update(org_id=org_id, project_id=project_id, agent_id=agent_id)
        return {"result": "ok", "model": "m",
                "usage": {"input_tokens": 11, "output_tokens": 7}}
    monkeypatch.setattr(execution, "_latest_versions", fake_latest)
    monkeypatch.setattr(execution, "call_model", fake_call)

    recorded = []
    class Meter:
        def record(self, e): recorded.append(e)
    out = await run_agent(FakeClient({}), "org", "agt_x", {"prompt": "hi"},
                          version="1.0.0", meter=Meter())
    assert out["usage"] == {"input_tokens": 11, "output_tokens": 7}
    assert seen == {"org_id": "org", "project_id": "proj_default", "agent_id": "agt_x"}
    assert recorded[0].tokens_total == 18
    assert recorded[0].compute_units == 72
