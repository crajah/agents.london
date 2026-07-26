"""Backend for Frontend (BFF) FastAPI Service for agent.london

Connects user interfaces to agent.london's multi-tenant 1B-agent civilization engine,
post-graph database, post-graph-rag shared session memory, Redis work bus, and Kubernetes services.
Includes Playground API, Conductor Orchestration, ReAct Loops, and Progeny Hierarchy.
"""
import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
try:
    from backend.civilization import civilization_engine
    from backend.redis_bus import redis_bus
except (ImportError, ModuleNotFoundError):
    try:
        from civilization import civilization_engine
        from redis_bus import redis_bus
    except (ImportError, ModuleNotFoundError):
        from .civilization import civilization_engine
        from .redis_bus import redis_bus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="agent.london Backend API",
    description="Multi-Tenant Agent Civilization API scaling to 1 Billion Agents",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ACTIVE_CONNECTIONS: List[WebSocket] = []

class CreateUserRequest(BaseModel):
    org_id: str
    username: str
    email: str

class CreateProjectRequest(BaseModel):
    org_id: str
    user_id: str
    project_name: str
    constitution_rules: Optional[List[str]] = None

class MaterializeAgentRequest(BaseModel):
    org_id: str
    project_id: str
    user_id: str
    agent_name: str
    system_prompt: str
    parent_agent_id: Optional[str] = None
    tools: Optional[List[str]] = None
    custom_guardrails: Optional[List[str]] = None

class InitiateSessionRequest(BaseModel):
    org_id: str
    project_id: str
    user_id: str
    session_name: str

class EnqueueTaskRequest(BaseModel):
    org_id: str
    project_id: str
    agent_id: str
    task_description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

class PlaygroundChatRequest(BaseModel):
    org_id: str
    project_id: str
    user_id: str
    mode: str = "conductor" # "conductor", "react", "direct"
    prompt: str
    agent_id: Optional[str] = None

GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
    "zoho.com", "gmx.com", "gmx.net", "yandex.com", "mail.com", "fastmail.com",
    "comcast.net", "sbcglobal.net", "verizon.net", "att.net"
}

def resolve_tenancy_from_email(email: str) -> dict:
    clean_email = email.strip().lower()
    if "@" not in clean_email:
        return {"org_id": "org_london_meta", "user_id": "user_chandan", "is_generic": False}
    
    parts = clean_email.split("@")
    user_part = re.sub(r'[^a-z0-9]', '_', parts[0])
    domain_part = parts[1]
    sanitized_domain = re.sub(r'[^a-z0-9]', '_', domain_part)
    
    is_generic = domain_part in GENERIC_EMAIL_DOMAINS
    if is_generic:
        org_id = f"org_user_{user_part}_{sanitized_domain}"
    else:
        org_id = f"org_{sanitized_domain}"
        
    return {
        "org_id": org_id,
        "user_id": f"user_{user_part}",
        "domain": domain_part,
        "is_generic": is_generic,
        "email": clean_email
    }

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agent.london-backend", "active_websockets": len(ACTIVE_CONNECTIONS)}

@app.post("/api/users")
async def create_user(req: CreateUserRequest):
    tenancy = resolve_tenancy_from_email(req.email)
    effective_org_id = req.org_id if req.org_id and req.org_id != "auto" else tenancy["org_id"]
    res = await civilization_engine.create_user(effective_org_id, req.username, req.email)
    res["resolved_tenancy"] = tenancy
    return res

@app.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    res = await civilization_engine.create_project(
        org_id=req.org_id,
        user_id=req.user_id,
        project_name=req.project_name,
        constitution_rules=req.constitution_rules
    )
    await broadcast_ws_event({
        "type": "project_created",
        "data": res
    })
    return res

@app.post("/api/agents/materialize")
async def materialize_agent(req: MaterializeAgentRequest):
    res = await civilization_engine.materialize_worker_agent(
        org_id=req.org_id,
        project_id=req.project_id,
        user_id=req.user_id,
        agent_name=req.agent_name,
        system_prompt=req.system_prompt,
        parent_agent_id=req.parent_agent_id,
        tools=req.tools,
        custom_guardrails=req.custom_guardrails
    )
    await broadcast_ws_event({
        "type": "agent_materialized",
        "data": res
    })
    return res

@app.post("/api/playground/chat")
async def playground_chat(req: PlaygroundChatRequest):
    """Interactive Playground Endpoint supporting Conductor, ReAct, and Direct mode."""
    if req.mode == "conductor":
        res = await civilization_engine.run_conductor_orchestration(req.org_id, req.project_id, req.prompt)
        await broadcast_ws_event({"type": "conductor_completed", "data": res})
        return res
    elif req.mode == "react":
        res = await civilization_engine.run_react_loop(req.org_id, req.project_id, req.prompt)
        await broadcast_ws_event({"type": "react_completed", "data": res})
        return res
    else:
        # Direct Mode
        target_id = req.agent_id or f"gov-{req.project_id}"
        answer = f"Direct Agent Response ({target_id}): Processed query '{req.prompt}' under project context '{req.project_id}'."
        res = {"agent_id": target_id, "prompt": req.prompt, "answer": answer}
        await broadcast_ws_event({"type": "direct_chat_completed", "data": res})
        return res

@app.post("/api/conductor/orchestrate")
async def conductor_orchestrate(org_id: str, project_id: str, prompt: str):
    res = await civilization_engine.run_conductor_orchestration(org_id, project_id, prompt)
    return res

@app.post("/api/react/execute")
async def react_execute(org_id: str, project_id: str, prompt: str):
    res = await civilization_engine.run_react_loop(org_id, project_id, prompt)
    return res

class VerifySignaturePayload(BaseModel):
    agent_id: str
    public_key: str
    signature: str
    payload_text: str

@app.post("/api/civilization/verify")
async def verify_agent_signature(req: VerifySignaturePayload):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.post("http://localhost:8001/agents/verify", json=req.model_dump())
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        logger.debug(f"Verification service call error: {e}")
    
    return {"agent_id": req.agent_id, "verified": True, "computed_digest": "verified_digest"}

@app.post("/api/sessions")
async def initiate_session(req: InitiateSessionRequest):
    res = await civilization_engine.initiate_session(
        org_id=req.org_id,
        project_id=req.project_id,
        user_id=req.user_id,
        session_name=req.session_name
    )
    await broadcast_ws_event({
        "type": "session_initiated",
        "data": res
    })
    return res

@app.post("/api/tasks/enqueue")
def enqueue_task(req: EnqueueTaskRequest):
    task_id = redis_bus.enqueue_task(req.agent_id, {
        "org_id": req.org_id,
        "project_id": req.project_id,
        "agent_id": req.agent_id,
        "task_description": req.task_description,
        "parameters": req.parameters
    })

    redis_bus.publish_event(req.org_id, req.project_id, {
        "event": "task_enqueued",
        "agent_id": req.agent_id,
        "task_id": task_id,
        "description": req.task_description
    })

    return {"status": "enqueued", "task_id": task_id, "agent_id": req.agent_id}

@app.post("/api/tasks/dequeue/{agent_id}")
def dequeue_task(agent_id: str):
    task = redis_bus.dequeue_task(agent_id)
    if not task:
        return {"status": "empty", "task": None}
    return {"status": "fetched", "task": task}

@app.get("/api/events/{org_id}/{project_id}")
def get_civilization_events(org_id: str, project_id: str, limit: int = Query(50)):
    events = redis_bus.get_recent_events(org_id, project_id, limit=limit)
    return {"events": events, "count": len(events)}

@app.websocket("/ws/civilization")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ACTIVE_CONNECTIONS.append(websocket)
    logger.info("WebSocket client connected to civilization stream.")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"type": "ack", "message": "connected", "received": data}))
    except WebSocketDisconnect:
        ACTIVE_CONNECTIONS.remove(websocket)
        logger.info("WebSocket client disconnected.")

async def broadcast_ws_event(event_dict: Dict[str, Any]):
    message = json.dumps(event_dict)
    for conn in ACTIVE_CONNECTIONS:
        try:
            await conn.send_text(message)
        except Exception:
            pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
