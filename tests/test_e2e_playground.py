"""The playground stream, proven against a real stack.

The claim is that what the interface shows is what happened: every event in the
stream is emitted at the moment the thing it describes occurs, in the order it
occurred, and nothing is emitted for work that did not run.

Nothing here is stubbed. The registries run, the planner is the real model, the
agents matched are really registered, and each stage is really invoked.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

import pytest

from conftest import agent_body, requires_stack   # noqa: F401
from test_e2e_backend import api, backend         # noqa: F401

pytestmark = [pytest.mark.asyncio, requires_stack]


async def collect(api, body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run one playground stream and return its events in arrival order."""
    events: List[Dict[str, Any]] = []
    async with api.stream("POST", "/api/playground/stream", json=body) as res:
        assert res.status_code == 200, await res.aread()
        assert res.headers["content-type"].startswith("text/event-stream")
        name, data = None, []
        async for line in res.aiter_lines():
            if line.startswith(":"):            # keepalive
                continue
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line == "":
                if name and data:
                    events.append({"event": name, "data": json.loads("\n".join(data))})
                name, data = None, []
    return events


async def seed_agents(agents, realm: str, project: str) -> List[str]:
    """Three published agents a plan can actually be staffed from."""
    specs = [
        ("agt_researcher", "Researcher",
         "Gathers and summarises background information on a topic.",
         "List the key facts about the topic in the input. Be brief."),
        ("agt_analyst", "Analyst",
         "Analyses gathered information and draws comparisons.",
         "Analyse the input and state the two most important comparisons. Be brief."),
        ("agt_writer", "Writer",
         "Writes a short structured memo from analysis.",
         "Write a three-sentence memo from the input."),
    ]
    made = []
    for agent_id, name, telos, prompt in specs:
        unique = f"{agent_id}_{uuid.uuid4().hex[:6]}"
        res = await agents.post("/agents", json=agent_body(
            org=realm, project=project, agent_id=unique, name=name,
            slug=unique.replace("_", "-"), telos=telos, description=telos,
            prompt=prompt, capabilities=[name.lower()]))
        assert res.status_code == 200, res.text
        made.append(unique)
    return made


async def test_a_goal_becomes_a_pipeline_and_every_stage_really_runs(
        api, agents, realm, project):
    await seed_agents(agents, realm, project)

    events = await collect(api, {
        "org_id": realm, "project_id": project,
        "prompt": "Research the market for electric delivery vans, analyse how "
                  "the top options compare, then write a short memo."})

    kinds = [e["event"] for e in events]
    assert kinds[0] == "accepted", kinds[:3]
    assert "error" not in kinds, [e for e in events if e["event"] == "error"]

    # The journey, in order: a decision, a plan, matches, a publication, runs.
    assert "intake" in kinds
    assert "decomposed" in kinds
    assert "matched" in kinds
    assert "published" in kinds
    assert kinds.index("decomposed") < kinds.index("matched") < kinds.index("published")
    assert kinds[-1] == "complete", kinds[-3:]

    published = next(e["data"] for e in events if e["event"] == "published")
    assert published["mcp_tool"].startswith("pipeline:")
    assert len(published["stages"]) >= 2
    for stage in published["stages"]:
        # A stage without a pin is not reproducible (F.51).
        assert stage["version"], stage
        assert stage["content_hash"], stage

    starts = [e["data"] for e in events if e["event"] == "step_start"]
    ends = [e["data"] for e in events if e["event"] == "step_end"]
    assert len(starts) == len(published["stages"]), kinds
    assert len(ends) == len(starts)

    # Nothing ends that did not start, and every end names the same step.
    assert [s["step"] for s in starts] == [e["step"] for e in ends]

    for end in ends:
        assert end["duration_ms"] >= 0          # measured, not invented (F.14)
        assert end["output"], "an agent reported no output at all"

    final = events[-1]["data"]
    assert final["failed"] is False
    assert final["answer"] == ends[-1]["output"], \
        "the deliverable must be the last stage's real output"
    assert final["duration_ms"] >= sum(e["duration_ms"] for e in ends)


async def test_each_stage_is_handed_the_previous_stages_output(
        api, agents, realm, project):
    """That is what makes it a pipeline rather than three separate calls."""
    await seed_agents(agents, realm, project)

    events = await collect(api, {
        "org_id": realm, "project_id": project,
        "prompt": "Research two cloud providers, compare their pricing, and "
                  "write a recommendation."})

    starts = [e["data"] for e in events if e["event"] == "step_start"]
    ends = [e["data"] for e in events if e["event"] == "step_end"]
    if len(starts) < 2:
        pytest.skip("the planner produced fewer than two staffed stages")

    for index in range(1, len(starts)):
        assert starts[index]["input"] == ends[index - 1]["output"], (
            f"stage {starts[index]['step']} was not handed "
            f"{ends[index - 1]['step']}'s output")


async def test_a_greeting_is_answered_without_composing_anything(
        api, realm, project):
    """Composing a pipeline for "hello" would be theatre, and would cost tokens."""
    events = await collect(api, {
        "org_id": realm, "project_id": project, "prompt": "hello, what is 2 + 2?"})

    kinds = [e["event"] for e in events]
    assert "intake" in kinds
    assert kinds[-1] == "complete"

    intake = next(e["data"] for e in events if e["event"] == "intake")
    if intake.get("route") != "SIMPLE_CHAT":
        pytest.skip(f"intake routed this as {intake.get('route')}")

    assert "published" not in kinds, "a pipeline was composed for a greeting"
    assert "step_start" not in kinds
    assert events[-1]["data"]["direct"] is True
    assert events[-1]["data"]["answer"]


async def test_a_goal_nothing_can_staff_is_reported_not_faked(
        api, realm, project):
    """An empty project has no agents to match, and says so."""
    events = await collect(api, {
        "org_id": realm, "project_id": project,
        "prompt": "Perform a full seismic reflection survey, invert the data to "
                  "a velocity model, and produce a drilling recommendation."})

    kinds = [e["event"] for e in events]
    assert "step_start" not in kinds, "something ran with no agent to run it"
    assert "published" not in kinds

    # Either the composition was refused, or intake answered it directly. What
    # must not happen is a fabricated pipeline or a fabricated answer.
    if "error" in kinds:
        detail = next(e["data"] for e in events if e["event"] == "error")
        assert detail["status"] in (409, 422, 502), detail
        assert detail["detail"]
    else:
        assert kinds[-1] == "complete"


async def test_a_single_published_agent_can_be_run_alone(api, agents, realm, project):
    made = await seed_agents(agents, realm, project)
    slug = made[0].replace("_", "-")

    events = await collect(api, {
        "org_id": realm, "project_id": project,
        "prompt": "Summarise what a delivery van is, in one sentence.",
        "agent": f"agent:{slug}@1.0.0"})

    kinds = [e["event"] for e in events]
    assert kinds == ["accepted", "step_start", "step_end", "complete"], kinds

    end = events[2]["data"]
    assert end["output"]
    assert end["duration_ms"] >= 0
    assert events[-1]["data"]["answer"] == end["output"]


async def test_an_unknown_agent_fails_rather_than_answering(api, realm, project):
    events = await collect(api, {
        "org_id": realm, "project_id": project, "prompt": "Do something.",
        "agent": "agent:does-not-exist@1.0.0"})

    kinds = [e["event"] for e in events]
    assert "error" in kinds, kinds
    assert "complete" not in kinds or events[-1]["data"].get("failed")
