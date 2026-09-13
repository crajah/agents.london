"""Agent GOALS -- structured intent for the reflex/deliberation split.

Phase 0/1 (see apps/genome/spec/reflex-deliberation-{spec,plan}.md): the reflex
layer reads `current_goal`; the deliberation (LLM) layer will SET goals in a later
phase. Until then every agent's goal is the default `provision`, so the reflex
policy has something to execute. The goal is a plain dict on the agent payload so
it round-trips through post-graph with no schema change.
"""
from __future__ import annotations

import os
import zlib

# Strategic heartbeat (reflex/deliberation §5): between LLM deliberations an agent
# runs on reflex; every ~this often it defers ONE turn to the LLM to re-strategise
# (trade, seek a mate, build, change goal). Jittered per agent so deferrals spread
# out instead of pulsing together; env-tunable.
STRATEGIC_PERIOD_S = float(os.getenv("GENOME_STRATEGIC_PERIOD", "120"))


def review_period(agent_payload: dict) -> float:
    """Seconds between an agent's strategic reviews -- base period + a per-agent
    jitter (0-60s) keyed off identity so a world's agents don't all defer to the
    LLM on the same tick."""
    uid = str(agent_payload.get("identity") or agent_payload.get("key") or "")
    return STRATEGIC_PERIOD_S + float(zlib.crc32(uid.encode()) % 61)


def first_review_at(agent_payload: dict, now: float) -> float:
    """When an agent's FIRST strategic review falls -- spread deterministically
    across the coming period (per-agent) so startup doesn't pulse every agent
    into the LLM at once."""
    uid = str(agent_payload.get("identity") or agent_payload.get("key") or "")
    period = max(1.0, review_period(agent_payload))
    return now + float(zlib.crc32(uid.encode()) % int(period))


def default_goal(genotype: dict | None = None) -> dict:
    """The standing goal when none is set: keep the line provisioned."""
    return {"kind": "provision", "params": {}, "set_by": "default"}


def current_goal(agent_payload: dict, now: float | None = None) -> dict:
    """The agent's active goal, or the default. (Goal stack + review_at + owner
    push/pop arrive in later phases; for now this just reads `goal` or defaults.)"""
    g = agent_payload.get("goal")
    if isinstance(g, dict) and g.get("kind"):
        return g
    return default_goal(agent_payload.get("genotype"))
