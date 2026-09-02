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
MINE_RATE_UNITS_PER_SEC = 1.0 / 10.0          # one unit per 10s (constant-
# motion revision: agents sip and move, never camp)
CARGO_CEILING = 15.0                          # genome-spec Rule 4.16
USER_CEILING_PER_KIND = 25.0                  # genome-spec Rule 4.15
HOME_XY = (0.5, 0.5)                          # legacy deposit point; worlds
# without muster points (pre-migration) still deposit here
MUSTER_COUNT = 5                              # muster points per world (fixed)
PILE_STANDOFF = 0.02                          # agents stand AT a pile, not ON it
MIN_SEPARATION = 0.018                        # no two agents rest on one spot
REACH = 0.035                                 # build/board reach: hands on it
MINE_STINT_UNITS = 5.0                        # one stint, then decide again

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
    contribute: tuple[str, dict] | None = None   # site_key, offered cargo — the
    # caller pours it in via construction.contribute, which says what stuck
    board: str | None = None                     # ark site key — the caller
    # claims a berth via construction.board (Rules 3.7e/4.10a)
    cache_op: tuple[str, str | None] | None = None   # ("build"|"stash"|
    # "collect", cache_key) — commons larders; the caller applies
    market_turn: bool = False                    # at the board with business:
    # the caller queues a structured market decision (genome-spec §4.5)
    portage: tuple[str, str] | None = None       # ("take_up"|"set_down",
    # site_key) — construction-spec §3.10–3.13; the caller applies
    found: str | None = None                     # construction name to break
    # ground on at the agent's feet (agent-driven founding, 2026-09-02)
    word: str | None = None                      # addressable counterparty to
    # send testimony to at ANY distance (Rules 9.1c/9.1d); caller applies
    service: tuple[str, str, str] | None = None  # (verb, counterparty,
    # skill): "request" from a known remote holder, or the holder's
    # "perform"/"refuse" answer (Rules 8.6-8.8); caller applies
    cargo_delta: dict[str, float] = field(default_factory=dict)
    done: bool = False


def on_event(kind: str, agent: AgentView, piles: list[PileView],
             now: float, payload: dict,
             stock: dict[str, float] | None = None,
             portals: list[dict] | None = None,
             ctx: dict | None = None) -> DecisionRequest | Effects:
    ts = max(1.0, (ctx or {}).get("time_scale", 1.0))
    """Entry point for every drained event. ctx (optional) carries the world
    around the decision: genotype, neighbour positions, occupied spots,
    muster points — loaded by the caller, never fetched here."""
    if kind == "arrival":
        return _decide_here(agent, piles, payload, stock, portals, ctx)
    if kind == "mining_done":
        # mechanical: the decision was taken when mining began; the next
        # decision is a fresh event a minute on, never at the same instant
        take = payload["take"]
        return Effects(cargo_delta={str(payload["pile_kind"]): take},
                       schedule=("decide", now + 15.0 / ts, agent.agent_uuid,
                                 {"pile_uuid": payload["pile_uuid"]}))
    if kind == "encounter":
        if (ctx or {}).get("carrying_site"):
            # Rule 3.12: carriers are occupied — no trading, no fighting,
            # no courting until the construction is set down
            return Effects(schedule=("decide", now + 120.0 / ts,
                                     agent.agent_uuid, {}))
        other = payload["other"]
        # Rule 6.6/3.4: the other agent's COLOUR is visible, nothing else; the
        # agent's own OPINION of that uuid (if any) rides in the payload.
        # Rule 3.7a/b: a held berth may change hands at any co-location,
        # countdown included -- the option appears only for a holder while
        # the water is coming
        enc_options = ["offer_trade", "propose_breeding", "attack", "ignore"]
        if (ctx or {}).get("has_berth") and \
                (ctx or {}).get("flood_in_s") is not None:
            enc_options.insert(0, "offer_berth")
        scried = {}
        if (ctx or {}).get("skill") == "Scrying":
            # skills-spec 4.2: the encounter turns sequential for a scryer
            scried = {"scried_cargo": other.get("cargo"),
                      "scried_infected": other.get("infected")}
        return DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="encounter",
            options=tuple(enc_options),
            context={"cargo_total": agent.cargo_total(),
                     "other_uuid": other["agent_uuid"],
                     "other_colours": other.get("colour_pair"),
                     "other_infected": other.get("infected", False),
                     **scried,
                     "opinion": payload.get("opinion"),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})

    if kind == "mating_proposal":
        # Rule 6.3: acceptance is the Selectivity decision. The proposer is
        # known only by colours and any prior opinion -- and by the fact of
        # the proposal itself, which is information too.
        p = payload
        read = {}
        if (ctx or {}).get("skill") == "Gene-reading" \
                and p["proposer"].get("genotype"):
            from .genotype import expressed as _expr
            read = {"suitor_expressed": {
                k: round(v, 3) for k, v in
                _expr(p["proposer"]["genotype"]).items()}}
        return DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="mating_proposal",
            options=("accept_mate", "decline_mate"),
            context={"cargo_total": agent.cargo_total(),
                     **read,
                     "proposer_uuid": p["proposer"]["agent_uuid"],
                     "proposer_colours": p["proposer"].get("colour_pair"),
                     "opinion": p.get("opinion"),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})

    if kind == "explored":
        sr = SIGHT_RADIUS * (ctx or {}).get("sight_mult", 1.0)   # a Cairn
        found = tuple(p.pile_uuid for p in piles                 # sees further
                      if (p.x - agent.x) ** 2 + (p.y - agent.y) ** 2
                      <= sr ** 2)
        return Effects(reveal=found,
                       mark_explored=(cell_of(agent.x, agent.y),),
                       schedule=("decide", now + 15.0 / ts,
                                 agent.agent_uuid, {}))
    if kind == "service_request":
        # Rule 8.6: someone who cannot, asks someone who can. Whether to
        # oblige is the holder's own decision -- terms, reciprocity and
        # reputation all live in that choice.
        return DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="service_request",
            options=("perform_service", "refuse_service"),
            context={"cargo_total": agent.cargo_total(),
                     "requester": payload.get("requester"),
                     "requester_colours": payload.get("requester_colours"),
                     "skill_asked": payload.get("skill"),
                     "opinion": payload.get("opinion"),
                     "favours_owed_to_me": payload.get("credit", 0),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})
    if kind == "decide":
        return _decide_here(agent, piles, payload, stock, portals, ctx)
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


def speed_factor(g: dict) -> float:
    """The Speed pool's surface (genotype-spec faculty table: movement rate
    across a map): grounded in Agility and Dexterity, range 0.7x-1.3x. A
    nimble genotype crosses a world in three-quarters the time a clumsy one
    takes -- visible in every journey, heritable like everything else."""
    from .genotype import norm
    vals = [norm(k, g.get(k, 5000.0)) for k in ("Agility", "Dexterity")]
    return 0.7 + 0.6 * (sum(vals) / len(vals))


def standoff(ax: float, ay: float, tx: float, ty: float,
             r: float = PILE_STANDOFF) -> tuple[float, float]:
    """Stop r short of the target, along the line of approach — an agent
    stands AT a pile or flag, never on top of it (collision rule)."""
    dx, dy = tx - ax, ty - ay
    d = (dx * dx + dy * dy) ** 0.5
    if d <= r:
        return (ax, ay)
    k = (d - r) / d
    return (ax + dx * k, ay + dy * k)


def separate(tx: float, ty: float, occupied: list, seed: str,
             r: float = MIN_SEPARATION) -> tuple[float, float]:
    """If the target rests on an occupied spot, walk a deterministic spiral of
    candidate offsets until clear. Occupied = other agents' rest positions and
    pile centres; two agents never share a pixel and nobody parks on a pile."""
    import math as _m
    import random as _r
    if not any((tx - ox) ** 2 + (ty - oy) ** 2 < r * r for ox, oy in occupied):
        return (tx, ty)
    a0 = _r.Random(f"sep:{seed}").uniform(0, 2 * _m.pi)
    for ring in (1.2, 2.0, 3.0):
        for i in range(8):
            a = a0 + i * _m.pi / 4
            cx = min(0.95, max(0.05, tx + _m.cos(a) * r * ring))
            cy = min(0.95, max(0.05, ty + _m.sin(a) * r * ring))
            if not any((cx - ox) ** 2 + (cy - oy) ** 2 < r * r
                       for ox, oy in occupied):
                return (cx, cy)
    return (tx, ty)                       # a crowd this dense keeps its pile-up


def nearest_muster(muster: list[dict], x: float, y: float) -> tuple[float, float]:
    """Deposits happen at the nearest muster flag (user directive: agents go
    to a muster point to drop their load; five per world)."""
    if not muster:
        return HOME_XY
    m = min(muster, key=lambda q: (q["x"] - x) ** 2 + (q["y"] - y) ** 2)
    return (m["x"], m["y"])


def _decide_here(agent: AgentView, piles: list[PileView], payload: dict,
                 stock: dict[str, float] | None = None,
                 portals: list[dict] | None = None,
                 ctx: dict | None = None) -> DecisionRequest:
    stock = stock or {}
    ctx = ctx or {}
    carrying = ctx.get("carrying_site")
    if carrying:
        # Rule 3.12: the party moves as one body and does nothing else.
        # The only doors out are a portal or the ground.
        opts = ["set_down_construction"]
        near_p = None
        for pt in (portals or []):
            if pt.get("to_world") and \
                    (pt["x"] - agent.x) ** 2 + (pt["y"] - agent.y) ** 2 \
                    < 0.03 ** 2:
                near_p = pt
                break
        if near_p:
            opts.insert(0, "take_portal")
        elif any(pt.get("to_world") for pt in (portals or [])):
            opts.insert(0, "carry_to_portal")
        opts.append("wait")
        return DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="carrying",
            options=tuple(opts),
            context={"cargo_total": agent.cargo_total(), "at_pile": None,
                     "reachable": [], "site_carried": carrying,
                     "site_name": ctx.get("carrying_name"),
                     "portal_to": near_p.get("to_world") if near_p else None,
                     "portal_xy": [near_p["x"], near_p["y"]] if near_p else None,
                     "portal_colours": near_p.get("dest_colours")
                     if near_p else None})
    at_pile = payload.get("pile_uuid")
    by_id = {p.pile_uuid: p for p in piles}
    options: list[str] = []
    here = by_id.get(at_pile)
    hold_cap = CARGO_CEILING + ctx.get("cargo_bonus", 0.0) \
        + (5.0 if ctx.get("skill") == "Porterage" else 0.0)   # a Granary
    if here and here.qty > 0.05 and agent.cargo_total() < hold_cap:
        options.append("mine_here")
    # Rule 5.2 of genome-spec: finding piles is work. Travel targets only piles
    # this agent KNOWS; the rest of the map must be explored -- unless a
    # Library stands: its map room knows every pile in the world
    known = frozenset(by_id) if ctx.get("map_room") \
        else (agent.known_piles or frozenset(by_id))
    reachable = [u for u in known
                 if u != at_pile and u in by_id and by_id[u].qty > 0.05]
    if reachable:
        options.append("travel_to_pile")
    frontier = frontier_cells(agent.explored) if agent.explored else []
    if frontier:
        options.append("explore_frontier")          # Curiosity: the near unknown
    if far_cells(agent.explored, agent.x, agent.y) and agent.explored:
        options.append("survey_far")                # Wanderlust: the far unknown
    ceiling = USER_CEILING_PER_KIND + ctx.get("stock_ceiling_bonus", 0.0)
    room = any(units > 0 and stock.get(kind, 0.0) < ceiling
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
    # construction sites are public fixtures; an agent carrying what an
    # unfinished one needs may deliver straight from its hold (Rule 3.5)
    sites = [s for s in ctx.get("sites", []) if not s.get("complete")]
    near_site = next((s for s in sites
                      if (s["x"] - agent.x) ** 2 + (s["y"] - agent.y) ** 2
                      < 0.03 ** 2), None)
    from . import construction as _con
    if near_site and _con.accepts(near_site, agent.cargo):
        options.append("contribute_here")
    if any(_con.accepts(s, agent.cargo) for s in sites
           if s is not near_site):
        options.append("travel_to_site")
    # commons caches (user directive): four different kinds, one unit each,
    # buys a larder in the market square; your colours open it
    from . import construction as _c2
    near_cache = None
    if ctx.get("is_commons"):
        caches = ctx.get("caches", [])
        near_cache = next(
            (s for s in caches
             if s.get("colours") == ctx.get("colour_pair")
             and (s["x"] - agent.x) ** 2 + (s["y"] - agent.y) ** 2
             < REACH ** 2), None)
        if near_cache:
            if agent.cargo_total() > 0:
                options.append("stash_cache")
            if near_cache.get("holdings"):
                options.append("collect_cache")
        if _c2.cache_cost(agent.cargo) is not None and \
                _c2.cache_spot_clear_payloads(caches, agent.x, agent.y):
            options.append("build_cache")
    # the marketplace (Rule 4.20): at the board with business — or business
    # worth walking to. Listings are world-public; ACTING needs presence.
    mkt = ctx.get("market")
    if mkt:
        at_market = (mkt["x"] - agent.x) ** 2 + (mkt["y"] - agent.y) ** 2 \
            < REACH ** 2
        lst = ctx.get("listings", [])       # market.summary() shape
        can_fill = any(
            not l.get("mine") and l.get("want")
            and all(agent.cargo.get(k, 0.0) + 1e-9 >= u
                    for k, u in l["want"].items())
            for l in lst)
        my_open = any(l.get("mine") for l in lst)
        if at_market and (agent.cargo_total() > 0 or can_fill or my_open):
            options.append("trade_at_market")
        elif not at_market and (can_fill or my_open or
                                (agent.cargo_total() >= 2 and lst)):
            # my_open included: the board summons its listers -- a trade
            # completes hand-to-hand, so an absent lister closes nothing
            options.append("go_to_market")
    # a completed construction within reach may be TAKEN UP (Rule 3.10) —
    # it lifts only when the pledges span its full crew of distinct users
    from . import construction as _c3
    near_portable = next(
        (s for s in ctx.get("sites", [])
         if _c3.portable(s) and not s.get("carried")
         and (s["x"] - agent.x) ** 2 + (s["y"] - agent.y) ** 2 < REACH ** 2),
        None)
    if near_portable:
        options.append("take_up_construction")
    # the water is coming (Rule 4.8): a boardable Ark changes everything
    ark = ctx.get("boardable_ark")
    if ark:
        near_ark = (ark["x"] - agent.x) ** 2 + (ark["y"] - agent.y) ** 2 \
            < 0.03 ** 2
        options.append("board_ark" if near_ark else "flee_to_ark")
    from .genotype import norm as _norm
    g = ctx.get("genotype") or {}
    _steps_through = _norm("Teleport Affinity",
                           g.get("Teleport Affinity", 5000.0)) >= 0.15
    if near_portal:
        # Teleport Affinity (genotype disposition): some agents simply will
        # not step through. Below the floor the option is never offered —
        # a mechanical faculty, like Gender's gate on carrying young.
        if _steps_through:
            options.append("take_portal")
    elif _steps_through and any(pt.get("to_world") for pt in (portals or [])):
        # a portal exists somewhere in this world and this agent is one that
        # crosses: walking to a door is now a CHOOSABLE act, not an accident
        options.append("travel_to_portal")
    # word at a distance (9.1c): an agent with a rolodex and something to
    # say may send testimony to a counterparty it has met or been told of
    if ctx.get("addressable") and ctx.get("has_testimony"):
        options.append("send_word")
    # capability brokerage (8.6): a known REMOTE holder may be asked to
    # perform -- the favour creates a relationship, not a purchase
    if ctx.get("known_remote_holders"):
        options.append("request_service")
    # agent-driven founding (user directive): ground may be broken by any
    # agent whose hold already serves the candidate's bill
    foundable = ctx.get("foundable") or []
    if foundable and not ctx.get("is_commons") and agent.cargo_total() > 0:
        options.append("found_construction")
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
                 "unexplored_count": GRID_K * GRID_K - len(agent.explored),
                 "site_here": near_site["key"] if near_site else None,
                 "portable_here": near_portable["key"] if near_portable else None,
                 "portable_name": near_portable["name"] if near_portable else None,
                 "portable_crew": (f"{len({p.get('user') for p in near_portable.get('porters', {}).values() if p.get('user')})}"
                                   f"/{near_portable.get('required_users', 1)} users pledged")
                 if near_portable else None,
                 "flood_in_s": ctx.get("flood_in_s"),
                 "ark_key": ark["key"] if ark else None,
                 "cache_here": near_cache["key"] if near_cache else None,
                 "market_board": [
                     {"key": l["key"], "give": l.get("give"),
                      "want": l.get("want"), "mine": l.get("mine")}
                     for l in ctx.get("listings", [])
                     if l.get("status", "open") == "open"][:8],
                 "sites_wanting": [s["key"] for s in sites
                                   if _con.accepts(s, agent.cargo)],
                 # standing world facts (Rule 12.4: facts, never advice —
                 # what a genotype does with them is its own affair)
                 "world_kinds": ctx.get("world_kinds"),
                 "stock_kinds": sorted((stock or {}).keys()),
                 "portal_count": sum(1 for pt in (portals or [])
                                     if pt.get("to_world")),
                 "debt_count": ctx.get("debt_count", 0),
                 "credit_count": ctx.get("credit_count", 0),
                 "foundable": foundable,
                 "sites_rising": [s["name"] for s in ctx.get("sites", [])
                                  if s.get("building_until")
                                  and not s.get("complete")
                                  and not s.get("destroyed")]})


def _route_effects(agent: AgentView, tx: float, ty: float, now: float,
                   terrain: list[dict], arrival_kind: str,
                   arrival_payload: dict, time_scale: float = 1.0,
                   pace: float = 1.0) -> Effects:
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
    # movement runs at REAL pace everywhere -- a crossing under a minute is
    # the working speed of the simulation; time_scale no longer compresses
    # journeys (it would read as teleportation), only the dwell floor
    scale = max(0.1, pace)
    arrives = now + max((route.arrives_at - now) / scale,
                        30.0 / max(1.0, time_scale))
    return Effects(
        movement={"waypoints": list(route.waypoints), "departed_at": now,
                  "arrives_at": arrives},
        schedule=(arrival_kind, arrives, agent.agent_uuid,
                  arrival_payload))


def apply_choice(choice: Choice, agent: AgentView, piles: list[PileView],
                 now: float, payload: dict,
                 terrain: list[dict] | None = None,
                 time_scale: float = 1.0,
                 ctx: dict | None = None) -> Effects:
    """Turn a decision into effects. The caller records the decision first."""
    terrain = terrain or []
    ctx = ctx or {}
    occupied = [q for q in ctx.get("occupied", [])]
    pace = speed_factor(ctx.get("genotype") or {}) \
        * ctx.get("pace_mult", 1.0) \
        * (1.1 if ctx.get("skill") == "Pathfinding" else 1.0)   # a Beacon
    # guides every journey; a Pathfinder needs no beacon
    by_id = {p.pile_uuid: p for p in piles}

    if choice.option == "mine_here":
        pile = by_id[payload["pile_uuid"]]
        want = min(pile.qty,
                   CARGO_CEILING + ctx.get("cargo_bonus", 0.0)
                   + (5.0 if ctx.get("skill") == "Porterage" else 0.0)
                   - agent.cargo_total(),
                   MINE_STINT_UNITS + ctx.get("mine_stint_bonus", 0.0)
                   + (2.0 if ctx.get("skill") == "Prospecting" else 0.0))
        rate = MINE_RATE_UNITS_PER_SEC * ctx.get("mine_rate_mult", 1.0)
        duration = want / rate / max(1.0, time_scale)
        return Effects(mine_pile=(pile.pile_uuid, want),
                       schedule=("mining_done", now + duration, agent.agent_uuid,
                                 {"pile_uuid": pile.pile_uuid,
                                  "pile_kind": pile.kind, "take": want}))

    if choice.option == "travel_to_pile":
        pile = by_id[choice.target]
        tx, ty = standoff(agent.x, agent.y, pile.x, pile.y)
        tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
        return _route_effects(agent, tx, ty, now, terrain,
                              "arrival", {"pile_uuid": pile.pile_uuid},
                              time_scale, pace)

    if choice.option == "go_home_deposit":
        hx, hy = nearest_muster(ctx.get("muster") or [], agent.x, agent.y)
        tx, ty = standoff(agent.x, agent.y, hx, hy)
        tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
        return _route_effects(agent, tx, ty, now, terrain,
                              "deposit_arrival", {}, time_scale, pace)

    if choice.option in ("explore_frontier", "survey_far"):
        # The LLM chose WHAT (near unknown vs expedition); the genotype and
        # the world around the agent choose HOW the walk looks — its movement
        # style (swarm, brownian, levy, lawnmower, perimeter). Computed
        # faculty: deterministic per (agent, moment), replayable.
        from . import styles as stylemod
        g = ctx.get("genotype") or {}
        env = {"neighbours": ctx.get("neighbours", []),
               "explored_frac": len(agent.explored) / (GRID_K * GRID_K)}
        seed = f"{agent.agent_uuid}:{int(now)}"
        style = stylemod.pick_style(g, env, seed)
        cand: list[tuple[float, float]] = []
        if choice.option == "survey_far":
            # expeditions stay expeditions: farthest unknown, style adds gait
            import random as _r
            jr = _r.Random(f"far:{seed}")
            cand += [(min(0.95, max(0.05, cx + jr.uniform(-0.04, 0.04))),
                      min(0.95, max(0.05, cy + jr.uniform(-0.04, 0.04))))
                     for cx, cy in (cell_centre(c) for c in
                                    far_cells(agent.explored, agent.x,
                                              agent.y)[:8])]
        else:
            sx, sy = stylemod.target_for(style, agent.x, agent.y,
                                         agent.explored, env, seed)
            if cell_of(sx, sy) not in agent.explored:
                cand.append((sx, sy))       # the style's own pick, if it
            # teaches anything new; frontier cells back it up
            cand += [cell_centre(c) for c in sorted(
                frontier_cells(agent.explored),
                key=lambda c: (cell_centre(c)[0] - agent.x) ** 2
                + (cell_centre(c)[1] - agent.y) ** 2)]
        for tx, ty in cand[:8]:
            if ctx.get("is_commons"):
                # a market GATHERS: wandering in the commons pulls toward
                # the square's centre, where the meetings are (6.2f's note)
                tx = tx * 0.4 + 0.5 * 0.6
                ty = ty * 0.4 + 0.5 * 0.6
            tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
            if pathmod.find_path(terrain, agent.x, agent.y, tx, ty) is not None:
                return _route_effects(agent, tx, ty, now, terrain,
                                      "explored",
                                      {"cell": list(cell_of(tx, ty)),
                                       "style": style},
                                      time_scale, pace)
        return Effects(schedule=("decide", now + 600.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "contribute_here":
        sites = {s["key"]: s for s in ctx.get("sites", [])}
        key = choice.target or payload.get("site_here")
        if key not in sites:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        s = sites[key]
        if (s["x"] - agent.x) ** 2 + (s["y"] - agent.y) ** 2 > REACH ** 2:
            # the moment passed and the agent stands elsewhere: walk back
            tx, ty = standoff(agent.x, agent.y, s["x"], s["y"])
            tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
            return _route_effects(agent, tx, ty, now, terrain,
                                  "decide", {}, time_scale, pace)
        return Effects(contribute=(key, dict(agent.cargo)),
                       schedule=("decide", now + 120.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "travel_to_site":
        from . import construction as _con
        cand = [s for s in ctx.get("sites", [])
                if not s.get("complete") and _con.accepts(s, agent.cargo)]
        if not cand:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        s = min(cand, key=lambda q: (q["x"] - agent.x) ** 2
                + (q["y"] - agent.y) ** 2)
        tx, ty = standoff(agent.x, agent.y, s["x"], s["y"])
        tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
        return _route_effects(agent, tx, ty, now, terrain,
                              "decide", {}, time_scale, pace)

    if choice.option == "board_ark":
        ark = ctx.get("boardable_ark")
        if ark and (ark["x"] - agent.x) ** 2 + (ark["y"] - agent.y) ** 2 \
                > REACH ** 2:
            tx, ty = standoff(agent.x, agent.y, ark["x"], ark["y"])
            tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
            return _route_effects(agent, tx, ty, now, terrain,
                                  "decide", {}, time_scale, pace)
        return Effects(board=payload.get("ark_key") or choice.target,
                       schedule=("decide", now + 3600.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "flee_to_ark":
        ark = ctx.get("boardable_ark")
        if not ark:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        tx, ty = standoff(agent.x, agent.y, ark["x"], ark["y"])
        tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
        return _route_effects(agent, tx, ty, now, terrain,
                              "decide", {}, time_scale, pace)

    if choice.option == "build_cache":
        return Effects(cache_op=("build", None),
                       schedule=("decide", now + 120.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option in ("stash_cache", "collect_cache"):
        key = payload.get("cache_here") or choice.target
        if not key:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        op = "stash" if choice.option == "stash_cache" else "collect"
        return Effects(cache_op=(op, key),
                       schedule=("decide", now + 120.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "trade_at_market":
        return Effects(market_turn=True,
                       schedule=("decide", now + 90.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "go_to_market":
        mkt = ctx.get("market")
        if not mkt:
            return Effects(schedule=("decide", now + 60.0,
                                     agent.agent_uuid, {}))
        tx, ty = standoff(agent.x, agent.y, mkt["x"], mkt["y"])
        tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
        return _route_effects(agent, tx, ty, now, terrain,
                              "decide", {}, time_scale, pace)

    if choice.option == "travel_to_portal":
        doors = [pt for pt in ctx.get("portals", []) if pt.get("to_world")]
        if not doors:
            return Effects(schedule=("decide", now + 600.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        pt = min(doors, key=lambda q: (q["x"] - agent.x) ** 2
                 + (q["y"] - agent.y) ** 2)
        tx, ty = standoff(agent.x, agent.y, pt["x"], pt["y"])
        return _route_effects(agent, tx, ty, now, terrain,
                              "decide", {}, time_scale, pace)

    if choice.option == "found_construction":
        from . import construction as _con
        cand = [n for n in (ctx.get("foundable") or payload.get("foundable")
                            or [])]
        if not cand:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        # mechanical resolution, not strategy (the travel_to_site precedent):
        # lowest tier first, preferring a bill the hold already serves;
        # plan items sort after the canonical tree
        cand.sort(key=lambda n: _con.TREE[n]["tier"]
                  if n in _con.TREE else 9)
        wk = [int(k) for k in (ctx.get("world_kinds") or [])]
        serving = [n for n in cand if n in _con.TREE
                   and any(k in _con.resolve_cost(n, wk) for k in agent.cargo)]
        return Effects(found=(serving or cand)[0],
                       schedule=("decide", now + 120.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "request_service":
        holders = ctx.get("known_remote_holders") or []
        if not holders:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        # mechanical resolution: the most recently met holder is asked
        who, skill = holders[-1]
        return Effects(service=("request", who, skill),
                       schedule=("decide", now + 600.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option in ("perform_service", "refuse_service"):
        verb = "perform" if choice.option == "perform_service" else "refuse"
        return Effects(service=(verb, payload.get("requester", ""),
                                payload.get("skill", "")),
                       schedule=("decide", now + 120.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "send_word":
        addr = ctx.get("addressable") or []
        if not addr:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        # mechanical resolution: the most recently met counterparty hears it
        return Effects(word=choice.target if choice.target in addr
                       else addr[-1],
                       schedule=("decide", now + 300.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "take_up_construction":
        sites = {s["key"]: s for s in ctx.get("sites", [])}
        key = payload.get("portable_here") or choice.target
        if key not in sites:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        s = sites[key]
        if (s["x"] - agent.x) ** 2 + (s["y"] - agent.y) ** 2 > REACH ** 2:
            tx, ty = standoff(agent.x, agent.y, s["x"], s["y"])
            tx, ty = separate(tx, ty, occupied, agent.agent_uuid)
            return _route_effects(agent, tx, ty, now, terrain,
                                  "decide", {}, time_scale, pace)
        return Effects(portage=("take_up", key),
                       schedule=("decide", now + 120.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "set_down_construction":
        key = payload.get("site_carried") or ctx.get("carrying_site") \
            or choice.target
        if not key:
            return Effects(schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        return Effects(portage=("set_down", key),
                       schedule=("decide", now + 60.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    if choice.option == "carry_to_portal":
        doors = [pt for pt in ctx.get("portals", []) if pt.get("to_world")]
        if not doors:
            return Effects(schedule=("decide", now + 600.0 / max(1.0, time_scale),
                                     agent.agent_uuid, {}))
        pt = min(doors, key=lambda q: (q["x"] - agent.x) ** 2
                 + (q["y"] - agent.y) ** 2)
        tx, ty = standoff(agent.x, agent.y, pt["x"], pt["y"])
        return _route_effects(agent, tx, ty, now, terrain,
                              "decide", {}, time_scale, pace)

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

    if choice.option in ("offer_trade", "propose_breeding", "attack",
                         "ignore", "offer_berth"):
        # resolution is pairwise and happens in the drain once BOTH have
        # answered; the engine only records intent
        return Effects(schedule=("encounter_answer", now, agent.agent_uuid,
                                 {"answer": choice.option,
                                  "other": payload.get("other", {})}))

    if choice.option == "wait":
        return Effects(schedule=("decide", now + 600.0 / max(1.0, time_scale),
                                 agent.agent_uuid, {}))

    raise ValueError(f"unknown option {choice.option!r}")


def on_deposit_arrival(agent: AgentView, stock: dict[str, float],
                       now: float,
                       ceiling: float = USER_CEILING_PER_KIND) -> Effects:
    """Deposit at the birth world, partially accepted at the user ceiling
    (genome-spec Rules 4.3, 4.15, 4.19) — raised by a standing Store
    (calibration §5). Remainder stays aboard."""
    accepted: dict[str, float] = {}
    delta: dict[str, float] = {}
    for kind, units in agent.cargo.items():
        room = ceiling - stock.get(kind, 0.0)
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
