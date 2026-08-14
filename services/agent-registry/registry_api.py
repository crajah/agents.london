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
    DEPRECATED, PUBLISHED, REVOKED, AgentVersionSpec, PipelineVersionSpec,
    RegistrationError,
)
from registry_store import (
    AGENTS, PIPELINES, RUNS, SPAWNS, ensure_schema, link_run, register_agent_version,
    register_pipeline_version, resolve_vertex, set_lifecycle, set_version_status,
    pipelines_pinning, _latest_versions,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterAgentRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str = "proj_default"
    identity: Dict[str, Any] = Field(..., description="name, slug, telos, description, caste")
    version: AgentVersionSpec
    spawned_by: Optional[str] = Field(None, description="agent_id of the spawning agent")
    derived_from: Optional[Dict[str, Any]] = Field(
        None, description="Origin realm/agent_id/version/content_hash for a copy (§11.1)")
    publish: bool = Field(
        True, description="False registers a draft: staged, unpinnable, undiscoverable")


class RegisterPipelineRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str = "proj_default"
    identity: Dict[str, Any]
    version: PipelineVersionSpec


class RetireRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str = "proj_default"
    version: str
    status: str = DEPRECATED
    replacement_version_id: Optional[str] = None
    cascade: bool = False


class LifecycleRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str = "proj_default"
    lifecycle: str = "dormant"


def _client(request: Request) -> Any:
    """The registry's post-graph client, held on app.state by the host app."""
    client = getattr(request.app.state, "pg_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Registry has no database connection.")
    return client


# ------------------------------------------------------------- registration

async def _embed_identity(identity: Dict[str, Any],
                          capabilities: Optional[List[str]] = None):
    """The discovery vector for an agent or pipeline (§3.1, §10).

    Computed from name, telos, description and capability names — which is what
    makes "find me an agent that can summarise filings" resolve without a
    keyword index. Never fails a registration: see backend/embedding.py.
    """
    try:
        from embedding import discovery_text, embed
        return await embed(discovery_text(
            identity.get("name"), identity.get("telos"),
            identity.get("description"), ", ".join(capabilities or [])))
    except Exception:
        logger.exception("embedding unavailable; registering without a "
                         "discovery vector")
        return None


@router.post("/agents", tags=["Agent Registry"])
async def register_agent(req: RegisterAgentRequest, request: Request):
    """Register one agent version (§3.2).

    Validation failures are 400s naming the rule, not 500s: a caller that
    pinned a draft or omitted a schema needs to know which, and the registry
    knows exactly which.
    """
    from tool_client import ToolResolutionError, catalogue_or_none

    client = _client(request)
    await ensure_schema(client, req.org_id)

    try:
        # Rule 3.5 / §9 rejection 10 — tools are resolved to pins before the
        # hash is computed, and a tool that is missing, unpublished, revoked or
        # out of scope fails the registration here rather than at run time.
        tools = await catalogue_or_none(req.org_id, req.project_id,
                                        required=bool(req.version.tools))
    except ToolResolutionError as e:
        raise HTTPException(
            status_code=503,
            detail=(f"Cannot resolve this agent's tools: {e}. Registering with "
                    f"unresolved tool names would publish a version whose tools "
                    f"404 mid-conversation.")) from e

    embedding = await _embed_identity(req.identity, req.version.capabilities)
    try:
        record = await register_agent_version(
            client, req.org_id, req.project_id, req.identity, req.version,
            embedding=embedding, spawned_by=req.spawned_by, tool_catalogue=tools,
            derived_from=req.derived_from, publish=req.publish)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "registered", "agent_id": req.version.agent_id,
            "version": req.version.version, "content_hash": record["content_hash"],
            "version_status": record["status"], "tools": record.get("tools", [])}


@router.post("/pipelines", tags=["Agent Registry"])
async def register_pipeline(req: RegisterPipelineRequest, request: Request):
    """Register one immutable pipeline composition (§3.4, §9)."""
    client = _client(request)
    await ensure_schema(client, req.org_id)
    embedding = await _embed_identity(req.identity, req.version.capabilities)
    try:
        record = await register_pipeline_version(
            client, req.org_id, req.project_id, req.identity, req.version,
            embedding=embedding)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "registered", "pipeline_id": req.version.pipeline_id,
            "version": record["version"], "is_cyclic": record["is_cyclic"],
            "back_edges": record["back_edges"], "steps": len(req.version.steps),
            "resolved_steps": record["steps"]}


# ----------------------------------------------------------------- retirement

@router.post("/agents/{agent_id}/retire", tags=["Agent Registry"])
async def retire_agent_version(agent_id: str, req: RetireRequest, request: Request):
    """Deprecate or revoke one agent version (§4.4, Rule 4.4).

    Revoking a version that published pipelines pin requires either a
    replacement or an explicit cascade. Silent revocation would break pipelines
    that go on reporting success until a run fails at resolution.
    """
    client = _client(request)
    try:
        record = await set_version_status(
            client, AGENTS, req.org_id, req.project_id, agent_id, req.version,
            req.status, req.replacement_version_id, req.cascade)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": record["status"], "agent_id": agent_id,
            "version": req.version, "dependents": record.get("dependents", []),
            "cascaded": record.get("cascaded", [])}


@router.post("/pipelines/{pipeline_id}/retire", tags=["Agent Registry"])
async def retire_pipeline_version(pipeline_id: str, req: RetireRequest,
                                  request: Request):
    client = _client(request)
    try:
        record = await set_version_status(
            client, PIPELINES, req.org_id, req.project_id, pipeline_id, req.version,
            req.status, req.replacement_version_id, req.cascade)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": record["status"], "pipeline_id": pipeline_id,
            "version": req.version}


@router.post("/agents/{agent_id}/lifecycle", tags=["Agent Registry"])
async def set_agent_lifecycle(agent_id: str, req: LifecycleRequest, request: Request):
    """Deletion is dormancy (Rule 3.2).

    An agent is never removed: its `spawns` edges are the provenance record of
    everything below it, and deleting the agent deletes that record too.
    """
    client = _client(request)
    try:
        payload = await set_lifecycle(client, AGENTS, req.org_id, req.project_id,
                                      agent_id, req.lifecycle)
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"status": payload["lifecycle"], "agent_id": agent_id,
            "note": "Retained for provenance; excluded from discovery."}


@router.get("/agents/{agent_id}/dependents", tags=["Agent Registry"])
async def agent_dependents(agent_id: str, request: Request, version: str,
                           org_id: str = "org_default",
                           project_id: str = "proj_default"):
    """Which published pipelines pin this agent version (§10, by structure).

    One hop backwards along `composes_pipeline` — the query that composition
    being edges rather than a JSON blob on a row exists to make possible.
    """
    client = _client(request)
    return {"agent_id": agent_id, "version": version,
            "pipelines": await pipelines_pinning(client, org_id, project_id,
                                                 agent_id, version)}


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


# --------------------------------------------------------------- discovery

class DiscoverRequest(BaseModel):
    """A discovery call as a JSON body.

    The GET form is what a person or a service calls. This one exists because a
    registered tool is dispatched as `POST endpoint_url` with the arguments as
    the body (tool-registry Rule 7.1) — so without it, discovery could not be a
    tool, and an agent could not be given the ability to find another agent.
    """
    q: Optional[str] = None
    capability: Optional[str] = None
    kind: str = "agent"
    org_id: str = "org_default"
    project_id: Optional[str] = None
    top_k: int = 5
    include_inactive: bool = False


@router.post("/discover", tags=["Discovery"])
async def discover_post(req: DiscoverRequest, request: Request):
    """Same discovery, called the way a tool is dispatched."""
    return await discover(request, q=req.q, capability=req.capability,
                          kind=req.kind, org_id=req.org_id,
                          project_id=req.project_id, top_k=req.top_k,
                          include_inactive=req.include_inactive)


@router.get("/discover", tags=["Discovery"])
async def discover(request: Request, q: Optional[str] = None,
                   capability: Optional[str] = None,
                   kind: str = "agent", org_id: str = "org_default",
                   project_id: Optional[str] = None, top_k: int = 5,
                   include_inactive: bool = False):
    """Find agents or pipelines by description or by capability (§10).

    By vector when `q` is given — the path an orchestrator takes when it knows
    what it needs and not what it is called. By exact capability when
    `capability` is given. Rule 10.1: only published, active entries unless the
    caller explicitly asks otherwise.
    """
    client = _client(request)
    table = AGENTS if kind == "agent" else PIPELINES

    if capability and not q:
        entries = await published_versions(client, org_id, table, project_id)
        hits = [e for e in entries
                if capability in (e["record"].get("capabilities") or [])]
        return {"kind": kind, "capability": capability,
                "results": [_discovery_row(e) for e in hits[:top_k]],
                "count": min(len(hits), top_k), "method": "capability"}

    if not q:
        raise HTTPException(status_code=400,
                            detail="Provide q (semantic) or capability (exact).")

    try:
        from embedding import embed
        vector = await embed(q)
    except Exception:
        vector = None
    if vector is None:
        raise HTTPException(
            status_code=503,
            detail="Semantic discovery is unavailable: no embedding could be "
                   "computed. Query by capability instead, or retry.")

    try:
        found = await client.vector_search(
            table_name=table, realm=org_id, query_vector=vector,
            top_k=top_k * 3, space=project_id)
    except Exception as e:
        logger.exception("vector search failed in realm %r", org_id)
        raise HTTPException(status_code=503, detail=f"Vector search failed: {e}") from e

    results: List[Dict[str, Any]] = []
    for vertex, distance in found:
        identity = vertex.payload
        if isinstance(identity, str):
            identity = json.loads(identity)
        if not include_inactive and identity.get("lifecycle", "active") != "active":
            continue
        if identity.get("is_origin_stub"):
            continue          # a lineage stub is not a callable thing
        versions = await _latest_versions(client, table, org_id, int(vertex.id))
        current = identity.get("current_version")
        body = versions.get(current) if current else None
        if body is None or body.get("status") != PUBLISHED:
            continue
        results.append({**_discovery_row({"identity": identity,
                                          "version": body.get("version"),
                                          "record": body}),
                        "distance": distance})
        if len(results) >= top_k:
            break
    return {"kind": kind, "query": q, "results": results,
            "count": len(results), "method": "vector"}


def _discovery_row(entry: Dict[str, Any]) -> Dict[str, Any]:
    identity, record = entry["identity"], entry["record"]
    return {
        "id": identity.get("agent_id") or identity.get("pipeline_id"),
        "name": identity.get("name"),
        "slug": identity.get("slug"),
        "telos": identity.get("telos"),
        "description": identity.get("description"),
        "version": entry["version"],
        "content_hash": record.get("content_hash"),
        "capabilities": record.get("capabilities", []),
        "lifecycle": identity.get("lifecycle", "active"),
    }


@router.get("/agents/{agent_id}/descendants", tags=["Discovery"])
async def descendants(agent_id: str, request: Request,
                      org_id: str = "org_default", project_id: Optional[str] = None,
                      max_depth: int = 5):
    """Everything descended from this agent (§10, by structure).

    A bounded traversal over `spawns`. Rule 6.4: `max_depth`, `relation_types`
    and `space` are all passed. Depth because a provenance graph is not
    guaranteed acyclic once agents fork copies of each other; relation types so
    the walk is never routed through an edge the caller did not ask for; space
    because post-graph filters per step, and a walk that starts correctly
    scoped wanders into another project's subgraph after the first hop
    (Rule 2.1).
    """
    client = _client(request)
    pk = await resolve_vertex(client, AGENTS, org_id, agent_id, project_id)
    if pk is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent {agent_id!r}.")
    try:
        walked = await client.traverse(
            realm=org_id, start_table=AGENTS, start_id=str(pk),
            edge_tables=[SPAWNS], direction="out", max_depth=max_depth,
            relation_types=["spawned"], space=project_id)
    except Exception as e:
        logger.exception("traverse over spawns failed")
        raise HTTPException(status_code=503, detail=f"Traversal failed: {e}") from e

    return {"agent_id": agent_id, "max_depth": max_depth,
            "descendants": await _hydrate(client, org_id, pk, walked)}


async def _hydrate(client, realm: str, root_pk: int,
                   walked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn traversal rows into agent identities.

    `traverse` returns `{id, table_name, depth, path, edge_path, edge_ids}` —
    ids and depths, not payloads. Reading `.payload` off these rows returns
    nothing at all, silently, which is the shape of bug that makes a provenance
    endpoint look like it works on an empty graph and stay empty on a full one.
    """
    ref = client._get_table_ref(AGENTS, realm)
    rows: List[Dict[str, Any]] = []
    for step in walked or []:
        if step.get("table_name") != AGENTS:
            continue
        pk = int(step["id"])
        if pk == root_pk:
            continue          # the anchor is the agent asked about, not a descendant
        found = await client._fetch(
            f"SELECT payload FROM {ref} WHERE realm = $1 AND id = $2", realm, pk)
        if not found:
            continue
        payload = found[0]["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        rows.append({"agent_id": payload.get("agent_id"),
                     "name": payload.get("name"),
                     "lifecycle": payload.get("lifecycle", "active"),
                     "depth": step.get("depth")})
    return rows


# --------------------------------------------------------------------- runs

@router.get("/runs", tags=["Discovery"])
async def list_runs(request: Request, org_id: str = "org_default",
                    project_id: Optional[str] = None, limit: int = 25):
    """Recent runs, newest first (§3.5)."""
    client = _client(request)
    ref = client._get_table_ref(RUNS, org_id)
    args: List[Any] = [org_id]
    space_filter = ""
    if project_id:
        space_filter = " AND space = $2"
        args.append(project_id)
    try:
        rows = await client._fetch(
            f"SELECT id, payload FROM {ref} WHERE realm = $1{space_filter} "
            f"ORDER BY id DESC LIMIT {int(limit)}", *args)
    except Exception as e:
        if "does not exist" in str(e).lower():
            return {"runs": [], "count": 0}
        raise

    runs = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        runs.append({"pk": int(row["id"]), **payload})
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{run_pk}/context", tags=["Discovery"])
async def run_context(run_pk: int, request: Request, org_id: str = "org_default"):
    """Every context revision this run wrote, in order (§3.6).

    Revisions are returned rather than a final snapshot. The registry keeps
    each one precisely so a cyclic run can be read back afterwards (Rule 8.5) —
    showing only the last value discards the reason it is kept, and makes the
    second iteration of a loop indistinguishable from the first (F.33).

    Conflicts are returned alongside: last-writer-wins is recorded, not silent
    (Rule 8.6).
    """
    client = _client(request)
    try:
        records = await client.get_vertex_data(table_name=RUNS, realm=org_id,
                                               vertex_id=run_pk)
    except Exception as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail="No such run.") from e
        raise

    revisions, conflicts = [], []
    for record in records or []:
        body = record.to_dict() if hasattr(record, "to_dict") else record
        body = body.get("payload", body)
        if isinstance(body, str):
            body = json.loads(body)
        if not isinstance(body, dict):
            continue
        if body.get("kind") == "context":
            revisions.append(body)
        elif body.get("kind") == "conflict":
            conflicts.append(body)

    # Oldest first, and by revision within a key: the order a reader needs.
    revisions.sort(key=lambda r: (r.get("written_at") or "", r.get("revision") or 0))

    keys = {}
    for revision in revisions:
        keys.setdefault(revision["key"], []).append(revision)

    return {"run_pk": run_pk, "revisions": revisions, "count": len(revisions),
            "keys": keys, "conflicts": conflicts}


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


@router.get("/.well-known/agent.json", tags=["A2A"])
async def registry_agent_card(request: Request, org_id: str = "org_default"):
    """This registry's own A2A card (§7.2).

    A2A clients look here first to find out what they are talking to. Serving
    per-version cards without this one means a client has to be told each
    agent's URL out of band, which defeats the point of a well-known path.
    """
    client = _client(request)
    agents = await published_versions(client, org_id, AGENTS)
    pipelines = await published_versions(client, org_id, PIPELINES)
    skills = sorted({c for entry in agents + pipelines
                     for c in (entry["record"].get("capabilities") or [])})
    return {
        "name": "agent.london registry",
        "description": (
            "Versioned registry of agents and pipelines. Every published version "
            "is callable over MCP and A2A; nothing else is."),
        "url": str(request.base_url).rstrip("/"),
        "version": "1.0.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [{"id": s, "name": s.replace("_", " "),
                    "description": f"Offered by at least one published agent or pipeline.",
                    "inputModes": ["text"], "outputModes": ["text"]}
                   for s in skills],
        "provenance": {
            "published_agents": len(agents),
            "published_pipelines": len(pipelines),
            # Named so a client can discover the rest without guessing paths.
            "cards": "/a2a/agents/{slug}/{version}/card",
            "tools": "/mcp/tools",
            "discovery": "/discover",
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


class McpCallBody(BaseModel):
    """An MCP call with the name in the body rather than the path.

    A registered tool is dispatched as `POST endpoint_url` with the arguments
    as the body, and the endpoint is fixed at registration — so a tool that
    invokes an agent cannot put the agent's name in its own URL. This is the
    form `mcp-agent-invoke` calls.
    """
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    org_id: str = "org_default"
    project_id: str = "proj_default"


@router.post("/mcp/call", tags=["MCP"])
async def mcp_call_by_body(body: McpCallBody, request: Request):
    """Same invocation, with the callee named in the body."""
    return await mcp_call(body.tool_name,
                          CallRequest(arguments=body.arguments, org_id=body.org_id,
                                      project_id=body.project_id),
                          request)


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
        out = await _run_pipeline(request, client, req, entry,
                                  trigger={"kind": "mcp", "by": tool_name})
        # Rule 6.3 surfaced at the protocol edge: a halted run is not success.
        return {"content": [{"type": "text", "text": json.dumps(out["output"])}],
                "isError": out["status"] != "succeeded",
                "status": out["status"], "halt_reason": out.get("halt_reason")}
    except ExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


async def _run_pipeline(request: Request, client, req: CallRequest,
                        entry: Dict[str, Any],
                        trigger: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a published pipeline version through the runtime."""
    from execution import step_runner_for
    from pipeline_runtime import PipelineExecutor, RedisTransport, RunStore
    from registry_model import PipelineVersionSpec

    spec = PipelineVersionSpec(**{
        k: v for k, v in entry["record"].items()
        if k in PipelineVersionSpec.model_fields})
    # A run with no store executes and leaves no record — the audit trail the
    # whole design rests on is only there if something writes it.
    store = RunStore(request.app.state.pg_client_factory, linker=link_run) \
        if getattr(request.app.state, "pg_client_factory", None) else None

    async def resolve_pipeline(pipeline_id: str, version: Optional[str] = None):
        """Load a pipeline spec for a nested invocation (§6.3)."""
        found = await _find_by_slug_or_id(client, req.org_id, PIPELINES,
                                          pipeline_id, version)
        return PipelineVersionSpec(**{
            k: v for k, v in found["record"].items()
            if k in PipelineVersionSpec.model_fields})

    executor = PipelineExecutor(
        step_runner_for(client, req.org_id, req.project_id),
        transport=RedisTransport(getattr(request.app.state, "redis", None)),
        meter=getattr(request.app.state, "meter", None), store=store,
        org_id=req.org_id, project_id=req.project_id,
        pipeline_resolver=resolve_pipeline)
    run = await executor.execute(spec, req.arguments, trigger=trigger)
    return run.to_payload()


async def _find_by_slug_or_id(client, realm: str, table: str, identifier: str,
                              version: Optional[str]) -> Dict[str, Any]:
    """Resolve by slug first, then by business id, to a published version."""
    key = "agent_id" if table == AGENTS else "pipeline_id"
    for entry in await published_versions(client, realm, table):
        identity = entry["identity"]
        if identity.get("slug") != identifier and identity.get(key) != identifier:
            continue
        if version is None or entry["version"] == version:
            return entry
    raise HTTPException(
        status_code=404,
        detail=f"No published {table[:-1]} {identifier}"
               f"{'@' + version if version else ''}.")


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
        run = await _run_pipeline(
            request, client, req, entry,
            trigger={"kind": "a2a", "by": f"{slug}@{version}"})
    except ExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    state = {"succeeded": "completed"}.get(run["status"], "failed")
    body = {"state": state,
            "artifacts": [{"parts": [{"type": "text",
                                      "text": json.dumps(run["output"])}]}]}
    if run["status"] == "halted":
        body["halt_reason"] = run.get("halt_reason")
    return body
