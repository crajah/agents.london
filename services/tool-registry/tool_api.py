"""HTTP surface for the tool registry: registration, discovery and invocation.

Exposure is derived from the registry, never maintained alongside it: a
published, active, in-scope tool version is listed and callable, and anything
else is neither. Two lists that can disagree eventually will, and the failure
mode — a tool an agent can discover and cannot call — surfaces mid-conversation
where a model will narrate around it rather than report it.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from tool_model import (
    ACTIVE, DEPRECATED, DORMANT, PUBLISHED, REVOKED, RegistrationError,
    ToolIdentity, ToolVersionSpec, discovery_text, validate_arguments,
)
from tool_store import (
    TOOLS, ensure_schema, get_tool, list_tools, register_tool_version,
    set_lifecycle, set_version_status,
)

logger = logging.getLogger(__name__)
router = APIRouter()

AGENT_REGISTRY_URL = os.getenv(
    "AGENT_REGISTRY_URL",
    "http://agent-registry-service.default.svc.cluster.local:8001")
REPUTATION_TIMEOUT = float(os.getenv("REPUTATION_TIMEOUT", "5"))


# ------------------------------------------------------------------- requests

class RegisterToolRequest(BaseModel):
    identity: ToolIdentity
    version: ToolVersionSpec


class LegacyRegisterRequest(BaseModel):
    """The pre-versioning registration shape, still accepted.

    Deployment manifests and the backend register tools with this body. Rather
    than break them, it is translated into an identity plus a `1.0.0` version —
    so a caller that has not been updated still produces a properly versioned,
    hashed, pinnable tool rather than an unversioned vertex.
    """
    tool_id: str
    name: str
    description: str = ""
    scope_type: str = "project"
    org_id: str
    project_id: Optional[str] = None
    endpoint_url: str
    min_reputation_score: float = 0.0
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    side_effects: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def split(self) -> "tuple[ToolIdentity, ToolVersionSpec]":
        identity = ToolIdentity(
            tool_id=self.tool_id, name=self.name, description=self.description,
            scope_type=self.scope_type, org_id=self.org_id,
            project_id=self.project_id, capabilities=self.capabilities,
            kind=self.metadata.get("kind", "http"))
        schema = self.input_schema or {"type": "object", "properties": {}}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        version = ToolVersionSpec(
            tool_id=self.tool_id, version=self.version,
            endpoint_url=self.endpoint_url,
            input_schema=schema,
            # A legacy caller declared no output shape. An empty object schema
            # is honest about that — it says "an object, contents undeclared" —
            # where inventing properties would put a false contract in the hash.
            output_schema=self.output_schema or {"type": "object", "properties": {}},
            # Rule 6.2 has no safe default, but rejecting every legacy caller
            # would take the registry down. `external` is the conservative
            # choice: it forbids speculative execution and retry-without-key,
            # which is the behaviour that matters until the caller declares.
            side_effects=self.side_effects or "external",
            min_reputation_score=self.min_reputation_score)
        return identity, version


class CallToolRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    org_id: str
    project_id: Optional[str] = None
    version: Optional[str] = Field(None, description="Pin; omit for current_version")
    caller: Dict[str, Any] = Field(
        default_factory=dict,
        description="agent_id, run_id, step_id — recorded on the usage event")
    idempotency_key: Optional[str] = None


class RetireRequest(BaseModel):
    org_id: str
    version: str
    status: str = DEPRECATED
    replacement_version_id: Optional[str] = None


# ------------------------------------------------------------------- helpers

def _client(request: Request) -> Any:
    client = getattr(request.app.state, "pg_client", None)
    if client is None:
        raise HTTPException(status_code=503,
                            detail="Tool registry has no database connection.")
    return client


def _cache(request: Request):
    return request.app.state.cache


def _meter(request: Request):
    return getattr(request.app.state, "meter", None)


async def discovery_embedding(identity: ToolIdentity, version: ToolVersionSpec):
    """Discovery vector, or None. Never fails a registration — see embedding.py.

    Public because the startup seeder needs the same vector the HTTP path
    computes. It did not have it, and seeded tools were written with no vector
    at all — present in `GET /tools`, invisible to `/tools/search`, which is
    what `mcp-tool-discovery` calls. An agent looking for a capability found
    nothing and concluded the realm did not have it.
    """
    try:
        from embedding import embed
        return await embed(discovery_text(identity, version))
    except Exception:
        logger.exception("embedding unavailable; tool registered without a "
                         "discovery vector")
        return None


def _public(identity: ToolIdentity, record: Dict[str, Any]) -> Dict[str, Any]:
    """The outward shape of a tool. Never includes auth material.

    `auth` is reduced to its mode: a caller needs to know *that* the tool
    requires a bearer token, and has no use for the reference naming where it
    lives (Rule 6.3).
    """
    return {
        **identity.model_dump(mode="json"),
        "version": record.get("version"),
        "content_hash": record.get("content_hash"),
        "endpoint_url": record.get("endpoint_url"),
        "transport": record.get("transport"),
        "input_schema": record.get("input_schema"),
        "output_schema": record.get("output_schema"),
        "side_effects": record.get("side_effects"),
        "auth_mode": (record.get("auth") or {}).get("mode", "none"),
        "limits": record.get("limits"),
        "min_reputation_score": record.get("min_reputation_score", 0.0),
        "status": record.get("status"),
        # Rule 5.2: a caller that wants to pin needs the version and the hash,
        # and a second round trip to get them is a race.
        "pin": {"tool_id": identity.tool_id, "version": record.get("version"),
                "content_hash": record.get("content_hash")},
    }


# -------------------------------------------------------------- registration

@router.post("/tools/register", tags=["Tool Registry"])
async def register_tool(body: Dict[str, Any], request: Request):
    """Register one immutable tool version (§3, §4, §8).

    Accepts both the versioned body (`{identity, version}`) and the legacy flat
    body, so existing callers keep working while producing versioned tools.
    """
    client = _client(request)
    try:
        if "identity" in body and "version" in body:
            parsed = RegisterToolRequest(**body)
            identity, version = parsed.identity, parsed.version
        else:
            identity, version = LegacyRegisterRequest(**body).split()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await ensure_schema(client, identity.org_id)

    try:
        record = await register_tool_version(
            client, identity, version, embedding=await discovery_embedding(identity, version))
    except RegistrationError as e:
        # A 400 naming the rule, not a 500: a caller that omitted side_effects
        # or collided a hash needs to know which, and the registry knows.
        raise HTTPException(status_code=400, detail=str(e)) from e

    _cache(request).put(identity.org_id, identity.tool_id, record.get("version"),
                        identity.model_dump(mode="json"), record)
    return {"status": "registered", "tool_id": identity.tool_id,
            "version": record.get("version"), "content_hash": record.get("content_hash"),
            "scope": identity.scope_type, "pin": {
                "tool_id": identity.tool_id, "version": record.get("version"),
                "content_hash": record.get("content_hash")}}


@router.post("/tools/{tool_id}/retire", tags=["Tool Registry"])
async def retire_tool_version(tool_id: str, req: RetireRequest, request: Request):
    """Deprecate or revoke one version (Rule 4.5, Rule 9.3)."""
    client = _client(request)
    try:
        record = await set_version_status(
            client, req.org_id, tool_id, req.version, req.status,
            req.replacement_version_id)
    except RegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _cache(request).drop(req.org_id, tool_id)
    return {"status": record["status"], "tool_id": tool_id, "version": req.version,
            "replacement_version_id": record.get("replacement_version_id")}


@router.delete("/tools/{tool_id}", tags=["Tool Registry"])
async def delete_tool(tool_id: str, request: Request, org_id: str = Query(...)):
    """Deletion is dormancy (Rule 9.1), written to post-graph (Rule 9.2).

    The tool is not removed: published agent versions pin it, and their hashes
    must stay resolvable or their history stops being auditable.
    """
    client = _client(request)
    try:
        await set_lifecycle(client, org_id, tool_id, DORMANT)
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    _cache(request).drop(org_id, tool_id)
    return {"status": "dormant", "tool_id": tool_id,
            "note": "Retained for provenance; excluded from discovery."}


@router.post("/tools/{tool_id}/restore", tags=["Tool Registry"])
async def restore_tool(tool_id: str, request: Request, org_id: str = Query(...)):
    client = _client(request)
    try:
        await set_lifecycle(client, org_id, tool_id, ACTIVE)
    except RegistrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    _cache(request).drop(org_id, tool_id)
    return {"status": "active", "tool_id": tool_id}


# ----------------------------------------------------------------- discovery

@router.get("/tools", tags=["Tool Registry"])
async def list_all_tools(request: Request,
                         org_id: str = Query(..., description="Required: the realm"),
                         project_id: Optional[str] = Query(None),
                         scope_type: Optional[str] = Query(None),
                         include_inactive: bool = Query(False)):
    """Every tool visible to `(org_id, project_id)`.

    `org_id` is **required** (Rule 2.1). It previously defaulted, and a listing
    without a realm is not "all tools" — it is every tenant's catalogue.
    """
    client = _client(request)
    entries = await list_tools(client, org_id, project_id, include_inactive)
    tools = [_public(e["identity"], e["record"]) for e in entries]
    if scope_type:
        tools = [t for t in tools if t.get("scope_type") == scope_type]
    for entry in entries:
        _cache(request).put(org_id, entry["identity"].tool_id, entry["version"],
                            entry["identity"].model_dump(mode="json"), entry["record"])
    return {"tools": tools, "count": len(tools)}


class SearchToolsRequest(BaseModel):
    """A tool search as a JSON body.

    Dispatch posts a tool's arguments as the request body (§7.1), so a
    GET-only search cannot itself be registered as a tool — and an agent that
    cannot look up a capability has to be told every tool name in advance.
    """
    q: str
    org_id: str
    project_id: Optional[str] = None
    top_k: int = 5


@router.post("/tools/search", tags=["Tool Registry"])
async def search_tools_post(req: SearchToolsRequest, request: Request):
    """Same search, called the way a tool is dispatched."""
    return await search_tools(request, q=req.q, org_id=req.org_id,
                              project_id=req.project_id, top_k=req.top_k)


@router.get("/tools/search", tags=["Tool Registry"])
async def search_tools(request: Request, q: str = Query(..., min_length=1),
                       org_id: str = Query(...),
                       project_id: Optional[str] = Query(None),
                       top_k: int = Query(5, ge=1, le=50)):
    """Vector discovery over tool descriptions (§5).

    This is the path an orchestrator takes when it knows what it needs and not
    what it is called.
    """
    client = _client(request)
    try:
        from embedding import embed
        vector = await embed(q)
    except Exception:
        vector = None
    if vector is None:
        raise HTTPException(
            status_code=503,
            detail="Semantic search is unavailable: no embedding could be computed. "
                   "Use GET /tools and filter, or retry.")

    try:
        hits = await client.vector_search(
            table_name=TOOLS, realm=org_id, query_vector=vector, top_k=top_k * 3,
            space=project_id)
    except Exception as e:
        logger.exception("vector search failed in realm %r", org_id)
        raise HTTPException(status_code=503, detail=f"Vector search failed: {e}") from e

    out: List[Dict[str, Any]] = []
    for vertex, distance in hits:
        payload = vertex.payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        try:
            identity = ToolIdentity(**{k: v for k, v in payload.items()
                                       if k in ToolIdentity.model_fields})
        except Exception:
            continue
        # Rule 5.1: never return a tool the caller cannot invoke. Returning one
        # teaches an agent to plan around a capability it does not have.
        if identity.lifecycle != ACTIVE or not identity.visible_to(project_id):
            continue
        found = await get_tool(client, org_id, identity.tool_id)
        if not found:
            continue
        record = found[1]
        if record.get("status") != PUBLISHED:
            continue
        out.append({**_public(identity, record), "distance": distance})
        if len(out) >= top_k:
            break
    return {"query": q, "tools": out, "count": len(out)}


@router.get("/tools/rag-documents", tags=["Tool Registry"])
async def get_tool_rag_documents(request: Request, org_id: str = Query(...),
                                 project_id: Optional[str] = Query(None)):
    """Tools rendered as prose for post-graph-rag indexing (§5.1).

    Derived on every request, never stored: a second copy of a tool's
    description drifts from the first, and nothing reports the divergence.
    """
    client = _client(request)
    entries = await list_tools(client, org_id, project_id)
    documents = []
    for entry in entries:
        identity, record = entry["identity"], entry["record"]
        documents.append({
            "id": identity.tool_id,
            "tool_id": identity.tool_id,
            "name": identity.name,
            "description": identity.description,
            "title": f"Tool_{identity.tool_id}",
            "content": (
                f"Tool Name: {identity.name}\n"
                f"Tool ID: {identity.tool_id}\n"
                f"Version: {record.get('version')}\n"
                f"Scope Type: {identity.scope_type}\n"
                f"Side Effects: {record.get('side_effects')}\n"
                f"Capabilities: {', '.join(identity.capabilities) or 'None'}\n"
                f"Endpoint URL: {record.get('endpoint_url')}\n"
                f"Description & Capabilities: {identity.description}\n"
                f"Input Schema Parameters: {json.dumps(record.get('input_schema', {}))}\n"
                f"Output Schema: {json.dumps(record.get('output_schema', {}))}"),
        })
    return {"documents": documents, "count": len(documents)}


@router.get("/tools/{tool_id}", tags=["Tool Registry"])
async def get_one_tool(tool_id: str, request: Request, org_id: str = Query(...),
                       version: Optional[str] = Query(None)):
    """One tool, at `version` or at `current_version`.

    Declared after `/tools/search` and `/tools/rag-documents` on purpose: FastAPI
    matches routes in declaration order, so a path parameter registered first
    would swallow both of them.
    """
    client = _client(request)
    found = await get_tool(client, org_id, tool_id, version)
    if not found:
        raise HTTPException(status_code=404,
                            detail=f"MCP tool {tool_id!r} not found in realm {org_id!r}.")
    identity, record = found
    _cache(request).put(org_id, tool_id, record.get("version"),
                        identity.model_dump(mode="json"), record)
    return {"tool": _public(identity, record)}


# ---------------------------------------------------------------- invocation

async def reputation_of(agent_id: str, org_id: str,
                        project_id: Optional[str] = None) -> Optional[float]:
    """The calling agent's reputation, or None if it could not be established.

    The realm is named. Both registries keep each organisation in its own
    PostgreSQL schema, so a lookup that omits it reads whichever realm the
    agent registry defaults to — which is empty for this tenant, returns 404,
    and denies a legitimate caller with a 503 that blames the network.
    """
    url = f"{AGENT_REGISTRY_URL.rstrip('/')}/agents/{agent_id}"
    params = {"org_id": org_id}
    if project_id:
        params["project_id"] = project_id
    try:
        async with httpx.AsyncClient(timeout=REPUTATION_TIMEOUT) as http:
            res = await http.get(url, params=params)
    except httpx.HTTPError as e:
        logger.warning("agent registry unreachable for reputation check: %s", e)
        return None
    if res.status_code != 200:
        return None
    try:
        return float(res.json()["agent"].get("reputation_score", 0.0))
    except (KeyError, TypeError, ValueError):
        return None


async def enforce_reputation(record: Dict[str, Any], caller: Dict[str, Any],
                             tool_id: str, org_id: str,
                             project_id: Optional[str] = None) -> None:
    """Rule 6.1 — evaluated at invocation, and fails closed.

    A threshold that is stored and never evaluated is worse than no threshold:
    it reads, to everyone looking at the registration, like a control that
    exists. When a threshold is set and the caller's standing cannot be
    established, the call is denied — an unverified caller is exactly the case
    the threshold was written for.
    """
    required = float(record.get("min_reputation_score") or 0.0)
    if required <= 0:
        return                      # nothing to check; no cross-service call
    agent_id = caller.get("agent_id")
    if not agent_id:
        raise HTTPException(
            status_code=403,
            detail=f"Tool {tool_id!r} requires reputation >= {required}; "
                   f"the call declared no calling agent.")
    score = await reputation_of(agent_id, org_id, project_id)
    if score is None:
        raise HTTPException(
            status_code=503,
            detail=f"Tool {tool_id!r} requires reputation >= {required} and the "
                   f"standing of {agent_id!r} could not be established.")
    if score < required:
        raise HTTPException(
            status_code=403,
            detail=f"Tool {tool_id!r} requires reputation >= {required}; "
                   f"{agent_id!r} has {score}.")


@router.post("/tools/{tool_id}/call", tags=["Tool Registry"])
async def call_tool(tool_id: str, req: CallToolRequest, request: Request):
    """Invoke one tool version (§7.1).

    Listing without invoking made the registry descriptive only: an agent could
    discover a tool and had no way to use it.
    """
    client = _client(request)
    found = await get_tool(client, req.org_id, tool_id, req.version)
    if not found:
        raise HTTPException(status_code=404,
                            detail=f"MCP tool {tool_id!r} not found in realm {req.org_id!r}.")
    identity, record = found

    if identity.lifecycle != ACTIVE:
        raise HTTPException(status_code=410,
                            detail=f"Tool {tool_id!r} is {identity.lifecycle}.")
    if record.get("status") == REVOKED:
        replacement = record.get("replacement_version_id")
        raise HTTPException(
            status_code=410,
            detail=f"Tool {tool_id}@{record.get('version')} is revoked."
                   + (f" Use {replacement}." if replacement else ""))
    if record.get("status") != PUBLISHED and record.get("status") != DEPRECATED:
        raise HTTPException(status_code=404,
                            detail=f"Tool {tool_id}@{record.get('version')} is not published.")
    if not identity.visible_to(req.project_id):
        # 404 rather than 403: an out-of-scope tool must not be confirmed to
        # exist by probing from a project that cannot use it.
        raise HTTPException(status_code=404,
                            detail=f"MCP tool {tool_id!r} not found in this project.")

    # Rule 7.1 — validated before dispatch. A tool receiving an argument shape
    # it did not declare either fails confusingly or succeeds on the wrong thing.
    problem = validate_arguments(req.arguments, record.get("input_schema") or {})
    if problem:
        raise HTTPException(status_code=400,
                            detail=f"Arguments do not match {tool_id}'s input schema: {problem}")

    # Rule 6.2 — at-least-once delivery over a side-effecting tool means the
    # effect happens at least once too, unless the callee can deduplicate.
    if record.get("side_effects") != "read" and not req.idempotency_key:
        raise HTTPException(
            status_code=400,
            detail=f"Tool {tool_id!r} declares side_effects "
                   f"{record.get('side_effects')!r} and requires an idempotency_key.")

    await enforce_reputation(record, req.caller, tool_id,
                             req.org_id, req.project_id)

    meter = _meter(request)
    _record_bytes(meter, "search_query", req, tool_id, record, req.arguments)

    result = await dispatch(record, req)

    _record_bytes(meter, "search_results", req, tool_id, record, result)
    return {"status": "success", "tool_id": tool_id,
            "version": record.get("version"), "result": result}


def _record_bytes(meter, kind: str, req: CallToolRequest, tool_id: str,
                  record: Dict[str, Any], payload: Any) -> None:
    """One usage event (§11). Never raises into the call path (AG Rule 12.2).

    Query and results are separate events (Rule 11.2), not one event with two
    byte counts: a cheap query can return an expensive result, and separating
    them at write time is the only way to bill them apart later.
    """
    if meter is None:
        return
    try:
        from metering import UsageEvent
        cost_kind = (record.get("cost_hint") or {}).get("kind")
        meter.record(UsageEvent(
            org_id=req.org_id, project_id=req.project_id or "proj_default",
            kind=cost_kind if cost_kind in ("rag_lookup",) else kind,
            bytes=len(json.dumps(payload, default=str).encode("utf-8")),
            # Rule 11.3: without these the ledger says an organisation spent
            # something and cannot say on what.
            agent_id=req.caller.get("agent_id"),
            agent_version=req.caller.get("agent_version"),
            run_id=req.caller.get("run_id"),
            model=tool_id))
    except Exception:
        logger.exception("metering failed for tool %s; the call stands", tool_id)


def resolve_secret(secret_ref: Dict[str, str]) -> Optional[str]:
    """Read the credential a tool's `auth.secret_ref` names (Rule 6.3).

    The registry stores a *reference*; the value lives wherever the platform
    put it. Kubernetes mounts a secret either into the environment or onto a
    path, so both are looked at, most specific first:

        1. an environment variable named by `key`
        2. an environment variable named `{NAME}_{KEY}`
        3. a file at `/var/run/secrets/{name}/{key}`

    Returns None when nothing resolves, so the caller can fail with a message
    naming the missing configuration rather than sending an empty Authorization
    header and reporting the far end's 401 as if the tool were broken.
    """
    name = (secret_ref or {}).get("name", "")
    key = (secret_ref or {}).get("key", "")
    if key and os.getenv(key):
        return os.getenv(key)
    combined = f"{name}_{key}".upper().replace("-", "_")
    if os.getenv(combined):
        return os.getenv(combined)
    if name and key:
        path = pathlib.Path("/var/run/secrets") / name / key
        try:
            if path.is_file():
                return path.read_text().strip()
        except OSError:
            logger.warning("could not read the secret mounted at %s", path)
    return None


def auth_headers(record: Dict[str, Any], tool_id: str) -> Dict[str, str]:
    """The Authorization header a tool version declares, or an error.

    `auth.mode` was stored on every version and applied to nothing, which made
    it the same kind of decoration `min_reputation_score` was: it reads like a
    control and does nothing. A tool declaring `bearer` was dispatched to
    without credentials, and the far end's 401 came back as a 502 blaming the
    endpoint.
    """
    auth = record.get("auth") or {}
    mode = auth.get("mode", "none")
    if mode == "none":
        return {}

    token = resolve_secret(auth.get("secret_ref") or {})
    if not token:
        ref = auth.get("secret_ref") or {}
        raise HTTPException(
            status_code=503,
            detail=(f"Tool {tool_id!r} declares auth mode {mode!r} but the secret "
                    f"it names ({ref.get('name')}/{ref.get('key')}) is not "
                    f"available to this service. The registry stores a reference, "
                    f"never the credential."))
    if mode in ("bearer", "secret_ref"):
        return {"Authorization": f"Bearer {token}"}
    if mode == "service_account":
        return {"X-Service-Account-Token": token}
    return {}


async def dispatch(record: Dict[str, Any], req: CallToolRequest) -> Any:
    """Forward the call to the tool's endpoint, or raise.

    Rule 7.2: every failure path raises. It never returns a plausible-looking
    synthetic result — an agent cannot distinguish fabricated evidence from
    real evidence, so the registry must never produce any.
    """
    url = record.get("endpoint_url")
    if not url:
        raise HTTPException(status_code=503,
                            detail="Tool has no endpoint_url configured.")
    limits = record.get("limits") or {}
    timeout = float(limits.get("timeout_secs") or 30.0)

    headers = {"Content-Type": "application/json"}
    if req.idempotency_key:
        headers["Idempotency-Key"] = req.idempotency_key
    headers.update(auth_headers(record, tool_id=record.get("tool_id", "")))

    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            res = await http.post(url, json=req.arguments, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502,
                            detail=f"Tool endpoint unreachable: {e}") from e
    if res.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Tool endpoint returned {res.status_code}: {res.text[:200]}")

    max_bytes = limits.get("max_bytes")
    if max_bytes and len(res.content) > int(max_bytes):
        raise HTTPException(
            status_code=502,
            detail=f"Tool returned {len(res.content)} bytes, over its declared "
                   f"max_bytes of {max_bytes}.")
    try:
        return res.json()
    except ValueError:
        return {"text": res.text}
