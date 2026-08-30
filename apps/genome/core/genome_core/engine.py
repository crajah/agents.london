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
from . import path as pathmod

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
    known_piles: frozenset[str] = frozenset()   # fog of knowledge (§8: the map
    # is private knowledge that took journeys to acquire)
    explored: frozenset[tuple[int, int]] = frozenset()   # visited GRID_K cells

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
    reveal: tuple[str, ...] = ()                 # pile uuids newly known
    mark_explored: tuple[tuple[int, int], ...] = ()   # grid cells now visited
    transfer: dict | None = None                 # {"to_world","portal_xy"} — the
    # caller signs the assertion and flips presence (genome-spec §6)
    cargo_delta: dict[str, float] = field(default_factory=dict)
    done: bool = False


def on_event(kind: str, agent: AgentView, piles: list[PileView],
             now: float, payload: dict,
             stock: dict[str, float] | None = None,
             portals: list[dict] | None = None) -> DecisionRequest | Effects:
    """Entry point for every drained event."""
    if kind == "arrival":
        return _decide_here(agent, piles, payload, stock, portals)
    if kind == "mining_done":
        # mechanical: the decision was taken when mining began; the next
        # decision is a fresh event a minute on, never at the same instant
        take = payload["take"]
        return Effects(cargo_delta={str(payload["pile_kind"]): take},
                       schedule=("decide", now + 60.0, agent.agent_uuid,
                                 {"pile_uuid": payload["pile_uuid"]}))
    if kind == "encounter":
        other = payload["other"]
        # Rule 6.6/3.4: the other agent's COLOUR is visible, nothing else; the
        # agent's own OPINION of that uuid (if any) rides in the payload.
        return DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="encounter",
            options=("offer_trade", "propose_breeding", "attack", "ignore"),
            context={"cargo_total": agent.cargo_total(),
                     "other_uuid": other["agent_uuid"],
                     "other_colours": other.get("colour_pair"),
                     "other_infected": other.get("infected", False),
                     "opinion": payload.get("opinion"),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})

    if kind == "mating_proposal":
        # Rule 6.3: acceptance is the Selectivity decision. The proposer is
        # known only by colours and any prior opinion -- and by the fact of
        # the proposal itself, which is information too.
        p = payload
        return DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="mating_proposal",
            options=("accept_mate", "decline_mate"),
            context={"cargo_total": agent.cargo_total(),
                     "proposer_uuid": p["proposer"]["agent_uuid"],
                     "proposer_colours": p["proposer"].get("colour_pair"),
                     "opinion": p.get("opinion"),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})

    if kind == "explored":
        found = tuple(p.pile_uuid for p in piles
                      if (p.x - agent.x) ** 2 + (p.y - agent.y) ** 2
                      <= SIGHT_RADIUS ** 2)
        return Effects(reveal=found,
                       mark_explored=(cell_of(agent.x, agent.y),),
                       schedule=("decide", now + 60.0, agent.agent_uuid, {}))
    if kind == "decide":
        return _decide_here(agent, piles, payload, stock, portals)
    raise ValueError(f"unknown event kind {kind!r}")


SIGHT_RADIUS = 0.18
GRID_K = 6                # exploration grid: 36 regions per world


def cell_of(x: float, y: float) -> tuple[int, int]:
    return (min(GRID_K - 1, int(x * GRID_K)), min(GRID_K - 1, int(y * GRID_K)))


def cell_centre(c: tuple[int, int]) -> tuple[float, float]:
    return ((c[0] + 0.5) / GRID_K, (c[1] + 0.5) / GRID_K)


def frontier_cells(explored: frozenset) -> list[tuple[int, int]]:
    """Unexplored cells ADJACENT to explored ones — the edge of the known.
    Game-like expansion: the map grows outward from where you have been."""
    out = []
    for i in range(GRID_K):
        for j in range(GRID_K):
            if (i, j) in explored:
                continue
            if any((i + di, j + dj) in explored
                   for di in (-1, 0, 1) for dj in (-1, 0, 1)):
                out.append((i, j))
    return out


def far_cells(explored: frozenset, x: float, y: float) -> list[tuple[int, int]]:
    """Unexplored cells sorted farthest-first from the agent — expeditions,
    not errands. Wanderlust's surface within a world."""
    unknown = [(i, j) for i in range(GRID_K) for j in range(GRID_K)
               if (i, j) not in explored]
    return sorted(unknown, key=lambda c: -((cell_centre(c)[0] - x) ** 2
                                           + (cell_centre(c)[1] - y) ** 2))       # PROVISIONAL: reveal radius on arrival (Sight scales later)


def _decide_here(agent: AgentView, piles: list[PileView], payload: dict,
                 stock: dict[str, float] | None = None,
                 portals: list[dict] | None = None) -> DecisionRequest:
    stock = stock or {}
    at_pile = payload.get("pile_uuid")
    by_id = {p.pile_uuid: p for p in piles}
    options: list[str] = []
    here = by_id.get(at_pile)
    if here and here.qty > 0.05 and agent.cargo_total() < CARGO_CEILING:
        options.append("mine_here")
    # Rule 5.2 of genome-spec: finding piles is work. Travel targets only piles
    # this agent KNOWS; the rest of the map must be explored.
    known = agent.known_piles or frozenset(by_id)   # empty = legacy: all known
    reachable = [u for u in known
                 if u != at_pile and u in by_id and by_id[u].qty > 0.05]
    if reachable:
        options.append("travel_to_pile")
    frontier = frontier_cells(agent.explored) if agent.explored else []
    if frontier:
        options.append("explore_frontier")          # Curiosity: the near unknown
    if far_cells(agent.explored, agent.x, agent.y) and agent.explored:
        options.append("survey_far")                # Wanderlust: the far unknown
    room = any(units > 0 and stock.get(kind, 0.0) < USER_CEILING_PER_KIND
               for kind, units in agent.cargo.items())
    if room and agent.realm == agent.home_realm:
        options.append("go_home_deposit")
    # a linked portal within reach offers passage (genome-spec Rule 6.1a:
    # passage itself is instantaneous; getting to the portal is the journey)
    near_portal = None
    for pt in (portals or []):
        if pt.get("to_world") and \
                (pt["x"] - agent.x) ** 2 + (pt["y"] - agent.y) ** 2 < 0.03 ** 2:
            near_portal = pt
            break
    if near_portal:
        options.append("take_portal")
    if not options:
        options = ["wait"]
    return DecisionRequest(
        agent_uuid=agent.agent_uuid, situation="at_" + (at_pile or "large"),
        options=tuple(options),
        context={"cargo_total": agent.cargo_total(), "at_pile": at_pile,
                 "portal_to": near_portal.get("to_world") if near_portal else None,
                 "portal_xy": [near_portal["x"], near_portal["y"]] if near_portal else None,
                 "portal_colours": near_portal.get("dest_colours") if near_portal else None,
                 "reachable": reachable,
                 "frontier_count": len(frontier_cells(agent.explored))
                 if agent.explored else 0,
                 "unexplored_count": GRID_K * GRID_K - len(agent.explored)})


def _route_effects(agent: AgentView, tx: float, ty: float, now: float,
                   terrain: list[dict], arrival_kind: str,
                   arrival_payload: dict, time_scale: float = 1.0) -> Effects:
    """Route computed once, at decision time (execution-spec Rule 2.1a).

    time_scale is a PER-WORLD DEMO AFFORDANCE: journeys in a scaled world
    complete scale-times faster. It applies here, at route creation, so every
    closed form downstream -- server and client -- needs no change: arrives_at
    is simply nearer. Real worlds run at 1.0; analyses must exclude scaled
    worlds (the same discipline as founding centres, Rule 3.2b)."""
    pts = pathmod.find_path(terrain, agent.x, agent.y, tx, ty)
    if pts is None:                      # worldgen guarantees this cannot happen
        raise RuntimeError("unroutable destination")
    route = forms.Route(tuple(pts), now)
    # Dwell floor: no journey resolves in under two minutes. Without it, two
    # adjacent piles produce an arrival->decide->travel loop at LLM cost every
    # few seconds -- observed live, one agent burning a call per tick shuttling
    # between piles at her feet. Arrival, unloading and looking around take
    # time; the floor is that time.
    scale = max(1.0, time_scale)
    arrives = now + max((route.arrives_at - now) / scale, 120.0 / scale)
    return Effects(
        movement={"waypoints": list(route.waypoints), "departed_at": now,
                  "arrives_at": arrives},
        schedule=(arrival_kind, arrives, agent.agent_uuid,
                  arrival_payload))


def apply_choice(choice: Choice, agent: AgentView, piles: list[PileView],
                 now: float, payload: dict,
                 terrain: list[dict] | None = None,
                 time_scale: float = 1.0) -> Effects:
    """Turn a decision into effects. The caller records the decision first."""
    terrain = terrain or []
    by_id = {p.pile_uuid: p for p in piles}

    if choice.option == "mine_here":
        pile = by_id[payload["pile_uuid"]]
        want = min(pile.qty, CARGO_CEILING - agent.cargo_total())
        duration = want / MINE_RATE_UNITS_PER_SEC / max(1.0, time_scale)
        return Effects(mine_pile=(pile.pile_uuid, want),
                       schedule=("mining_done", now + duration, agent.agent_uuid,
                                 {"pile_uuid": pile.pile_uuid,
                                  "pile_kind": pile.kind, "take": want}))

    if choice.option == "travel_to_pile":
        pile = by_id[choice.target]
        return _route_effects(agent, pile.x, pile.y, now, terrain,
                              "arrival", {"pile_uuid": pile.pile_uuid},
                              time_scale)

    if choice.option == "go_home_deposit":
        hx, hy = HOME_XY
        return _route_effects(agent, hx, hy, now, terrain,
                              "deposit_arrival", {}, time_scale)

    if choice.option in ("explore_frontier", "survey_far"):
        if choice.option == "explore_frontier":
            cand = sorted(frontier_cells(agent.explored),
                          key=lambda c: (cell_centre(c)[0] - agent.x) ** 2
                          + (cell_centre(c)[1] - agent.y) ** 2)
        else:
            cand = far_cells(agent.explored, agent.x, agent.y)
        for c in cand[:8]:          # nearest frontier / farthest unknown first
            tx, ty = cell_centre(c)
            if pathmod.find_path(terrain, agent.x, agent.y, tx, ty) is not None:
                return _route_effects(agent, tx, ty, now, terrain,
                                      "explored", {"cell": list(c)},
                                      time_scale)
        return Effects(schedule=("decide", now + 3600.0, agent.agent_uuid, {}))

    if choice.option == "take_portal":
        return Effects(
            transfer={"to_world": payload.get("portal_to") or
                      choice.target,
                      "portal_xy": payload.get("portal_xy")},
            schedule=("decide", now + 60.0, agent.agent_uuid, {}))

    if choice.option in ("accept_mate", "decline_mate"):
        return Effects(schedule=("mating_answer", now, agent.agent_uuid,
                                 {"answer": choice.option,
                                  "proposer": payload.get("proposer", {})}))

    if choice.option in ("offer_trade", "propose_breeding", "attack", "ignore"):
        # resolution is pairwise and happens in the drain once BOTH have
        # answered; the engine only records intent
        return Effects(schedule=("encounter_answer", now, agent.agent_uuid,
                                 {"answer": choice.option,
                                  "other": payload.get("other", {})}))

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
