"""The backend, end to end, against the real registries.

The backend fronts the three registries. Until now it had no test at all, and
three of its endpoints answered without ever calling anything:

  - `GET /api/mcp/v1/tools` returned a hardcoded list of six tools that existed
    nowhere else in the system;
  - `POST /api/mcp/v1/tools/call` answered `status: success` for any name it did
    not recognise, with an invented response, a fabricated `ed25519:` signature
    and a made-up latency — and returned an invented *search result*, complete
    with a google.com link, whenever the search tool was unreachable;
  - `POST /api/a2a/v1/dispatch` reported `delivered` with a fabricated
    acknowledgement without contacting the target.

These tests hold that shut. Everything runs against the live database, the real
model router and the real registry processes.
"""
import uuid

import pytest

from conftest import (
    ROUTER, ROUTER_AUTH, TEXT_IN, TEXT_OUT, agent_body, object_schema,
    requires_stack, tool_body,
)

pytestmark = [pytest.mark.e2e, requires_stack]

# The backend's key format is four groups of four uppercase alphanumerics.
API_KEY = "TEST-KEY0-0000-0001"
AUTH = {"X-Project-API-Key": API_KEY}


# --------------------------------------------------------------- the backend

@pytest.fixture
def backend(stack, monkeypatch):
    """The real backend app, pointed at the running registries.

    Imported here rather than in `conftest` because it is heavy — it pulls in
    the civilization engine — and only this file needs it.
    """
    import importlib
    import os
    import pathlib
    import sys

    os.environ["TOOL_REGISTRY_URL"] = stack["tool"].url
    os.environ["AGENT_REGISTRY_URL"] = stack["agent"].url
    os.environ["DOCUMENT_REGISTRY_URL"] = stack["document"].url

    root = pathlib.Path(__file__).resolve().parents[1]
    for path in (str(root), str(root / "backend")):
        if path not in sys.path:
            sys.path.insert(0, path)

    main = importlib.import_module("backend.main")
    # The URLs are read at import time, so a module already imported by an
    # earlier test would hold stale ones. The engine holds its own copy —
    # it talks to the registry directly — so it is pointed at the same place.
    main.TOOL_REGISTRY_URL = stack["tool"].url
    main.AGENT_REGISTRY_URL = stack["agent"].url
    main.DOCUMENT_REGISTRY_URL = stack["document"].url
    for module_name in ("backend.civilization", "backend.civilization_adk"):
        module = sys.modules.get(module_name)
        if module and hasattr(module, "AGENT_REGISTRY_URL"):
            module.AGENT_REGISTRY_URL = stack["agent"].url
    return main


@pytest.fixture
async def api(backend):
    import httpx
    transport = httpx.ASGITransport(app=backend.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://backend", timeout=180.0) as client:
        yield client


# ------------------------------------------------------------------- models

async def test_the_backend_reports_the_configured_models(api):
    """One canonical pair, so the UI cannot preselect a model nothing runs."""
    res = await api.get("/api/models")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["default_model"] == "gemini-3.5-flash-lite"
    assert body["embedding_model"] == "gemini-embedding-001"
    assert body["embedding_dim"] == 1536


async def test_the_model_list_comes_from_the_real_router(api):
    """It asks the router rather than reciting a list that goes stale."""
    res = await api.get("/api/models")
    body = res.json()
    assert body["source"] == "litellm_router", body.get("warning")
    served = {m["id"] for m in body["models"]}
    assert "gemini-3.5-flash-lite" in served
    assert "gemini-embedding-001" in served


async def test_the_configured_models_are_the_ones_the_engine_uses():
    """The constants the whole backend reads, not a per-module opinion."""
    from backend import env_config
    assert env_config.DEFAULT_LLM_MODEL == "gemini-3.5-flash-lite"
    assert env_config.RAG_MODEL == "gemini-3.5-flash-lite"
    assert env_config.EMBEDDING_MODEL == "gemini-embedding-001"
    assert env_config.EMBEDDING_DIM == 1536


# ------------------------------------------------------------- the MCP surface

async def test_the_mcp_catalogue_is_the_registries_not_a_hardcoded_list(
        api, tools, agents, realm, project):
    """Every listed tool exists in a registry and is callable (AG Rule 7.4)."""
    assert (await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-backend-probe", name="Backend Probe",
        description="A tool registered for the backend catalogue test.",
        endpoint=f"{ROUTER.rstrip('/')}/chat/completions",
        side_effects="read", auth=ROUTER_AUTH))).status_code == 200

    assert (await agents.post("/agents", json=agent_body(
        org=realm, project=project, agent_id="agt_backend_probe",
        name="Backend Probe Agent", slug="backend-probe-agent",
        telos="Answer probes from the backend.",
        description="An agent registered for the backend catalogue test.",
        prompt="Reply with the single word PROBE."))).status_code == 200

    res = await api.get("/api/mcp/v1/tools",
                        params={"org_id": realm, "project_id": project})
    assert res.status_code == 200, res.text
    body = res.json()
    names = {t["name"] for t in body["tools"]}

    # From the tool registry, and from the agent registry.
    assert "mcp-backend-probe" in names
    assert "agent:backend-probe-agent@1.0.0" in names

    # None of the six invented tools survive.
    for invented in ("agent_prime_orchestrator", "agent_master_strategist",
                     "agent_anomaly_detector", "agent_grand_critic",
                     "mcp_google_search", "mcp_document_rag_query"):
        assert invented not in names, f"{invented} is still being advertised"

    registries = {t["registry"] for t in body["tools"]}
    assert registries <= {"agent-registry", "tool-registry"}


async def test_an_unreachable_registry_is_reported_not_hidden(api, monkeypatch,
                                                              realm, project):
    """A short list that looks complete is worse than one that says what is missing."""
    from backend import main
    monkeypatch.setattr(main, "TOOL_REGISTRY_URL", "http://127.0.0.1:9")

    res = await api.get("/api/mcp/v1/tools",
                        params={"org_id": realm, "project_id": project})
    assert res.status_code == 200
    body = res.json()
    assert body.get("warning")
    assert any(u["registry"] == "tool-registry" for u in body["unavailable"])


async def test_calling_an_agent_through_the_backend_really_runs_it(
        api, agents, realm, project):
    """The model answers, and the answer is the agent's — not a template."""
    assert (await agents.post("/agents", json=agent_body(
        org=realm, project=project, agent_id="agt_echo", name="Echo",
        slug="echo-agent", telos="Answer with one fixed word.",
        description="An agent that replies with one fixed word.",
        prompt="Reply with the single word ECHOED and nothing else."))
    ).status_code == 200

    res = await api.post("/api/mcp/v1/tools/call", headers=AUTH, json={
        "org_id": realm, "project_id": project,
        "tool_name": "agent:echo-agent@1.0.0",
        "arguments": {"prompt": "say it"}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["isError"] is False
    assert "ECHOED" in body["content"][0]["text"].upper()
    assert body["usage"]["input_tokens"] > 0


async def test_calling_a_tool_through_the_backend_reaches_the_tool(
        api, tools, documents, realm, project):
    """A real cross-service hop: backend -> tool registry -> document registry."""
    assert (await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-kb-search", name="Knowledge Search",
        description="Searches the indexed corpus.",
        endpoint=f"{documents.service.url}/query", side_effects="read",
        input_schema=object_schema(
            {"org_id": {"type": "string"}, "project_id": {"type": "string"},
             "query": {"type": "string"}, "mode": {"type": "string"}},
            ["project_id", "query"])))).status_code == 200

    res = await api.post("/api/mcp/v1/tools/call", headers=AUTH, json={
        "org_id": realm, "project_id": project, "tool_name": "mcp-kb-search",
        "arguments": {"org_id": realm, "project_id": project,
                      "query": "anything", "mode": "naive"},
        "caller": {"agent_id": "agt_backend", "run_id": "run_backend"}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["tool"] == "mcp-kb-search"
    # The document registry's own shape came back through two hops.
    assert "engine" in body["result"] or "data" in body["result"]


async def test_an_unknown_tool_is_a_failure_not_an_invented_success(
        api, realm, project):
    """The handler used to answer `status: success` for any name at all."""
    res = await api.post("/api/mcp/v1/tools/call", headers=AUTH, json={
        "org_id": realm, "project_id": project,
        "tool_name": "agent_completely_made_up",
        "arguments": {"prompt": "hello"}})
    assert res.status_code >= 400, res.text
    body = res.json()
    assert "success" not in str(body).lower() or res.status_code >= 400
    assert "ed25519:mcp_sig" not in str(body)


async def test_an_unreachable_search_tool_does_not_invent_results(
        api, tools, realm, project):
    """Rule 7.2 — an agent cannot tell fabricated evidence from real evidence.

    The old handler answered with a made-up snippet and a google.com link,
    described as retrieved from inside the cluster.
    """
    assert (await tools.post("/tools/register", json=tool_body(
        org=realm, tool_id="mcp-google-search", name="Search",
        description="Web search.", endpoint="http://127.0.0.1:9/search",
        side_effects="external", limits={"timeout_secs": 5}))).status_code == 200

    res = await api.post("/api/mcp/v1/tools/call", headers=AUTH, json={
        "org_id": realm, "project_id": project, "tool_name": "mcp_google_search",
        "arguments": {"query": "anything"}, "idempotency_key": "k1"})
    assert res.status_code >= 400, res.text
    body = str(res.json())
    assert "google.com/search" not in body
    assert "Retrieved web search results" not in body


async def test_the_mcp_surface_still_requires_a_project_key(api, realm, project):
    unauthenticated = await api.post("/api/mcp/v1/tools/call", json={
        "org_id": realm, "project_id": project, "tool_name": "anything",
        "arguments": {}})
    assert unauthenticated.status_code == 401

    malformed = await api.post("/api/mcp/v1/tools/call",
                               headers={"X-Project-API-Key": "not-a-key"},
                               json={"org_id": realm, "project_id": project,
                                     "tool_name": "anything", "arguments": {}})
    assert malformed.status_code == 400


# --------------------------------------------------------------------- A2A

async def test_a2a_dispatch_really_delivers(api, agents, realm, project):
    """The target answers, and its answer comes back."""
    assert (await agents.post("/agents", json=agent_body(
        org=realm, project=project, agent_id="agt_target", name="Target",
        slug="target-agent", telos="Receive delegated work.",
        description="An agent that receives A2A tasks.",
        prompt="Reply with the single word RECEIVED and nothing else."))
    ).status_code == 200

    res = await api.post("/api/a2a/v1/dispatch", headers=AUTH, json={
        "org_id": realm, "project_id": project,
        "sender_agent_id": "agt_sender", "target_agent_id": "agt_target",
        "payload": {"prompt": "please handle this"}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "completed"
    assert body["status"] == "delivered"
    assert body["target_card"] == "/a2a/agents/target-agent/1.0.0/card"
    # The real answer, not an acknowledgement template.
    text = str(body["response"])
    assert "RECEIVED" in text.upper()
    assert "ed25519:a2a_ack" not in text


async def test_a2a_to_an_unregistered_agent_is_not_delivered(api, realm, project):
    """It used to report `delivered` for any target id at all."""
    res = await api.post("/api/a2a/v1/dispatch", headers=AUTH, json={
        "org_id": realm, "project_id": project,
        "sender_agent_id": "agt_sender", "target_agent_id": "agt_does_not_exist",
        "payload": {"prompt": "hello"}})
    assert res.status_code == 404, res.text
    assert "not registered" in res.json()["detail"]


# --------------------------------------------------------------- discovery

async def test_backend_discovery_prefers_registered_agents(
        api, agents, realm, project):
    """The registry can answer "which agent can I call"; the archetype list cannot."""
    for agent_id, slug, telos in [
        ("agt_reconciler", "invoice-reconciler",
         "Reconciles supplier invoices against purchase orders and flags "
         "discrepancies."),
        ("agt_translator2", "language-translator",
         "Translates prose between human languages."),
    ]:
        assert (await agents.post("/agents", json=agent_body(
            org=realm, project=project, agent_id=agent_id, name=slug.title(),
            slug=slug, telos=telos, description=telos,
            prompt="Reply with OK."))).status_code == 200

    res = await api.post("/api/agents/discover", json={
        "org_id": realm, "project_id": project,
        "query": "check supplier bills against what we ordered"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "agent-registry"

    top = body["discovered_agents"][0]
    assert top["agent_id"] == "agt_reconciler"
    # What a caller needs in order to pin and invoke it.
    assert top["registered"] is True
    assert top["version"] == "1.0.0"
    assert top["content_hash"].startswith("sha256:")
    assert top["mcp_tool"] == "agent:invoice-reconciler@1.0.0"


async def test_a_discovered_agent_can_be_invoked_by_the_name_discovery_gave(
        api, agents, realm, project):
    """Discovery and invocation join up: no translation step in between."""
    assert (await agents.post("/agents", json=agent_body(
        org=realm, project=project, agent_id="agt_summariser",
        name="Summariser", slug="doc-summariser",
        telos="Writes short summaries of long documents.",
        description="Writes short summaries of long documents.",
        prompt="Reply with the single word SUMMARISED."))).status_code == 200

    found = await api.post("/api/agents/discover", json={
        "org_id": realm, "project_id": project,
        "query": "shorten this long document for me"})
    tool_name = found.json()["discovered_agents"][0]["mcp_tool"]

    ran = await api.post("/api/mcp/v1/tools/call", headers=AUTH, json={
        "org_id": realm, "project_id": project, "tool_name": tool_name,
        "arguments": {"prompt": "a long document"}})
    assert ran.status_code == 200, ran.text
    assert "SUMMARISED" in ran.json()["content"][0]["text"].upper()


# ------------------------------------------------------- document proxying

async def test_the_backend_creates_and_lists_document_spaces(
        api, documents, realm, project):
    created = await api.post(f"/api/projects/{project}/spaces",
                             params={"space_name": "backend_docs",
                                     "org_id": realm,
                                     "description": "Made through the backend."})
    assert created.status_code == 200, created.text
    assert created.json()["document_space"] == "backend_docs"

    listed = await api.get(f"/api/projects/{project}/spaces",
                           params={"org_id": realm})
    assert listed.status_code == 200
    names = {s["document_space"] for s in listed.json()["spaces"]}
    assert "backend_docs" in names


async def test_ingesting_through_the_backend_reaches_the_corpus(
        api, documents, realm, project):
    uploaded = await api.post(
        f"/api/projects/{project}/spaces/backend_docs/documents/upload-text",
        params={"document_name": "note.md", "org_id": realm,
                "content": ("The Tallinn depot completed its automation "
                            "programme ahead of schedule.")})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["indexed"] is True

    found = await api.post(f"/api/projects/{project}/rag/query",
                           params={"query": "What happened at the Tallinn depot?",
                                   "org_id": realm})
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["status"] in {"success", "degraded"}
    chunks = body["data"].get("chunks") or []
    assert chunks, "the corpus returned nothing for a document it holds"
    assert "tallinn" in " ".join(str(c.get("content", "")) for c in chunks).lower()


async def test_an_unreachable_document_registry_is_not_reported_as_success(
        api, monkeypatch, realm, project):
    """It used to answer `status: success` and describe an ingest that never happened."""
    from backend import main
    monkeypatch.setattr(main, "DOCUMENT_REGISTRY_URL", "http://127.0.0.1:9")

    res = await api.post(
        f"/api/projects/{project}/spaces/notes/documents/upload-text",
        params={"document_name": "lost.md", "org_id": realm,
                "content": "This never reached the corpus."})
    assert res.status_code == 502, res.text
    assert "did not happen" in res.json()["detail"]

    query = await api.post(f"/api/projects/{project}/rag/query",
                           params={"query": "anything", "org_id": realm})
    assert query.status_code == 502
    assert "empty corpus" in query.json()["detail"]


async def test_a_file_the_ladder_cannot_read_is_rejected_through_the_backend(
        api, documents, realm, project):
    """Rule 5.3 travels all the way out: 415, and nothing stored."""
    unreadable = bytes(range(256)) * 8
    res = await api.post(
        f"/api/projects/{project}/spaces/backend_docs/documents/upload-file",
        params={"org_id": realm},
        files={"file": ("mystery.bin", unreadable, "application/octet-stream")})
    assert res.status_code == 415, res.text
    assert "mystery.bin" in res.json()["detail"]


async def test_backend_document_calls_are_scoped_to_the_realm(api, documents,
                                                              project):
    """Two organisations, one project id, no leakage."""
    left = "t_" + uuid.uuid4().hex[:10]
    right = "t_" + uuid.uuid4().hex[:10]

    for realm, text in ((left, "The left organisation runs a plant in Turin."),
                        (right, "The right organisation runs a plant in Porto.")):
        res = await api.post(
            f"/api/projects/{project}/spaces/notes/documents/upload-text",
            params={"document_name": "secret.md", "org_id": realm, "content": text})
        assert res.status_code == 200, res.text

    for realm, expected in ((left, "Turin"), (right, "Porto")):
        listed = await api.get(f"/api/projects/{project}/documents",
                               params={"org_id": realm})
        docs = listed.json()["documents"]
        assert len(docs) == 1
        assert docs[0]["org_id"] == realm


# --------------------------------------------------------------- guardrails

async def test_guardrails_come_from_the_agents_that_carry_them(api, realm, project):
    """The panel used to render three rules written into the browser.

    They named the project, so they read as though they had been discovered
    from its constitution. Nothing had been discovered. This asserts the
    endpoint returns what an agent actually carries, and names the agent bound
    by it (F.34).
    """
    created = await api.post("/api/projects", json={
        "org_id": realm, "user_id": "u_guardrails",
        "project_name": project,
        "constitution_rules": ["No agent may email a customer without review."]})
    assert created.status_code == 200, created.text
    project_id = created.json().get("project_id", project)

    materialized = await api.post("/api/agents/materialize", json={
        "org_id": realm, "project_id": project_id, "user_id": "u_guardrails",
        "agent_name": "ContractReader",
        "system_prompt": "Read contracts and summarise obligations.",
        "custom_guardrails": ["Never quote a clause it did not read in full."]})
    assert materialized.status_code == 200, materialized.text

    res = await api.get(f"/api/projects/{project_id}/guardrails",
                        params={"org_id": realm})
    assert res.status_code == 200, res.text
    body = res.json()

    rules = {g["rule"]: g for g in body["guardrails"]}
    assert "Never quote a clause it did not read in full." in rules, body

    carried = rules["Never quote a clause it did not read in full."]
    assert carried["source"] == "discovered_prompt"
    assert carried["level"]
    assert "ContractReader" in " ".join(carried["bound_agents"])
    # No action is recorded anywhere, so none is asserted (F.34).
    assert carried["action"] is None
    assert body["agents_scanned"] >= 1


async def test_a_project_with_no_guardrails_says_so_rather_than_inventing_three(
        api, realm, project):
    res = await api.get(f"/api/projects/{project}/guardrails",
                        params={"org_id": realm})
    assert res.status_code == 200, res.text
    assert res.json()["guardrails"] == []


# --------------------------------------------------------------------- runs

async def test_the_runs_list_is_the_registrys_and_survives_an_empty_realm(
        api, realm, project):
    """An untouched realm has no runs — and that is a 200 with none, not a 500."""
    res = await api.get("/api/runs", params={"org_id": realm, "project_id": project})
    assert res.status_code == 200, res.text
    assert res.json()["runs"] == []


async def test_an_unreachable_registry_does_not_become_an_empty_run_list(
        api, monkeypatch, realm):
    """Nothing recorded and nothing reachable are different, and must read so."""
    from backend import main
    monkeypatch.setattr(main, "AGENT_REGISTRY_URL", "http://127.0.0.1:9")

    res = await api.get("/api/runs", params={"org_id": realm})
    assert res.status_code == 502, res.text
    assert "unreachable" in res.json()["detail"].lower()
