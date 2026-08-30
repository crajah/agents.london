"""Per-agent model assignment — execution-spec.md §10.

Assigned at random on creation, one per tier; not heritable; survives
regeneration; a withdrawn model re-rolls on next regeneration. The pool is
gated by the disposition-expression screen at >=1.5x genotype dominance
(Rules 10.6/10.7): a model enters only by passing it.
"""
from __future__ import annotations

import random

# Screened pools. flash-lite passed the full validation programme
# (validation/RESULTS.md); candidates join by passing the screen, never by
# being available.
POOLS: dict[str, list[str]] = {
    "economy": ["gemini-3.5-flash-lite"],
    "deliberative": ["gemini-3.5-flash-lite"],   # placeholder until a
    # deliberative candidate passes the screen (gemini-3.7-flash was
    # rate-limited out of validation; re-run before admitting)
}


def assign_models(agent_uuid: str) -> dict[str, str]:
    """Deterministic per agent (so regeneration keeps the assignment,
    Rule 10.3) yet uniform across agents (Rule 10.1)."""
    return {tier: random.Random(f"model:{agent_uuid}:{tier}").choice(pool)
            for tier, pool in POOLS.items()}


def reroll_if_withdrawn(assigned: dict[str, str], agent_uuid: str,
                        generation: int) -> dict[str, str]:
    """Rule 10.4: a model no longer in its pool re-rolls on regeneration;
    the generation count varies the draw."""
    out = {}
    for tier, model in assigned.items():
        if model in POOLS.get(tier, []):
            out[tier] = model
        else:
            out[tier] = random.Random(
                f"model:{agent_uuid}:{tier}:regen{generation}"
            ).choice(POOLS[tier])
    return out
