"""Tool Registry Microservice (Kubernetes Service) for agent.london

Registers every Model Context Protocol (MCP) tool available to agents.
Tools can be linked and scoped to an {org} or a {project}.
Persisted in post-graph database table (mcp_tools).
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from post_graph import AsyncPostGraph
except ImportError:
    AsyncPostGraph = None

logger = logging.getLogger(__name__)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

async def get_pg_client(realm: str = "global") -> Optional[Any]:
    if not AsyncPostGraph:
        return None

    local_user = os.getenv("USER", "crajah")
    candidate_dsns = [
        DB_URI,
        f"postgresql://{local_user}@localhost:5432/postgres",
        f"postgresql://crajah:postgrespassword@localhost:5432/postgres",
        f"postgresql://postgres:postgres@localhost:5432/postgres"
    ]
    unique_dsns = []
    for d in candidate_dsns:
        if d and d not in unique_dsns:
            unique_dsns.append(d)

    for dsn in unique_dsns:
        try:
            client = AsyncPostGraph(dsn=dsn)
            await client.connect()
            await client.create_vertex_table("mcp_tools", realm=realm)
            return client
        except Exception as e:
            logger.debug(f"PostGraph connection attempt to {dsn} failed: {e}")

    return None

async def sync_tools_from_post_graph():
    """Populates local cache from post-graph database on startup using project realms."""
    realms_to_sync = ["proj_alpha_civilization", "proj_quantum_agents", "proj_neural_swarm", "org_london_meta"]
    for r in realms_to_sync:
        client = await get_pg_client(r)
        if not client:
            continue
        try:
            vertices = await client.get_vertices(table_name="mcp_tools", realm=r)
            for v in vertices:
                payload = v.payload if hasattr(v, "payload") else v
                if isinstance(payload, dict) and "tool_id" in payload:
                    TOOL_REGISTRY[payload["tool_id"]] = payload
            await client.close()
        except Exception as e:
            logger.warning(f"Failed to sync tool registry from post-graph in realm '{r}': {e}")
            try:
                await client.close()
            except Exception:
                pass

async def persist_tool_to_pg(tool_id: str, payload: Dict[str, Any]):
    """Persists tool vertex into post-graph database using project realm."""
    realm = payload.get("project_id") or payload.get("org_id") or "proj_alpha_civilization"
    client = await get_pg_client(realm)
    if not client:
        return
    try:
        await client.add_vertex(table_name="mcp_tools", realm=realm, payload=payload)
        await client.close()
    except Exception as e:
        logger.warning(f"Error persisting tool '{tool_id}' to post-graph in realm '{realm}': {e}")
        try:
            await client.close()
        except Exception:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    await sync_tools_from_post_graph()
    yield

app = FastAPI(
    title="MCP Tool Registry Service",
    description="Kubernetes Service for registering and linking MCP tools to organizations and projects",
    version="1.1.0",
    lifespan=lifespan
)

class ToolRegistrationRequest(BaseModel):
    tool_id: str = Field(..., description="Unique MCP tool identifier (e.g. mcp-pgvector-search)")
    name: str
    description: str
    scope_type: str = Field("project", description="Scope level: 'org' or 'project'")
    org_id: str
    project_id: Optional[str] = None
    endpoint_url: str = Field(..., description="HTTP/gRPC/IPC endpoint for MCP tool execution")
    min_reputation_score: float = Field(0.0, description="Minimum reputation score required to access tool")
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "tool-registry", "registered_tools": len(TOOL_REGISTRY), "persistence": "post-graph"}

@app.post("/tools/register")
async def register_tool(req: ToolRegistrationRequest):
    tool_dict = req.model_dump()
    tool_id = req.tool_id
    TOOL_REGISTRY[tool_id] = tool_dict

    # Persist tool vertex to post-graph database
    await persist_tool_to_pg(tool_id, tool_dict)

    return {"status": "registered", "tool_id": tool_id, "scope": req.scope_type}

@app.get("/tools")
def list_tools(
    org_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None)
):
    results = list(TOOL_REGISTRY.values())
    if org_id:
        results = [t for t in results if t["org_id"] == org_id]
    if project_id:
        results = [t for t in results if t["scope_type"] == "org" or t.get("project_id") == project_id]
    if scope_type:
        results = [t for t in results if t["scope_type"] == scope_type]
    return {"tools": results, "count": len(results)}

@app.get("/tools/{tool_id}")
def get_tool(tool_id: str):
    if tool_id not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"MCP Tool '{tool_id}' not found in registry.")
    return {"tool": TOOL_REGISTRY[tool_id]}

@app.delete("/tools/{tool_id}")
def delete_tool(tool_id: str):
    if tool_id not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"MCP Tool '{tool_id}' not found.")
    del TOOL_REGISTRY[tool_id]
    return {"status": "deleted", "tool_id": tool_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
