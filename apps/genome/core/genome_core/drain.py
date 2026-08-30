"""The store-backed drain: one due event in, effects persisted, next event
scheduled. This is the tick worker's inner loop and the in-cluster smoke's
engine — the same code path, so the smoke proves the worker.

system-spec Rule 8.4: nothing here calls a model. A decision that needs one is
resolved by the injected decider — the stub in Phase 1, a queue handoff to the
kagent casts in Phase 2.
"""
from __future__ import annotations

import json
import uuid as uuidlib

from . import combat, engine, forms, identity, opinion
from . import genotype as G
from . import worldgen
from .models import assign_models
from .store import GenomeStore


def _iso(t: float) -> str:
    # virtual-clock ISO: fixed-width seconds since epoch sorts lexically,
    # matching due_events' string comparison
    return f"{t:020.3f}"


def from_iso(s: str) -> float:
    return float(s)


async def load_agent(store: GenomeStore, world_realm: str, agent_uuid: str,
                     home_realm: str, now: float) -> tuple[engine.AgentView, dict]:
    """View + the agent's stored payload (genotype, knowledge). Position is
    derived from the latest movement intent and the clock — never stored
    (execution-spec Rule 2.2)."""
    rows = await store._c.find_vertices("agents", realm="genome_agents",
                                        filters={"key": agent_uuid}, limit=1)
    payload = rows[0].payload if rows else {}
    latest = await store.latest_movement(agent_uuid)
    cargo: dict[str, float] = {}
    x, y = engine.HOME_XY
    if latest is not None:
        pl = latest.payload
        cargo = pl.get("cargo", {})
        if "waypoints" in pl:
            r = forms.Route(tuple(tuple(q) for q in pl["waypoints"]),
                            pl["departed_at"])
            x, y = forms.route_position(r, now)
    view = engine.AgentView(
        agent_uuid, home_realm, world_realm, x, y, cargo,
        frozenset(payload.get("known_piles", [])),
        frozenset(tuple(c) for c in payload.get("explored", [])))
    return view, payload


async def persist_effects(store: GenomeStore, world_realm: str,
                          agent: engine.AgentView, eff: engine.Effects,
                          piles_meta: dict, now: float) -> None:
    if eff.movement:
        await store.set_movement(agent.agent_uuid,
                                 {**eff.movement, "cargo": agent.cargo})
    if eff.mine_pile:
        pile_uuid, want = eff.mine_pile
        m = piles_meta[pile_uuid]
        p = forms.PileState(m["qty_at"], m.get("measured_at", 0.0), m["rate"], m["cap"])
        p2, _taken = forms.mine(p, now, want)
        await store.put_pile(world_realm, pile_uuid,
                             {**m, "qty_at": p2.qty_at, "measured_at": now})
    if eff.cargo_delta:
        cargo = dict(agent.cargo)
        for kind, d in eff.cargo_delta.items():
            cargo[kind] = cargo.get(kind, 0.0) + d
            if cargo[kind] <= 1e-9:
                del cargo[kind]
        # cargo rides on the movement history record (append-only)
        await store.set_movement(agent.agent_uuid,
                                 {"waypoints": [[agent.x, agent.y]],
                                  "departed_at": now, "arrives_at": now,
                                  "cargo": cargo})
    if eff.deposit:
        await _bump_stock(store, world_realm, eff.deposit)   # stock on world_meta
    if eff.schedule:
        kind, due, subject, payload = eff.schedule
        await store.schedule(world_realm, f"ev-{uuidlib.uuid4().hex[:10]}",
                             _iso(due), kind, subject, payload)


async def _bump_stock(store: GenomeStore, world_realm: str,
                      accepted: dict[str, float]) -> None:
    rows = await store._c.find_vertices("world_meta", realm=world_realm,
                                        filters={"key": world_realm}, limit=1)
    payload = rows[0].payload if rows else {"key": world_realm}
    stock = payload.get("stock", {})
    for kind, units in accepted.items():
        stock[kind] = stock.get(kind, 0.0) + units
    await store.put_world(world_realm, {**payload, "stock": stock})


async def get_stock(store: GenomeStore, world_realm: str) -> dict:
    rows = await store._c.find_vertices("world_meta", realm=world_realm,
                                        filters={"key": world_realm}, limit=1)
    return (rows[0].payload.get("stock", {}) if rows else {})


async def drain_one(store: GenomeStore, world_realm: str, home_realm: str,
                    ev, decider, seed: int) -> str:
    """Process one due event vertex. Returns the choice or event kind."""
    pl = ev.payload
    now = from_iso(pl["due_at"])
    agent_uuid = pl["subject"]
    agent, agent_payload = await load_agent(store, world_realm, agent_uuid,
                                            home_realm, now)
    pile_rows = await store.piles_in(world_realm)
    piles_meta = {v.payload["key"]: v.payload for v in pile_rows}
    pile_views = [engine.PileView(
        k, m["kind"], m["x"], m["y"],
        forms.pile_quantity(forms.PileState(m["qty_at"], m.get("measured_at", 0.0),
                                            m["rate"], m["cap"]), now))
        for k, m in piles_meta.items()]
    world_payload = await _world_payload(store, world_realm)
    terrain = world_payload.get("terrain", [])
    portals = world_payload.get("portals", [])
    stock = await get_stock(store, world_realm)

    if pl["kind"] == "encounter_answer":
        return await resolve_encounter(store, world_realm, agent,
                                       agent_payload, pl, now)

    if pl["kind"] == "deposit_arrival":
        eff = engine.on_deposit_arrival(agent, stock, now)
        outcome = "deposit"
    else:
        res = engine.on_event(pl["kind"], agent, pile_views, now,
                              pl.get("payload", {}), stock, portals)
        if isinstance(res, engine.DecisionRequest):
            decided = decider(res, agent_payload, seed)
            # a decider may return (Choice, model_name) or a bare Choice
            choice, model = decided if isinstance(decided, tuple) \
                else (decided, "stub")
            await store.record_decision(agent_uuid, {
                "at": pl["due_at"], "situation": res.situation,
                "options": list(res.options), "choice": choice.option,
                "model": model, "tier": "economy" if model != "stub" else "stub"})
            merged = dict(pl.get("payload", {}))
            for k in ("portal_to", "portal_xy"):
                if res.context.get(k):
                    merged[k] = res.context[k]
            eff = engine.apply_choice(choice, agent, pile_views, now,
                                      merged, terrain)
            outcome = choice.option
        else:
            eff = res
            outcome = pl["kind"]
    await persist_effects(store, world_realm, agent, eff, piles_meta, now)
    if eff.transfer:
        await do_transfer(store, world_realm, agent, agent_payload,
                          eff.transfer, portals, now)
    if eff.reveal or eff.mark_explored:      # knowledge grows on the agent
        kp = sorted(set(agent_payload.get("known_piles", [])) | set(eff.reveal))
        ex = sorted({tuple(c) for c in agent_payload.get("explored", [])}
                    | set(eff.mark_explored))
        await store.put_agent(agent.agent_uuid,
                              {**agent_payload, "known_piles": kp,
                               "explored": [list(c) for c in ex]})
    await store.complete_event(world_realm, ev.payload["key"], _iso(now))
    return outcome


async def _world_payload(store: GenomeStore, world_realm: str) -> dict:
    rows = await store._c.find_vertices("world_meta", realm=world_realm,
                                        filters={"key": world_realm}, limit=1)
    return rows[0].payload if rows else {}


async def do_transfer(store: GenomeStore, origin_realm: str,
                      agent: engine.AgentView, agent_payload: dict,
                      transfer: dict, portals: list[dict], now: float) -> bool:
    """Teleportation — genome-spec §6. The ORIGIN world signs an assertion; the
    destination verifies chain + signature + fresh counter before admitting
    (Rules 6.9-6.12). Passage is instantaneous (Rule 6.1a): presence flips and
    the agent stands at the destination portal.
    """
    to_world = transfer["to_world"]
    origin_meta = await _world_payload(store, origin_realm)
    dest_meta = await _world_payload(store, to_world)
    root_pub = origin_meta.get("root_public_pem", "").encode()
    origin_cert = origin_meta.get("cert")
    agent_cert = agent_payload.get("cert")
    if not (root_pub and origin_cert and agent_cert):
        return False                       # unsigned worlds cannot emigrate
    counter = int(agent_payload.get("transfer_counter", 0)) + 1
    assertion = identity.make_transfer(origin_cert, agent_cert, counter, to_world)
    ok, why = identity.accept_transfer(
        root_pub, origin_cert, agent_cert, assertion,
        int(agent_payload.get("transfer_counter", 0)))
    if not ok:
        return False
    # find the destination-side coordinates from the origin portal record
    dest_xy = None
    for pt in portals:
        if pt.get("to_world") == to_world:
            dest_xy = pt.get("dest_xy")
            break
    dest_xy = dest_xy or [0.5, 0.5]
    await store.set_presence(origin_realm, agent.agent_uuid, False)
    await store.set_presence(to_world, agent.agent_uuid, True)
    await store.set_movement(agent.agent_uuid,
                             {"waypoints": [dest_xy], "departed_at": now,
                              "arrives_at": now, "cargo": agent.cargo})
    await store.put_agent(agent.agent_uuid,
                          {**agent_payload, "transfer_counter": counter,
                           "last_transfer": assertion["doc"]})
    return True


# ---------------- encounters (Phase 6 core) ----------------

async def resolve_encounter(store: GenomeStore, world_realm: str,
                            agent: engine.AgentView, agent_payload: dict,
                            pl: dict, now: float) -> str:
    """Both parties answered independently; the pair resolves once, keyed by
    the sorted uuids. Trade needs BOTH; one attack suffices (Rule 9.3);
    outcomes become opinion evidence via the surprise update (Rule 6.10a)."""
    me = agent.agent_uuid
    other_uuid = pl["payload"]["other"]["agent_uuid"]
    my_answer = pl["payload"]["answer"]
    pair = "|".join(sorted((me, other_uuid)))
    # store my answer on a pair vertex; second writer resolves
    pair_key = f"enc-{pair}-{pl['payload'].get('round', 0)}"
    rows = await store._c.find_vertices("events", realm=world_realm,
                                        filters={"key": pair_key}, limit=1)
    if not rows:
        await store._c.add_vertex("events", realm=world_realm,
                                  payload={"key": pair_key, "kind": "enc_state",
                                           "answers": {me: my_answer},
                                           "due_at": _iso(now), "done_at": _iso(now)})
        await store.complete_event(world_realm, pl["key"], _iso(now))
        return f"encounter_wait({my_answer})"
    state = rows[0].payload
    answers = {**state.get("answers", {}), me: my_answer}
    await store._c.upsert_vertex("events", realm=world_realm,
                                 vertex_id=int(rows[0].id),
                                 payload={**state, "answers": answers})
    if len(answers) < 2:
        await store.complete_event(world_realm, pl["key"], _iso(now))
        return f"encounter_wait({my_answer})"

    a_ans, b_ans = answers.get(me), answers.get(other_uuid)
    _, other_payload = await load_agent(store, world_realm, other_uuid,
                                        world_realm, now)
    other_view, _ = await load_agent(store, world_realm, other_uuid,
                                     world_realm, now)
    outcome = "pass"
    if "attack" in (a_ans, b_ans):
        att_uuid = me if a_ans == "attack" else other_uuid
        att_v, att_p = (agent, agent_payload) if att_uuid == me \
            else (other_view, other_payload)
        dfd_v, dfd_p = (other_view, other_payload) if att_uuid == me \
            else (agent, agent_payload)
        f_att = combat.Fighter(att_v.agent_uuid, att_p["genotype"],
                               att_p.get("stamina", 1.0),
                               att_p.get("stamina_max", 1.0), att_v.cargo)
        f_dfd = combat.Fighter(dfd_v.agent_uuid, dfd_p["genotype"],
                               dfd_p.get("stamina", 1.0),
                               dfd_p.get("stamina_max", 1.0), dfd_v.cargo)
        res = combat.resolve(f_att, f_dfd, seed=pair_key)
        # spoils move winner-ward; movement records carry cargo
        win_v = att_v if res["winner"] == att_v.agent_uuid else dfd_v
        lose_v = dfd_v if win_v is att_v else att_v
        if res["spoils"]:
            wc = dict(win_v.cargo); lc = dict(lose_v.cargo)
            for k, u in res["spoils"].items():
                wc[k] = wc.get(k, 0.0) + u
                lc[k] = lc.get(k, 0.0) - u
                if lc[k] <= 1e-9: del lc[k]
            for v, cargo in ((win_v, wc), (lose_v, lc)):
                await store.set_movement(v.agent_uuid,
                    {"waypoints": [[v.x, v.y]], "departed_at": now,
                     "arrives_at": now, "cargo": cargo})
        # the defender LEARNED something (Rule 6.10a): the attacker's
        # Aggression, updated by surprise against its prior estimate
        victim_p = dfd_p if att_uuid != dfd_v.agent_uuid else att_p
        est = (dfd_p.get("opinions", {}).get(att_uuid, {})
               .get("Aggression", {"estimate": 5000.0, "weight": 0.0}))
        op = opinion.Opinion(est["estimate"], est["weight"])
        op2 = opinion.update_event(op, acted_high=True, theta=5000.0, k=0.15)
        ops = dict(dfd_p.get("opinions", {}))
        ops.setdefault(att_uuid, {})["Aggression"] = \
            {"estimate": op2.estimate, "weight": op2.weight}
        await store.put_agent(dfd_v.agent_uuid, {**dfd_p, "opinions": ops})
        await store.record_decision(att_uuid, {"at": _iso(now),
            "situation": "combat", "options": [], "choice": "resolved",
            "model": "arithmetic", "tier": "computed", "result": res})
        outcome = f"combat:{res['winner']}_wins"
    elif a_ans == "propose_breeding" and b_ans == "propose_breeding":
        outcome = await consummate(store, world_realm, agent, agent_payload,
                                   other_view, other_payload, pair_key, now)
    elif a_ans == "offer_trade" and b_ans == "offer_trade":
        # simplest exchange: one unit of each side's most-held kind, both ways,
        # ceilings respected (proper negotiation arrives with A2A turns)
        mine = max(agent.cargo, key=agent.cargo.get, default=None)
        theirs = max(other_view.cargo, key=other_view.cargo.get, default=None)
        if mine and theirs and mine != theirs:
            ac, oc = dict(agent.cargo), dict(other_view.cargo)
            ac[mine] -= 1.0; oc[mine] = oc.get(mine, 0.0) + 1.0
            oc[theirs] -= 1.0; ac[theirs] = ac.get(theirs, 0.0) + 1.0
            for v, cargo in ((agent, ac), (other_view, oc)):
                cargo = {k: u for k, u in cargo.items() if u > 1e-9}
                await store.set_movement(v.agent_uuid,
                    {"waypoints": [[v.x, v.y]], "departed_at": now,
                     "arrives_at": now, "cargo": cargo})
            outcome = "trade:1for1"
        else:
            outcome = "trade:nothing_to_exchange"
    # both resume their lives
    for u in (me, other_uuid):
        await store.schedule(world_realm, f"post-enc-{u}-{int(now)}",
                             _iso(now + 60.0), "decide", u, {})
    await store.complete_event(world_realm, pl["key"], _iso(now))
    return outcome


async def consummate(store: GenomeStore, world_realm: str,
                     a_view: engine.AgentView, a_pl: dict,
                     b_view: engine.AgentView, b_pl: dict,
                     pair_key: str, now: float) -> str:
    """Both agreed (Rule 9.4). Gender gates at consummation -- it was never
    visible (Rules 6.4-6.6): two agents may court and only now discover
    incompatibility. Cost: collectively 2 units of each of 4 distinct kinds.
    Two progeny, one per parent's user, each materialised and certified by its
    owning parent's HOME world (genome-spec §9.4 commentary)."""
    ga, gb = a_pl["genotype"], b_pl["genotype"]
    if G.gender_of(ga) == G.gender_of(gb):
        return "breeding:incompatible"
    spend = G.breeding_cost_met(a_view.cargo, b_view.cargo)
    if spend is None:
        return "breeding:cannot_afford"
    # spend the pool (two-phase in spirit: both debits in one drain op)
    ca, cb = dict(a_view.cargo), dict(b_view.cargo)
    for k, u in spend["a"].items():
        ca[k] -= u
        if ca[k] <= 1e-9: del ca[k]
    for k, u in spend["b"].items():
        cb[k] -= u
        if cb[k] <= 1e-9: del cb[k]
    for v, cargo in ((a_view, ca), (b_view, cb)):
        await store.set_movement(v.agent_uuid,
            {"waypoints": [[v.x, v.y]], "departed_at": now,
             "arrives_at": now, "cargo": cargo})

    born = []
    for parent_view, parent_pl, mate_pl in ((a_view, a_pl, b_pl),
                                            (b_view, b_pl, a_pl)):
        import uuid as _u
        child_uuid = f"agent-{_u.uuid4().hex[:10]}"
        seed = f"{pair_key}:{child_uuid}"
        cg = G.crossover(parent_pl["genotype"], mate_pl["genotype"], seed)
        home = parent_pl.get("home_realm", world_realm)
        home_meta = await _world_payload(store, home)
        ident = identity.identity_hash(cg, home, child_uuid)
        cert = None
        if home_meta.get("cert"):
            cert = identity.issue_agent_cert(home_meta["cert"], child_uuid, ident)
        name = G.child_name(parent_pl.get("name", "X Y Z"),
                            mate_pl.get("name", "X Y Z"),
                            seed, worldgen.FIRST_NAMES)
        # Rule 7.5: parental influence is exactly one objective
        inherited_obj = (parent_pl.get("objectives") or [None])[0]
        await store.put_agent(child_uuid, {
            "alive": True, "home_realm": home,
            "name": name,
            "parents": [a_view.agent_uuid, b_view.agent_uuid],
            "genotype": cg,
            "colour_pair": G.child_colours(
                parent_pl.get("colour_pair") or ["#888888"] * 2,
                mate_pl.get("colour_pair") or ["#888888"] * 2, seed),
            "identity": ident, "cert": cert, "transfer_counter": 0,
            "models": assign_models(child_uuid),
            "objectives": [inherited_obj] if inherited_obj else [],
            "known_piles": [], "explored": [],
        })
        await store.set_presence(home, child_uuid, True)
        await store.set_movement(child_uuid,
            {"waypoints": [[engine.HOME_XY[0], engine.HOME_XY[1]]],
             "departed_at": now, "arrives_at": now, "cargo": {}})
        await store.schedule(home, f"born-{child_uuid}", _iso(now + 60.0),
                             "decide", child_uuid, {})
        born.append((child_uuid, name, home))
        await store.record_decision(child_uuid, {
            "at": _iso(now), "situation": "birth", "options": [],
            "choice": "born", "model": "arithmetic", "tier": "computed",
            "parents": [a_view.agent_uuid, b_view.agent_uuid],
            "identity": ident})
    return "breeding:" + ";".join(f"{n} -> {h}" for _, n, h in born)
