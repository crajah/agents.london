"""Agent Registry Microservice (Ontological Registry) for agent.london

Registers every agent as a versioned entity bound with cryptographic keypairs,
SHA-256 digests, Telos objectives, caste classifications, utility token
balances, reputation scores, and progeny tracking.

**One store.** Two agent models used to coexist here — an `agent_registry`
vertex table behind `POST /agents/register`, and the `agents` / `pipelines`
graph behind `POST /agents`. An agent registered through one was invisible to
the other. The older surface is now a translation layer over the graph
(`legacy_shim.py`): the requests and responses are unchanged, and there is one
place an agent is described.

See spec/agent-graph-spec.md.
"""
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from post_graph import AsyncPostGraph

import legacy_shim
from legacy_shim import AgentRegistrationRequest
from registry_api import router as graph_router
from registry_model import RegistrationError
from registry_store import AGENTS, PIPELINES, ensure_schema, register_agent_version

logger = logging.getLogger(__name__)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)

# Realm means schema (spec §2): physical isolation per organisation. Left off,
# every tenant's rows land in one set of public tables separated only by a
# column — logical isolation wearing the name of physical, which is the kind of
# difference nobody notices until it matters.
SCHEMA_PER_REALM = os.getenv("SCHEMA_PER_REALM", "1").lower() in ("1", "true", "yes")

# The realm an unscoped read falls back to. Matches apps/civilization/backend/main.py's
# DEFAULT_ORG_ID: a realm is a PostgreSQL schema, so the two disagreeing means
# reading an empty schema and reporting "not found" for an agent that exists.
DEFAULT_ORG = os.getenv("DEFAULT_ORG_ID", "org_london_meta")

# The model a kagent manifest names when the agent version declares none.
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "gemini-3.5-flash-lite")


@asynccontextmanager
async def pg_client(org_id: str = DEFAULT_ORG):
    """Connected post-graph client for one org realm, closed on the way out.

    Connection failures are raised rather than returning None. An earlier
    version fell back to a hardcoded localhost DSN with an embedded password,
    which turned a misconfigured POSTGRES_URI into a silent write to the wrong
    database rather than an error.
    """
    client = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM)
    await client.connect()
    try:
        await ensure_schema(client, org_id)
        yield client
    finally:
        try:
            await client.close()
        except Exception:
            logger.exception("Failed to close post-graph client for realm '%s'", org_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One long-lived client for every endpoint (§9). Opened here so a database
    # that is unreachable stops the service starting, rather than surfacing as
    # a 503 on the first registration.
    client = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM)
    await client.connect()
    app.state.pg_client = client
    app.state.pg_client_factory = pg_client
    await ensure_schema(client, DEFAULT_ORG)

    # Metering is optional infrastructure: accounting must never be the reason
    # the registry will not start (Rule 12.2).
    app.state.meter = None
    try:
        from metering import configure
        app.state.meter = configure(pg_client)
        await app.state.meter.start()
    except Exception:
        logger.exception("metering unavailable; the registry runs unmetered")

    # Redis carries step messages (spec §8.1). Optional: without it the
    # transport is a declared no-op and runs still execute, so a broken cache
    # cannot stop the registry serving. Rule 8.3 applies once a client is
    # present — a publish failure then fails the run rather than being skipped.
    app.state.redis = None
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis
            app.state.redis = aioredis.from_url(redis_url, decode_responses=True)
            await app.state.redis.ping()
            logger.info("Redis transport connected at %s", redis_url)
        except Exception:
            app.state.redis = None
            logger.exception("Redis unreachable at %s; runs will execute without "
                             "a published event stream", redis_url)
    try:
        yield
    finally:
        if app.state.meter:
            await app.state.meter.stop()
        if app.state.redis:
            await app.state.redis.aclose()
        await client.close()


tags_metadata = [
    {"name": "Agent Registration", "description": "Register, retrieve, update, and manage agent version histories."},
    {"name": "Agent Registry", "description": "The versioned graph surface: agents, pipelines, retirement."},
    {"name": "Discovery", "description": "Find agents and pipelines by description, capability or structure."},
    {"name": "MCP", "description": "Model Context Protocol tool listing and invocation."},
    {"name": "A2A", "description": "Agent-to-Agent cards and task submission."},
    {"name": "GraphRAG Indexing", "description": "Generate dynamic Markdown documents and index agent specifications into post-graph-rag."},
    {"name": "System", "description": "Health check and microservice status endpoints."},
]

app = FastAPI(
    title="Agent Registry & Ontological Microservice",
    description="""
    # 🤖 agent.london Agent Registry OpenAPI Specs

    Manages versioned, cryptographically bound agent representations (Telos, Castes,
    Cryptographic Signatures, Progeny Tracking) backed by PostgreSQL `post-graph`
    and `post-graph-rag`.

    Every published agent and pipeline version is callable over MCP and A2A;
    nothing else is.

    - **Interactive Swagger Documentation:** [/docs](/docs)
    - **ReDoc API Documentation:** [/redoc](/redoc)
    - **OpenAPI Schema JSON:** [/openapi.json](/openapi.json)
    """,
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

app.include_router(graph_router)


def _client():
    client = getattr(app.state, "pg_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Registry has no database connection.")
    return client


class AuditRequest(BaseModel):
    auditor_id: str
    reputation_delta: float
    audit_notes: str
    passed_compliance: bool
    org_id: str = DEFAULT_ORG
    project_id: str = "proj_default"


class TokenAllocationRequest(BaseModel):
    arbiter_id: str
    amount: float
    reason: str
    org_id: str = DEFAULT_ORG
    project_id: str = "proj_default"


class VerifySignatureRequest(BaseModel):
    agent_id: str
    public_key: str
    signature: str
    payload_text: str
    org_id: str = DEFAULT_ORG


@app.get("/", tags=["System"])
@app.get("/health", tags=["System"])
async def health_check():
    """Reports what is actually reachable, not constants."""
    database = "unreachable"
    agents = 0
    try:
        await _client()._fetch("SELECT 1")
        database = "ok"
        agents = len(await legacy_shim.load_all(_client(), DEFAULT_ORG))
    except Exception as e:
        logger.warning("health: database unreachable: %s", e)
    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": "agent-registry",
        "database": database,
        "registered_agents": agents,
        "persistence": "post-graph",
        "schema_per_realm": SCHEMA_PER_REALM,
        "redis": "on" if getattr(app.state, "redis", None) else "off",
        "metering": "on" if getattr(app.state, "meter", None) else "off",
    }


# ------------------------------------------------------- legacy registration

@app.post("/agents/register", tags=["Agent Registration"])
async def register_agent(req: AgentRegistrationRequest):
    """Register an agent. Unchanged contract, backed by the graph (§13.3).

    The request and response shapes are exactly what they were; underneath, the
    identity fields go to the `agents` vertex and the behavioural fields to an
    immutable version record, so this agent is pinnable, discoverable and
    callable like any other.
    """
    from tool_client import ToolResolutionError, catalogue_or_none

    client = _client()
    await ensure_schema(client, req.org_id)
    identity, version = req.split()

    try:
        tools = await catalogue_or_none(req.org_id, req.project_id,
                                        required=bool(version.tools))
    except ToolResolutionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot resolve this agent's tools: {e}") from e

    embedding = None
    try:
        from embedding import discovery_text, embed
        embedding = await embed(discovery_text(
            identity.name, identity.telos, identity.description,
            ", ".join(version.capabilities)))
    except Exception:
        logger.exception("embedding unavailable; registering without a vector")

    try:
        record = await register_agent_version(
            client, req.org_id, req.project_id,
            identity.model_dump(mode="json"), version,
            embedding=embedding, spawned_by=req.parent_agent_id,
            tool_catalogue=tools)
    except RegistrationError as e:
        # A 400 naming the rule. The previous implementation swallowed every
        # write failure individually and returned success regardless, which
        # left a graph that is not wrong in any detectable place, merely
        # missing edges.
        raise HTTPException(status_code=400, detail=str(e)) from e

    history = await legacy_shim.version_history(client, req.org_id, req.agent_id,
                                                req.project_id)
    attested = req.attestation()
    return {
        "status": "registered",
        "agent_id": req.agent_id,
        "caste": req.caste,
        "parent_agent_id": req.parent_agent_id,
        "public_key": attested["public_key"],
        "hash_digest": attested["hash_digest"],
        "version": req.version,
        "total_versions": len(history),
        # New, additive: what the graph now knows about this agent.
        "content_hash": record["content_hash"],
        "version_id": record["version_id"],
        "tools": record.get("tools", []),
    }


@app.post("/agents/verify", tags=["Agent Registration"])
async def verify_agent(req: VerifySignatureRequest):
    agent = await legacy_shim.load_agent(_client(), req.org_id, req.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' not found.")

    computed_digest = hashlib.sha256(req.payload_text.encode()).hexdigest()
    expected_sig = f"ed25519:{computed_digest}"
    is_valid = (agent.get("public_key") == req.public_key) and (
        req.signature == expected_sig or req.signature == agent.get("signature"))
    return {
        "agent_id": req.agent_id,
        "verified": is_valid,
        "computed_digest": computed_digest,
        "registered_public_key": agent.get("public_key"),
    }


@app.post("/agents/{agent_id}/audit", tags=["Agent Registration"])
async def audit_agent(agent_id: str, req: AuditRequest):
    """Record an oversight audit and move the reputation score.

    An identity update, not a new version (§4.2): auditing an agent does not
    change what it does, so it must not change its content hash.
    """
    client = _client()
    agent = await legacy_shim.load_agent(client, req.org_id, agent_id, req.project_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    score = max(0.0, min(100.0, float(agent.get("reputation_score", 100.0))
                         + req.reputation_delta))
    try:
        await legacy_shim.update_identity(
            client, req.org_id, req.project_id, agent_id,
            {"reputation_score": score, "lifecycle_status": "AUDITED",
             "last_audit": {"auditor_id": req.auditor_id, "notes": req.audit_notes,
                            "passed": req.passed_compliance}})
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {"status": "audited", "agent_id": agent_id, "auditor_id": req.auditor_id,
            "new_reputation_score": score, "passed": req.passed_compliance}


@app.post("/agents/{agent_id}/allocate-tokens", tags=["Agent Registration"])
async def allocate_tokens(agent_id: str, req: TokenAllocationRequest):
    client = _client()
    agent = await legacy_shim.load_agent(client, req.org_id, agent_id, req.project_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    balance = max(0.0, float(agent.get("token_balance", 0.0)) + req.amount)
    changes: Dict[str, Any] = {"token_balance": balance}
    if balance <= 0.0:
        changes["lifecycle_status"] = "TERMINATED_ECONOMIC"
        # Economic death is dormancy, not deletion (Rule 3.2): the agent's
        # spawns edges are the provenance record of everything below it.
        changes["lifecycle"] = "dormant"
    try:
        await legacy_shim.update_identity(client, req.org_id, req.project_id,
                                          agent_id, changes)
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {"status": "updated", "agent_id": agent_id, "new_token_balance": balance,
            "lifecycle_status": changes.get("lifecycle_status",
                                            agent.get("lifecycle_status"))}


# ------------------------------------------------------------------- reading

@app.get("/agents", tags=["Agent Registration"])
async def list_agents(org_id: Optional[str] = Query(None),
                      project_id: Optional[str] = Query(None),
                      caste: Optional[str] = Query(None),
                      role: Optional[str] = Query(None),
                      include_dormant: bool = Query(False)):
    agents = await legacy_shim.load_all(_client(), org_id or DEFAULT_ORG, project_id)
    if not include_dormant:
        agents = [a for a in agents if a.get("lifecycle", "active") == "active"]
    if caste:
        agents = [a for a in agents if a.get("caste") == caste]
    if role:
        agents = [a for a in agents if a.get("role") == role]
    return {"agents": agents, "count": len(agents)}


@app.get("/agents/rag-documents", tags=["GraphRAG Indexing"])
async def get_rag_documents(project_id: Optional[str] = Query(None),
                            org_id: str = Query(DEFAULT_ORG)):
    """Agents rendered as prose for post-graph-rag indexing.

    Derived on every request, never stored: a second copy of an agent's
    description drifts from the first and nothing reports the divergence.
    """
    agents = await legacy_shim.load_all(_client(), org_id, project_id)
    documents = []
    for a in agents:
        tools = a.get("tools") or []
        tool_names = ", ".join(
            t.get("tool_id", str(t)) if isinstance(t, dict) else str(t)
            for t in tools) or "None"
        guardrails = "; ".join(g.get("rule", "") for g in (a.get("guardrails") or [])) or "None"
        documents.append({
            "agent_id": a["agent_id"],
            "name": a.get("name"),
            "caste": a.get("caste"),
            "text": (
                f"Agent Name: {a.get('name')}\n"
                f"Agent ID: {a['agent_id']}\n"
                f"Caste: {a.get('caste')}\n"
                f"Role: {a.get('role')}\n"
                f"Telos Objective: {a.get('telos')}\n"
                f"Version: {a.get('version')}\n"
                f"Content Hash: {a.get('content_hash')}\n"
                f"Cryptographic Public Key: {a.get('public_key')}\n"
                f"Hash Digest: {a.get('hash_digest')}\n"
                f"Reputation Score: {a.get('reputation_score')}\n"
                f"Utility Token Balance: {a.get('token_balance')}\n"
                f"Available MCP Tools: {tool_names}\n"
                f"Inviolable Guardrails: {guardrails}\n"
                f"System Prompt & Capabilities: {a.get('system_prompt')}"),
            "metadata": {
                "source": "agent_registry",
                "category": "agent_metadata",
                "collection": project_id or "all",
                "document": f"agent_{a['agent_id']}.md",
            },
        })
    return {"documents": documents, "count": len(documents)}


@app.get("/agents/{agent_id}", tags=["Agent Registration"])
async def get_agent(agent_id: str, org_id: str = Query(DEFAULT_ORG),
                    project_id: Optional[str] = Query(None)):
    client = _client()
    agent = await legacy_shim.load_agent(client, org_id, agent_id, project_id)
    if agent is None:
        raise HTTPException(status_code=404,
                            detail=f"Agent '{agent_id}' not found in registry.")
    return {"agent": agent,
            "history": await legacy_shim.version_history(client, org_id, agent_id,
                                                         project_id)}


@app.get("/agents/{agent_id}/progeny", tags=["Agent Registration"])
async def get_agent_progeny(agent_id: str, org_id: str = Query(DEFAULT_ORG),
                            project_id: Optional[str] = Query(None)):
    """Children of an agent, derived from the `spawns` edges.

    Not a stored list. A list and the edges are two records of one fact, and a
    failed write left them disagreeing with nothing to reconcile them.
    """
    client = _client()
    agent = await legacy_shim.load_agent(client, org_id, agent_id, project_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    child_ids = await legacy_shim.progeny_of(client, org_id, agent_id, project_id)
    children = []
    for child_id in child_ids:
        child = await legacy_shim.load_agent(client, org_id, child_id, project_id)
        if child:
            children.append(child)
    return {"agent_id": agent_id, "name": agent.get("name"),
            "parent_agent_id": agent.get("parent_agent_id"),
            "progeny_count": len(children), "progeny": children}


@app.get("/agents/{agent_id}/kagent-manifest", tags=["Agent Registration"])
async def generate_kagent_manifest(agent_id: str, org_id: str = Query(DEFAULT_ORG),
                                   project_id: Optional[str] = Query(None)):
    agent = await legacy_shim.load_agent(_client(), org_id, agent_id, project_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    tools = agent.get("tools") or []
    manifest = {
        "apiVersion": "kagent.dev/v1alpha1",
        "kind": "KAgent",
        "metadata": {
            "name": agent_id,
            "namespace": f"org-{str(agent.get('org_id', org_id)).lower()}",
            "labels": {
                "agents.london/org": agent.get("org_id", org_id),
                "agents.london/project": project_id or "all",
                "agents.london/caste": agent.get("caste"),
                "agents.london/role": agent.get("role"),
            },
        },
        "spec": {
            "agentName": agent.get("name"),
            "caste": agent.get("caste"),
            "telos": agent.get("telos"),
            "version": agent.get("version"),
            "cryptographicBinding": {
                "publicKey": agent.get("public_key"),
                "hashDigest": agent.get("hash_digest"),
                "signature": agent.get("signature"),
                # The content hash is what actually pins behaviour (§4.2); the
                # digest above is the legacy attestation and covers less.
                "contentHash": agent.get("content_hash"),
            },
            "economicModel": {
                "tokenBalance": agent.get("token_balance"),
                "reputationScore": agent.get("reputation_score"),
            },
            "modelRouter": {
                "serviceUrl": os.getenv("OPENAI_API_BASE", os.getenv(
                    "LITELLM_URL",
                    "http://litellm-service.default.svc.cluster.local:80/v1")),
                "defaultModel": (agent.get("model") or {}).get("name", DEFAULT_LLM_MODEL),
                "apiKeySecretRef": {"name": "litellm-api-keys", "key": "MASTER_KEY"},
            },
            # Pinned tools, so a manifest names exact tool versions rather than
            # whatever those ids happen to mean at deploy time.
            "mcpTools": tools,
            "memoryPolicy": agent.get("memory_policy", {}),
            "inviolableGuardrails": [g.get("rule") for g in (agent.get("guardrails") or [])],
        },
    }
    return {"agent_id": agent_id, "manifest_object": manifest,
            "yaml_manifest": yaml.dump(manifest, sort_keys=False)}


@app.get("/pipelines/{pipeline_id}/graph", tags=["Agent Registration"])
async def get_pipeline_graph(pipeline_id: str, org_id: str = Query(DEFAULT_ORG),
                             project_id: Optional[str] = Query(None)):
    """A pipeline's composition and dependency edges.

    Read from the edges rather than from a JSON blob on the row, which is the
    reason composition is stored as edges at all (§1).
    """
    client = _client()
    from registry_store import COMPOSES, STEP_DEPENDENCY, resolve_vertex

    pipeline_pk = await resolve_vertex(client, PIPELINES, org_id, pipeline_id,
                                       project_id)
    if pipeline_pk is None:
        raise HTTPException(status_code=404,
                            detail=f"Pipeline '{pipeline_id}' not found in registry.")

    ref = client._get_table_ref(PIPELINES, org_id)
    rows = await client._fetch(
        f"SELECT payload FROM {ref} WHERE realm = $1 AND id = $2", org_id, pipeline_pk)
    identity = rows[0]["payload"] if rows else {}
    if isinstance(identity, str):
        import json
        identity = json.loads(identity)

    # get_neighbors, not get_edges: the latter does not exist on AsyncPostGraph,
    # so these lookups raised AttributeError and the debug-level handler that
    # swallowed it left both lists empty on every request.
    composes = await client.get_neighbors(
        realm=org_id, vertex_table=PIPELINES, vertex_id=pipeline_pk,
        edge_tables=[COMPOSES], direction="out")
    contained = [{"agent_vertex": edge.to_id, **(edge.payload or {})}
                 for _vertex, edge in composes]

    # Dependency edges run agent -> agent and are scoped to a pipeline version
    # (Rule 5.1), so they are filtered on it rather than walked from the
    # pipeline vertex, which is not one of their endpoints.
    dep_ref = client._get_table_ref(STEP_DEPENDENCY, org_id)
    current = identity.get("current_version")
    dep_rows = await client._fetch(
        f"SELECT from_id, to_id, relation_type, payload FROM {dep_ref} "
        f"WHERE realm = $1 AND payload->>'pipeline_version_id' = $2",
        org_id, f"plv_{pipeline_id}_{current}")

    dependencies = []
    for row in dep_rows:
        payload = row["payload"]
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        dependencies.append({"from_agent": row["from_id"], "to_agent": row["to_id"],
                             "relation_type": row["relation_type"],
                             "payload": payload})

    return {
        "pipeline_id": pipeline_id,
        "name": identity.get("name"),
        "telos": identity.get("telos"),
        "current_version": current,
        "lifecycle": identity.get("lifecycle", "active"),
        "post_graph_representation": {
            "root_vertex_id": pipeline_pk,
            "contained_agent_vertices": contained,
            "step_dependency_edges": dependencies,
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
