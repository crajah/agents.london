"""Per-agent model assignment — execution-spec.md §10.

Assigned at random on creation, one per tier; not heritable; survives
regeneration; a withdrawn model re-rolls on next regeneration. The pool is
gated by the disposition-expression screen at >=1.5x genotype dominance
(Rules 10.6/10.7): a model enters only by passing it.
"""
from __future__ import annotations

import random

# Pools revised 2026-09-01 (user decision): Gemini out, the unbudgeted
# self-hosted trio in -- MiniMax-M2.7, DeepSeek-V3.2 and Llama-3.3-70B all
# answer the constrained decision call cleanly through the router (probed
# live before admission; the formal Rule 10.6 screen re-run is still owed).
# Three models in one pool restores what Rule 10.1 wants: per-agent
# assignment with genuine variety.
POOLS: dict[str, list[str]] = {
    "economy": ["MiniMax-M2.7", "DeepSeek-V3.2", "gpt-oss-120b"],
    "deliberative": ["DeepSeek-V3.2"],
}

# flat-rate models: NO token cap at all -- the request omits max_tokens and
# the model reasons as long as it needs (user decision; llama swapped for
# gpt-oss-120b, probed clean through the router)
UNBUDGETED = {"MiniMax-M2.7", "DeepSeek-V3.2", "gpt-oss-120b"}


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
