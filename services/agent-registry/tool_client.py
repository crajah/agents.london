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
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

TOOL_REGISTRY_URL = os.getenv(
    "TOOL_REGISTRY_URL",
    "http://tool-registry-service.default.svc.cluster.local:8002")
TOOL_TIMEOUT = float(os.getenv("TOOL_REGISTRY_TIMEOUT", "10"))

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
