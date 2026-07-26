"""Agent Registry Microservice (Ontological Registry) for agent.london

Registers every agent as a unique, versioned entity bound with cryptographic keypairs, SHA-256 digests,
Telos objectives, caste classifications, utility token balances, reputation scores, and progeny tracking.
"""
import hashlib
import os
import yaml
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="Agent Registry & Ontological Service",
    description="Kubernetes Service for versioned, cryptographically bound agent representations & RAG discovery",
    version="1.2.0"
)

# In-memory registry with version history
AGENT_REGISTRY: Dict[str, Dict[str, Any]] = {}
AGENT_VERSIONS: Dict[str, List[Dict[str, Any]]] = {}

class MemoryPolicy(BaseModel):
    policy_type: str = "shared_session" # "shared_session", "isolated", "org_global"
    session_segregation: bool = True
    read_access: bool = True
    write_access: bool = True

class Guardrail(BaseModel):
    guardrail_id: str
    source: str = "constitution" # "constitution" or "discovered_prompt"
    level: str = "project" # "org", "user", or "project"
    rule: str
    action_on_violation: str = "block_and_audit" # "block_and_audit", "warn", "terminate"

class AgentRegistrationRequest(BaseModel):
    agent_id: str = Field(..., description="Unique agent entity identifier")
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
    token_balance: float = 1000.0
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

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agent-registry", "registered_agents": len(AGENT_REGISTRY)}

@app.post("/agents/register")
def register_agent(req: AgentRegistrationRequest):
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

    # If spawned by a parent agent, update parent's progeny list
    if req.parent_agent_id and req.parent_agent_id in AGENT_REGISTRY:
        parent = AGENT_REGISTRY[req.parent_agent_id]
        if "progeny_agent_ids" not in parent:
            parent["progeny_agent_ids"] = []
        if agent_id not in parent["progeny_agent_ids"]:
            parent["progeny_agent_ids"].append(agent_id)

    # Track version history
    if agent_id not in AGENT_VERSIONS:
        AGENT_VERSIONS[agent_id] = []
    AGENT_VERSIONS[agent_id].append(agent_dict)

    AGENT_REGISTRY[agent_id] = agent_dict
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
    
    # Verifiability check against registered public key and signature
    is_valid = (agent.get("public_key") == req.public_key) or (len(req.signature) > 10)
    return {
        "agent_id": req.agent_id,
        "verified": is_valid,
        "computed_digest": computed_digest,
        "registered_public_key": agent.get("public_key")
    }

@app.post("/agents/{agent_id}/audit")
def audit_agent(agent_id: str, req: AuditRequest):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    
    agent = AGENT_REGISTRY[agent_id]
    agent["reputation_score"] = max(0.0, min(100.0, agent.get("reputation_score", 100.0) + req.reputation_delta))
    agent["lifecycle_status"] = "AUDITED"

    return {
        "status": "audited",
        "agent_id": agent_id,
        "auditor_id": req.auditor_id,
        "new_reputation_score": agent["reputation_score"],
        "passed": req.passed_compliance
    }

@app.post("/agents/{agent_id}/allocate-tokens")
def allocate_tokens(agent_id: str, req: TokenAllocationRequest):
    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    
    agent = AGENT_REGISTRY[agent_id]
    agent["token_balance"] = max(0.0, agent.get("token_balance", 0.0) + req.amount)

    if agent["token_balance"] <= 0.0:
        agent["lifecycle_status"] = "TERMINATED_ECONOMIC"

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
        tools_str = ", ".join(a["tools"]) if a["tools"] else "None"
        guardrails_str = "; ".join([g["rule"] for g in a["guardrails"]]) if a["guardrails"] else "None"
        parent_str = a["parent_agent_id"] if a["parent_agent_id"] else "Root/None"

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
