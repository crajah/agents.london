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
import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from post_graph import AsyncPostGraph

logger = logging.getLogger(__name__)


@asynccontextmanager
async def pg_client(org_id: str = "org_default"):
    """Connected post-graph client for one org realm, closed on the way out.

    Connection failures are raised. This registry has no meaningful degraded
    mode: without the database it can neither read the tools it is asked for
    nor persist the ones it is given, and answering "no tools" is worse than
    refusing, because the caller cannot tell the two apart.
    """
    client = AsyncPostGraph(dsn=DB_URI)
    await client.connect()
    try:
        await client.create_vertex_table("mcp_tools", realm=org_id)
        yield client
    finally:
        try:
            await client.close()
        except Exception:
            # The work is already done or already failed; a close error must
            # not mask either, but it is still worth seeing.
            logger.exception("Failed to close post-graph client for realm '%s'", org_id)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

async def sync_tools_from_post_graph():
    """Populates local cache from post-graph on startup, across known org realms.

    Raises if a realm cannot be read. Starting with an empty cache would make
    the registry answer "no such tool" for every tool that exists, which is
    indistinguishable from a correct answer.
    """
    for org_id in ["org_london_meta", "org_default"]:
        async with pg_client(org_id) as client:
            vertices = await client.get_vertices(table_name="mcp_tools", realm=org_id)
            for v in vertices:
                payload = v.payload if hasattr(v, "payload") else v
                if isinstance(payload, dict) and "tool_id" in payload:
                    TOOL_REGISTRY[payload["tool_id"]] = payload

async def persist_tool_to_pg(tool_id: str, payload: Dict[str, Any]):
    """Persists tool vertex into post-graph. realm=org_id (physical), space=project_id (logical).

    Raises if the write fails. A registration that returns success while the
    tool exists only in this process's memory is lost at the next restart, and
    nothing downstream can detect that it was never stored.
    """
    org_id = payload.get("org_id", "org_default")
    project_id = payload.get("project_id")
    async with pg_client(org_id) as client:
        await client.add_vertex(table_name="mcp_tools", realm=org_id, space=project_id, payload=payload)

async def register_default_tools():
    """Pre-registers standard MCP tools in tool registry cache."""
    default_tools = [
        {
            "tool_id": "mcp-google-search",
            "name": "Google Search (GCP API)",
            "description": "Performs web and Google searches from within Kubernetes cluster via GCP Custom Search API.",
            "scope_type": "org",
            "org_id": "org_london_meta",
            "endpoint_url": "http://tool-registry-service.default.svc.cluster.local:8002/tools/google-search",
            "min_reputation_score": 0.0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query prompt"},
                    "num_results": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        },
        {
            "tool_id": "mcp-pgvector-search",
            "name": "PostGraph Vector Memory Search",
            "description": "Queries post-graph-rag shared vector memory for semantic document chunks and knowledge graphs.",
            "scope_type": "org",
            "org_id": "org_london_meta",
            "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
            "min_reputation_score": 0.0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Vector similarity query text"},
                    "top_k": {"type": "integer", "default": 3}
                },
                "required": ["query"]
            }
        },
        {
            "tool_id": "mcp-redis-queue",
            "name": "Redis Cluster Event Bus & Task Queue",
            "description": "Publishes event streams or queues background sub-tasks on Redis pub-sub channels.",
            "scope_type": "org",
            "org_id": "org_london_meta",
            "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
            "min_reputation_score": 0.0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Target Redis channel or queue name"},
                    "payload": {"type": "object", "description": "Event message JSON payload"}
                },
                "required": ["channel", "payload"]
            }
        },
        {
            "tool_id": "mcp-sql-query",
            "name": "PostgreSQL Relational DB Executor",
            "description": "Executes parameterized SQL queries against post-graph database tables.",
            "scope_type": "org",
            "org_id": "org_london_meta",
            "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
            "min_reputation_score": 0.0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql_query": {"type": "string", "description": "SQL statement to execute"}
                },
                "required": ["sql_query"]
            }
        },
        {
            "tool_id": "kagent-operator",
            "name": "Kubernetes Agent Cluster Operator",
            "description": "Interacts with Kubernetes API server to inspect pods, deployments, and cluster rollouts.",
            "scope_type": "org",
            "org_id": "org_london_meta",
            "endpoint_url": "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call",
            "min_reputation_score": 0.0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Cluster operator command (e.g. get pods, status)"}
                },
                "required": ["command"]
            }
        }
    ]
    for tool in default_tools:
        TOOL_REGISTRY[tool["tool_id"]] = tool
        await persist_tool_to_pg(tool["tool_id"], tool)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await sync_tools_from_post_graph()
    await register_default_tools()
    yield

tags_metadata = [
    {"name": "Tool Registry", "description": "Register, retrieve, link, and execute Model Context Protocol (MCP) tools."},
    {"name": "System", "description": "Health check and microservice status endpoints."}
]

app = FastAPI(
    title="MCP Tool Registry Microservice",
    description="""
    # 🧰 agent.london MCP Tool Registry OpenAPI Specs
    
    Manages registration, capability discovery, and execution binding for Model Context Protocol (MCP) tools (Search, Code Execution, SQL Queries, Kubernetes Operators) backed by `post-graph`.
    
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
        results = [t for t in results if t.get("org_id") == org_id]
    if project_id:
        results = [t for t in results if t.get("scope_type") == "org" or t.get("project_id") == project_id]
    if scope_type:
        results = [t for t in results if t.get("scope_type") == scope_type]
    return {"tools": results, "count": len(results)}

@app.get("/tools/rag-documents")
def get_tool_rag_documents(project_id: Optional[str] = Query(None), org_id: Optional[str] = Query(None)):
    """Export human-readable text documents of registered MCP tools for post-graph-rag indexing."""
    import json
    tools = list(TOOL_REGISTRY.values())
    if org_id:
        tools = [t for t in tools if t.get("org_id") == org_id]
    if project_id:
        tools = [t for t in tools if t.get("scope_type") == "org" or t.get("project_id") == project_id]

    documents = []
    for t in tools:
        doc_text = (
            f"Tool Name: {t['name']}\n"
            f"Tool ID: {t['tool_id']}\n"
            f"Scope Type: {t.get('scope_type')}\n"
            f"Endpoint URL: {t.get('endpoint_url')}\n"
            f"Description & Capabilities: {t.get('description')}\n"
            f"Input Schema Parameters: {json.dumps(t.get('input_schema', {}))}\n"
            f"Metadata: {json.dumps(t.get('metadata', {}))}"
        )
        documents.append({
            "id": t["tool_id"],
            "tool_id": t["tool_id"],
            "name": t["name"],
            "description": t.get("description"),
            "content": doc_text,
            "title": f"Tool_{t['tool_id']}"
        })
    return {"documents": documents, "count": len(documents)}

@app.get("/tools/{tool_id}")
def get_tool(tool_id: str):
    if tool_id not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"MCP Tool '{tool_id}' not found in registry.")
    return {"tool": TOOL_REGISTRY[tool_id]}

class GoogleSearchRequest(BaseModel):
    query: str
    num_results: int = Field(5, ge=1, le=10)
    project_id: Optional[str] = "proj_alpha_civilization"

@app.post("/tools/google-search")
async def execute_google_search(req: GoogleSearchRequest):
    """Executes a Google Search query from within the Kubernetes cluster via GCP Custom Search API.

    Every failure path returns an error. This endpoint previously answered
    `status: success` with three invented results whose snippets described
    themselves as "empirically retrieved" — handing an agent fabricated
    evidence it had no way to distinguish from a real search, and which would
    then be reasoned over and persisted as fact.
    """
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_CX")
    if not api_key or not cx:
        raise HTTPException(
            status_code=503,
            detail="Search is unconfigured: set GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX.",
        )

    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": api_key, "cx": cx, "q": req.query, "num": req.num_results}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url, params=params)
    except httpx.HTTPError as e:
        logger.warning("GCP Custom Search request failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Search upstream unreachable: {e}") from e

    if res.status_code != 200:
        logger.warning("GCP Custom Search returned %s: %s", res.status_code, res.text[:200])
        raise HTTPException(
            status_code=502,
            detail=f"Search upstream returned {res.status_code}.",
        )

    items = res.json().get("items", [])
    results = [
        {"title": item.get("title"), "snippet": item.get("snippet"), "link": item.get("link")}
        for item in items
    ]
    return {
        "status": "success",
        "source": "gcp_custom_search_api",
        "query": req.query,
        "count": len(results),
        "results": results,
    }

@app.delete("/tools/{tool_id}")
def delete_tool(tool_id: str):
    if tool_id not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"MCP Tool '{tool_id}' not found.")
    del TOOL_REGISTRY[tool_id]
    return {"status": "deleted", "tool_id": tool_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
