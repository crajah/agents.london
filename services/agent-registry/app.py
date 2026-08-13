"""Agent Registry Microservice (Ontological Registry) for agent.london

Registers every agent as a unique, versioned entity bound with cryptographic keypairs, SHA-256 digests,
Telos objectives, caste classifications, utility token balances, reputation scores, and progeny tracking.
Persisted in post-graph database tables (agent_registry and agent_registry_data).
"""
import asyncio
import hashlib
import logging
import os
import yaml
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from post_graph import AsyncPostGraph

logger = logging.getLogger(__name__)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)

# Local in-memory cache synced with post-graph
AGENT_REGISTRY: Dict[str, Dict[str, Any]] = {}
AGENT_VERSIONS: Dict[str, List[Dict[str, Any]]] = {}

@asynccontextmanager
async def pg_client(org_id: str = "org_default"):
    """Connected post-graph client for one org realm, closed on the way out.

    Connection failures are raised rather than returning None. The previous
    version also fell back to a hardcoded localhost DSN with an embedded
    password, which turned a misconfigured POSTGRES_URI into a silent write to
    the wrong database rather than an error.
    """
    client = AsyncPostGraph(dsn=DB_URI)
    await client.connect()
    try:
        await client.create_vertex_table("agent_registry", realm=org_id)
        yield client
    finally:
        try:
            await client.close()
        except Exception:
            logger.exception("Failed to close post-graph client for realm '%s'", org_id)

async def sync_from_post_graph():
    """Populates local cache from post-graph on startup. Syncs across known org realms."""
    orgs_to_sync = ["org_london_meta", "org_default"]
    for org_id in orgs_to_sync:
        async with pg_client(org_id) as client:
            # get_vertices without space returns all spaces (all projects) in the realm
            vertices = await client.get_vertices(table_name="agent_registry", realm=org_id)
            for v in vertices:
                payload = v.payload if hasattr(v, "payload") else v
                if isinstance(payload, dict) and "agent_id" in payload:
                    agent_id = payload["agent_id"]
                    AGENT_REGISTRY[agent_id] = payload
                    # Version history is genuinely optional — an agent that has
                    # never been re-registered has none — so its absence is a
                    # normal state rather than a failure, and the current
                    # payload stands in as the only known version.
                    records = await client.get_vertex_data(
                        table_name="agent_registry", realm=org_id, vertex_id=agent_id)
                    AGENT_VERSIONS[agent_id] = (
                        [rec.to_dict() for rec in records] if records else [payload])

async def persist_agent_to_pg(agent_id: str, payload: Dict[str, Any]):
    """Persists agent to post-graph. realm=org_id (physical), space=project_id (logical).

    Every write here is required. Previously each one was individually wrapped
    in `except Exception: pass`, so a pipeline could be registered with some,
    none, or an arbitrary subset of its step dependencies stored, and the
    caller was told it succeeded either way — leaving a graph that is not
    wrong in any detectable place, merely missing edges.
    """
    org_id = payload.get("org_id", "org_default")
    project_id = payload.get("project_id", "proj_default")
    async with pg_client(org_id) as client:
        await client.add_vertex(table_name="agent_registry", realm=org_id, space=project_id, payload=payload)
        await client.add_vertex_data(table_name="agent_registry", realm=org_id, vertex_id=agent_id, payload=payload)

        if payload.get("caste") == "pipeline" or payload.get("role") == "multi_agent_execution_pipeline":
            await client.create_edge_table("composes_pipeline", from_vertex_table="agent_registry", to_vertex_table="agent_registry", realm=org_id)
            await client.create_edge_table("pipeline_step_dependency", from_vertex_table="agent_registry", to_vertex_table="agent_registry", realm=org_id)

            # relation_type is required by add_edge. Omitting it raised
            # TypeError on every call, which the removed `except Exception:
            # pass` swallowed — so no pipeline edge was ever written.
            for target_agent_id in payload.get("assigned_agents", []):
                await client.add_edge("composes_pipeline", realm=org_id, from_id=agent_id, to_id=target_agent_id,
                                      relation_type="contains_agent",
                                      payload={"relation": "contains_agent", "pipeline_id": agent_id}, space=project_id)

            graph_data = payload.get("graph", {})
            nodes = {n.get("id"): n for n in graph_data.get("nodes", []) if n.get("id")}
            for edge in graph_data.get("edges", []):
                src = nodes.get(edge.get("from"), {}).get("agent_id", edge.get("from"))
                dst = nodes.get(edge.get("to"), {}).get("agent_id", edge.get("to"))
                if src and dst:
                    relationship = edge.get("relationship", "depends_on")
                    await client.add_edge("pipeline_step_dependency", realm=org_id, from_id=src, to_id=dst,
                                          relation_type=relationship,
                                          payload={"relationship": relationship, "pipeline_id": agent_id}, space=project_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await sync_from_post_graph()
    yield

tags_metadata = [
    {"name": "Agent Registration", "description": "Register, retrieve, update, and manage agent version histories."},
    {"name": "GraphRAG Indexing", "description": "Generate dynamic Markdown documents and index agent specifications into post-graph-rag."},
    {"name": "System", "description": "Health check and microservice status endpoints."}
]

app = FastAPI(
    title="Agent Registry & Ontological Microservice",
    description="""
    # 🤖 agent.london Agent Registry OpenAPI Specs
    
    Manages versioned, cryptographically bound agent representations (Telos, Castes, Cryptographic Signatures, Progeny Tracking) backed by PostgreSQL `post-graph` and `post-graph-rag`.
    
    - **Interactive Swagger Documentation:** [/docs](/docs)
    - **ReDoc API Documentation:** [/redoc](/redoc)
    - **OpenAPI Schema JSON:** [/openapi.json](/openapi.json)
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
    lifespan=lifespan
)

class MemoryPolicy(BaseModel):
    policy_type: str = "shared_session"
    session_segregation: bool = True
    read_access: bool = True
    write_access: bool = True

class Guardrail(BaseModel):
    guardrail_id: str
    source: str = "constitution"
    level: str = "project"
    rule: str
    action_on_violation: str = "block_and_audit"

class AgentRegistrationRequest(BaseModel):
    agent_id: str = Field(..., description="Unique agent entity identifier")
    uaid: Optional[str] = Field(None, description="Unique Agent Identifier (UAID) Digital Passport issued by Federated Root CA")
    entra_agent365_principal_id: Optional[str] = Field(None, description="Entra Agent 365 Security Principal ID")
    codebase_hash_attestation: Optional[str] = Field(None, description="Cryptographic SHA256 codebase and prompt hash digest")
    x509_certificate: Optional[Dict[str, Any]] = Field(default_factory=dict, description="X.509 Digital Passport Certificate issued by Federated Root CA")
    parent_agent_id: Optional[str] = Field(None, description="ID of parent agent if spawned as progeny")
    org_id: str
    user_id: str
    project_id: str
    name: str
    caste: str = Field("task_workforce", description="genesis, archivist, economist, judicature, architect, task_workforce, auditor")
    role: str = Field("worker", description="permanent_governor, permanent_creator, permanent_inspector, permanent_conductor, permanent_react, worker")
    telos: str = Field(..., description="Definable core objective of the agent")
    version: str = "v1.0.0"
    system_prompt: str
    tools: List[str] = Field(default_factory=list, description="List of linked MCP tool IDs")
    memory_policy: MemoryPolicy = Field(default_factory=MemoryPolicy)
    guardrails: List[Guardrail] = Field(default_factory=list)
    token_balance: float = 10000000.0
    reputation_score: float = 100.0
    public_key: Optional[str] = None
    signature: Optional[str] = None
    hash_digest: Optional[str] = None
    replicas: int = 1

class AuditRequest(BaseModel):
    auditor_id: str
    reputation_delta: float
    audit_notes: str
    passed_compliance: bool

class TokenAllocationRequest(BaseModel):
    arbiter_id: str
    amount: float
    reason: str

class VerifySignatureRequest(BaseModel):
    agent_id: str
    public_key: str
    signature: str
    payload_text: str

@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agent-registry", "registered_agents": len(AGENT_REGISTRY), "persistence": "post-graph"}

@app.post("/agents/register")
async def register_agent(req: AgentRegistrationRequest):
    agent_dict = req.model_dump()
    agent_id = req.agent_id

    # Generate SHA-256 payload digest if not supplied
    if not req.hash_digest:
        raw = f"{agent_id}:{req.telos}:{req.system_prompt}:{req.parent_agent_id or 'none'}"
        agent_dict["hash_digest"] = hashlib.sha256(raw.encode()).hexdigest()
    if not req.public_key:
        agent_dict["public_key"] = f"ed25519:{hashlib.sha256((agent_id + '_pub').encode()).hexdigest()[:32]}"
    if not req.signature:
        agent_dict["signature"] = f"sig:{hashlib.sha256((agent_dict['hash_digest'] + '_sig').encode()).hexdigest()[:48]}"

    agent_dict["lifecycle_status"] = "INSTANTIATED"
    agent_dict["progeny_agent_ids"] = AGENT_REGISTRY.get(agent_id, {}).get("progeny_agent_ids", [])

    # Update parent progeny lineage
    if req.parent_agent_id and req.parent_agent_id in AGENT_REGISTRY:
        parent = AGENT_REGISTRY[req.parent_agent_id]
        if "progeny_agent_ids" not in parent:
            parent["progeny_agent_ids"] = []
        if agent_id not in parent["progeny_agent_ids"]:
            parent["progeny_agent_ids"].append(agent_id)
            asyncio.create_task(persist_agent_to_pg(req.parent_agent_id, parent))

    # Track version history
    if agent_id not in AGENT_VERSIONS:
        AGENT_VERSIONS[agent_id] = []
    AGENT_VERSIONS[agent_id].append(agent_dict)
    AGENT_REGISTRY[agent_id] = agent_dict

    # Persist to post-graph PostgreSQL database
    await persist_agent_to_pg(agent_id, agent_dict)

    return {
        "status": "registered",
        "agent_id": agent_id,
        "caste": req.caste,
        "parent_agent_id": req.parent_agent_id,
        "public_key": agent_dict["public_key"],
        "hash_digest": agent_dict["hash_digest"],
        "version": req.version,
        "total_versions": len(AGENT_VERSIONS[agent_id])
    }

@app.post("/agents/verify")
def verify_agent(req: VerifySignatureRequest):
    if req.agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' not found.")
    
    agent = AGENT_REGISTRY[req.agent_id]
    computed_digest = hashlib.sha256(req.payload_text.encode()).hexdigest()
    expected_sig = f"ed25519:{computed_digest}"
    is_valid = (agent.get("public_key") == req.public_key) and (req.signature == expected_sig or req.signature == agent.get("signature"))
    return {
        "agent_id": req.agent_id,
        "verified": is_valid,
        "computed_digest": computed_digest,
        "registered_public_key": agent.get("public_key")
    }

@app.post("/agents/{agent_id}/audit")
async def audit_agent(agent_id: str, req: AuditRequest):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    
    agent = AGENT_REGISTRY[agent_id]
    agent["reputation_score"] = max(0.0, min(100.0, agent.get("reputation_score", 100.0) + req.reputation_delta))
    agent["lifecycle_status"] = "AUDITED"

    if agent_id in AGENT_VERSIONS:
        AGENT_VERSIONS[agent_id].append(dict(agent))

    await persist_agent_to_pg(agent_id, agent)

    return {
        "status": "audited",
        "agent_id": agent_id,
        "auditor_id": req.auditor_id,
        "new_reputation_score": agent["reputation_score"],
        "passed": req.passed_compliance
    }

@app.post("/agents/{agent_id}/allocate-tokens")
async def allocate_tokens(agent_id: str, req: TokenAllocationRequest):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    
    agent = AGENT_REGISTRY[agent_id]
    agent["token_balance"] = max(0.0, agent.get("token_balance", 0.0) + req.amount)

    if agent["token_balance"] <= 0.0:
        agent["lifecycle_status"] = "TERMINATED_ECONOMIC"

    if agent_id in AGENT_VERSIONS:
        AGENT_VERSIONS[agent_id].append(dict(agent))

    await persist_agent_to_pg(agent_id, agent)

    return {
        "status": "updated",
        "agent_id": agent_id,
        "new_token_balance": agent["token_balance"],
        "lifecycle_status": agent["lifecycle_status"]
    }

@app.get("/agents")
def list_agents(
    org_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    caste: Optional[str] = Query(None),
    role: Optional[str] = Query(None)
):
    results = list(AGENT_REGISTRY.values())
    if org_id:
        results = [a for a in results if a["org_id"] == org_id]
    if project_id:
        results = [a for a in results if a["project_id"] == project_id]
    if caste:
        results = [a for a in results if a["caste"] == caste]
    if role:
        results = [a for a in results if a["role"] == role]
    return {"agents": results, "count": len(results)}

@app.get("/agents/rag-documents")
def get_rag_documents(project_id: Optional[str] = Query(None)):
    """Export human-readable text documents of registered agents for post-graph-rag indexing."""
    agents = list(AGENT_REGISTRY.values())
    if project_id:
        agents = [a for a in agents if a["project_id"] == project_id]

    documents = []
    for a in agents:
        tools_str = ", ".join(a.get("tools") or []) or "None"
        guardrails_str = "; ".join([g.get("rule", "") for g in (a.get("guardrails") or [])]) or "None"
        parent_str = a.get("parent_agent_id") or "Root/None"

        doc_text = (
            f"Agent Name: {a['name']}\n"
            f"Agent ID: {a['agent_id']}\n"
            f"Caste: {a['caste']}\n"
            f"Role: {a['role']}\n"
            f"Telos Objective: {a['telos']}\n"
            f"Cryptographic Public Key: {a.get('public_key')}\n"
            f"Hash Digest: {a.get('hash_digest')}\n"
            f"Reputation Score: {a.get('reputation_score')}\n"
            f"Utility Token Balance: {a.get('token_balance')}\n"
            f"Parent Progeny Lineage: {parent_str}\n"
            f"Available MCP Tools: {tools_str}\n"
            f"Inviolable Guardrails: {guardrails_str}\n"
            f"System Prompt & Capabilities: {a['system_prompt']}"
        )
        documents.append({
            "agent_id": a["agent_id"],
            "name": a["name"],
            "caste": a["caste"],
            "text": doc_text,
            "metadata": {
                "source": "agent_registry",
                "category": "agent_metadata",
                "collection": a["project_id"],
                "document": f"agent_{a['agent_id']}.md"
            }
        })

    return {"documents": documents, "count": len(documents)}

@app.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry.")
    return {
        "agent": AGENT_REGISTRY[agent_id],
        "history": AGENT_VERSIONS.get(agent_id, [])
    }

@app.get("/agents/{agent_id}/progeny")
def get_agent_progeny(agent_id: str):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    
    agent = AGENT_REGISTRY[agent_id]
    progeny_ids = agent.get("progeny_agent_ids", [])
    progeny_details = [AGENT_REGISTRY[pid] for pid in progeny_ids if pid in AGENT_REGISTRY]

    return {
        "agent_id": agent_id,
        "name": agent["name"],
        "parent_agent_id": agent.get("parent_agent_id"),
        "progeny_count": len(progeny_details),
        "progeny": progeny_details
    }

@app.get("/agents/{agent_id}/kagent-manifest")
def generate_kagent_manifest(agent_id: str):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    
    agent = AGENT_REGISTRY[agent_id]
    manifest = {
        "apiVersion": "kagent.dev/v1alpha1",
        "kind": "KAgent",
        "metadata": {
            "name": agent_id,
            "namespace": f"org-{agent['org_id'].lower()}",
            "labels": {
                "agents.london/org": agent["org_id"],
                "agents.london/project": agent["project_id"],
                "agents.london/caste": agent["caste"],
                "agents.london/role": agent["role"]
            }
        },
        "spec": {
            "agentName": agent["name"],
            "caste": agent["caste"],
            "telos": agent["telos"],
            "cryptographicBinding": {
                "publicKey": agent.get("public_key"),
                "hashDigest": agent.get("hash_digest"),
                "signature": agent.get("signature")
            },
            "economicModel": {
                "tokenBalance": agent.get("token_balance"),
                "reputationScore": agent.get("reputation_score")
            },
            "modelRouter": {
                "serviceUrl": os.getenv("OPENAI_API_BASE", os.getenv("LITELLM_URL", "http://litellm-service.default.svc.cluster.local:80/v1")),
                "defaultModel": "DeepSeek-V3.2",
                "apiKeySecretRef": {
                    "name": "litellm-api-keys",
                    "key": "MASTER_KEY"
                }
            },
            "mcpTools": agent["tools"],
            "memoryPolicy": agent["memory_policy"],
            "inviolableGuardrails": [g["rule"] for g in agent["guardrails"]]
        }
    }

    yaml_str = yaml.dump(manifest, sort_keys=False)
    return {
        "agent_id": agent_id,
        "manifest_object": manifest,
        "yaml_manifest": yaml_str
    }

@app.get("/pipelines/{pipeline_id}/graph")
async def get_pipeline_graph(pipeline_id: str):
    """Retrieves pipeline entity and post-graph edge connections composing the execution workflow."""
    if pipeline_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found in registry.")

    pipeline_entity = AGENT_REGISTRY[pipeline_id]
    org_id = pipeline_entity.get("org_id", "org_default")

    contained_agents = []
    step_dependencies = []

    # get_neighbors, not get_edges: the latter does not exist on AsyncPostGraph,
    # so these lookups raised AttributeError and the debug-level handler that
    # swallowed it left both lists empty on every request.
    async with pg_client(org_id) as client:
        composes = await client.get_neighbors(
            realm=org_id, vertex_table="agent_registry", vertex_id=pipeline_id,
            edge_tables=["composes_pipeline"], direction="out")
        contained_agents = [edge.to_id for _vertex, edge in composes]

        deps = await client.get_neighbors(
            realm=org_id, vertex_table="agent_registry", vertex_id=pipeline_id,
            edge_tables=["pipeline_step_dependency"], direction="out")
        step_dependencies = [
            {
                "from_agent": edge.from_id,
                "to_agent": edge.to_id,
                "payload": edge.payload or {},
            }
            for _vertex, edge in deps
        ]

    return {
        "pipeline_id": pipeline_id,
        "name": pipeline_entity.get("name"),
        "caste": pipeline_entity.get("caste"),
        "role": pipeline_entity.get("role"),
        "telos": pipeline_entity.get("telos"),
        "graph_specification": pipeline_entity.get("graph", {}),
        "post_graph_representation": {
            "root_vertex_id": pipeline_id,
            "contained_agent_vertices": contained_agents or pipeline_entity.get("assigned_agents", []),
            "step_dependency_edges": step_dependencies
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
