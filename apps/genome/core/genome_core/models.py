"""Per-agent model assignment — execution-spec.md §10.

Assigned at random on creation, one per tier; not heritable; survives
regeneration; a withdrawn model re-rolls on next regeneration. The pool is
gated by the disposition-expression screen at >=1.5x genotype dominance
(Rules 10.6/10.7): a model enters only by passing it.
"""
from __future__ import annotations

import random

# Pools revised 2026-09-10 (incident): the self-hosted trio went bad --
# MiniMax-M2.7 spiked to 20s+ per call (wildly variable) and gpt-oss-120b
# started erroring; the decider calls the router with BLOCKING urllib, so a
# single slow/failing model froze the whole worker's event loop for ~23s and
# the sim stalled (agents "standing around"). Swapped to models probed fast and
# reliable live: Llama-3.3-70B (~0.7s) and gemma-4-31B (~1.6s) self-hosted, plus
# gemini-3.6-flash (~1.0s) as a different-backend insurance against the
# self-hosted cluster degrading. Rebalance toward cheaper self-hosted once it
# stabilises. (assign_models is recomputed per decision, so this takes effect
# for every agent immediately on deploy.)
POOLS: dict[str, list[str]] = {
    "economy": ["Meta-Llama-3.3-70B-Instruct", "gemma-4-31B-it",
                "gemini-3.6-flash"],
    "deliberative": ["Meta-Llama-3.3-70B-Instruct", "gemma-4-31B-it",
                     "gemini-3.6-flash"],
}


def temperament(agent_uuid: str) -> float:
    """Per-agent sampling temperature, 0.7-1.3, dealt like the model: fixed
    for life, varied across the population -- two agents with the same model
    still won't think alike (user: 'mix things up')."""
    return 0.7 + 0.6 * random.Random(f"temp:{agent_uuid}").random()

# flat-rate models: NO token cap -- the request omits max_tokens. The
# self-hosted models are flat-rate; the hosted gemini stays budgeted (capped)
# because it is metered per token and "gemini is costly" (user).
UNBUDGETED = {"Meta-Llama-3.3-70B-Instruct", "gemma-4-31B-it"}


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
