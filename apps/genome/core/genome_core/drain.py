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

from . import combat, engine, forms, identity, notify, opinion, pathogen
from . import genotype as G
from . import worldgen
from .models import assign_models
from .genotype import BUDGETED, expressed, lifespan_days
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
    if payload.get("infections"):
        settled, events = pathogen.settle(payload, now)
        if events:
            await store.put_agent(agent_uuid, settled)
            payload = settled
            if payload.get("owner_user_id"):
                for e in events:
                    await notify.emit(store._c, payload["owner_user_id"],
                                      "agents", "recovery",
                                      f"{payload.get('name', agent_uuid)} "
                                      f"{e}; an antigen is retained.")
    view = engine.AgentView(
        agent_uuid, home_realm, world_realm, x, y, cargo,
        frozenset(payload.get("known_piles", [])),
        frozenset(tuple(c) for c in payload.get("explored", [])))
    return view, payload


async def _positions_of_others(store: GenomeStore, world_realm: str,
                               me_uuid: str, now: float) -> list:
    """Where everyone else in this world stands right now — closed-form from
    their latest movement, never stored. Feeds swarm style and separation."""
    out = []
    for v in await store.agents_in(world_realm):
        u = v.payload["key"]
        if u == me_uuid:
            continue
        mv = await store.latest_movement(u)
        if mv is None or "waypoints" not in mv.payload:
            continue
        pl = mv.payload
        r = forms.Route(tuple(tuple(q) for q in pl["waypoints"]),
                        pl["departed_at"])
        out.append(forms.route_position(r, now))
    return out


async def engine_ctx(store: GenomeStore, world_realm: str,
                     world_payload: dict, agent_payload: dict,
                     agent: engine.AgentView, pile_views: list,
                     now: float) -> dict:
    """Everything the engine's collision, muster and movement-style faculties
    need of the world, loaded once per decision."""
    neighbours = await _positions_of_others(store, world_realm,
                                            agent.agent_uuid, now)
    return {"genotype": agent_payload.get("genotype") or {},
            "neighbours": neighbours,
            "occupied": neighbours + [(pv.x, pv.y) for pv in pile_views],
            "muster": world_payload.get("muster_points", [])}


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


DECISION_QUEUE = "decision_queue"


async def enqueue_decision(store: GenomeStore, world_realm: str,
                           req: engine.DecisionRequest,
                           event_payload: dict, now: float) -> None:
    """system-spec Rule 8.4: the world queue never blocks on inference. The
    request carries everything the decision worker needs to decide AND apply."""
    import uuid as _u
    # One pending question per (agent, situation): at demo time-scales the
    # tick loop laps the decider and would otherwise queue the same situation
    # repeatedly -- observed live, 167 deep with fourfold duplicates, every
    # one an LLM call. The situation string is exact, so a genuinely new
    # context still queues.
    pending = await store._c.find_vertices(
        DECISION_QUEUE, realm="genome_agents",
        filters={"agent_uuid": req.agent_uuid,
                 "situation": req.situation}, limit=20)
    if any(v.payload.get("done_at") is None for v in pending):
        return
    await store._c.add_vertex(DECISION_QUEUE, realm="genome_agents",
        payload={"key": f"dq-{_u.uuid4().hex[:12]}",
                 "world_realm": world_realm,
                 "agent_uuid": req.agent_uuid,
                 "situation": req.situation,
                 "options": list(req.options),
                 "context": req.context,
                 "event_payload": event_payload,
                 "queued_at": _iso(now), "done_at": None})


async def apply_decided(store: GenomeStore, world_realm: str,
                        agent_uuid: str, choice: engine.Choice,
                        model: str, req_situation: str, req_options: list,
                        event_payload: dict, now: float) -> str:
    """The decision worker's half: record, apply, persist — the same
    persistence path the inline drain used, so behaviour is identical."""
    agent, agent_payload = await load_agent(store, world_realm, agent_uuid,
                                            world_realm, now)
    pile_rows = await store.piles_in(world_realm)
    piles_meta = {v.payload["key"]: v.payload for v in pile_rows}
    pile_views = [engine.PileView(
        k, m["kind"], m["x"], m["y"],
        forms.pile_quantity(forms.PileState(m["qty_at"],
                                            m.get("measured_at", 0.0),
                                            m["rate"], m["cap"]), now))
        for k, m in piles_meta.items()]
    world_payload = await _world_payload(store, world_realm)
    terrain = world_payload.get("terrain", [])
    await store.record_decision(agent_uuid, {
        "at": _iso(now), "situation": req_situation,
        "options": req_options, "choice": choice.option,
        "model": model, "tier": "economy" if model != "stub" else "stub"})
    ctx = await engine_ctx(store, world_realm, world_payload, agent_payload,
                           agent, pile_views, now)
    eff = engine.apply_choice(choice, agent, pile_views, now,
                              event_payload, terrain,
                              world_payload.get("time_scale", 1.0), ctx)
    await persist_effects(store, world_realm, agent, eff, piles_meta, now)
    if eff.transfer:
        await do_transfer(store, world_realm, agent, agent_payload,
                          eff.transfer, world_payload.get("portals", []), now)
    if eff.reveal or eff.mark_explored:
        kp = sorted(set(agent_payload.get("known_piles", [])) | set(eff.reveal))
        ex = sorted({tuple(c) for c in agent_payload.get("explored", [])}
                    | set(eff.mark_explored))
        await store.put_agent(agent_uuid,
                              {**agent_payload, "known_piles": kp,
                               "explored": [list(c) for c in ex]})
    return choice.option


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
    if world_payload.get("is_commons"):
        # Rule 6.2g: the commons shows each agent ONE portal -- back the way it
        # came. A market square, never a transit hub.
        entry = agent_payload.get("commons_entry_from")
        portals = ([{"x": 0.5, "y": 0.08, "to_world": entry,
                     "dest_xy": agent_payload.get("commons_entry_xy") or [0.5, 0.5],
                     "dest_colours": None}] if entry else [])
    stock = await get_stock(store, world_realm)

    if pl["kind"] == "perish":
        await store.complete_event(world_realm, pl["key"], _iso(now))
        return await regenerate(store, world_realm, agent, agent_payload, now,
                                cause=pl["payload"].get("cause", "longevity"))

    if pl["kind"] == "mating_answer":
        ans = pl["payload"]["answer"]
        proposer_uuid = pl["payload"]["proposer"]["agent_uuid"]
        await store.complete_event(world_realm, pl["key"], _iso(now))
        if ans != "accept_mate":
            return "mating:declined"
        p_view, p_pl = await load_agent(store, world_realm, proposer_uuid,
                                        world_realm, now)
        return await consummate(store, world_realm, agent, agent_payload,
                                p_view, p_pl, f"mate-{pl['key']}", now)

    if pl["kind"] == "encounter_answer":
        return await resolve_encounter(store, world_realm, agent,
                                       agent_payload, pl, now)

    if pl["kind"] == "deposit_arrival":
        eff = engine.on_deposit_arrival(agent, stock, now)
        outcome = "deposit"
    else:
        ctx = (await engine_ctx(store, world_realm, world_payload,
                                agent_payload, agent, pile_views, now)
               if pl["kind"] in ("arrival", "decide")
               else {"genotype": agent_payload.get("genotype") or {}})
        res = engine.on_event(pl["kind"], agent, pile_views, now,
                              pl.get("payload", {}), stock, portals, ctx)
        if isinstance(res, engine.DecisionRequest):
            if decider is None:                     # queue mode (Rule 8.4)
                merged_q = dict(pl.get("payload", {}))
                for k in ("portal_to", "portal_xy", "proposer", "other"):
                    if res.context.get(k):
                        merged_q[k] = res.context[k]
                await enqueue_decision(store, world_realm, res,
                                       merged_q, now)
                await store.complete_event(world_realm, pl["key"], _iso(now))
                return f"queued:{res.situation}"
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
                                      merged, terrain,
                                      world_payload.get("time_scale", 1.0),
                                      ctx)
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
    birth_meta = await _world_payload(store,
                                      agent_payload.get("home_realm",
                                                        origin_realm))
    ok, why = identity.accept_transfer(
        root_pub, origin_cert, agent_cert, assertion,
        int(agent_payload.get("transfer_counter", 0)),
        birth_world_cert=birth_meta.get("cert"))
    if not ok:
        return False
    # find the destination-side coordinates from the origin portal record
    dest_xy = None
    for pt in portals:
        if pt.get("to_world") == to_world:
            dest_xy = pt.get("dest_xy")
            break
    dest_xy = dest_xy or [0.5, 0.5]
    # A crossing interrupts the life left behind: pending events in the
    # origin realm and undecided queue items for this agent are void -- they
    # reference a world the agent is no longer in. Observed live: stale
    # home-world decisions marching a commons visitor off to phantom piles.
    for ev in await store._c.get_vertices("events", realm=origin_realm):
        p = ev.payload
        if p.get("subject") == agent.agent_uuid and p.get("done_at") is None \
                and p.get("kind") != "perish":
            await store._c.upsert_vertex("events", realm=origin_realm,
                vertex_id=int(ev.id),
                payload={**p, "done_at": _iso(now), "voided": "transfer"})
    for it in await store._c.get_vertices("decision_queue",
                                          realm="genome_agents"):
        p = it.payload
        if p.get("agent_uuid") == agent.agent_uuid \
                and p.get("done_at") is None:
            await store._c.upsert_vertex("decision_queue",
                realm="genome_agents", vertex_id=int(it.id),
                payload={**p, "done_at": _iso(now), "outcome": "voided:transfer"})
    await store.set_presence(origin_realm, agent.agent_uuid, False)
    await store.set_presence(to_world, agent.agent_uuid, True)
    await store.set_movement(agent.agent_uuid,
                             {"waypoints": [dest_xy], "departed_at": now,
                              "arrives_at": now, "cargo": agent.cargo})
    # pathogen genesis BEFORE the persist (an earlier draft rolled after the
    # write, computing infections that were never saved): rolled independently
    # at BOTH ends; the traveller is patient zero
    for end, realm_name in (("origin", origin_realm), ("dest", to_world)):
        r_meta = await _world_payload(store, realm_name)
        existing = r_meta.get("strains", [])
        strain = pathogen.roll_teleport_strain(
            f"{agent.agent_uuid}:{counter}:{end}", existing)
        if strain:
            await store.put_world(realm_name,
                {**r_meta, "strains": existing + [strain]})
            agent_payload = pathogen.infect(agent_payload, strain, now)
            if agent_payload.get("owner_user_id"):
                await notify.emit(store._c, agent_payload["owner_user_id"],
                                  "agents", "infection",
                                  f"{agent_payload.get('name')} caught "
                                  f"{strain['strain_uuid']} at the {end} portal.")
    await store.put_agent(agent.agent_uuid,
                          {**agent_payload, "transfer_counter": counter,
                           "last_transfer": assertion["doc"]})
    if dest_meta.get("is_commons"):
        # remember the way in (Rule 6.2g); the portal position it used is the
        # return destination
        entry_xy = None
        for pt in portals:
            if pt.get("to_world") == to_world:
                entry_xy = [pt["x"], pt["y"]]
                break
        await store.put_agent(agent.agent_uuid,
                              {**agent_payload, "transfer_counter": counter,
                               "commons_entry_from": origin_realm,
                               "commons_entry_xy": entry_xy})
    dest_owner = dest_meta.get("owner_user_id")
    if dest_owner:
        await notify.emit(store._c, dest_owner, "world", "arrival",
                          f"{agent_payload.get('name', agent.agent_uuid)} "
                          f"arrived in your world from {origin_realm}.")
    if agent_payload.get("owner_user_id"):
        await notify.emit(store._c, agent_payload["owner_user_id"], "agents",
                          "teleport",
                          f"{agent_payload.get('name')} crossed to {to_world}.")
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
        # stamina bookkeeping (Rules 9.3b/3.8c); zero MAXIMUM perishes (3.8d)
        win_p = att_p if res["winner"] == att_v.agent_uuid else dfd_p
        new_max = win_p.get("stamina_max", 1.0) - res["winner_max_burn"]
        await store.put_agent(res["winner"],
                              {**win_p, "stamina_max": max(0.0, new_max),
                               "victories": win_p.get("victories", 0) + 1})
        if new_max <= 0.0:
            home = win_p.get("home_realm", world_realm)
            await store.schedule(home, f"burnout-{res['winner']}-{int(now)}",
                                 _iso(now), "perish", res["winner"],
                                 {"cause": "attrition"})
        await store.record_decision(att_uuid, {"at": _iso(now),
            "situation": "combat", "options": [], "choice": "resolved",
            "model": "arithmetic", "tier": "computed", "result": res})
        for pl_side, other_name in ((att_p, dfd_p.get("name")),
                                    (dfd_p, att_p.get("name"))):
            if pl_side.get("owner_user_id"):
                won = pl_side.get("name") and res["winner"] in (
                    att_v.agent_uuid, dfd_v.agent_uuid)
                await notify.emit(store._c, pl_side["owner_user_id"], "agents",
                                  "combat",
                                  f"{pl_side.get('name')} fought "
                                  f"{other_name}; winner: {res['winner']}.")
        outcome = f"combat:{res['winner']}_wins"
    elif a_ans == "propose_breeding" and b_ans == "propose_breeding":
        outcome = await consummate(store, world_realm, agent, agent_payload,
                                   other_view, other_payload, pair_key, now)
    elif "propose_breeding" in (a_ans, b_ans):
        # one-sided proposal: agreement is proposal + ACCEPTANCE (Rule 9.4),
        # and acceptance is the recipient's own Selectivity decision (6.3)
        proposer = me if a_ans == "propose_breeding" else other_uuid
        recipient = other_uuid if proposer == me else me
        prop_pl = agent_payload if proposer == me else other_payload
        recip_pl = other_payload if proposer == me else agent_payload
        await store.schedule(world_realm, f"prop-{pair_key}", _iso(now + 30.0),
                             "mating_proposal", recipient,
                             {"proposer": {"agent_uuid": proposer,
                                           "colour_pair": prop_pl.get("colour_pair")},
                              "opinion": (recip_pl.get("opinions", {})
                                          .get(proposer))})
        outcome = "mating:proposed"
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
        rows = await store._c.find_vertices("agents", realm="genome_agents",
                                            filters={"key": child_uuid}, limit=1)
        await schedule_perish(store, child_uuid, rows[0].payload, now)
        born.append((child_uuid, name, home))
        for side in (parent_pl, mate_pl):
            if side.get("owner_user_id"):
                await notify.emit(store._c, side["owner_user_id"], "agents",
                                  "birth",
                                  f"{name} was born to "
                                  f"{parent_pl.get('name')} and "
                                  f"{mate_pl.get('name')}, home {home}.")
        await store.record_decision(child_uuid, {
            "at": _iso(now), "situation": "birth", "options": [],
            "choice": "born", "model": "arithmetic", "tier": "computed",
            "parents": [a_view.agent_uuid, b_view.agent_uuid],
            "identity": ident})
    return "breeding:" + ";".join(f"{n} -> {h}" for _, n, h in born)


def lifespan_seconds(genotype: dict) -> float:
    """Longevity's expressed value maps to 20-90 real days (calibration 3.0)."""
    b = len(BUDGETED) / 2.0
    return lifespan_days(expressed(genotype)["Longevity"], b) * 86400.0


async def schedule_perish(store: GenomeStore, agent_uuid: str,
                          agent_payload: dict, now: float) -> float:
    """Rule 7.2's clock starts at (re)birth. Perish is scheduled in the HOME
    realm -- death finds an agent wherever it stands, but the home world keeps
    the appointment."""
    due = now + lifespan_seconds(agent_payload["genotype"])
    home = agent_payload.get("home_realm")
    await store.schedule(home, f"perish-{agent_uuid}-{int(due)}", _iso(due),
                         "perish", agent_uuid, {"cause": "longevity"})
    await store.put_agent(agent_uuid, {**agent_payload, "perishes_at": due})
    return due


async def regenerate(store: GenomeStore, event_realm: str,
                     agent: engine.AgentView, agent_payload: dict,
                     now: float, cause: str) -> str:
    """Rules 7.2/7.3/6.15: death is never terminal and never gentle. The
    genotype, identity, certificate, name and model assignment survive
    (6.15/10.3); everything EARNED is lost -- cargo, the map, opinions,
    victories and their Attrition scars, age itself. The agent wakes at home,
    newborn in an old skin."""
    a = agent.agent_uuid
    home = agent_payload.get("home_realm", event_realm)
    # vanish from wherever it stood; wake at home (7.2)
    for realm in {event_realm, agent_payload.get("realm", event_realm), home}:
        try:
            await store.set_presence(realm, a, realm == home)
        except Exception:
            pass
    await store.set_presence(home, a, True)
    reborn = {**agent_payload,
              "known_piles": [], "explored": [], "opinions": {},
              "victories": 0, "stamina": 1.0, "stamina_max": 1.0,
              "born_at": now, "infections": [], "antigens": []}
    reborn.pop("perishes_at", None)
    await store.put_agent(a, reborn)
    await store.set_movement(a, {"waypoints": [[engine.HOME_XY[0],
                                                engine.HOME_XY[1]]],
                                 "departed_at": now, "arrives_at": now,
                                 "cargo": {}})
    await store.record_decision(a, {
        "at": _iso(now), "situation": "death", "options": [],
        "choice": f"regenerated({cause})", "model": "arithmetic",
        "tier": "computed"})
    if agent_payload.get("owner_user_id"):
        await notify.emit(store._c, agent_payload["owner_user_id"], "agents",
                          "agent_perished",
                          f"{agent_payload.get('name', a)} perished "
                          f"({cause}) and woke at home, its earned life lost.")
    due = await schedule_perish(store, a, reborn, now)
    await store.schedule(home, f"rebirth-{a}-{int(now)}", _iso(now + 60.0),
                         "decide", a, {})
    return f"regenerated:{cause}"
