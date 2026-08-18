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
from registry_store import AGENTS, _latest_versions, _newest, resolve_vertex

logger = logging.getLogger(__name__)

MODEL_ROUTER_URL = os.getenv("OPENAI_API_BASE",
                             os.getenv("LITELLM_URL", "http://localhost:4000/v1"))
API_KEY = os.getenv("OPENAI_API_KEY", "")
CALL_TIMEOUT = float(os.getenv("AGENT_CALL_TIMEOUT", "120"))

# The model an agent version gets when it declares none. Set once for the
# whole system via DEFAULT_LLM_MODEL; the literal is only the fallback.
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "gemini-3.5-flash-lite")

# How many times an agent may go round the ask-a-tool loop before it has to
# answer. Bounded because a model that keeps calling tools is a cost with no
# ceiling; generous enough that a search-then-read-then-answer sequence fits.
MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "6"))

# A tool result larger than this is truncated, and the truncation is stated in
# the text handed to the model.
MAX_TOOL_RESULT_CHARS = int(os.getenv("AGENT_MAX_TOOL_RESULT_CHARS", "24000"))


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
        # Ordered by semver, not lexically: `max()` over strings puts "1.9.0"
        # above "1.10.0", so an unpinned call would silently start resolving to
        # an older version once a minor number reached double digits.
        body = published[_newest(published)]
    if body.get("status") != PUBLISHED:
        raise ExecutionError(
            f"{business_id}@{body.get('version')} is {body.get('status')}, not published")
    return body


async def _chat(base: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """One round trip to the model router."""
    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as http:
            res = await http.post(f"{base.rstrip('/')}/chat/completions",
                                  headers={"Authorization": f"Bearer {API_KEY}"},
                                  json=body)
    except httpx.HTTPError as e:
        raise ExecutionError(f"model router unreachable: {e}") from e
    if res.status_code != 200:
        raise ExecutionError(f"model router returned {res.status_code}: {res.text[:200]}")
    return res.json()


async def call_model(record: Dict[str, Any], prompt: str,
                     org_id: Optional[str] = None,
                     project_id: Optional[str] = None,
                     agent_id: Optional[str] = None) -> Dict[str, Any]:
    """Run one agent version: the model, and the tools that version pinned.

    An agent's `tools` were inside its content hash and resolved at
    registration, and then never offered to anything. The model was called with
    a system prompt and a user turn and no tools at all, so a published agent
    that pinned a search tool could not search — it could only describe not
    being able to. That is what produced refusals like "web search is not
    granted to this realm" from an agent that had been given a search tool.

    The loop below is bounded. Each round the model may ask for tool calls;
    each call goes to the registry that owns the tool, and its real result — or
    its real failure — is handed back. Nothing is summarised on the way through
    and nothing is substituted when a call fails, because a model cannot tell a
    fabricated tool result from a real one and will cite either.

    Usage is summed across every round, read from the provider rather than
    estimated: a token estimate in a billing record is a number that looks
    authoritative and is not.
    """
    model = (record.get("model") or {})
    name = model.get("name") or DEFAULT_MODEL
    base = model.get("api_base") or MODEL_ROUTER_URL

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": record.get("system_prompt", "")},
        {"role": "user", "content": prompt},
    ]
    totals = {"input_tokens": 0, "output_tokens": 0}
    calls: List[Dict[str, Any]] = []

    offered = await _offer_tools(record, org_id, project_id)

    for round_index in range(MAX_TOOL_ROUNDS + 1):
        body = {"model": name, "messages": messages, **(model.get("params") or {})}
        # On the last permitted round the tools are withdrawn, so the model is
        # required to answer with what it has rather than asking for another
        # call it will not get.
        if offered and round_index < MAX_TOOL_ROUNDS:
            body["tools"] = offered
            body["tool_choice"] = "auto"

        data = await _chat(base, body)
        usage = data.get("usage") or {}
        totals["input_tokens"] += usage.get("prompt_tokens", 0)
        totals["output_tokens"] += usage.get("completion_tokens", 0)

        message = data["choices"][0]["message"]
        requested = message.get("tool_calls") or []
        if not requested:
            return {
                "result": message.get("content") or "",
                "model": name,
                "tool_calls": calls,
                # Normalised to the names the meter and the runtime both expect,
                # so a provider that renames these does not silently zero the
                # accounting.
                "usage": totals,
            }

        messages.append({"role": "assistant", "content": message.get("content"),
                         "tool_calls": requested})
        for request in requested:
            outcome = await _run_tool_call(request, org_id, project_id, agent_id)
            calls.append(outcome["record"])
            messages.append({"role": "tool", "tool_call_id": request.get("id"),
                             "name": outcome["record"]["tool_id"],
                             "content": outcome["content"]})

    # Unreachable in practice: the final round withdraws the tools.
    raise ExecutionError("agent did not finish within its tool-call budget")


async def _offer_tools(record: Dict[str, Any], org_id: Optional[str],
                       project_id: Optional[str]) -> List[Dict[str, Any]]:
    """The tools this version pinned, in the shape a model is offered them.

    An unreachable tool registry is logged and the agent runs without tools
    rather than failing outright — it can still answer from what it knows, and
    it is told nothing that would let it claim otherwise. Its prompt already
    forbids inventing a result it did not obtain.
    """
    pinned = record.get("tools") or []
    if not pinned or not org_id:
        return []
    try:
        import tool_client
        available = await tool_client.usable(org_id, project_id, pinned)
        return tool_client.as_model_tools(available)
    except Exception:
        logger.exception("could not offer pinned tools to %s; running without them",
                         record.get("agent_id"))
        return []


async def _run_tool_call(request: Dict[str, Any], org_id: Optional[str],
                         project_id: Optional[str],
                         agent_id: Optional[str]) -> Dict[str, Any]:
    """Execute one tool call the model asked for, and report what happened."""
    import tool_client

    function = request.get("function") or {}
    tool_id = function.get("name") or ""
    raw = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except json.JSONDecodeError as e:
        message = f"arguments were not valid JSON: {e}"
        return {"content": f"ERROR: {message}",
                "record": {"tool_id": tool_id, "ok": False, "error": message}}

    # A side-effecting tool requires an idempotency key (tool-registry Rule
    # 6.2). It is derived from the call id so a retried round does not repeat
    # the effect.
    outcome = await tool_client.invoke(
        tool_id, arguments, org_id or "", project_id, caller=agent_id,
        idempotency_key=f"{agent_id or 'agent'}:{request.get('id') or tool_id}")

    if not outcome["ok"]:
        # The model is told the truth: this call failed, and how. It is not
        # given a plausible substitute to reason over.
        return {"content": f"ERROR: {outcome['error']}",
                "record": {"tool_id": tool_id, "ok": False,
                           "error": outcome["error"], "arguments": arguments}}

    result = outcome["result"]
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        # Truncated, and said so. A silently cut result reads as a complete one.
        text = (text[:MAX_TOOL_RESULT_CHARS]
                + f"\n… [truncated at {MAX_TOOL_RESULT_CHARS} characters]")
    return {"content": text,
            "record": {"tool_id": tool_id, "ok": True, "arguments": arguments}}


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
    output = await call_model(record, prompt_from_payload(payload),
                              org_id=realm, project_id=project_id, agent_id=agent_id)
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


def step_runner_for(client, realm: str, space: Optional[str] = None):
    """A step_runner for PipelineExecutor, bound to one realm.

    Each step resolves its pinned version and calls it. The pin travels on the
    composes_pipeline edge, so a run executes exactly the versions the pipeline
    was published against — not whatever is current.

    No meter here on purpose. `PipelineExecutor._meter_step` accounts every step
    from the `usage` this function returns, and a second emitter for the same
    operation would double-bill in a way the ledger cannot detect, because both
    rows would be individually correct (AG Rule 12.0).
    """
    async def _run(step_id: str, version_id: str, payload: Dict[str, Any], context):
        agent_id, version = _split(version_id)
        record = await resolve_version(client, realm, AGENTS, agent_id, version, space)
        out = await call_model(record, prompt_from_payload(payload),
                               org_id=realm, project_id=space, agent_id=agent_id)
        out["step_id"] = step_id
        out["agent_id"] = agent_id
        out["agent_version"] = version
        return out
    return _run


def _split(version_id: str) -> Tuple[str, str]:
    body = version_id[len("agv_"):] if version_id.startswith("agv_") else version_id
    agent_id, _, version = body.rpartition("_")
    return agent_id, version
