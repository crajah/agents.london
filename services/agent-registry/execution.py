"""Executing a registered agent version, and pipelines built from them.

This is the layer the registry was missing: it could describe an agent and
refuse a bad one, but nothing could run it. MCP `tools/call` and A2A task
submission both land here, so an agent advertised over either protocol is
actually invocable rather than merely listed.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from registry_model import PUBLISHED
from registry_store import AGENTS, PIPELINES, _latest_versions, resolve_vertex

logger = logging.getLogger(__name__)

MODEL_ROUTER_URL = os.getenv("OPENAI_API_BASE",
                             os.getenv("LITELLM_URL", "http://localhost:4000/v1"))
API_KEY = os.getenv("OPENAI_API_KEY", "")
CALL_TIMEOUT = float(os.getenv("AGENT_CALL_TIMEOUT", "120"))


class ExecutionError(RuntimeError):
    """A version could not be resolved or the model call failed."""


async def resolve_version(client, realm: str, table: str, business_id: str,
                          version: Optional[str] = None,
                          space: Optional[str] = None) -> Dict[str, Any]:
    """Resolve a business id and version to its published record.

    An unpublished version is not resolvable (Rule 4.3): if it were, a caller
    could invoke a draft by guessing its number, which is the whole point of
    the draft state existing.
    """
    pk = await resolve_vertex(client, table, realm, business_id, space)
    if pk is None:
        raise ExecutionError(f"unknown {table[:-1]} {business_id!r} in realm {realm!r}")
    versions = await _latest_versions(client, table, realm, pk)
    if version:
        body = versions.get(version)
        if body is None:
            raise ExecutionError(f"{business_id} has no version {version}")
    else:
        published = {v: b for v, b in versions.items() if b.get("status") == PUBLISHED}
        if not published:
            raise ExecutionError(f"{business_id} has no published version")
        body = published[max(published)]
    if body.get("status") != PUBLISHED:
        raise ExecutionError(
            f"{business_id}@{body.get('version')} is {body.get('status')}, not published")
    return body


async def call_model(record: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    """One model call for one agent version, returning output and usage.

    Usage is read from the provider response rather than estimated. The ledger
    records what was charged; a token estimate in a billing record is a number
    that looks authoritative and is not.
    """
    model = (record.get("model") or {})
    name = model.get("name") or "DeepSeek-V3.2"
    base = model.get("api_base") or MODEL_ROUTER_URL
    body = {
        "model": name,
        "messages": [
            {"role": "system", "content": record.get("system_prompt", "")},
            {"role": "user", "content": prompt},
        ],
        **(model.get("params") or {}),
    }
    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as http:
            res = await http.post(f"{base.rstrip('/')}/chat/completions",
                                  headers={"Authorization": f"Bearer {API_KEY}"},
                                  json=body)
    except httpx.HTTPError as e:
        raise ExecutionError(f"model router unreachable: {e}") from e
    if res.status_code != 200:
        raise ExecutionError(f"model router returned {res.status_code}: {res.text[:200]}")

    data = res.json()
    usage = data.get("usage") or {}
    return {
        "result": data["choices"][0]["message"]["content"],
        "model": name,
        # Normalised to the names the meter and the runtime both expect, so a
        # provider that renames these does not silently zero the accounting.
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def prompt_from_payload(payload: Dict[str, Any]) -> str:
    """The user turn for a step, from its declared input."""
    if isinstance(payload, str):
        return payload
    for key in ("prompt", "input", "text", "query", "question"):
        if payload.get(key):
            return str(payload[key])
    return json.dumps(payload, ensure_ascii=False)


async def run_agent(client, realm: str, agent_id: str, payload: Dict[str, Any],
                    version: Optional[str] = None, space: Optional[str] = None,
                    meter=None, project_id: str = "proj_default") -> Dict[str, Any]:
    """Execute one agent version. The unit both MCP and A2A ultimately call."""
    record = await resolve_version(client, realm, AGENTS, agent_id, version, space)
    output = await call_model(record, prompt_from_payload(payload))
    if meter is not None:
        try:
            from metering import UsageEvent
            u = output["usage"]
            meter.record(UsageEvent(
                org_id=realm, project_id=project_id, kind="llm_call",
                agent_id=agent_id, agent_version=record.get("version"),
                model=output.get("model"),
                tokens_input=u["input_tokens"], tokens_output=u["output_tokens"],
                bytes=len(str(payload).encode()) + len(output["result"].encode())))
        except Exception:
            logger.exception("metering failed for agent %s; result stands", agent_id)
    return output


def step_runner_for(client, realm: str, space: Optional[str] = None, meter=None):
    """A step_runner for PipelineExecutor, bound to one realm.

    Each step resolves its pinned version and calls it. The pin travels on the
    composes_pipeline edge, so a run executes exactly the versions the pipeline
    was published against — not whatever is current.
    """
    async def _run(step_id: str, version_id: str, payload: Dict[str, Any], context):
        agent_id, version = _split(version_id)
        record = await resolve_version(client, realm, AGENTS, agent_id, version, space)
        out = await call_model(record, prompt_from_payload(payload))
        out["step_id"] = step_id
        return out
    return _run


def _split(version_id: str) -> Tuple[str, str]:
    body = version_id[len("agv_"):] if version_id.startswith("agv_") else version_id
    agent_id, _, version = body.rpartition("_")
    return agent_id, version
