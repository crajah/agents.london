"""Proving tool lookup by RAG, and invocation, end to end against the real stack.

Nothing here is stubbed. Tools are registered into a live PostgreSQL, embedded
by the real `text-embedding-3-small`, searched through real pgvector, and
dispatched to real HTTP endpoints on other real services.

The endpoints the tools point at are deliberately genuine:

  - the document registry's `/query` — a real GraphRAG lookup;
  - the document registry's text upload — a real, side-effecting write;
  - the model router's `/v1/chat/completions` — a real third-party-shaped API.

That makes `POST /tools/{id}/call` a real cross-service call rather than a
round trip to a fixture.
"""
import uuid

import pytest

from conftest import (
    CHAT_MODEL, ROUTER, ROUTER_AUTH, object_schema, requires_stack, tool_body,
)

pytestmark = [pytest.mark.e2e, requires_stack]


# --------------------------------------------------------------- a corpus

def seed(realm: str, documents_url: str, project: str):
    """Five tools with genuinely distinct purposes.

    The descriptions share no vocabulary with each other, so a retrieval that
    ranks the right one first is evidence about the wiring rather than luck.
    """
    return [
        tool_body(
            org=realm, tool_id="mcp-vector-memory",
            name="Knowledge Base Semantic Search",
            description=("Searches indexed documents and knowledge graphs to "
                         "retrieve passages relevant to a natural language "
                         "question. Use it to find what the corpus says about "
                         "a topic."),
            capabilities=["retrieve", "semantic_search"],
            endpoint=f"{documents_url}/query", side_effects="read",
            input_schema=object_schema({
                "org_id": {"type": "string"},
                "project_id": {"type": "string"},
                "query": {"type": "string", "description": "the question to answer"},
                "top_k": {"type": "integer"},
                "mode": {"type": "string"}}, ["project_id", "query"]),
            output_schema=object_schema({"data": {"type": "object"},
                                         "engine": {"type": "string"}})),
        tool_body(
            org=realm, tool_id="mcp-invoice-reconciler",
            name="Supplier Invoice Reconciliation",
            description=("Matches supplier invoices against purchase orders and "
                         "goods received notes, flagging price and quantity "
                         "discrepancies for the accounts payable ledger."),
            capabilities=["reconcile", "accounting"],
            endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
            side_effects="external", auth=ROUTER_AUTH),
        tool_body(
            org=realm, tool_id="mcp-cluster-operator",
            name="Kubernetes Cluster Operator",
            description=("Inspects pods, deployments and rollout status on the "
                         "Kubernetes API server, and restarts failed workloads."),
            capabilities=["operate", "inspect"],
            endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
            side_effects="write", auth=ROUTER_AUTH),
        tool_body(
            org=realm, tool_id="mcp-translate",
            name="Human Language Translation",
            description=("Translates prose between human languages, preserving "
                         "tone and idiom."),
            capabilities=["translate"],
            endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
            side_effects="external", auth=ROUTER_AUTH),
        tool_body(
            org=realm, tool_id="mcp-timeseries-forecast",
            name="Time Series Forecasting",
            description=("Fits seasonal models to historical numeric series and "
                         "projects future values with confidence intervals."),
            capabilities=["forecast"],
            endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
            side_effects="read", auth=ROUTER_AUTH),
    ]


async def register_all(tools, bodies):
    for body in bodies:
        res = await tools.post("/tools/register", json=body)
        assert res.status_code == 200, res.text


# ------------------------------------------------------- RAG lookup proper

async def test_a_natural_language_query_finds_the_right_tool(
        tools, documents, realm, project):
    """The headline: a caller says what it needs, and gets the tool that does it.

    No keyword matching — the query shares almost no vocabulary with the tool's
    own description ("what does the corpus say" vs "searches indexed documents
    and knowledge graphs"). The match comes from the embedding.
    """
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.get("/tools/search", params={
        "q": "I need to look up what our documents say about a subject",
        "org_id": realm, "top_k": 3})
    assert res.status_code == 200, res.text
    found = res.json()["tools"]
    assert found, "vector search returned nothing"
    assert found[0]["tool_id"] == "mcp-vector-memory", \
        f"ranked {[t['tool_id'] for t in found]}"


@pytest.mark.parametrize("query,expected", [
    ("check supplier bills against what we ordered", "mcp-invoice-reconciler"),
    ("something is wrong with the pods in my cluster", "mcp-cluster-operator"),
    ("render this paragraph into French", "mcp-translate"),
    ("predict next quarter's numbers from history", "mcp-timeseries-forecast"),
    ("search the knowledge base for relevant passages", "mcp-vector-memory"),
])
async def test_each_intent_retrieves_its_own_tool(
        tools, documents, realm, project, query, expected):
    """Five different intents, five different tools, one index."""
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.get("/tools/search",
                          params={"q": query, "org_id": realm, "top_k": 5})
    ranked = [t["tool_id"] for t in res.json()["tools"]]
    assert ranked and ranked[0] == expected, f"{query!r} ranked {ranked}"


async def test_search_returns_a_pin_so_the_caller_can_bind_it(
        tools, documents, realm, project):
    """Rule 5.2 — a caller that wants to pin needs the version and the hash,
    and a second round trip to get them is a race."""
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.get("/tools/search", params={
        "q": "search indexed knowledge", "org_id": realm, "top_k": 1})
    top = res.json()["tools"][0]
    assert top["pin"]["tool_id"] == top["tool_id"]
    assert top["pin"]["version"] == "1.0.0"
    assert top["pin"]["content_hash"].startswith("sha256:")


async def test_discovery_never_returns_a_tool_the_caller_cannot_invoke(
        tools, documents, realm, project):
    """Rule 5.1 — returning one teaches an agent to plan around a capability
    it does not have."""
    other_project = "proj_" + uuid.uuid4().hex[:8]
    await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-private-ledger", name="Private Ledger Access",
        description=("Reads the confidential general ledger and trial balance "
                     "for statutory reporting."),
        scope_type="project", project=other_project,
        endpoint=f"{ROUTER.rstrip('/')}/chat/completions", side_effects="read"))

    # Asking from a different project, with wording aimed straight at it.
    res = await tools.get("/tools/search", params={
        "q": "read the confidential general ledger and trial balance",
        "org_id": realm, "project_id": project, "top_k": 5})
    assert [t["tool_id"] for t in res.json()["tools"]] == []

    # And from its own project, it is right there.
    res = await tools.get("/tools/search", params={
        "q": "read the confidential general ledger and trial balance",
        "org_id": realm, "project_id": other_project, "top_k": 5})
    assert [t["tool_id"] for t in res.json()["tools"]] == ["mcp-private-ledger"]


async def test_a_dormant_tool_leaves_the_index(tools, documents, realm, project):
    await register_all(tools, seed(realm, documents.service.url, project))

    before = await tools.get("/tools/search", params={
        "q": "translate this text into another language", "org_id": realm})
    assert before.json()["tools"][0]["tool_id"] == "mcp-translate"

    assert (await tools.delete("/tools/mcp-translate",
                               params={"org_id": realm})).status_code == 200

    after = await tools.get("/tools/search", params={
        "q": "translate this text into another language", "org_id": realm})
    assert "mcp-translate" not in [t["tool_id"] for t in after.json()["tools"]]


async def test_dormancy_survives_a_restart_because_it_is_in_the_database(
        tools, db, realm, documents, project):
    """Rule 9.2 — the delete that used to mutate a dict came back on restart."""
    await register_all(tools, seed(realm, documents.service.url, project))
    await tools.delete("/tools/mcp-translate", params={"org_id": realm})

    row = await db.fetchrow(
        f'SELECT payload FROM "{realm}".mcp_tools '
        f"WHERE payload->>'tool_id' = 'mcp-translate'")
    import json
    payload = row["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["lifecycle"] == "dormant"


# ------------------------------------------------------- the RAG export

async def test_tools_render_as_documents_for_rag_indexing(
        tools, documents, realm, project):
    """§5.1 — tool selection can be part of ordinary retrieval."""
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.get("/tools/rag-documents", params={"org_id": realm})
    body = res.json()
    assert body["count"] == 5
    one = next(d for d in body["documents"] if d["tool_id"] == "mcp-vector-memory")
    assert "Version: 1.0.0" in one["content"]
    assert "Side Effects: read" in one["content"]
    assert "Input Schema Parameters" in one["content"]


# ----------------------------------------------------------- invocation

async def test_a_discovered_tool_can_then_be_invoked(
        tools, documents, realm, project):
    """Discovery and invocation are the same registry: found it, now call it.

    The call reaches the document registry over real HTTP and comes back with
    that service's real answer.
    """
    await register_all(tools, seed(realm, documents.service.url, project))

    found = (await tools.get("/tools/search", params={
        "q": "look up what our documents say", "org_id": realm, "top_k": 1})
    ).json()["tools"][0]

    res = await tools.post(f"/tools/{found['tool_id']}/call", json={
        "org_id": realm, "project_id": project,
        "arguments": {"org_id": realm, "project_id": project,
                      "query": "anything at all", "top_k": 3, "mode": "naive"},
        "caller": {"agent_id": "agt_probe", "run_id": "run_probe"}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["version"] == "1.0.0"
    # The far end really answered: this is the document registry's own shape.
    assert "engine" in body["result"] or "data" in body["result"]


async def test_arguments_are_validated_before_dispatch(
        tools, documents, realm, project):
    """Rule 7.1 — a tool receiving an undeclared shape fails confusingly or
    succeeds on the wrong thing."""
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.post("/tools/mcp-vector-memory/call", json={
        "org_id": realm, "project_id": project,
        "arguments": {"project_id": project}})          # no `query`
    assert res.status_code == 400
    assert "query" in res.json()["detail"]


async def test_a_side_effecting_tool_requires_an_idempotency_key(
        tools, documents, realm, project):
    """Rule 6.2 — at-least-once delivery means the effect happens at least once."""
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.post("/tools/mcp-cluster-operator/call", json={
        "org_id": realm, "project_id": project,
        "arguments": {"query": "get pods"}})
    assert res.status_code == 400
    assert "idempotency_key" in res.json()["detail"]


async def test_a_read_only_tool_needs_no_key(tools, documents, realm, project):
    await register_all(tools, seed(realm, documents.service.url, project))
    res = await tools.post("/tools/mcp-vector-memory/call", json={
        "org_id": realm, "project_id": project,
        "arguments": {"org_id": realm, "project_id": project, "query": "x",
                      "mode": "naive"}})
    assert res.status_code == 200, res.text


async def test_an_out_of_scope_tool_cannot_be_invoked_by_probing(
        tools, realm, project):
    """404 rather than 403: existence must not be confirmable from outside."""
    other = "proj_" + uuid.uuid4().hex[:8]
    await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-scoped", name="Scoped",
        description="Only this project may call it.",
        scope_type="project", project=other,
        endpoint=f"{ROUTER.rstrip('/')}/chat/completions"))

    res = await tools.post("/tools/mcp-scoped/call", json={
        "org_id": realm, "project_id": project, "arguments": {"query": "x"}})
    assert res.status_code == 404


async def test_a_failing_endpoint_is_reported_not_invented(tools, realm, project):
    """Rule 7.2 — the registry must never manufacture a plausible result.

    The endpoint points at a port nothing is listening on, which is a real
    connection failure rather than a simulated one.
    """
    await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-unreachable", name="Unreachable",
        description="Points at a port with nothing behind it.",
        endpoint="http://127.0.0.1:9/nothing", side_effects="read",
        limits={"timeout_secs": 5}))

    res = await tools.post("/tools/mcp-unreachable/call", json={
        "org_id": realm, "project_id": project, "arguments": {"query": "x"}})
    assert res.status_code == 502
    assert "unreachable" in res.json()["detail"].lower()


async def test_reputation_is_enforced_against_the_live_agent_registry(
        tools, agents, realm, project):
    """Rule 6.1 — the threshold was stored and never evaluated. It is now, and
    the score comes from the agent registry over real HTTP."""
    # The declared schema matches what the endpoint really takes, because the
    # registry validates against it before dispatch (Rule 7.1) — a tool whose
    # declaration lies about its own contract fails at the far end instead.
    gated = tool_body(
        org=realm, tool_id="mcp-restricted", name="Restricted Operation",
        description="Only well regarded agents may call this.",
        endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
        side_effects="read", min_reputation_score=90.0, auth=ROUTER_AUTH,
        input_schema=object_schema(
            {"model": {"type": "string"},
             "messages": {"type": "array", "description": "the conversation"},
             "max_tokens": {"type": "integer"}},
            ["model", "messages"]),
        output_schema=object_schema({"choices": {"type": "array"}}))
    assert (await tools.post("/tools/register", json=gated)).status_code == 200

    call_arguments = {"model": CHAT_MODEL, "max_tokens": 5,
                      "messages": [{"role": "user", "content": "Say OK"}]}

    # A real agent, registered through the real registry, with a low score.
    low = await agents.post("/agents/register", json={
        "agent_id": "agt_lowly", "org_id": realm, "user_id": "u", "project_id": project,
        "name": "Lowly Agent", "telos": "Do small things.",
        "system_prompt": "You do small things.", "reputation_score": 10.0})
    assert low.status_code == 200, low.text

    denied = await tools.post("/tools/mcp-restricted/call", json={
        "org_id": realm, "project_id": project, "arguments": call_arguments,
        "caller": {"agent_id": "agt_lowly"}})
    assert denied.status_code == 403
    assert "10.0" in denied.json()["detail"]

    trusted = await agents.post("/agents/register", json={
        "agent_id": "agt_trusted", "org_id": realm, "user_id": "u",
        "project_id": project, "name": "Trusted Agent",
        "telos": "Do important things.",
        "system_prompt": "You do important things.", "reputation_score": 99.0})
    assert trusted.status_code == 200, trusted.text

    allowed = await tools.post("/tools/mcp-restricted/call", json={
        "org_id": realm, "project_id": project,
        "arguments": call_arguments,
        "caller": {"agent_id": "agt_trusted"}})
    assert allowed.status_code == 200, allowed.text


async def test_an_anonymous_caller_cannot_pass_a_reputation_gate(
        tools, realm, project):
    """Fails closed: an unverified caller is the case the threshold is for."""
    await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-gated", name="Gated",
        description="Requires standing.",
        endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
        min_reputation_score=50.0))

    res = await tools.post("/tools/mcp-gated/call", json={
        "org_id": realm, "project_id": project, "arguments": {"query": "x"}})
    assert res.status_code == 403
    assert "no calling agent" in res.json()["detail"]


# ------------------------------------------------------------- accounting

async def ledger(db, realm, minimum: int = 1, seconds: float = 25.0):
    """The realm's usage events, once the batched meter has flushed.

    The meter is a bounded queue drained on a timer (AG Rule 12.2) — it never
    blocks the operation it measures, so a test must wait for it rather than
    expect a synchronous write.
    """
    import asyncio
    import json
    rows = []
    deadline = seconds / 0.5
    while deadline > 0:
        await asyncio.sleep(0.5)
        deadline -= 1
        try:
            rows = await db.fetch(f'SELECT payload FROM "{realm}".usage_events')
        except Exception:
            continue                       # the table appears on the first flush
        if len(rows) >= minimum:
            break
    kinds = {}
    for row in rows:
        payload = row["payload"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        kinds.setdefault(payload["kind"], []).append(payload)
    return kinds


async def test_invoking_a_tool_writes_usage_events(
        tools, documents, db, realm, project):
    """§11 — `search_query` before dispatch, `search_results` after.

    Rule 11.2 keeps them as separate rows: a cheap query can return an
    expensive result, and one combined counter cannot be billed apart later.
    """
    await register_all(tools, seed(realm, documents.service.url, project))

    for _ in range(3):
        res = await tools.post("/tools/mcp-vector-memory/call", json={
            "org_id": realm, "project_id": project,
            "arguments": {"org_id": realm, "project_id": project,
                          "query": "billing", "mode": "naive"},
            "caller": {"agent_id": "agt_probe", "run_id": "run_1"}})
        assert res.status_code == 200, res.text

    kinds = await ledger(db, realm, minimum=9)

    assert len(kinds.get("search_query", [])) == 3
    assert len(kinds.get("search_results", [])) == 3

    query, result = kinds["search_query"][0], kinds["search_results"][0]
    for event in (query, result):
        assert event["org_id"] == realm
        assert event["project_id"] == project
        assert event["agent_id"] == "agt_probe"        # Rule 11.3
    # The result of a search is bigger than the query that asked for it, which
    # is the whole reason they are billed apart.
    assert result["bytes"] > query["bytes"] > 0


async def test_each_service_meters_only_its_own_kinds(
        tools, documents, db, realm, project):
    """AG Rule 12.0 — a kind has one emitter, or the ledger double-bills.

    One tool call crosses two services. The tool registry books the search; the
    document registry books the retrieval it performed. Neither books the
    other's, and both land in the same per-organisation ledger.
    """
    await register_all(tools, seed(realm, documents.service.url, project))

    res = await tools.post("/tools/mcp-vector-memory/call", json={
        "org_id": realm, "project_id": project,
        "arguments": {"org_id": realm, "project_id": project,
                      "query": "anything", "mode": "naive"},
        "caller": {"agent_id": "agt_probe", "run_id": "run_2"}})
    assert res.status_code == 200, res.text

    kinds = await ledger(db, realm, minimum=3)

    assert len(kinds.get("search_query", [])) == 1      # the tool registry
    assert len(kinds.get("search_results", [])) == 1    # the tool registry
    assert len(kinds.get("rag_lookup", [])) == 1        # the document registry

    # The document registry does not know the calling agent — it was called by
    # the tool registry, not by the agent — so its event carries no agent_id.
    # That is the honest record, not a gap: attributing it would be a guess.
    assert kinds["rag_lookup"][0]["agent_id"] is None
    assert kinds["search_query"][0]["agent_id"] == "agt_probe"
