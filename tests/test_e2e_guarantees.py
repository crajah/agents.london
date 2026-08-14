"""The guarantees the specification makes, proved against the live stack.

Immutability, tenancy, provenance, cycles, recursion, retirement, exposure, and
the legacy surface — each asserted against a real PostgreSQL and real service
processes rather than a test double.

Several of these cover mechanisms that had a writer and no caller, or a caller
and no writer, until an end-to-end test asked for them by name.
"""
import uuid

import pytest

from conftest import TEXT_IN, TEXT_OUT, agent_body, requires_stack

pytestmark = [pytest.mark.e2e, requires_stack]


def simple(org, project, agent_id, slug, *, prompt=None, telos=None, **kw):
    return agent_body(
        org=org, project=project, agent_id=agent_id, name=slug.title(), slug=slug,
        telos=telos or f"An agent called {slug}.",
        description=f"An agent called {slug} that does one thing.",
        prompt=prompt or "Reply with the single word OK.", **kw)


# ------------------------------------------------------------ immutability

async def test_a_published_version_cannot_be_edited(agents, realm, project):
    """Rule 3.3 — publish a new version instead of editing a published one."""
    body = simple(realm, project, "agt_fixed", "fixed-agent")
    assert (await agents.post("/agents", json=body)).status_code == 200

    changed = simple(realm, project, "agt_fixed", "fixed-agent",
                     prompt="Reply with something else entirely.")
    res = await agents.post("/agents", json=changed)
    assert res.status_code == 400
    assert "Rule 3.3" in res.json()["detail"]


async def test_republishing_identical_content_is_not_an_error(agents, realm, project):
    """Registration is retried by deployment tooling; a retry is not a change."""
    body = simple(realm, project, "agt_same", "same-agent")
    first = await agents.post("/agents", json=body)
    second = await agents.post("/agents", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["content_hash"] == second.json()["content_hash"]


async def test_the_same_content_under_a_new_version_is_rejected(
        agents, realm, project):
    """Rule 4.2 — either a pointless bump, or a change to something the hash
    deliberately excludes. Both are worth an error."""
    assert (await agents.post("/agents", json=simple(
        realm, project, "agt_dup", "dup-agent"))).status_code == 200
    res = await agents.post("/agents", json=simple(
        realm, project, "agt_dup", "dup-agent", version="1.0.1"))
    assert res.status_code == 400
    assert "Rule 4.2" in res.json()["detail"]


async def test_a_new_version_appends_rather_than_replaces(agents, realm, project):
    for version, prompt in (("1.0.0", "Reply with OK."), ("1.1.0", "Reply with FINE.")):
        res = await agents.post("/agents", json=simple(
            realm, project, "agt_versioned", "versioned-agent",
            version=version, prompt=prompt))
        assert res.status_code == 200, res.text

    detail = await agents.get("/agents/agt_versioned",
                              params={"org_id": realm, "project_id": project})
    history = detail.json()["history"]
    assert [h["version"] for h in history] == ["1.0.0", "1.1.0"]
    assert history[0]["content_hash"] != history[1]["content_hash"]


async def test_two_agents_cannot_share_a_slug(agents, realm, project):
    """§9 rejection 9 — the slug is the MCP tool name and the A2A card URL."""
    assert (await agents.post("/agents", json=simple(
        realm, project, "agt_first", "shared-slug"))).status_code == 200
    res = await agents.post("/agents", json=simple(
        realm, project, "agt_second", "shared-slug",
        prompt="Reply with the single word DIFFERENT."))
    assert res.status_code == 400
    assert "rejection 9" in res.json()["detail"]


# ----------------------------------------------------------------- tenancy

async def test_two_realms_are_separate_schemas(agents, db, project):
    """AG §2 — no query crosses a realm, because a realm is a schema."""
    left = "t_" + uuid.uuid4().hex[:10]
    right = "t_" + uuid.uuid4().hex[:10]

    for realm in (left, right):
        res = await agents.post("/agents", json=simple(
            realm, project, "agt_same_id", "same-slug",
            telos=f"An agent belonging to {realm}."))
        assert res.status_code == 200, res.text

    for realm in (left, right):
        listed = await agents.get("/agents", params={"org_id": realm})
        ids = [a["agent_id"] for a in listed.json()["agents"]]
        assert ids == ["agt_same_id"]

    # The same business id in two realms is two rows in two schemas.
    for realm in (left, right):
        count = await db.fetchval(f'SELECT count(*) FROM "{realm}".agents')
        assert count == 1


async def test_discovery_does_not_cross_realms(agents):
    """A tenant's catalogue must not appear in another tenant's discovery."""
    project = "proj_" + uuid.uuid4().hex[:8]
    mine = "t_" + uuid.uuid4().hex[:10]
    theirs = "t_" + uuid.uuid4().hex[:10]

    await agents.post("/agents", json=simple(
        mine, project, "agt_mine", "mine-agent",
        telos="Reconciles supplier invoices against purchase orders."))
    await agents.post("/agents", json=simple(
        theirs, project, "agt_theirs", "theirs-agent",
        telos="Reconciles supplier invoices against purchase orders."))

    found = await agents.get("/discover", params={
        "q": "reconcile supplier invoices", "org_id": mine, "top_k": 10})
    assert [r["id"] for r in found.json()["results"]] == ["agt_mine"]


# -------------------------------------------------------------- provenance

async def test_spawn_edges_record_who_created_whom(agents, realm, project):
    """Rule 3.2 — the spawns edges are the provenance record of everything below."""
    assert (await agents.post("/agents", json=simple(
        realm, project, "agt_root", "root-agent"))).status_code == 200

    for child in ("agt_child_a", "agt_child_b"):
        res = await agents.post("/agents", json=simple(
            realm, project, child, child.replace("_", "-"),
            telos=f"A child agent named {child}.", spawned_by="agt_root"))
        assert res.status_code == 200, res.text

    res = await agents.post("/agents", json=simple(
        realm, project, "agt_grandchild", "grandchild-agent",
        telos="A grandchild agent.", spawned_by="agt_child_a"))
    assert res.status_code == 200, res.text

    progeny = await agents.get("/agents/agt_root/progeny",
                               params={"org_id": realm, "project_id": project})
    assert progeny.status_code == 200, progeny.text
    assert sorted(p["agent_id"] for p in progeny.json()["progeny"]) == \
        ["agt_child_a", "agt_child_b"]


async def test_descendants_is_a_bounded_traversal(agents, realm, project):
    """§10 by structure, and Rule 6.4's bounded walk.

    This is the endpoint whose traversal used the wrong parameter names and
    read `.payload` off rows that carry ids — it returned nothing at all, and
    only a real graph could show that.
    """
    await agents.post("/agents", json=simple(realm, project, "agt_a", "gen-a"))
    await agents.post("/agents", json=simple(
        realm, project, "agt_b", "gen-b", telos="Second generation.",
        spawned_by="agt_a"))
    await agents.post("/agents", json=simple(
        realm, project, "agt_c", "gen-c", telos="Third generation.",
        spawned_by="agt_b"))

    res = await agents.get("/agents/agt_a/descendants",
                           params={"org_id": realm, "project_id": project,
                                   "max_depth": 5})
    assert res.status_code == 200, res.text
    found = {d["agent_id"]: d["depth"] for d in res.json()["descendants"]}
    assert found == {"agt_b": 1, "agt_c": 2}

    # Bounded: depth 1 stops before the grandchild.
    shallow = await agents.get("/agents/agt_a/descendants",
                               params={"org_id": realm, "project_id": project,
                                       "max_depth": 1})
    assert [d["agent_id"] for d in shallow.json()["descendants"]] == ["agt_b"]


async def test_a_fork_records_its_lineage(agents, db, realm, project):
    """§5 — `derived_from`, written within the realm."""
    await agents.post("/agents", json=simple(realm, project, "agt_origin", "origin"))
    res = await agents.post("/agents", json={
        **simple(realm, project, "agt_fork", "forked",
                 telos="A fork of the origin.", prompt="Reply with FORKED."),
        "derived_from": {"agent_id": "agt_origin"}})
    assert res.status_code == 200, res.text

    edges = await db.fetchval(f'SELECT count(*) FROM "{realm}".derived_from')
    assert edges == 1


async def test_a_cross_org_copy_records_a_local_origin_stub(agents, db, realm, project):
    """§11.1 — a realm is a schema, so the edge points at a local stub carrying
    the origin's realm, id, version and hash."""
    res = await agents.post("/agents", json={
        **simple(realm, project, "agt_copy", "copied",
                 telos="A copy published from another organisation."),
        "derived_from": {"realm": "org_elsewhere", "agent_id": "agt_far",
                         "version": "2.1.0", "content_hash": "sha256:abc"}})
    assert res.status_code == 200, res.text

    import json
    row = await db.fetchrow(
        f'SELECT payload FROM "{realm}".agents '
        f"WHERE payload->>'is_origin_stub' = 'true'")
    assert row is not None, "no origin stub was written"
    payload = row["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["origin_realm"] == "org_elsewhere"
    assert payload["origin_content_hash"] == "sha256:abc"
    assert payload["lifecycle"] == "dormant"

    # A stub is lineage, not a callable agent, so it stays out of listings.
    listed = await agents.get("/agents", params={"org_id": realm})
    assert "org_elsewhere::agt_far" not in [a["agent_id"] for a in listed.json()["agents"]]


# --------------------------------------------------------------- prompts

async def test_the_prompt_is_versioned_independently(agents, db, realm, project):
    """§3.2 — `prompts` had a table and no writer."""
    await agents.post("/agents", json=simple(
        realm, project, "agt_prompted", "prompted", prompt="Reply with ALPHA."))
    await agents.post("/agents", json=simple(
        realm, project, "agt_prompted", "prompted", version="1.1.0",
        prompt="Reply with BETA."))

    rows = await db.fetch(f'SELECT id FROM "{realm}".prompts')
    assert len(rows) == 1, "one prompt vertex per agent"
    records = await db.fetch(
        f'SELECT payload FROM "{realm}".prompts_data WHERE id = $1', rows[0]["id"])
    assert len(records) == 2, "one record per distinct prompt"


# ------------------------------------------------------- cycles and limits

async def test_a_cyclic_pipeline_without_a_bound_is_rejected(agents, realm, project):
    """Rule 6.1 — an unbounded cycle is a way to exhaust a budget silently."""
    for agent_id, slug in (("agt_x", "cycle-x"), ("agt_y", "cycle-y")):
        await agents.post("/agents", json=simple(realm, project, agent_id, slug))

    res = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_unbounded", "name": "U",
                     "slug": "unbounded", "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_unbounded", "version": "1.0.0",
            "steps": {"x": {"version_id": "agv_agt_x_1.0.0"},
                      "y": {"version_id": "agv_agt_y_1.0.0"}},
            "dependencies": [
                {"from_step": "x", "to_step": "y", "relationship": "depends_on"},
                {"from_step": "y", "to_step": "x", "relationship": "on_condition",
                 "condition": "result"}],
            "entry_steps": ["x"], "exit_steps": ["y"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert res.status_code == 400
    assert "Rule 6.1" in res.json()["detail"]


async def test_an_inescapable_cycle_is_rejected(agents, realm, project):
    """Rule 6.2 — a cycle with no conditional edge and no exit runs to the cap
    on every execution, and is detectable at publish."""
    for agent_id, slug in (("agt_p", "loop-p"), ("agt_q", "loop-q")):
        await agents.post("/agents", json=simple(realm, project, agent_id, slug))

    res = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_stuck", "name": "S", "slug": "stuck",
                     "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_stuck", "version": "1.0.0",
            "steps": {"p": {"version_id": "agv_agt_p_1.0.0"},
                      "q": {"version_id": "agv_agt_q_1.0.0"}},
            "dependencies": [
                {"from_step": "p", "to_step": "q", "relationship": "depends_on"},
                {"from_step": "q", "to_step": "p", "relationship": "depends_on"}],
            "entry_steps": ["p"], "exit_steps": ["q"],
            "execution": {"max_iterations": 5},
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert res.status_code == 400
    assert "Rule 6.2" in res.json()["detail"]


async def test_a_bounded_cycle_halts_and_is_never_reported_as_success(
        agents, realm, project, db):
    """Rules 6.1 and 6.3 — exhaustion ends `halted`, and `halted` is not success
    at any layer, including the protocol edge."""
    for agent_id, slug in (("agt_l", "cyc-l"), ("agt_m", "cyc-m")):
        await agents.post("/agents", json=simple(
            realm, project, agent_id, slug, prompt="Reply with the word LOOP."))

    slug = "bounded-cycle-" + uuid.uuid4().hex[:6]
    published = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_cycle_" + uuid.uuid4().hex[:6],
                     "name": "Bounded Cycle", "slug": slug,
                     "telos": "A cycle that runs out.", "description": "x"},
        "version": {
            "pipeline_id": "pln_cycle", "version": "1.0.0",
            "steps": {"l": {"version_id": "agv_agt_l_1.0.0"},
                      "m": {"version_id": "agv_agt_m_1.0.0"}},
            "dependencies": [
                {"from_step": "l", "to_step": "m", "relationship": "depends_on",
                 "payload_map": {"result": "prompt"}},
                # `result` is always present, so this edge always fires and the
                # cycle only ends at the cap — which is the point.
                {"from_step": "m", "to_step": "l", "relationship": "on_condition",
                 "condition": "result", "payload_map": {"result": "prompt"}}],
            "entry_steps": ["l"], "exit_steps": ["m"],
            "execution": {"max_iterations": 4, "on_limit": "halt_and_return"},
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert published.status_code == 200, published.text
    assert published.json()["is_cyclic"] is True
    assert published.json()["back_edges"], "the back edge was not detected"

    # Over MCP: halted is an error, not a success.
    mcp = await agents.post(f"/mcp/tools/pipeline:{slug}@1.0.0/call", json={
        "org_id": realm, "project_id": project,
        "arguments": {"prompt": "begin"}})
    assert mcp.status_code == 200, mcp.text
    assert mcp.json()["status"] == "halted"
    assert mcp.json()["isError"] is True
    assert "max_iterations" in mcp.json()["halt_reason"]

    # Over A2A: halted surfaces as failed with a halt_reason (§11.5).
    a2a = await agents.post(f"/a2a/pipelines/{slug}/1.0.0/tasks", json={
        "org_id": realm, "project_id": project,
        "arguments": {"prompt": "begin"}})
    assert a2a.status_code == 200, a2a.text
    assert a2a.json()["state"] == "failed"
    assert a2a.json()["halt_reason"]

    import json
    rows = await db.fetch(f'SELECT payload FROM "{realm}".pipeline_runs')
    payload = rows[-1]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["status"] == "halted"
    assert payload["iteration_count"] == 4


# ------------------------------------------------------------- recursion

async def test_a_step_can_invoke_another_pipeline(agents, db, realm, project):
    """§6.3 — the edge is written at publish and followed by the executor.

    Recursion had a table, then a writer with no field to trigger it. This is
    the first path that exercises the whole mechanism.
    """
    # The inner pipeline, and the agent it runs.
    await agents.post("/agents", json=simple(
        realm, project, "agt_inner", "inner-worker",
        prompt="Reply with the single word INNER."))
    inner_slug = "inner-" + uuid.uuid4().hex[:6]
    inner = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_inner", "name": "Inner",
                     "slug": inner_slug, "telos": "The nested work.",
                     "description": "x"},
        "version": {
            "pipeline_id": "pln_inner", "version": "1.0.0",
            "steps": {"inner": {"version_id": "agv_agt_inner_1.0.0"}},
            "dependencies": [], "entry_steps": ["inner"], "exit_steps": ["inner"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert inner.status_code == 200, inner.text

    # An agent that declares it invokes that pipeline.
    caller = await agents.post("/agents", json={
        **simple(realm, project, "agt_caller", "outer-caller",
                 prompt="Reply with the single word OUTER."),
    })
    assert caller.status_code == 200, caller.text
    caller_v2 = simple(realm, project, "agt_caller", "outer-caller",
                       version="1.1.0", prompt="Reply with the single word OUTER.")
    caller_v2["version"]["invokes_pipeline"] = {"pipeline_id": "pln_inner",
                                                "version": "1.0.0"}
    assert (await agents.post("/agents", json=caller_v2)).status_code == 200

    outer_slug = "outer-" + uuid.uuid4().hex[:6]
    outer = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_outer", "name": "Outer",
                     "slug": outer_slug, "telos": "Calls the inner pipeline.",
                     "description": "x"},
        "version": {
            "pipeline_id": "pln_outer", "version": "1.0.0",
            "steps": {"call": {"version_id": "agv_agt_caller_1.1.0"}},
            "dependencies": [], "entry_steps": ["call"], "exit_steps": ["call"],
            "execution": {"max_recursion_depth": 2},
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert outer.status_code == 200, outer.text

    # The edge exists in the graph.
    edges = await db.fetchval(f'SELECT count(*) FROM "{realm}".invokes_pipeline')
    assert edges >= 1, "no invokes_pipeline edge was written"

    # And the executor follows it: two runs, parent and child.
    run = await agents.post(f"/mcp/tools/pipeline:{outer_slug}@1.0.0/call", json={
        "org_id": realm, "project_id": project, "arguments": {"prompt": "go"}})
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "succeeded", run.text

    import json
    rows = await db.fetch(f'SELECT payload FROM "{realm}".pipeline_runs')
    runs = []
    for row in rows:
        payload = row["payload"]
        runs.append(json.loads(payload) if isinstance(payload, str) else payload)
    children = [r for r in runs if r.get("parent_run_id")]
    assert children, "the nested run was not recorded"
    assert children[0]["depth"] == 1


# ------------------------------------------------------------ run linkage

async def test_a_run_is_linked_to_its_definition_and_its_steps(
        agents, db, realm, project):
    """§5 — `run_of` and `run_step`. Both had a writer that nothing called."""
    await agents.post("/agents", json=simple(
        realm, project, "agt_linked", "linked-agent", prompt="Reply with OK."))
    slug = "linked-" + uuid.uuid4().hex[:6]
    res = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_linked", "name": "Linked", "slug": slug,
                     "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_linked", "version": "1.0.0",
            "steps": {"only": {"version_id": "agv_agt_linked_1.0.0"}},
            "dependencies": [], "entry_steps": ["only"], "exit_steps": ["only"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert res.status_code == 200, res.text

    run = await agents.post(f"/mcp/tools/pipeline:{slug}@1.0.0/call", json={
        "org_id": realm, "project_id": project, "arguments": {"prompt": "go"}})
    assert run.json()["status"] == "succeeded", run.text

    assert await db.fetchval(f'SELECT count(*) FROM "{realm}".run_of') >= 1
    assert await db.fetchval(f'SELECT count(*) FROM "{realm}".run_step') >= 1

    import json
    edge = await db.fetchrow(f'SELECT payload FROM "{realm}".run_step LIMIT 1')
    payload = edge["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["step_id"] == "only"
    assert payload["status"] == "succeeded"


# ------------------------------------------------------------ retirement

async def test_revoking_a_pinned_version_needs_a_replacement_or_a_cascade(
        agents, realm, project):
    """Rule 4.4 — silent revocation breaks pipelines that report success."""
    await agents.post("/agents", json=simple(
        realm, project, "agt_pinned", "pinned-agent"))
    slug = "pinning-" + uuid.uuid4().hex[:6]
    assert (await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_pinning", "name": "P", "slug": slug,
                     "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_pinning", "version": "1.0.0",
            "steps": {"s": {"version_id": "agv_agt_pinned_1.0.0"}},
            "dependencies": [], "entry_steps": ["s"], "exit_steps": ["s"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})).status_code == 200

    blocked = await agents.post("/agents/agt_pinned/retire", json={
        "org_id": realm, "project_id": project, "version": "1.0.0",
        "status": "revoked"})
    assert blocked.status_code == 400
    assert "Rule 4.4" in blocked.json()["detail"]

    cascaded = await agents.post("/agents/agt_pinned/retire", json={
        "org_id": realm, "project_id": project, "version": "1.0.0",
        "status": "revoked", "cascade": True})
    assert cascaded.status_code == 200, cascaded.text
    assert cascaded.json()["cascaded"] == ["pln_pinning@1.0.0"]


async def test_a_dormant_agent_leaves_discovery_but_keeps_its_provenance(
        agents, db, realm, project):
    """Rule 3.2 — deletion is dormancy, because the spawns edges are the record."""
    await agents.post("/agents", json=simple(
        realm, project, "agt_parent2", "parent-two",
        telos="Reconciles supplier invoices against purchase orders."))
    await agents.post("/agents", json=simple(
        realm, project, "agt_kid", "kid-agent", telos="A child.",
        spawned_by="agt_parent2"))

    res = await agents.post("/agents/agt_parent2/lifecycle", json={
        "org_id": realm, "project_id": project, "lifecycle": "dormant"})
    assert res.status_code == 200, res.text

    found = await agents.get("/discover", params={
        "q": "reconcile supplier invoices", "org_id": realm,
        "project_id": project, "top_k": 5})
    assert "agt_parent2" not in [r["id"] for r in found.json()["results"]]

    # The agent and its edge are still there.
    assert await db.fetchval(
        f"SELECT count(*) FROM \"{realm}\".agents "
        f"WHERE payload->>'agent_id' = 'agt_parent2'") == 1
    assert await db.fetchval(f'SELECT count(*) FROM "{realm}".spawns') == 1


# -------------------------------------------------------------- @latest

async def test_latest_is_resolved_at_publish_and_stored_resolved(
        agents, realm, project):
    """§4.3 — a pipeline whose behaviour changes because a dependency was
    republished is not reproducible."""
    for version, prompt in (("1.0.0", "Reply with ONE."),
                            ("1.10.0", "Reply with TEN.")):
        assert (await agents.post("/agents", json=simple(
            realm, project, "agt_latest", "latest-agent",
            version=version, prompt=prompt))).status_code == 200

    slug = "latest-pin-" + uuid.uuid4().hex[:6]
    res = await agents.post("/pipelines", json={
        "org_id": realm, "project_id": project,
        "identity": {"pipeline_id": "pln_latest", "name": "L", "slug": slug,
                     "telos": "x", "description": "x"},
        "version": {
            "pipeline_id": "pln_latest", "version": "1.0.0",
            "steps": {"s": {"version_id": "agv_agt_latest_latest"}},
            "dependencies": [], "entry_steps": ["s"], "exit_steps": ["s"],
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT}})
    assert res.status_code == 200, res.text
    # Semver, not string order: 1.10.0 is newer than 1.0.0.
    assert res.json()["resolved_steps"]["s"]["version_id"] == "agv_agt_latest_1.10.0"


# --------------------------------------------------------------- exposure

async def test_only_published_versions_are_exposed(agents, realm, project):
    """Rule 7.4 — two lists that can disagree eventually will."""
    assert (await agents.post("/agents", json=simple(
        realm, project, "agt_live", "live-agent"))).status_code == 200
    assert (await agents.post("/agents", json=simple(
        realm, project, "agt_staged", "staged-agent",
        prompt="Reply with STAGED.", publish=False))).status_code == 200

    listed = await agents.get("/mcp/tools", params={"org_id": realm})
    names = {t["name"] for t in listed.json()["tools"]}
    assert "agent:live-agent@1.0.0" in names
    assert not any(n.startswith("agent:staged-agent") for n in names)

    card = await agents.get("/a2a/agents/staged-agent/1.0.0/card",
                            params={"org_id": realm})
    assert card.status_code == 404


async def test_the_registry_publishes_its_own_agent_card(agents, realm, project):
    """§7.2 — A2A clients look here first."""
    await agents.post("/agents", json=simple(
        realm, project, "agt_carded", "carded-agent",
        capabilities=["summarise"]))

    res = await agents.get("/.well-known/agent.json", params={"org_id": realm})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provenance"]["published_agents"] >= 1
    assert body["provenance"]["cards"].startswith("/a2a/")
    assert "summarise" in [s["id"] for s in body["skills"]]


async def test_an_agent_is_invocable_over_mcp_and_a2a(agents, realm, project):
    """Published means callable. The model really answers."""
    await agents.post("/agents", json=simple(
        realm, project, "agt_callable", "callable-agent",
        prompt="Reply with the single word PONG and nothing else."))

    mcp = await agents.post("/mcp/tools/agent:callable-agent@1.0.0/call", json={
        "org_id": realm, "project_id": project, "arguments": {"prompt": "ping"}})
    assert mcp.status_code == 200, mcp.text
    assert mcp.json()["isError"] is False
    assert "PONG" in mcp.json()["content"][0]["text"].upper()
    assert mcp.json()["usage"]["input_tokens"] > 0

    a2a = await agents.post("/a2a/agents/callable-agent/1.0.0/tasks", json={
        "org_id": realm, "project_id": project, "arguments": {"prompt": "ping"}})
    assert a2a.status_code == 200, a2a.text
    assert a2a.json()["state"] == "completed"


# --------------------------------------------------------- the legacy surface

async def test_the_original_registration_surface_still_works(
        agents, db, realm, project):
    """§13.3 — same request, same response, one store underneath."""
    res = await agents.post("/agents/register", json={
        "agent_id": "agt_legacy", "org_id": realm, "user_id": "user_1",
        "project_id": project, "name": "Legacy Agent", "caste": "archivist",
        "role": "worker", "telos": "Maintains the ledger of record.",
        "system_prompt": "You maintain records. Reply with OK.",
        "version": "v1.0.0", "token_balance": 500.0, "reputation_score": 77.0,
        "guardrails": [{"guardrail_id": "g1", "rule": "never disclose PII"}]})
    assert res.status_code == 200, res.text
    body = res.json()

    # The response shape the frontend and backend read is unchanged.
    for key in ("status", "agent_id", "caste", "parent_agent_id", "public_key",
                "hash_digest", "version", "total_versions"):
        assert key in body, key
    assert body["version"] == "v1.0.0"          # echoed as sent
    assert body["public_key"].startswith("ed25519:")

    # And it landed in the graph, not a second table.
    assert await db.fetchval(
        f"SELECT count(*) FROM \"{realm}\".agents "
        f"WHERE payload->>'agent_id' = 'agt_legacy'") == 1
    versions = await db.fetch(f'SELECT payload FROM "{realm}".agents_data')
    assert versions, "no version record was written"

    detail = await agents.get("/agents/agt_legacy",
                              params={"org_id": realm, "project_id": project})
    agent = detail.json()["agent"]
    assert agent["caste"] == "archivist"
    assert agent["token_balance"] == 500.0
    assert agent["reputation_score"] == 77.0
    assert agent["guardrails"][0]["rule"] == "never disclose PII"
    assert agent["system_prompt"].startswith("You maintain records")
    assert agent["version"] == "1.0.0"          # semver in the graph
    assert agent["content_hash"].startswith("sha256:")


async def test_auditing_moves_reputation_without_making_a_version(
        agents, db, realm, project):
    """§4.2 — auditing does not change what the agent does."""
    await agents.post("/agents/register", json={
        "agent_id": "agt_audited", "org_id": realm, "user_id": "u",
        "project_id": project, "name": "Audited", "telos": "Be audited.",
        "system_prompt": "Reply with OK.", "reputation_score": 50.0})
    before = await db.fetchval(f'SELECT count(*) FROM "{realm}".agents_data')

    res = await agents.post("/agents/agt_audited/audit", json={
        "org_id": realm, "project_id": project, "auditor_id": "agt_auditor",
        "reputation_delta": -20.0, "audit_notes": "Cut corners.",
        "passed_compliance": False})
    assert res.status_code == 200, res.text
    assert res.json()["new_reputation_score"] == 30.0

    after = await db.fetchval(f'SELECT count(*) FROM "{realm}".agents_data')
    assert after == before, "an audit must not append a version"


async def test_spending_a_balance_to_zero_makes_an_agent_dormant(
        agents, realm, project):
    """Economic death is dormancy, not deletion (Rule 3.2)."""
    await agents.post("/agents/register", json={
        "agent_id": "agt_broke", "org_id": realm, "user_id": "u",
        "project_id": project, "name": "Broke", "telos": "Run out of money.",
        "system_prompt": "Reply with OK.", "token_balance": 100.0})

    res = await agents.post("/agents/agt_broke/allocate-tokens", json={
        "org_id": realm, "project_id": project, "arbiter_id": "agt_arbiter",
        "amount": -100.0, "reason": "exhausted"})
    assert res.status_code == 200, res.text
    assert res.json()["new_token_balance"] == 0.0
    assert res.json()["lifecycle_status"] == "TERMINATED_ECONOMIC"

    listed = await agents.get("/agents", params={"org_id": realm})
    assert "agt_broke" not in [a["agent_id"] for a in listed.json()["agents"]]
    kept = await agents.get("/agents", params={"org_id": realm,
                                               "include_dormant": True})
    assert "agt_broke" in [a["agent_id"] for a in kept.json()["agents"]]


async def test_the_kagent_manifest_names_the_content_hash(agents, realm, project):
    """The manifest pins behaviour, not just a name."""
    await agents.post("/agents/register", json={
        "agent_id": "agt_manifest", "org_id": realm, "user_id": "u",
        "project_id": project, "name": "Manifest Agent",
        "telos": "Be deployed.", "system_prompt": "Reply with OK."})

    res = await agents.get("/agents/agt_manifest/kagent-manifest",
                           params={"org_id": realm, "project_id": project})
    assert res.status_code == 200, res.text
    spec = res.json()["manifest_object"]["spec"]
    assert spec["cryptographicBinding"]["contentHash"].startswith("sha256:")
    assert spec["version"] == "1.0.0"
    assert "yaml_manifest" in res.json()
