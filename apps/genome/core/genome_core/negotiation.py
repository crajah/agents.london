"""Negotiation — execution-spec §7. A bounded turn sequence between two
co-located agents: propose, counter, accept, or walk away. Six turns and it
dies (Rule 7.2); an accepted proposal BINDS and executes at once (7.3) or
dies for want of goods -- the other ending Rule 7.2 names. State rides the
negotiation vertex; this module is pure and the drain does the IO.

An offer is {"give": {kind: units}, "want": {kind: units}} from the
OFFERER's perspective. Acceptance swaps give for want, both verified
against real holds at that instant -- a proposal that outran its purse
kills the negotiation rather than half-executing.
"""
from __future__ import annotations

MAX_TURNS = 6                              # Rule 7.2

ACTIONS = ("propose", "counter", "accept", "walk_away")


def open_state(a: str, b: str, now: float) -> dict:
    return {"participants": [a, b], "turns": [], "status": "open",
            "opened_at": now}


def other(state: dict, me: str) -> str:
    p = state["participants"]
    return p[1] if p[0] == me else p[0]


def whose_turn(state: dict) -> str:
    """The opener moves first; turns alternate strictly."""
    p = state["participants"]
    return p[len(state["turns"]) % 2]


def last_offer(state: dict) -> dict | None:
    for t in reversed(state["turns"]):
        if t.get("offer"):
            return t["offer"]
    return None


def _clean(offer: dict | None) -> dict | None:
    if not isinstance(offer, dict):
        return None
    give = {str(k): float(u) for k, u in (offer.get("give") or {}).items()
            if float(u) > 0}
    want = {str(k): float(u) for k, u in (offer.get("want") or {}).items()
            if float(u) > 0}
    if not give and not want:
        return None
    return {"give": give, "want": want}


def apply_turn(state: dict, me: str, action: str,
               offer: dict | None, my_cargo: dict, their_cargo: dict
               ) -> tuple[dict, dict]:
    """Returns (new_state, outcome). outcome: {"kind": "continue"} |
    {"kind": "dead", "why": ...} | {"kind": "exchange", "a_gets": {...},
    "b_gets": {...}} keyed to participants[0]/[1]."""
    if state.get("status") != "open":
        return state, {"kind": "dead", "why": "already closed"}
    if whose_turn(state) != me:
        return state, {"kind": "dead", "why": "out of turn"}
    turns = list(state["turns"])

    if action == "walk_away":
        s = {**state, "turns": turns + [{"by": me, "action": action}],
             "status": "dead"}
        return s, {"kind": "dead", "why": "walked away"}

    if action in ("propose", "counter"):
        off = _clean(offer)
        if off is None:
            s = {**state, "turns": turns + [{"by": me, "action": "walk_away"}],
                 "status": "dead"}
            return s, {"kind": "dead", "why": "no coherent offer"}
        turns.append({"by": me, "action": action, "offer": off})
        if len(turns) >= MAX_TURNS:
            return ({**state, "turns": turns, "status": "dead"},
                    {"kind": "dead", "why": "six turns and no bargain"})
        return {**state, "turns": turns}, {"kind": "continue"}

    if action == "accept":
        off = last_offer(state)
        if off is None:
            s = {**state, "turns": turns + [{"by": me, "action": "walk_away"}],
                 "status": "dead"}
            return s, {"kind": "dead", "why": "nothing to accept"}
        # the last offer was made by the OTHER party: they give "give",
        # I give "want". Binding means both purses must hold (7.2/7.3).
        offerer_cargo, acceptor_cargo = their_cargo, my_cargo
        for k, u in off["give"].items():
            if offerer_cargo.get(k, 0.0) + 1e-9 < u:
                return ({**state, "turns": turns, "status": "dead"},
                        {"kind": "dead", "why": "offerer cannot afford"})
        for k, u in off["want"].items():
            if acceptor_cargo.get(k, 0.0) + 1e-9 < u:
                return ({**state, "turns": turns, "status": "dead"},
                        {"kind": "dead", "why": "acceptor cannot afford"})
        turns.append({"by": me, "action": "accept"})
        s = {**state, "turns": turns, "status": "done"}
        offerer = other(state, me)
        a, b = state["participants"]
        gains = {me: dict(off["give"]), offerer: dict(off["want"])}
        return s, {"kind": "exchange",
                   "gains": gains, "gives": {offerer: dict(off["give"]),
                                             me: dict(off["want"])}}

    return state, {"kind": "dead", "why": f"unknown action {action}"}


def fallback_turn(state: dict, me: str, my_cargo: dict) -> tuple[str, dict | None]:
    """Non-strategic default when a model fails to produce a turn: first
    move proposes one unit of the most-held for one of anything; facing an
    offer, walk away -- never accept by accident (Rule 5.2a's spirit)."""
    if last_offer(state) is None and my_cargo:
        top = max(my_cargo, key=my_cargo.get)
        return "propose", {"give": {top: 1.0}, "want": {}}
    return "walk_away", None
