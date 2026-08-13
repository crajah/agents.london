"""HTTP surface for the agent graph: registration, MCP and A2A.

Exposure is *derived* from the registry rather than maintained alongside it
(Rule 7.4). A published version is callable; an unpublished one is not. Two
lists that can disagree eventually will, and the failure mode — a tool that
advertises itself and then 404s — is the kind that only shows up in front of a
caller.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from registry_model import (
    PUBLISHED, AgentVersionSpec, PipelineVersionSpec, RegistrationError,
)
from registry_store import (
    AGENTS, PIPELINES, ensure_schema, register_agent_version,
    register_pipeline_version, resolve_vertex, _latest_versions,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterAgentRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str = "proj_default"
    identity: Dict[str, Any] = Field(..., description="name, slug, telos, description, caste")
    version: AgentVersionSpec
    spawned_by: Optional[str] = Field(None, description="agent_id of the spawning agent")


class RegisterPipelineRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str = "proj_default"
    identity: Dict[str, Any]
    version: PipelineVersionSpec


def _client(request: Request) -> Any:
    """The registry's post-graph client, held on app.state by the host app."""
    client = getattr(request.app.state, "pg_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Registry has no database connection.")
    return client


# ------------------------------------------------------------- registration

@router.post("/agents", tags=["Agent Registry"])
async def register_agent(req: RegisterAgentRequest, request: Request):
    """Register one immutable agent version (§3.2).

    Validation failures are 400s naming the rule, not 500s: a caller that
    pinned a draft or omitted a schema needs to know which, and the registry
    knows exactly which.
    """
    client = _client(request)
    await ensure_schema(client, req.org_id)
    try:
        record = await register_agent_version(
            client, req.org_id, req.project_id, req.identity, req.version,
            spawned_by=req.spawned_by)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "registered", "agent_id": req.version.agent_id,
            "version": req.version.version, "content_hash": record["content_hash"]}


@router.post("/pipelines", tags=["Agent Registry"])
async def register_pipeline(req: RegisterPipelineRequest, request: Request):
    """Register one immutable pipeline composition (§3.4, §9)."""
    client = _client(request)
    await ensure_schema(client, req.org_id)
    try:
        record = await register_pipeline_version(
            client, req.org_id, req.project_id, req.identity, req.version)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "registered", "pipeline_id": req.version.pipeline_id,
            "version": req.version.version, "is_cyclic": record["is_cyclic"],
            "back_edges": record["back_edges"], "steps": len(req.version.steps)}


# ----------------------------------------------------------------- listing

async def published_versions(client, realm: str, table: str,
                             space: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every published version in a realm, with its identity payload attached.

    Rule 10.1: only published, active entries. Draft, deprecated and revoked
    versions exist in history and stay out of every discovery surface.
    """
    ref = client._get_table_ref(table, realm)
    args: List[Any] = [realm]
    space_filter = ""
    if space:
        space_filter = " AND space = $2"
        args.append(space)
    rows = await client._fetch(
        f"SELECT id, payload FROM {ref} WHERE realm = $1{space_filter}", *args)

    out: List[Dict[str, Any]] = []
    for row in rows:
        identity = row["payload"]
        if isinstance(identity, str):
            import json
            identity = json.loads(identity)
        if identity.get("lifecycle", "active") != "active":
            continue
        versions = await _latest_versions(client, table, realm, int(row["id"]))
        for version, body in versions.items():
            if body.get("status") == PUBLISHED:
                out.append({"identity": identity, "version": version, "record": body})
    return out


# --------------------------------------------------------------------- MCP

def mcp_tool_name(kind: str, slug: str, version: Optional[str] = None) -> str:
    """`agent:{slug}@{version}` — the version is part of the name (Rule 7.1)."""
    return f"{kind}:{slug}@{version}" if version else f"{kind}:{slug}"


def as_mcp_tool(kind: str, entry: Dict[str, Any], pinned: bool = True) -> Dict[str, Any]:
    identity, record = entry["identity"], entry["record"]
    slug = identity.get("slug") or identity.get("name", "unnamed")
    caps = record.get("capabilities") or []
    description = " ".join(filter(None, [
        identity.get("telos", ""), identity.get("description", ""),
        f"Capabilities: {', '.join(caps)}." if caps else "",
    ])).strip()
    return {
        "name": mcp_tool_name(kind, slug, entry["version"] if pinned else None),
        "description": description,
        # Rule 7.2: the stored schema, unmodified. A second hand-maintained copy
        # drifts, and the drift surfaces as a validation error the caller cannot
        # diagnose from the outside.
        "inputSchema": record.get("input_schema", {"type": "object"}),
    }


@router.get("/mcp/tools", tags=["MCP"])
async def mcp_tools(request: Request, org_id: str = "org_default",
                    project_id: Optional[str] = None):
    """tools/list — every published agent and pipeline version.

    Each is listed twice: once pinned to its exact version, and once under an
    unversioned alias resolving to the current version. The alias is documented
    as unstable because it is: it changes under callers when a new version
    publishes.
    """
    client = _client(request)
    tools: List[Dict[str, Any]] = []
    for table, kind in ((AGENTS, "agent"), (PIPELINES, "pipeline")):
        entries = await published_versions(client, org_id, table, project_id)
        seen_alias = set()
        for entry in entries:
            tools.append(as_mcp_tool(kind, entry))
            slug = entry["identity"].get("slug")
            if slug and entry["version"] == entry["identity"].get("current_version") \
                    and slug not in seen_alias:
                seen_alias.add(slug)
                alias = as_mcp_tool(kind, entry, pinned=False)
                alias["description"] += " (unversioned alias — resolves to the " \
                                        "current version and changes without notice)"
                tools.append(alias)
    return {"tools": tools, "count": len(tools)}


# --------------------------------------------------------------------- A2A

def as_agent_card(kind: str, entry: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    identity, record = entry["identity"], entry["record"]
    slug = identity.get("slug") or identity.get("name", "unnamed")
    plural = "agents" if kind == "agent" else "pipelines"
    return {
        "name": identity.get("name", slug),
        "description": identity.get("description", ""),
        "url": f"{base_url.rstrip('/')}/a2a/{plural}/{slug}/{entry['version']}",
        "version": entry["version"],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [
            {"id": c, "name": c.replace("_", " "), "description": identity.get("telos", ""),
             "inputModes": ["text"], "outputModes": ["text"]}
            for c in (record.get("capabilities") or [])
        ],
        # Beyond the A2A baseline: what this is, and what it was built from.
        # A delegating caller that cannot verify provenance is trusting a name.
        "provenance": {
            "agent_id": identity.get("agent_id") or identity.get("pipeline_id"),
            "content_hash": record.get("content_hash"),
            "is_pipeline": kind == "pipeline",
            "is_cyclic": record.get("is_cyclic", False),
        },
    }


@router.get("/a2a/{plural}/{slug}/{version}/card", tags=["A2A"])
async def a2a_card(plural: str, slug: str, version: str, request: Request,
                   org_id: str = "org_default"):
    if plural not in ("agents", "pipelines"):
        raise HTTPException(status_code=404, detail="Unknown card type.")
    client = _client(request)
    table = AGENTS if plural == "agents" else PIPELINES
    kind = "agent" if plural == "agents" else "pipeline"
    for entry in await published_versions(client, org_id, table):
        if entry["identity"].get("slug") == slug and entry["version"] == version:
            return as_agent_card(kind, entry, base_url="")
    # Distinguishable from "exists but unpublished" only in the log, on purpose:
    # an unpublished version must not be discoverable by probing.
    raise HTTPException(status_code=404,
                        detail=f"No published {kind} {slug}@{version}.")


# ------------------------------------------------------- invocation (MCP/A2A)

class CallRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    org_id: str = "org_default"
    project_id: str = "proj_default"


def parse_tool_name(name: str) -> tuple:
    """`agent:slug@1.2.3` -> ("agent", "slug", "1.2.3"); version optional."""
    kind, _, rest = name.partition(":")
    if kind not in ("agent", "pipeline") or not rest:
        raise HTTPException(status_code=400, detail=f"Malformed tool name {name!r}.")
    slug, _, version = rest.partition("@")
    return kind, slug, (version or None)


async def _find_by_slug(client, realm: str, table: str, slug: str,
                        version: Optional[str]) -> Dict[str, Any]:
    for entry in await published_versions(client, realm, table):
        if entry["identity"].get("slug") != slug:
            continue
        if version is None or entry["version"] == version:
            return entry
    raise HTTPException(status_code=404,
                        detail=f"No published {table[:-1]} {slug}"
                               f"{'@' + version if version else ''}.")


@router.post("/mcp/tools/{tool_name}/call", tags=["MCP"])
async def mcp_call(tool_name: str, req: CallRequest, request: Request):
    """tools/call — resolve the name to a published version and execute it.

    Listing without invoking made the MCP surface descriptive only: a client
    could discover a tool and had no way to use it.
    """
    from execution import ExecutionError, run_agent
    client = _client(request)
    kind, slug, version = parse_tool_name(tool_name)
    table = AGENTS if kind == "agent" else PIPELINES
    entry = await _find_by_slug(client, req.org_id, table, slug, version)

    try:
        if kind == "agent":
            out = await run_agent(
                client, req.org_id, entry["identity"]["agent_id"], req.arguments,
                version=entry["version"], project_id=req.project_id,
                meter=getattr(request.app.state, "meter", None))
            return {"content": [{"type": "text", "text": out["result"]}],
                    "isError": False, "usage": out["usage"]}
        out = await _run_pipeline(request, client, req, entry)
        # Rule 6.3 surfaced at the protocol edge: a halted run is not success.
        return {"content": [{"type": "text", "text": json.dumps(out["output"])}],
                "isError": out["status"] != "succeeded",
                "status": out["status"], "halt_reason": out.get("halt_reason")}
    except ExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


async def _run_pipeline(request: Request, client, req: CallRequest,
                        entry: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a published pipeline version through the runtime."""
    from execution import step_runner_for
    from pipeline_runtime import PipelineExecutor, RedisTransport, RunStore
    from registry_model import PipelineVersionSpec

    spec = PipelineVersionSpec(**{
        k: v for k, v in entry["record"].items()
        if k in PipelineVersionSpec.model_fields})
    executor = PipelineExecutor(
        step_runner_for(client, req.org_id, req.project_id,
                        meter=getattr(request.app.state, "meter", None)),
        transport=RedisTransport(getattr(request.app.state, "redis", None)),
        meter=getattr(request.app.state, "meter", None),
        org_id=req.org_id, project_id=req.project_id)
    run = await executor.execute(spec, req.arguments)
    return run.to_payload()


@router.post("/a2a/{plural}/{slug}/{version}/tasks", tags=["A2A"])
async def a2a_task(plural: str, slug: str, version: str, req: CallRequest,
                   request: Request):
    """A2A task submission, mapped onto a run.

    A halted run is reported `failed` with a halt_reason (spec §11.5). A2A has
    no state for "stopped early with partial output", and mapping it to
    `completed` would let a client read a partial result as a complete one.
    """
    from execution import ExecutionError, run_agent
    if plural not in ("agents", "pipelines"):
        raise HTTPException(status_code=404, detail="Unknown task target.")
    client = _client(request)
    table = AGENTS if plural == "agents" else PIPELINES
    entry = await _find_by_slug(client, req.org_id, table, slug, version)

    try:
        if plural == "agents":
            out = await run_agent(
                client, req.org_id, entry["identity"]["agent_id"], req.arguments,
                version=version, project_id=req.project_id,
                meter=getattr(request.app.state, "meter", None))
            return {"state": "completed",
                    "artifacts": [{"parts": [{"type": "text", "text": out["result"]}]}],
                    "usage": out["usage"]}
        run = await _run_pipeline(request, client, req, entry)
    except ExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    state = {"succeeded": "completed"}.get(run["status"], "failed")
    body = {"state": state,
            "artifacts": [{"parts": [{"type": "text",
                                      "text": json.dumps(run["output"])}]}]}
    if run["status"] == "halted":
        body["halt_reason"] = run.get("halt_reason")
    return body
