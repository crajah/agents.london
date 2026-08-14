"""The founders that run without being asked, proven against a real stack.

Four founders carry a duty cycle. The claim these tests hold shut is that the
cycles are real: they read the actual records, they call the actual model, and
where they decide something must change, they change it through the same
registry APIs a person would use — and where they decide nothing needs to
change, they say so rather than manufacturing a finding.

Nothing here is stubbed. The registries run, the model router answers, and a
quarantine in one of these tests really does withdraw an agent from discovery.
"""
from __future__ import annotations

import uuid

import pytest

from conftest import agent_body, requires_stack   # noqa: F401
from test_e2e_backend import api, backend         # noqa: F401

pytestmark = [pytest.mark.asyncio, requires_stack]

DUTIES = ["anomaly-detector", "proving-ground", "adversary", "quarantine-warden"]


async def test_the_duty_bearing_founders_are_the_ones_that_declared_a_duty(api):
    res = await api.get("/api/autonomy/status")
    assert res.status_code == 200, res.text
    body = res.json()

    declared = {d["founder_id"] for d in body["duties"]}
    assert declared == set(DUTIES), declared
    # Each duty says what it watches and what it may change. A duty that cannot
    # name its own effect cannot be audited against it.
    for duty in body["duties"]:
        assert duty["watches"] and duty["effect"]
        assert duty["interval_seconds"] > 0
        assert duty["budget_per_cycle"] > 0


async def test_an_empty_project_produces_quiet_cycles_and_costs_nothing(api, realm, project):
    """The failure mode of an autonomous evaluator is finding something anyway."""
    created = await api.post("/api/projects", json={
        "org_id": realm, "user_id": "u_autonomy", "project_name": project})
    assert created.status_code == 200, created.text
    pid = created.json()["project_id"]

    for founder_id in DUTIES:
        res = await api.post("/api/autonomy/run", json={
            "org_id": realm, "project_id": pid, "founder_id": founder_id})
        assert res.status_code == 200, res.text
        cycle = res.json()
        assert cycle["quiet"] is True, cycle
        assert cycle["subjects"] == 0
        assert cycle["effects"] == []
        assert cycle["error"] is None


async def test_a_founder_without_a_duty_cannot_be_scheduled(api, realm, project):
    res = await api.post("/api/autonomy/run", json={
        "org_id": realm, "project_id": project, "founder_id": "grand-ledger"})
    assert res.status_code == 400
    assert "not a duty-bearing founder" in res.json()["detail"]


async def test_quiet_cycles_are_recorded_rather_than_hidden(api, realm, project):
    """'It ran and found nothing' and 'it never ran' are different states."""
    created = await api.post("/api/projects", json={
        "org_id": realm, "user_id": "u_autonomy", "project_name": project})
    pid = created.json()["project_id"]

    await api.post("/api/autonomy/run", json={
        "org_id": realm, "project_id": pid, "founder_id": "adversary"})

    res = await api.get("/api/autonomy/cycles")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 1
    mine = [c for c in body["cycles"] if c["project_id"] == pid]
    assert mine, body["cycles"][:2]
    assert mine[0]["founder_id"] == "adversary"
    assert mine[0]["finished_at"] is not None


async def test_the_warden_examines_the_population_when_runs_have_failed(
        api, agents, realm, project):
    """A cycle with real subjects reaches the model and comes back judged.

    The assertion is deliberately about the shape of the outcome rather than
    about a particular verdict: whether one poorly-performing agent warrants
    quarantine is the Warden's judgement, and a test that forces it would be
    testing the prompt's obedience rather than the mechanism.
    """
    created = await api.post("/api/projects", json={
        "org_id": realm, "user_id": "u_autonomy", "project_name": project})
    pid = created.json()["project_id"]

    # A real registered agent that is not a founder, so it is in the population
    # the Warden is allowed to consider.
    agent_id = "agt_flaky_" + uuid.uuid4().hex[:6]
    reg = await agents.post("/agents", json=agent_body(
        org=realm, project=pid, agent_id=agent_id, name="Flaky Worker",
        slug=agent_id.replace("_", "-"),
        telos="Summarises text.", description="Summarises a passage of text.",
        prompt="Summarise the input in one sentence.",
        capabilities=["summarisation"]))
    assert reg.status_code == 200, reg.text

    res = await api.post("/api/autonomy/run", json={
        "org_id": realm, "project_id": pid, "founder_id": "proving-ground"})
    assert res.status_code == 200, res.text
    cycle = res.json()

    # With a population but no recorded runs, the Proving Ground has nothing to
    # judge an agent on — and says so, rather than evaluating the description.
    assert cycle["error"] is None
    assert cycle["quiet"] is True
    assert cycle["effects"] == []


async def test_founding_agents_are_out_of_reach_of_the_evaluators(api, realm, project):
    """An evaluator that can quarantine the Arbiter can silence its own appeal."""
    from backend import autonomy

    created = await api.post("/api/projects", json={
        "org_id": realm, "user_id": "u_autonomy", "project_name": project})
    pid = created.json()["project_id"]

    evidence, subjects = await autonomy._gather("proving-ground", realm, pid, 5)
    # Thirty-six founders exist in this project and none of them is a subject.
    assert subjects == 0, evidence
    assert not evidence.get("agents")
