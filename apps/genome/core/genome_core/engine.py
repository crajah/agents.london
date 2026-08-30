"""The autonomy loop — execution-spec.md §4: event → decision → intent →
scheduled event. Pure logic: no I/O, no clock of its own, no inference.

The engine answers one event at a time. Some events resolve mechanically
(mining completes, cargo deposits); others yield a DecisionRequest, and the
caller — stub decider in Phase 1, ADK in Phase 2 — returns a Choice which
`apply_choice` turns into writes and the next scheduled event. Every choice is
recorded (execution-spec §6) by the caller.

Provisional constants live in calibration-spec.md §4's open list; the two used
here are marked PROVISIONAL and surface in `PROVISIONAL` for the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import forms

# PROVISIONAL (calibration §4: base collection rate — Toolhouse improves it)
MINE_RATE_UNITS_PER_SEC = 1.0 / 60.0          # one unit a minute
CARGO_CEILING = 15.0                          # genome-spec Rule 4.16
USER_CEILING_PER_KIND = 25.0                  # genome-spec Rule 4.15
HOME_XY = (0.5, 0.5)                          # deposit point PROVISIONAL

PROVISIONAL = {"MINE_RATE_UNITS_PER_SEC": MINE_RATE_UNITS_PER_SEC,
               "HOME_XY": HOME_XY}


@dataclass(frozen=True)
class AgentView:
    """What the engine needs of an agent; the caller loads and persists."""
    agent_uuid: str
    home_realm: str
    realm: str
    x: float
    y: float
    cargo: dict[str, float]          # kind -> units

    def cargo_total(self) -> float:
        return sum(self.cargo.values())


@dataclass(frozen=True)
class PileView:
    pile_uuid: str
    kind: int
    x: float
    y: float
    qty: float                        # derived by the caller via forms


@dataclass(frozen=True)
class DecisionRequest:
    """Handed to the decider. Options are concrete actions, never advice —
    the situation is the opponent (genotype-spec Rule 6.10a's lesson applies
    to framing here too)."""
    agent_uuid: str
    situation: str
    options: tuple[str, ...]
    context: dict


@dataclass(frozen=True)
class Choice:
    option: str
    target: str | None = None         # pile_uuid for travel/mine


@dataclass(frozen=True)
class Effects:
    """What the caller must persist. Nothing here touches storage directly."""
    movement: dict | None = None                 # intent to write
    schedule: tuple[str, float, str, dict] | None = None   # kind, due, subject, payload
    mine_pile: tuple[str, float] | None = None   # pile_uuid, want
    deposit: dict[str, float] | None = None      # kind -> units accepted
    cargo_delta: dict[str, float] = field(default_factory=dict)
    done: bool = False


def on_event(kind: str, agent: AgentView, piles: list[PileView],
             now: float, payload: dict,
             stock: dict[str, float] | None = None) -> DecisionRequest | Effects:
    """Entry point for every drained event."""
    if kind == "arrival":
        return _decide_here(agent, piles, payload, stock)
    if kind == "mining_done":
        # mechanical: the decision was taken when mining began; the next
        # decision is a fresh event a minute on, never at the same instant
        take = payload["take"]
        return Effects(cargo_delta={str(payload["pile_kind"]): take},
                       schedule=("decide", now + 60.0, agent.agent_uuid,
                                 {"pile_uuid": payload["pile_uuid"]}))
    if kind == "decide":
        return _decide_here(agent, piles, payload, stock)
    raise ValueError(f"unknown event kind {kind!r}")


def _decide_here(agent: AgentView, piles: list[PileView], payload: dict,
                 stock: dict[str, float] | None = None) -> DecisionRequest:
    stock = stock or {}
    at_pile = payload.get("pile_uuid")
    by_id = {p.pile_uuid: p for p in piles}
    options: list[str] = []
    here = by_id.get(at_pile)
    # Guard: an empty pile offers no mining — otherwise a want=0 mine completes
    # instantly and the loop spins at a single timestamp.
    if here and here.qty > 0.05 and agent.cargo_total() < CARGO_CEILING:
        options.append("mine_here")
    reachable = [p.pile_uuid for p in piles
                 if p.pile_uuid != at_pile and p.qty > 0.05]
    if reachable:
        options.append("travel_to_pile")
    # Guard: depositing needs room under the user ceiling (Rule 4.15) for at
    # least one carried kind — a full store accepts nothing (Rule 4.19), and a
    # zero-acceptance round trip is a same-timestamp spin.
    room = any(units > 0 and stock.get(kind, 0.0) < USER_CEILING_PER_KIND
               for kind, units in agent.cargo.items())
    if room and agent.realm == agent.home_realm:
        options.append("go_home_deposit")
    if not options:
        options = ["wait"]
    return DecisionRequest(
        agent_uuid=agent.agent_uuid, situation="at_" + (at_pile or "large"),
        options=tuple(options),
        context={"cargo_total": agent.cargo_total(), "at_pile": at_pile,
                 "reachable": reachable})


def apply_choice(choice: Choice, agent: AgentView, piles: list[PileView],
                 now: float, payload: dict) -> Effects:
    """Turn a decision into effects. The caller records the decision first."""
    by_id = {p.pile_uuid: p for p in piles}

    if choice.option == "mine_here":
        pile = by_id[payload["pile_uuid"]]
        want = min(pile.qty, CARGO_CEILING - agent.cargo_total())
        duration = want / MINE_RATE_UNITS_PER_SEC
        return Effects(mine_pile=(pile.pile_uuid, want),
                       schedule=("mining_done", now + duration, agent.agent_uuid,
                                 {"pile_uuid": pile.pile_uuid,
                                  "pile_kind": pile.kind, "take": want}))

    if choice.option == "travel_to_pile":
        pile = by_id[choice.target]
        arrives = forms.arrival_time(agent.x, agent.y, pile.x, pile.y, now)
        return Effects(
            movement={"from_x": agent.x, "from_y": agent.y,
                      "to_x": pile.x, "to_y": pile.y,
                      "departed_at": now, "arrives_at": arrives},
            schedule=("arrival", arrives, agent.agent_uuid,
                      {"pile_uuid": pile.pile_uuid}))

    if choice.option == "go_home_deposit":
        hx, hy = HOME_XY
        arrives = forms.arrival_time(agent.x, agent.y, hx, hy, now)
        return Effects(
            movement={"from_x": agent.x, "from_y": agent.y, "to_x": hx,
                      "to_y": hy, "departed_at": now, "arrives_at": arrives},
            schedule=("deposit_arrival", arrives, agent.agent_uuid, {}))

    if choice.option == "wait":
        return Effects(schedule=("decide", now + 3600.0, agent.agent_uuid, {}))

    raise ValueError(f"unknown option {choice.option!r}")


def on_deposit_arrival(agent: AgentView, stock: dict[str, float],
                       now: float) -> Effects:
    """Deposit at the birth world, partially accepted at the user ceiling
    (genome-spec Rules 4.3, 4.15, 4.19). Remainder stays aboard."""
    accepted: dict[str, float] = {}
    delta: dict[str, float] = {}
    for kind, units in agent.cargo.items():
        room = USER_CEILING_PER_KIND - stock.get(kind, 0.0)
        take = max(0.0, min(units, room))
        if take > 0:
            accepted[kind] = take
            delta[kind] = -take
    return Effects(deposit=accepted, cargo_delta=delta,
                   schedule=("decide", now + 60.0, agent.agent_uuid, {}))


def stub_decider(req: DecisionRequest, seed: int) -> Choice:
    """Phase 1's decider: uniform over the options, deterministic per seed —
    the loop must be provable without an LLM (BUILD 1.3). Never strategic:
    a clever stub would put its own behaviour on display (Rule 12.5's fence)."""
    import random
    r = random.Random(f"{seed}:{req.agent_uuid}:{req.situation}:{req.options}")
    option = r.choice(req.options)
    target = r.choice(req.context["reachable"]) \
        if option == "travel_to_pile" and req.context["reachable"] else None
    return Choice(option=option, target=target)
