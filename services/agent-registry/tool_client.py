"""Reading the tool registry, so agents can pin real tools.

An agent version's `tools` list is inside its `content_hash` (§4.2), so a bare
`tool_id` would let an agent's hash certify behaviour that changes when someone
edits a tool's endpoint or schema. Resolving to `{tool_id, version,
content_hash}` at registration is what closes that (Rule 3.5).

The catalogue is fetched per registration rather than cached: registration is
rare, correctness of the pin matters more than a round trip, and a stale
catalogue would pin a version that no longer exists.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

TOOL_REGISTRY_URL = os.getenv(
    "TOOL_REGISTRY_URL",
    "http://tool-registry-service.default.svc.cluster.local:8002")
TOOL_TIMEOUT = float(os.getenv("TOOL_REGISTRY_TIMEOUT", "10"))
# A tool call is real work — a web search, an ingest — so it gets a longer
# ceiling than a catalogue read.
TOOL_CALL_TIMEOUT = float(os.getenv("TOOL_CALL_TIMEOUT", "120"))

# When the tool registry cannot be reached, registration of a tool-using agent
# fails rather than proceeding with unresolved names. Registering an agent whose
# tools were never checked produces a published version that 404s mid-conversation,
# where a model narrates around the failure rather than reporting it.
STRICT = os.getenv("TOOL_RESOLUTION_STRICT", "1").lower() in ("1", "true", "yes")


class ToolResolutionError(RuntimeError):
    """The tool catalogue could not be established."""


async def catalogue(org_id: str, project_id: Optional[str] = None
                    ) -> Dict[str, Dict[str, str]]:
    """`tool_id -> {version, content_hash}` for tools this agent may call.

    Scoped to `(org_id, project_id)`, so a tool that exists in another project
    is absent here — which is the correct answer for an agent that could not
    call it anyway.
    """
    params = {"org_id": org_id}
    if project_id:
        params["project_id"] = project_id
    url = f"{TOOL_REGISTRY_URL.rstrip('/')}/tools"
    try:
        async with httpx.AsyncClient(timeout=TOOL_TIMEOUT) as http:
            res = await http.get(url, params=params)
    except httpx.HTTPError as e:
        raise ToolResolutionError(f"tool registry unreachable: {e}") from e
    if res.status_code != 200:
        raise ToolResolutionError(
            f"tool registry returned {res.status_code}: {res.text[:200]}")

    out: Dict[str, Dict[str, str]] = {}
    for tool in res.json().get("tools", []):
        pin = tool.get("pin") or {}
        tool_id = tool.get("tool_id")
        version = pin.get("version") or tool.get("version")
        digest = pin.get("content_hash") or tool.get("content_hash")
        if tool_id and version and digest:
            out[tool_id] = {"version": version, "content_hash": digest}
    return out


async def catalogue_or_none(org_id: str, project_id: Optional[str],
                            required: bool) -> Optional[Dict[str, Dict[str, str]]]:
    """The catalogue, or None when an agent declares no tools.

    `required` is whether the agent being registered names any tools at all. An
    agent with no tools does not need the tool registry to be up, and making it
    a dependency of every registration would couple two services that have
    nothing to say to each other in that case.
    """
    if not required:
        return None
    try:
        return await catalogue(org_id, project_id)
    except ToolResolutionError:
        if STRICT:
            raise
        logger.exception(
            "tool catalogue unavailable and TOOL_RESOLUTION_STRICT is off; "
            "registering with unresolved tool names")
        return None


async def usable(org_id: str, project_id: Optional[str],
                 tool_ids: List[str]) -> List[Dict[str, Any]]:
    """The full record of each tool an agent pinned, for offering to a model.

    A model can only call a tool it has been shown, and it can only be shown a
    tool whose input schema is known. `catalogue()` above answers "does this
    pin resolve"; this answers "what may this agent actually do", which is the
    question the execution path was never asking.
    """
    params = {"org_id": org_id}
    if project_id:
        params["project_id"] = project_id
    url = f"{TOOL_REGISTRY_URL.rstrip('/')}/tools"
    try:
        async with httpx.AsyncClient(timeout=TOOL_TIMEOUT) as http:
            res = await http.get(url, params=params)
    except httpx.HTTPError as e:
        raise ToolResolutionError(f"tool registry unreachable: {e}") from e
    if res.status_code != 200:
        raise ToolResolutionError(
            f"tool registry returned {res.status_code}: {res.text[:200]}")

    wanted = {t if isinstance(t, str) else t.get("tool_id") for t in tool_ids}
    return [tool for tool in res.json().get("tools", [])
            if tool.get("tool_id") in wanted]


def as_model_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pinned tools, in the shape a chat model is offered functions in.

    The description carries the declared side effects, because whether a call
    can be retried or repeated is something the caller has to know before it
    makes one, and the model is the caller here (Rule 6.2).
    """
    offered = []
    for tool in tools:
        effects = tool.get("side_effects", "read")
        note = ("" if effects == "read" else
                f" This tool has {effects} side effects: call it once, "
                f"deliberately, and never to explore.")
        offered.append({
            "type": "function",
            "function": {
                "name": tool["tool_id"],
                "description": (tool.get("description") or tool.get("name") or "")[:900] + note,
                "parameters": tool.get("input_schema")
                              or {"type": "object", "properties": {}},
            },
        })
    return offered


async def invoke(tool_id: str, arguments: Dict[str, Any], org_id: str,
                 project_id: Optional[str], caller: Optional[str] = None,
                 version: Optional[str] = None,
                 idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Call one tool through the registry that owns it.

    Returns `{ok, result}` or `{ok: False, error}`. A failure is handed back to
    the model as a failure — never as an empty result, and never as a plausible
    substitute. A model that receives fabricated tool output cannot tell it from
    real output and will reason over it as evidence.
    """
    payload = {"arguments": arguments, "org_id": org_id,
               "project_id": project_id, "caller": caller}
    if version:
        payload["version"] = version
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    url = f"{TOOL_REGISTRY_URL.rstrip('/')}/tools/{tool_id}/call"
    try:
        async with httpx.AsyncClient(timeout=TOOL_CALL_TIMEOUT) as http:
            res = await http.post(url, json=payload)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"{tool_id} is unreachable: {e}"}
    if res.status_code != 200:
        detail = res.text[:400]
        try:
            detail = res.json().get("detail", detail)
        except ValueError:
            pass
        return {"ok": False, "error": f"{tool_id} failed ({res.status_code}): {detail}"}
    return {"ok": True, "result": res.json().get("result")}
