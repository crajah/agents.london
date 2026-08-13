"""Translating the civilization engine's agent payloads into registry versions.

The engine builds free-form dicts; the registry (spec §3.2) needs an identity
and an immutable version with declared schemas. This module is the seam between
the two, kept separate so the engine does not grow a second opinion about what
a version is.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)

# A default contract for agents the engine spawns without declaring one. It is
# deliberately permissive rather than absent: Rule 3.4 makes schemas required,
# and an agent that cannot state its interface is still better registered with
# a stated free-text contract than left out of the graph entirely.
DEFAULT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string", "description": "Task for the agent."}},
    "required": ["prompt"],
}
DEFAULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"result": {"type": "string", "description": "The agent's response."}},
}


def slugify(value: str) -> str:
    """URL- and MCP-safe slug. The slug appears in tool names and card URLs."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return (slug or "agent")[:64].rstrip("-")


def to_identity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The stable half: what does not change between versions (§3.1)."""
    name = payload.get("name") or payload.get("agent_id", "agent")
    return {
        "name": name,
        "slug": payload.get("slug") or slugify(name),
        "caste": payload.get("caste", "progeny"),
        "telos": payload.get("telos", ""),
        "description": payload.get("description") or payload.get("telos", ""),
        "owner": payload.get("owner") or payload.get("parent_agent_id"),
        "lifecycle": "active",
    }


def to_version(payload: Dict[str, Any], version: str = "1.0.0") -> Dict[str, Any]:
    """The immutable half: everything behaviour depends on (§3.2.1).

    `system_prompt` is included because it *is* the behaviour — Rule 4.1 makes
    a prompt edit at least a patch bump, which only works if the prompt is
    inside the hashed material.
    """
    model_name = payload.get("model") or payload.get("model_name") or "DeepSeek-V3.2"
    return {
        "agent_id": payload["agent_id"],
        "version": payload.get("version", version),
        "system_prompt": payload.get("system_prompt", ""),
        "model": {
            "name": model_name,
            "api_base": payload.get("api_base"),
            "params": payload.get("model_params", {}),
            "fallback_models": payload.get("fallback_models", []),
        },
        "tools": payload.get("tools", []),
        "input_schema": payload.get("input_schema") or DEFAULT_INPUT_SCHEMA,
        "output_schema": payload.get("output_schema") or DEFAULT_OUTPUT_SCHEMA,
        "capabilities": payload.get("capabilities", []),
        "resource_limits": payload.get("resource_limits", {}),
        "changelog": payload.get("changelog", "Registered by the civilization engine."),
    }


def to_registration(payload: Dict[str, Any], org_id: str, project_id: str) -> Dict[str, Any]:
    """A complete POST /agents body for the registry."""
    return {
        "org_id": org_id,
        "project_id": project_id,
        "identity": to_identity(payload),
        "version": to_version(payload),
        "spawned_by": payload.get("parent_agent_id"),
    }
