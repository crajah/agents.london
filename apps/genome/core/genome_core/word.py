"""Word at a distance and gossip at arm's length — genome-spec.md Rules
9.1c/9.1d (claims, questions, testimony travel to ADDRESSABLE counterparties
only), 13.5a/13.5b (owner-sourced marking survives relay; Loyalty disposes
whether an agent relays at all) and 6.10b (owner-sourced evidence folds in
weaker, compounding per hop).

Everything here is mechanics: WHO to know, WHAT a testimony carries, HOW it
folds. Whether to speak stays a decision (Rule 12.5's fence)."""
from __future__ import annotations

import random

from .genotype import norm
from .opinion import Opinion, update_value

MAX_ADDRESSABLE = 24          # a head's rolodex
MAX_HEARD = 6                 # the bounded pile of unverified claims
RELAY_BASE_K = 0.25           # fold rate for first-hand testimony
RELAY_DECAY = 0.6             # ...compounding per hop (Rule 6.10b)
OWNER_PENALTY = 0.5           # owner-sourced folds in weaker still


def meet(payload: dict, other_uuid: str) -> dict:
    """An encounter grants addressability both ways (9.1d: 'encountered');
    newest last, oldest forgotten."""
    addr = [u for u in (payload.get("addressable") or [])
            if u != other_uuid] + [other_uuid]
    return {**payload, "addressable": addr[-MAX_ADDRESSABLE:]}


def introduce(payload: dict, subject_uuid: str) -> dict:
    """Testimony ABOUT an agent makes it addressable (9.1d: 'been told of').
    Introductions are worth something."""
    if subject_uuid == payload.get("key"):
        return payload
    return meet(payload, subject_uuid)


def strongest_opinion(payload: dict) -> tuple[str, str, dict] | None:
    """The claim most worth the breath: the (subject, locus) this agent's
    evidence puts furthest from neutral, weighted."""
    best = None
    for subject, loci in (payload.get("opinions") or {}).items():
        for locus, v in loci.items():
            score = abs(v.get("estimate", 5000.0) - 5000.0) \
                * min(1.0, v.get("weight", 0.0) / 3.0)
            if score > 1e-9 and (best is None or score > best[0]):
                best = (score, subject, locus, v)
    if best is None:
        return None
    _, subject, locus, v = best
    return subject, locus, v


def fold_testimony(payload: dict, subject: str, locus: str,
                   claimed: float, relays: int,
                   owner_sourced: bool) -> dict:
    """Rule 6.10b made arithmetic: testimony folds at RELAY_BASE_K, cut by
    RELAY_DECAY per hop, halved again when the chain began at an owner."""
    k = RELAY_BASE_K * (RELAY_DECAY ** max(0, relays))
    if owner_sourced:
        k *= OWNER_PENALTY
    ops = {sub: dict(loci) for sub, loci in
           (payload.get("opinions") or {}).items()}
    cur = ops.get(subject, {}).get(locus,
                                   {"estimate": 5000.0, "weight": 0.0})
    op2 = update_value(Opinion(cur["estimate"], cur["weight"]), claimed, k)
    ops.setdefault(subject, {})[locus] = {"estimate": op2.estimate,
                                          "weight": op2.weight}
    return {**payload, "opinions": ops}


def hear(payload: dict, text: str, source: str, relays: int,
         owner_sourced: bool) -> dict:
    heard = (payload.get("heard") or [])[-(MAX_HEARD - 1):] + [{
        "text": text, "from": source, "relays": relays,
        "owner_sourced": owner_sourced}]
    return {**payload, "heard": heard}


def would_relay_confidence(payload: dict, seed: str) -> bool:
    """Rule 13.5b: Loyalty disposes. A loyal head keeps its owner's words;
    a disloyal one gossips. Deterministic per (agent, moment)."""
    g = payload.get("genotype") or {}
    p_gossip = 1.0 - norm("Loyalty", g.get("Loyalty", 5000.0))
    return random.Random(f"relay:{seed}").random() < p_gossip


def relayable_confidence(payload: dict) -> str | None:
    """The owner's standing word -- the secret worth keeping or selling."""
    objs = payload.get("objectives") or []
    return objs[0] if objs else None
