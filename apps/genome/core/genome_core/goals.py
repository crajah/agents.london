"""Agent GOALS -- structured intent for the reflex/deliberation split.

Phase 0/1 (see apps/genome/spec/reflex-deliberation-{spec,plan}.md): the reflex
layer reads `current_goal`; the deliberation (LLM) layer will SET goals in a later
phase. Until then every agent's goal is the default `provision`, so the reflex
policy has something to execute. The goal is a plain dict on the agent payload so
it round-trips through post-graph with no schema change.
"""
from __future__ import annotations


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
