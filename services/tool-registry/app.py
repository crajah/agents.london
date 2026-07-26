"""Tool Registry Microservice (Kubernetes Service) for agent.london

Registers every Model Context Protocol (MCP) tool available to agents.
Tools can be linked and scoped to an {org} or a {project}.
"""
import os
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="MCP Tool Registry Service",
    description="Kubernetes Service for registering and linking MCP tools to organizations and projects",
    version="1.0.0"
)

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

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

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "tool-registry", "registered_tools": len(TOOL_REGISTRY)}

@app.post("/tools/register")
def register_tool(req: ToolRegistrationRequest):
    tool_dict = req.model_dump()
    tool_id = req.tool_id
    TOOL_REGISTRY[tool_id] = tool_dict
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
