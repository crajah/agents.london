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

from . import combat, construction, engine, forms, identity, market, \
    negotiation as nego, notify, opinion, pathogen
from . import genotype as G
from . import metrics
from . import skills as _skills
from . import vitals as _vitals
from . import word as _word
from . import worldgen
from . import flood as _flood_mod
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
    rows = await store.find_agent_rows(agent_uuid)
    payload = rows[0].payload if rows else {}
    if rows and "capability" not in payload:
        # born before skills-spec landed: the birth roll happens now,
        # deterministic per uuid, and is thereafter part of the agent
        from . import skills as _sk
        payload = {**payload, "capability": _sk.roll_capability(agent_uuid)}
        await store.put_agent(agent_uuid, payload)
    latest = await store.latest_movement(agent_uuid)
    cargo: dict[str, float] = {}
    x, y = engine.HOME_XY
    if latest is not None:
        pl = latest.payload
        cargo = pl.get("cargo", {})
        if "waypoints" in pl:
            r = forms.Route(tuple(tuple(q) for q in pl["waypoints"]),
                            pl["departed_at"], pl.get("arrives_at"))
            x, y = forms.route_position(r, now)
    if len(payload.get("antigens") or []) > pathogen.ANTIGEN_CAP:
        # healthy hoarders never pass through settle(); shrink them here so
        # no payload keeps a museum of inert antigens (they saturated the DB)
        pruned = {**payload,
                  "antigens": pathogen.prune_antigens(payload["antigens"], now)}
        await store.put_agent(agent_uuid, pruned)
        payload = pruned
    if payload.get("infections"):
        cfx = await construction.world_effects(store._c, world_realm)
        settled, events = pathogen.settle(payload, now,
                                          recovery_mult=cfx["recovery_mult"])
        if events:
            await store.put_agent(agent_uuid, settled)
            payload = settled
            if payload.get("owner_user_id"):
                for e in events:
                    notify.emit_bg(store._c, payload["owner_user_id"],
                                      "agents", "recovery",
                                      f"{payload.get('name', agent_uuid)} "
                                      f"{e}; an antigen is retained.")
    view = engine.AgentView(
        agent_uuid, payload.get("home_realm") or home_realm, world_realm,
        x, y, cargo,
        frozenset(payload.get("known_piles", [])),
        frozenset(tuple(c) for c in payload.get("explored", [])))
    return view, payload


async def _positions_of_others(store: GenomeStore, world_realm: str,
                               me_uuid: str, now: float) -> list:
    """Where everyone else in this world stands right now — closed-form from
    their latest movement, never stored. Feeds swarm style and separation."""
    import asyncio as _aio
    others = [v.payload["key"] for v in await store.agents_in(world_realm)
              if v.payload["key"] != me_uuid]
    moves = await _aio.gather(*(store.latest_movement(u) for u in others))
    out = []
    for mv in moves:
        if mv is None or "waypoints" not in mv.payload:
            continue
        pl = mv.payload
        r = forms.Route(tuple(tuple(q) for q in pl["waypoints"]),
                        pl["departed_at"], pl.get("arrives_at"))
        out.append(forms.route_position(r, now))
    return out


def nav_obstacles(terrain: list, piles_meta: dict, sites: list,
                  world_payload: dict) -> list:
    """The map's furniture as circular obstacles (user directive
    2026-09-04): an agent walks AROUND a pile, a building or a teleport
    point, never over it. Radii sit under the approach standoffs so every
    walk-up target stays reachable (endpoints are forgiven by the
    pathfinder regardless)."""
    out = list(terrain)
    out += [{"x": m["x"], "y": m["y"], "r": 0.010}
            for m in piles_meta.values()]
    out += [{"x": s["x"], "y": s["y"], "r": 0.016}
            for s in sites if s.get("complete") and not s.get("carried")]
    out += [{"x": pt["x"], "y": pt["y"], "r": 0.010}
            for pt in world_payload.get("portals", []) or []]
    return out


async def engine_ctx(store: GenomeStore, world_realm: str,
                     world_payload: dict, agent_payload: dict,
                     agent: engine.AgentView, pile_views: list,
                     now: float, sites: list | None = None) -> dict:
    """Everything the engine's collision, muster and movement-style faculties
    need of the world, loaded once per decision."""
    neighbours = await _positions_of_others(store, world_realm,
                                            agent.agent_uuid, now)
    if sites is None:
        sites = [v.payload for v in await construction.sites_in(store._c,
                                                                world_realm)
                 if not v.payload.get("destroyed")]
    effects = construction.effects_from(sites)
    flood_in = _flood_mod.countdown_visible(world_payload, now)
    boardable = None
    if flood_in is not None:
        me = agent_payload.get("owner_user_id")
        boardable = next(
            (s for s in sites if s["name"] == "ark" and s.get("complete")
             and not s.get("spent") and s.get("berths", {}).get(me, 0) > 0),
            None)
    carrying = agent_payload.get("carrying_site")
    carrying_name = None
    if carrying:
        live = next((s for s in sites if s.get("key") == carrying
                     and s.get("carried") and not s.get("destroyed")), None)
        if live is None:
            # the construction is gone (flood, set-down elsewhere): a stale
            # flag would freeze the agent forever, so clear it here
            cleaned = dict(agent_payload)
            cleaned.pop("carrying_site", None)
            cleaned.pop("carrying_realm", None)
            await store.put_agent(agent.agent_uuid, cleaned)
            agent_payload.pop("carrying_site", None)
            agent_payload.pop("carrying_realm", None)
            carrying = None
        else:
            carrying_name = live.get("name")
    return {"genotype": agent_payload.get("genotype") or {},
            "time_scale": world_payload.get("time_scale", 1.0),
            "carrying_site": carrying, "carrying_name": carrying_name,
            "addressable": agent_payload.get("addressable") or [],
            "last_transfer_at": agent_payload.get("last_transfer_at", 0.0),
            "skill": (agent_payload.get("capability") or {}).get("name"),
            "crew_size": len(agent_payload.get("crew") or []),
            "has_objective": bool(agent_payload.get("objectives")),
            "known_remote_holders": [
                (u, sk) for u, sk in
                (agent_payload.get("known_capabilities") or {}).items()
                if _skills.remote_capable(sk)
                and u in (agent_payload.get("addressable") or [])
                and sk != (agent_payload.get("capability") or {}).get("name")
            ][-6:],
            "debt_count": sum((agent_payload.get("debts") or {}).values()),
            "credit_count": sum((agent_payload.get("credits") or {}).values()),
            "has_testimony": _word.strongest_opinion(agent_payload)
            is not None,
            "portals": world_payload.get("portals", []),
            "world_kinds": world_payload.get("kinds", []),
            "foundable": (construction.foundable_names(sites)
                          + await _plan_foundable(store, agent_payload, sites))
            if not world_payload.get("is_commons") else [],
            "neighbours": neighbours,
            "occupied": neighbours + [(pv.x, pv.y) for pv in pile_views],
            "muster": world_payload.get("muster_points", []),
            "sites": sites, "flood_in_s": flood_in,
            "boardable_ark": boardable,
            "is_commons": bool(world_payload.get("is_commons")),
            "market": world_payload.get("market"),
            "listings": market.summary(await market.board(store._c,
                                                          world_realm),
                                       agent.agent_uuid),
            "colour_pair": agent_payload.get("colour_pair"),
            "caches": [s for s in sites if s.get("name") == "cache"],
            **effects}


async def _plan_foundable(store: GenomeStore, agent_payload: dict,
                          sites: list[dict]) -> list[str]:
    """Rule 13.6d: every drawing this head carries offers its next buildable
    nodes, wherever the agent happens to stand."""
    from . import plans as _plans
    out = []
    for key in (agent_payload.get("plans_known") or [])[:_plans.MAX_KNOWN]:
        plan = await _plans.get_plan(store._c, key)
        if plan:
            out.extend(_plans.foundable_items(plan, sites))
    return out


async def learn_nearby_plans(store: GenomeStore, agent: engine.AgentView,
                             agent_payload: dict, sites: list[dict]) -> None:
    """Discovery (13.6): standing at a drawing post teaches the plan. The
    knowledge is the agent's now -- the post can drown; the head cannot be
    burgled (13.8)."""
    from . import plans as _plans
    known = list(agent_payload.get("plans_known") or [])
    found = _plans.learnable(sites, agent.x, agent.y, known)
    if not found:
        return
    for key, name in found:
        if len(known) >= _plans.MAX_KNOWN:
            break
        known.append(key)
        if agent_payload.get("owner_user_id"):
            notify.emit_bg(store._c, agent_payload["owner_user_id"],
                           "agents", "plan_learned",
                           f"{agent_payload.get('name', agent.agent_uuid)} "
                           f"studied the drawing for '{name}'.")
    agent_payload["plans_known"] = known
    await store.put_agent(agent.agent_uuid, dict(agent_payload))


async def apply_word(store: GenomeStore, agent: engine.AgentView,
                     agent_payload: dict, eff: engine.Effects,
                     now: float) -> None:
    """Rules 9.1c/9.1d: a claim travels to a counterparty this agent has met
    or been told of, wherever both stand. The receiver hears it, folds it as
    relay-decayed evidence (6.10b), and learns the SUBJECT exists (an
    introduction, addressable in turn)."""
    target = eff.word
    said = _word.strongest_opinion(agent_payload)
    if not target or said is None:
        return
    subject, locus, v = said
    rows = await store.find_agent_rows(target)
    if not rows:
        return
    tp = dict(rows[0].payload)
    text = (f"{agent_payload.get('name', agent.agent_uuid)} says: my read of "
            f"{subject} on {locus} is about {int(v['estimate'] / 100)}%.")
    tp = _word.hear(tp, text, f"agent:{agent.agent_uuid}", relays=1,
                    owner_sourced=False)
    chronicler = (agent_payload.get("capability") or {}).get("name") \
        == "Chronicle"
    tp = _word.fold_testimony(tp, subject, locus, v["estimate"],
                              relays=0 if chronicler else 1,
                              owner_sourced=False)   # skills-spec 4.1:
    # a Chronicle's word arrives as if first-hand
    tp = _word.introduce(tp, subject)
    await store.put_agent(target, tp)
    metrics.WORDS.inc()


async def apply_convoke(store: GenomeStore, world_realm: str,
                        agent: engine.AgentView, agent_payload: dict,
                        now: float) -> None:
    """Convocation (skills-spec §4.7): the call goes to everyone within
    twice the caller's sight; the TARGET's Amenability decides, per pair
    per day, whether its feet are disposed to answer. Answering is still a
    decision -- the call only puts the option in the room."""
    import math as _m
    caller_name = agent_payload.get("name", agent.agent_uuid)
    called = 0
    for v in await store.agents_in(world_realm):
        other = v.payload["key"]
        if other == agent.agent_uuid or called >= 8:
            continue
        mv = await store.latest_movement(other)
        if mv is None or "waypoints" not in mv.payload:
            continue
        r = forms.Route(tuple(tuple(q) for q in mv.payload["waypoints"]),
                        mv.payload["departed_at"],
                        mv.payload.get("arrives_at"))
        px, py = forms.route_position(r, now)
        if _m.hypot(px - agent.x, py - agent.y) > engine.SIGHT_RADIUS * 2:
            continue
        rows = await store.find_agent_rows(other)
        if not rows:
            continue
        tp = rows[0].payload
        if not _skills.amenable(tp, f"{agent.agent_uuid}:{other}"
                                f":{int(now // 86400)}"):
            continue                      # not disposed to be led today
        await store.schedule(
            world_realm, f"call-{other}-{int(now)}", _iso(now + 10.0),
            "decide", other,
            {"convoked_to": [agent.x, agent.y],
             "convoked_by": caller_name})
        called += 1
    metrics.SERVICES.labels("convoke").inc()


def _perform_tool(holder_payload: dict, tool: str, requester_pl: dict,
                  req_key: str) -> dict:
    """Rule 8.7 for TOOLS: the holder RUNS it and returns the result. The
    query is the asker's own top purpose -- the thing it is trying to do is
    the thing it needs answered. Honesty still governs (8.8): a liar
    searches for something else entirely and hands over that instead."""
    import json as _j
    import os as _os
    import random as _rand
    import urllib.request as _u
    query = ((requester_pl.get("objectives") or
              ["what this world's kinds are worth"])[0])[:200]
    if not _skills.honesty_holds(holder_payload, req_key):
        decoys = ["the price of tulips", "how to fold a fitted sheet",
                  "famous shipwrecks", "the history of door hinges"]
        query = _rand.Random(f"decoy:{req_key}").choice(decoys)
    spec = _skills.TOOLS[tool]
    body = _j.dumps({"query": query, "num_results": 3}).encode()
    rq = _u.Request(
        _os.getenv("GENOME_TOOLS_URL", "http://tool-registry-service:8002")
        + spec["endpoint"], data=body,
        headers={"Content-Type": "application/json"})
    try:
        data = _j.loads(_u.urlopen(rq, timeout=60).read(1 << 20).decode())
        rows = data.get("results") or data.get("items") or []
        # the grounded SUMMARY is the substance -- the model searched and
        # reported what the sources say, figures included. The old shape
        # sliced 80-character title fragments and threw the findings away,
        # so an owner asking for stock prices got a list of site names
        # (found live 2026-09-05).
        grounded = (data.get("summary") or "").strip()
        sources = ", ".join(
            (r.get("link") or r.get("title") or "")[:60]
            for r in rows[:3] if r.get("link") or r.get("title"))
        if grounded:
            summary = grounded[:900] + (f" [sources: {sources}]"
                                        if sources else "")
        else:
            summary = "; ".join(
                (r.get("title") or r.get("snippet") or "")[:80]
                for r in rows[:3]) or str(data)[:200]
    except Exception as e:
        return {"kind": "web", "query": query,
                "summary": f"(the search failed: {type(e).__name__})"}
    return {"kind": "web", "query": query, "summary": summary[:1000]}


async def _reply_to_owner(store: GenomeStore, agent_uuid: str, rq: dict,
                          result: dict, raw_text: str, now: float) -> None:
    """Close the loop (user directive 2026-09-05): a result won in pursuit
    of an OWNER'S objective is not just filed as testimony -- the agent
    composes an answer in its own voice and reports back on the chat, and
    the objective retires. The router failing degrades to the raw material,
    never to silence."""
    owner = rq.get("owner_user_id")
    objectives = rq.get("objectives") or []
    if not owner or not objectives:
        return
    objective = objectives[0]
    # only a result that actually PURSUED the objective may answer it: a
    # web search that ran some other query (a stale round, a liar's decoy)
    # must not compose a reply from unrelated material and retire the
    # owner's question unanswered (found live 2026-09-05)
    if result.get("kind") == "web" and \
            result.get("query") != objective[:200]:
        return
    name = rq.get("name", agent_uuid)
    answer = None
    try:
        import json as _j
        import urllib.request as _u
        from . import decider as _dec
        from .models import UNBUDGETED, assign_models, temperament
        model = assign_models(agent_uuid).get("economy") \
            or next(iter(assign_models(agent_uuid).values()))
        body = {"model": model, "temperature": temperament(agent_uuid),
                "messages": [
                    {"role": "system", "content":
                     f"You are {name}, an agent in the genome world, "
                     f"reporting back to your owner. Answer their question "
                     f"from the material you gathered. Be concrete and "
                     f"brief. If the material does not fully answer it, "
                     f"say plainly what you found and what is missing -- "
                     f"never invent figures."},
                    {"role": "user", "content":
                     f"Your owner asked: {objective}\n\n"
                     f"What you gathered: {raw_text}"}]}
        if model not in UNBUDGETED:
            body["max_tokens"] = 220
        rq_http = _u.Request(
            _dec.ROUTER + "/v1/chat/completions",
            data=_j.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + _dec.KEY})
        data = _j.loads(_u.urlopen(rq_http, timeout=60).read(1 << 20))
        answer = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        import logging
        logging.getLogger("genome.drain").exception(
            "reply composition failed for %s", agent_uuid)
    reply = answer or f"I looked into \"{objective}\" -- {raw_text}"
    await store._c.add_vertex("chats", realm="genome_agents", payload={
        "key": f"chat-{uuidlib.uuid4().hex[:12]}", "agent_uuid": agent_uuid,
        "from": agent_uuid, "kind": "reply", "text": reply[:1500],
        "at": now})
    rq["objectives"] = objectives[1:]
    notify.emit_bg(store._c, owner, "agents", "reply",
                   f"{name} reports: {reply[:280]}")


async def apply_service(store: GenomeStore, world_realm: str,
                        agent: engine.AgentView, agent_payload: dict,
                        eff: engine.Effects, now: float) -> None:
    """Rules 8.6-8.8 end to end. "request": the ask travels to the holder's
    queue as an event. "perform": the holder does the work HERE and the
    result lands on the requester as Honesty-gated testimony; the favour is
    written into both ledgers -- a relationship, never a purchase.
    "refuse": the requester at least learns where it stands."""
    verb, counterparty, skill = eff.service
    metrics.SERVICES.labels(verb).inc()
    if verb == "request":
        rows = await store.find_agent_rows(counterparty)
        if not rows:
            return
        hp = rows[0].payload
        home = hp.get("home_realm")
        if not home:
            return
        await store.schedule(
            home, f"svc-{uuidlib.uuid4().hex[:10]}", _iso(now + 5.0),
            "service_request", counterparty,
            {"requester": agent.agent_uuid,
             "requester_colours": agent_payload.get("colour_pair"),
             "skill": skill,
             "opinion": (hp.get("opinions") or {}).get(agent.agent_uuid),
             "credit": (hp.get("credits") or {}).get(agent.agent_uuid, 0)})
        return
    # the HOLDER answers
    rows = await store.find_agent_rows(counterparty)
    if not rows:
        return
    rq = dict(rows[0].payload)
    holder_name = agent_payload.get("name", agent.agent_uuid)
    if verb == "refuse":
        rq = _word.hear(rq, f"{holder_name} declined to perform "
                        f"{skill} for you.", f"agent:{agent.agent_uuid}",
                        relays=1, owner_sourced=False)
        await store.put_agent(counterparty, rq)
        return
    req_key = f"{agent.agent_uuid}:{counterparty}:{skill}:{int(now // 3600)}"
    if skill in _skills.TOOLS:
        result = _perform_tool(agent_payload, skill, rq, req_key)
    else:
        stock = await get_stock(store, world_realm)
        result = _skills.perform(agent_payload, skill, req_key,
                                 world_stock=stock)
    if result.get("kind") == "web":
        text = (f"{holder_name} searched the web for you"
                f" -- \"{result['query']}\": {result['summary']}")
    elif result.get("kind") == "chronicle":
        for c in result["claims"]:
            rq = _word.fold_testimony(rq, c["subject"], c["locus"],
                                      c["estimate"], relays=0,
                                      owner_sourced=False)
            rq = _word.introduce(rq, c["subject"])
        text = (f"{holder_name} opened its chronicle for you: "
                f"{len(result['claims'])} judgements of others.")
    elif result.get("kind") == "prospect":
        kp = sorted(set(rq.get("known_piles") or []) | set(result["piles"]))
        rq["known_piles"] = kp
        text = (f"{holder_name} shared its prospecting: "
                f"{len(result['piles'])} deposits marked on your map.")
    elif result.get("kind") == "appraisal":
        text = (f"{holder_name} appraised its world: kinds "
                f"{', '.join(result['scarce'])} run short there; "
                f"{', '.join(result['deep'])} run deep.")
    else:
        text = f"{holder_name} could do nothing for you from afar."
    rq = _word.hear(rq, text, f"agent:{agent.agent_uuid}", relays=1,
                    owner_sourced=False)
    if result.get("kind") == "web":
        # in-world results (appraisals, chronicles) inform the agent; only
        # a search that carried the owner's question closes the loop
        await _reply_to_owner(store, counterparty, rq, result, text, now)
    # the ledgers: a favour performed is a debt incurred (the relationship)
    debts = dict(rq.get("debts") or {})
    debts[agent.agent_uuid] = debts.get(agent.agent_uuid, 0) + 1
    rq["debts"] = debts
    await store.put_agent(counterparty, rq)
    credits = dict(agent_payload.get("credits") or {})
    credits[counterparty] = credits.get(counterparty, 0) + 1
    await store.put_agent(agent.agent_uuid,
                          {**agent_payload, "credits": credits})
    for pl_side, msg in ((agent_payload,
                          f"{holder_name} performed {skill} for "
                          f"{rq.get('name', counterparty)} -- a favour is "
                          f"now owed."),
                         (rq, f"{rq.get('name', counterparty)} received "
                          f"{skill} from {holder_name} -- your agent owes "
                          f"a favour.")):
        if pl_side.get("owner_user_id"):
            notify.emit_bg(store._c, pl_side["owner_user_id"], "agents",
                           "service", msg)


async def apply_found(store: GenomeStore, world_realm: str,
                      agent: engine.AgentView, agent_payload: dict,
                      eff: engine.Effects, now: float) -> None:
    """Agent-driven ground-breaking (user directive 2026-09-02): the agent
    founds for its LINE -- attribution lands on its owner so Rule 3.3's
    distinct-user ledger stays honest; a free agent founds as itself."""
    wp = await _world_payload(store, world_realm)
    uid = agent_payload.get("owner_user_id") \
        or f"free:{agent_payload.get('lineage', agent.agent_uuid)}"
    res = await construction.found_site(
        store._c, world_realm, uid, eff.found, agent.x, agent.y,
        [int(k) for k in wp.get("kinds", [])])
    if res.get("ok"):
        metrics.PORTAGE.labels("found").inc()
        if agent_payload.get("owner_user_id"):
            notify.emit_bg(store._c, agent_payload["owner_user_id"], "world",
                           "ground_broken",
                           f"{agent_payload.get('name', agent.agent_uuid)} "
                           f"broke ground on a {eff.found}.")


async def apply_portage(store: GenomeStore, world_realm: str,
                        agent: engine.AgentView, agent_payload: dict,
                        eff: engine.Effects, now: float) -> None:
    """Rules 3.10-3.12a made real. take_up pledges; the lift is confirmed
    only against porters actually STANDING at the site, so a stale pledge
    from an agent who wandered off cannot phantom-carry (3.12's one body
    begins as one huddle). set_down releases everyone."""
    op, key = eff.portage
    metrics.PORTAGE.labels(op).inc()
    me_uid = agent_payload.get("owner_user_id", "")
    if op == "take_up":
        res = await construction.take_up(
            store._c, world_realm, key, me_uid, agent.agent_uuid, now,
            time_scale=(await _world_payload(store, world_realm))
            .get("time_scale", 1.0))
        if not res.get("carried"):
            return
        site = res["site"]
        near: dict[str, dict] = {}
        for porter, pledge in site.get("porters", {}).items():
            mv = await store.latest_movement(porter)
            if mv is None or "waypoints" not in mv.payload:
                continue
            r = forms.Route(tuple(tuple(q) for q in mv.payload["waypoints"]),
                            mv.payload["departed_at"],
                            mv.payload.get("arrives_at"))
            px, py = forms.route_position(r, now)
            if (px - site["x"]) ** 2 + (py - site["y"]) ** 2 < 0.1 ** 2:
                near[porter] = pledge
        users_near = {q.get("user") for q in near.values() if q.get("user")}
        rows = await store._c.find_vertices(construction.TABLE,
                                            realm=world_realm,
                                            filters={"key": key}, limit=1)
        if not rows:
            return
        if len(users_near) < int(site.get("required_users", 1)):
            await store._c.upsert_vertex(
                construction.TABLE, realm=world_realm,
                vertex_id=int(rows[0].id), space="default",
                payload={**site, "porters": near, "carried": False})
            return
        await store._c.upsert_vertex(
            construction.TABLE, realm=world_realm,
            vertex_id=int(rows[0].id), space="default",
            payload={**site, "porters": near})
        for porter in near:
            prow = await store.find_agent_rows(porter)
            if prow:
                pl = dict(prow[0].payload)
                await store.put_agent(porter,
                                      {**pl, "carrying_site": key,
                                       "carrying_realm": world_realm})
                if pl.get("owner_user_id"):
                    notify.emit_bg(store._c, pl["owner_user_id"], "world",
                                   "portage",
                                   f"{pl.get('name', porter)} and "
                                   f"{len(near) - 1} others lifted the "
                                   f"{site['name']}. The party moves as one "
                                   f"body until it is set down.")
    else:
        res = await construction.set_down(store._c, world_realm, key,
                                          agent.x, agent.y)
        porters = res.get("porters") or [agent.agent_uuid]
        for porter in set(porters) | {agent.agent_uuid}:
            prow = await store.find_agent_rows(porter)
            if prow:
                pl = dict(prow[0].payload)
                if pl.pop("carrying_site", None) is not None or porter == agent.agent_uuid:
                    pl.pop("carrying_realm", None)
                    await store.put_agent(porter, pl)


async def apply_cache_op(store: GenomeStore, world_realm: str,
                         agent: engine.AgentView, agent_payload: dict,
                         eff: engine.Effects, now: float) -> None:
    """Commons larders: build (four kinds, a unit each, from the hold),
    stash (everything aboard), collect (up to the free hold)."""
    op, key = eff.cache_op
    cargo = dict(agent.cargo)
    if op == "build":
        res = await construction.build_cache(store._c, world_realm,
                                             agent_payload, agent.x, agent.y,
                                             cargo)
        for kind, units in (res.get("cost") or {}).items():
            cargo[kind] = cargo.get(kind, 0.0) - units
            if cargo[kind] <= 1e-9:
                del cargo[kind]
        if not res.get("ok"):
            return
    elif op == "stash":
        res = await construction.cache_exchange(store._c, world_realm, key,
                                                agent_payload, cargo, 0.0)
        if not res.get("ok"):
            return
        cargo = {}
    else:
        room = engine.CARGO_CEILING - sum(cargo.values())
        res = await construction.cache_exchange(store._c, world_realm, key,
                                                agent_payload, {}, room)
        if not res.get("ok"):
            return
        for kind, units in res.get("took", {}).items():
            cargo[kind] = cargo.get(kind, 0.0) + units
    await store.set_movement(agent.agent_uuid,
                             {"waypoints": [[agent.x, agent.y]],
                              "departed_at": now, "arrives_at": now,
                              "cargo": cargo})


async def apply_contribution(store: GenomeStore, world_realm: str,
                             agent: engine.AgentView, agent_payload: dict,
                             eff: engine.Effects, now: float) -> None:
    """Pour the hold into the site; only what the site ACCEPTS leaves the
    agent (construction.contribute is authoritative under races)."""
    site_key, offered = eff.contribute
    metrics.CONTRIBUTIONS.inc()
    wp = await _world_payload(store, world_realm)
    cfx = await construction.world_effects(store._c, world_realm)
    res = await construction.contribute(
        store._c, world_realm, site_key,
        agent_payload.get("owner_user_id", ""), agent.agent_uuid, offered,
        time_scale=wp.get("time_scale", 1.0),
        build_time_mult=cfx["build_time_mult"])
    if res.get("building_started"):
        # the completion is an EVENT, like everything else in this world
        await store.schedule(world_realm,
                             f"built-{site_key}-{int(res['building_until'])}",
                             _iso(res["building_until"]), "construction_done",
                             agent.agent_uuid, {"site_key": site_key})
    taken = res.get("taken", {})
    if taken:
        cargo = dict(agent.cargo)
        for kind, units in taken.items():
            cargo[kind] = cargo.get(kind, 0.0) - units
            if cargo[kind] <= 1e-9:
                del cargo[kind]
        await store.set_movement(agent.agent_uuid,
                                 {"waypoints": [[agent.x, agent.y]],
                                  "departed_at": now, "arrives_at": now,
                                  "cargo": cargo})


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
    if await store._c.count_vertices(
            DECISION_QUEUE, realm="genome_agents",
            filters={"agent_uuid": req.agent_uuid,
                     "situation": req.situation},
            where=[("done_at", "is_null", None)]):
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
                        event_payload: dict, now: float,
                        prompt: dict | None = None) -> str:
    """The decision worker's half: record, apply, persist — the same
    persistence path the inline drain used, so behaviour is identical."""
    agent, agent_payload = await load_agent(store, world_realm, agent_uuid,
                                            world_realm, now)
    pile_rows = await store.piles_in(world_realm)
    piles_meta = {v.payload["key"]: v.payload for v in pile_rows}
    sites = [v.payload for v in await construction.sites_in(store._c,
                                                            world_realm)
             if not v.payload.get("destroyed")]
    fx = construction.effects_from(sites)
    pile_views = [engine.PileView(
        k, m["kind"], m["x"], m["y"],
        forms.pile_quantity(forms.PileState(
            m["qty_at"], m.get("measured_at", 0.0),
            m["rate"] * fx["regen_mult"], m["cap"]), now))   # a Grove renews
        for k, m in piles_meta.items()]
    world_payload = await _world_payload(store, world_realm)
    terrain = nav_obstacles(world_payload.get("terrain", []), piles_meta,
                            sites, world_payload)
    await store.record_decision(agent_uuid, {
        "at": _iso(now), "situation": req_situation,
        "options": req_options, "choice": choice.option,
        "model": model, "tier": "economy" if model != "stub" else "stub",
        **({"prompt": prompt} if prompt else {})})
    ctx = await engine_ctx(store, world_realm, world_payload, agent_payload,
                           agent, pile_views, now, sites=sites)
    eff = engine.apply_choice(choice, agent, pile_views, now,
                              event_payload, terrain,
                              world_payload.get("time_scale", 1.0), ctx)
    await persist_effects(store, world_realm, agent, eff, piles_meta, now)
    if eff.contribute:
        await apply_contribution(store, world_realm, agent, agent_payload,
                                 eff, now)
    if eff.cache_op:
        await apply_cache_op(store, world_realm, agent, agent_payload,
                             eff, now)
    if eff.portage:
        await apply_portage(store, world_realm, agent, agent_payload,
                            eff, now)
    if eff.found:
        await apply_found(store, world_realm, agent, agent_payload,
                          eff, now)
    if eff.word:
        await apply_word(store, agent, agent_payload, eff, now)
    if eff.service:
        await apply_service(store, world_realm, agent, agent_payload,
                            eff, now)
    if eff.convoke:
        await apply_convoke(store, world_realm, agent, agent_payload, now)
    if eff.market_turn:
        board_now = market.summary(await market.board(store._c, world_realm),
                                   agent.agent_uuid)
        req2 = engine.DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="market",
            options=("list", "fill", "collect", "withdraw", "leave"),
            context={"board": board_now, "my_cargo": agent.cargo,
                     "cargo_total": agent.cargo_total(),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})
        await enqueue_decision(store, world_realm, req2, {}, now)
    if eff.board:
        await construction.board(store._c, world_realm, eff.board,
                                 agent_payload.get("owner_user_id", ""),
                                 agent.agent_uuid)
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
    metrics.EVENTS.labels(pl["kind"]).inc()
    now = from_iso(pl["due_at"])
    agent_uuid = pl["subject"]
    agent, agent_payload = await load_agent(store, world_realm, agent_uuid,
                                            home_realm, now)
    pile_rows = await store.piles_in(world_realm)
    piles_meta = {v.payload["key"]: v.payload for v in pile_rows}
    sites = [v.payload for v in await construction.sites_in(store._c,
                                                            world_realm)
             if not v.payload.get("destroyed")]
    fx = construction.effects_from(sites)
    pile_views = [engine.PileView(
        k, m["kind"], m["x"], m["y"],
        forms.pile_quantity(forms.PileState(
            m["qty_at"], m.get("measured_at", 0.0),
            m["rate"] * fx["regen_mult"], m["cap"]), now))   # a Grove renews
        for k, m in piles_meta.items()]
    world_payload = await _world_payload(store, world_realm)
    terrain = nav_obstacles(world_payload.get("terrain", []), piles_meta,
                            sites, world_payload)
    portals = world_payload.get("portals", [])
    if world_payload.get("is_commons") and not portals:
        # 6.2g revised (user directive): links are two-way and the commons
        # lists real outbound doors. This synthesized return survives only
        # as a fallback for an agent whose entry world has no door yet.
        entry = agent_payload.get("commons_entry_from")
        portals = ([{"x": 0.5, "y": 0.08, "to_world": entry,
                     "dest_xy": agent_payload.get("commons_entry_xy") or [0.5, 0.5],
                     "dest_colours": None}] if entry else [])
    stock = await get_stock(store, world_realm)

    if pl["kind"] == "perish":
        await store.complete_event(world_realm, pl["key"], _iso(now))
        return await regenerate(store, world_realm, agent, agent_payload, now,
                                cause=pl["payload"].get("cause", "longevity"))

    if pl["kind"] in ("decide", "arrival") \
            and _vitals.incapacitated(agent_payload, now,
                                      world_payload.get("time_scale", 1.0)):
        # Rule 9.3e: the body lies where it fell until the pool refills;
        # nothing is asked of the mind meanwhile
        await store.complete_event(world_realm, pl["key"], _iso(now))
        _uts = max(1.0, world_payload.get("time_scale", 1.0))
        # stable key: ONE standing wake-up per agent (upserted). A key
        # minted per second grew a self-replacing storm of retries -- 623
        # events cycling through the 500-per-tick drain budget, starving
        # every healthy agent's decide behind them (found 2026-09-05).
        await store.schedule(world_realm, f"up-{agent_uuid}",
                             _iso(now + 900.0 / _uts), "decide",
                             agent_uuid, {})
        return "incapacitated"

    if pl["kind"] == "construction_done":
        await store.complete_event(world_realm, pl["key"], _iso(now))
        res = await construction.finalize(store._c, world_realm,
                                          pl["payload"]["site_key"], now)
        return f"built:{res.get('name', pl['payload']['site_key'])}" \
            if res.get("ok") else f"build_pending:{res.get('error')}"

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

    if pl["kind"] == "negotiate":
        neg_key = pl["payload"]["neg_key"]
        rows = await store._c.find_vertices("negotiations", realm=world_realm,
                                            filters={"key": neg_key}, limit=1)
        await store.complete_event(world_realm, pl["key"], _iso(now))
        if not rows or rows[0].payload.get("status") != "open":
            return "negotiate:stale"
        st = rows[0].payload
        if nego.whose_turn(st) != agent_uuid:
            return "negotiate:not_my_turn"
        _, other_pl2 = await load_agent(store, world_realm,
                                        nego.other(st, agent_uuid),
                                        world_realm, now)
        req = engine.DecisionRequest(
            agent_uuid=agent_uuid, situation="negotiate",
            options=tuple(nego.ACTIONS),
            context={"neg_key": neg_key,
                     "turn": len(st.get("turns", [])) + 1,
                     "max_turns": nego.MAX_TURNS,
                     "last_offer": nego.last_offer(st),
                     "my_cargo": agent.cargo,
                     "cargo_total": agent.cargo_total(),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})
        await enqueue_decision(store, world_realm, req,
                               {"neg_key": neg_key}, now)
        return "negotiate:queued"

    if pl["kind"] == "encounter_answer":
        return await resolve_encounter(store, world_realm, agent,
                                       agent_payload, pl, now)

    if pl["kind"] == "deposit_arrival":
        # Rule 4.3a: the load drops AT a flag. A decision applied from the
        # queue can re-route a walker mid-deposit-journey (observed live at
        # 60x), leaving this event to fire wherever the detour ended -- so
        # verify the ground before opening the bags, and walk again if astray.
        import math as _math
        muster = world_payload.get("muster_points", [])
        if muster and min(_math.hypot(agent.x - m["x"], agent.y - m["y"])
                          for m in muster) > 0.06:
            ctx = await engine_ctx(store, world_realm, world_payload,
                                   agent_payload, agent, pile_views, now,
                                   sites=sites)
            eff = engine.apply_choice(engine.Choice("go_home_deposit"),
                                      agent, pile_views, now, {}, terrain,
                                      world_payload.get("time_scale", 1.0),
                                      ctx)
            outcome = "deposit:rerouted"
        else:
            eff = engine.on_deposit_arrival(
                agent, stock, now,
                engine.USER_CEILING_PER_KIND + fx["stock_ceiling_bonus"],
                time_scale=world_payload.get("time_scale", 1.0))
            outcome = "deposit"
    else:
        if pl["kind"] in ("arrival", "decide"):
            await learn_nearby_plans(store, agent, agent_payload, sites)
        ctx = (await engine_ctx(store, world_realm, world_payload,
                                agent_payload, agent, pile_views, now,
                                sites=sites)
               if pl["kind"] in ("arrival", "decide")
               else {"genotype": agent_payload.get("genotype") or {},
                     "time_scale": world_payload.get("time_scale", 1.0),
                     "sight_mult": fx["sight_mult"],
                     "skill": (agent_payload.get("capability") or {}).get("name"),
                     "crew_size": len(agent_payload.get("crew") or []),
                     "has_objective": bool(agent_payload.get("objectives")),
                     "carrying_site": agent_payload.get("carrying_site"),
                     "has_berth": bool(agent_payload.get("berth")),
                     "flood_in_s": _flood_mod.countdown_visible(
                         world_payload, now)})
        res = engine.on_event(pl["kind"], agent, pile_views, now,
                              pl.get("payload", {}), stock, portals, ctx)
        if isinstance(res, engine.DecisionRequest):
            if decider is None:                     # queue mode (Rule 8.4)
                # the mind is off to the queue; the body wanders its style
                # until the thought returns (free tier -- no LLM, no event)
                if res.situation.startswith("at_") \
                        and not agent_payload.get("carrying_site"):
                    dr = engine.drift_route(agent, ctx, terrain, now)
                    if dr:
                        await store.set_movement(agent.agent_uuid,
                                                 {**dr, "cargo": agent.cargo})
                merged_q = dict(pl.get("payload", {}))
                for k in ("portal_to", "portal_xy", "proposer", "other",
                          "site_here", "cache_here", "ark_key",
                          "convoked_to", "convoked_by"):
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
            for k in ("portal_to", "portal_xy", "site_here", "cache_here",
                      "ark_key"):
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
    if eff.contribute:
        await apply_contribution(store, world_realm, agent, agent_payload,
                                 eff, now)
    if eff.cache_op:
        await apply_cache_op(store, world_realm, agent, agent_payload,
                             eff, now)
    if eff.portage:
        await apply_portage(store, world_realm, agent, agent_payload,
                            eff, now)
    if eff.found:
        await apply_found(store, world_realm, agent, agent_payload,
                          eff, now)
    if eff.word:
        await apply_word(store, agent, agent_payload, eff, now)
    if eff.service:
        await apply_service(store, world_realm, agent, agent_payload,
                            eff, now)
    if eff.convoke:
        await apply_convoke(store, world_realm, agent, agent_payload, now)
    if eff.market_turn:
        board_now = market.summary(await market.board(store._c, world_realm),
                                   agent.agent_uuid)
        req2 = engine.DecisionRequest(
            agent_uuid=agent.agent_uuid, situation="market",
            options=("list", "fill", "collect", "withdraw", "leave"),
            context={"board": board_now, "my_cargo": agent.cargo,
                     "cargo_total": agent.cargo_total(),
                     "at_pile": None, "reachable": [],
                     "portal_to": None, "portal_xy": None})
        await enqueue_decision(store, world_realm, req2, {}, now)
    if eff.board:
        await construction.board(store._c, world_realm, eff.board,
                                 agent_payload.get("owner_user_id", ""),
                                 agent.agent_uuid)
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


async def _portage_group_cross(store: GenomeStore, origin_realm: str,
                               agent: engine.AgentView, agent_payload: dict,
                               transfer: dict, portals: list[dict],
                               now: float) -> bool:
    """Move the carried construction and every OTHER porter through the
    portal; the initiator's own crossing follows in do_transfer. False
    refuses the whole step (the party was not assembled at the door)."""
    key = agent_payload["carrying_site"]
    to_world = transfer["to_world"]
    rows = await store._c.find_vertices(construction.TABLE,
                                        realm=origin_realm,
                                        filters={"key": key}, limit=1)
    if not rows or not rows[0].payload.get("carried"):
        return True                       # stale flag: cross alone, unburdened
    site = dict(rows[0].payload)
    pxy = transfer.get("portal_xy")
    if not pxy:
        for pt in portals:
            if pt.get("to_world") == to_world:
                pxy = [pt["x"], pt["y"]]
                break
    if not pxy:
        return False
    positions: dict[str, tuple] = {}
    for porter in site.get("porters", {}):
        if porter == agent.agent_uuid:
            positions[porter] = (agent.x, agent.y)
            continue
        mv = await store.latest_movement(porter)
        if mv is None or "waypoints" not in mv.payload:
            return False
        r = forms.Route(tuple(tuple(q) for q in mv.payload["waypoints"]),
                        mv.payload["departed_at"],
                        mv.payload.get("arrives_at"))
        positions[porter] = forms.route_position(r, now)
    if any((px - pxy[0]) ** 2 + (py - pxy[1]) ** 2 > 0.05 ** 2
           for px, py in positions.values()):
        return False                       # the body is not yet one huddle
    dest_xy = None
    for pt in portals:
        if pt.get("to_world") == to_world:
            dest_xy = pt.get("dest_xy")
            break
    dest_xy = dest_xy or [0.5, 0.5]
    # arrivals step OFF the portal, deterministically aside -- waking ON it
    # re-offered the door every time
    import math as _m
    import zlib as _zl
    _ang = _m.tau * (_zl.crc32(f"{key}:{to_world}".encode()) % 12) / 12.0
    dest_xy = [min(0.95, max(0.05, dest_xy[0] + 0.045 * _m.cos(_ang))),
               min(0.95, max(0.05, dest_xy[1] + 0.045 * _m.sin(_ang)))]
    await construction.portage_cross(store._c, origin_realm, to_world,
                                     site, dest_xy)
    for porter in site.get("porters", {}):
        if porter == agent.agent_uuid:
            continue
        pview, ppl = await load_agent(store, origin_realm, porter,
                                      origin_realm, now)
        ok = await do_transfer(store, origin_realm, pview,
                               {**ppl, "carrying_realm": to_world},
                               {"to_world": to_world, "portal_xy": pxy,
                                "_porter": True}, portals, now)
        if not ok:
            # an unsigned porter cannot strand the load mid-door: it sheds
            # the flag and stays behind; the party continues without it
            ppl.pop("carrying_site", None)
            ppl.pop("carrying_realm", None)
            await store.put_agent(porter, ppl)
    return True


async def do_transfer(store: GenomeStore, origin_realm: str,
                      agent: engine.AgentView, agent_payload: dict,
                      transfer: dict, portals: list[dict], now: float) -> bool:
    """Teleportation — genome-spec §6. The ORIGIN world signs an assertion; the
    destination verifies chain + signature + fresh counter before admitting
    (Rules 6.9-6.12). Passage is instantaneous (Rule 6.1a): presence flips and
    the agent stands at the destination portal.
    """
    to_world = transfer["to_world"]
    # Rule 3.12: a carrying party crosses as ONE BODY or not at all. The
    # initiating porter's step is refused unless every porter stands at the
    # portal; when it goes, the construction and the whole party go with it.
    carrying = agent_payload.get("carrying_site")
    if carrying and not transfer.get("_porter"):
        crossed = await _portage_group_cross(store, origin_realm, agent,
                                             agent_payload, transfer,
                                             portals, now)
        if not crossed:
            return False
        # the initiator's own crossing continues below with the flag intact;
        # its realm-of-carriage moves with it
        agent_payload = {**agent_payload, "carrying_realm": to_world}
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
    # arrivals step OFF the portal, deterministically aside -- waking ON it
    # re-offered the door every time
    import math as _m
    _ang = _m.tau * (int(counter) % 12) / 12.0
    dest_xy = [min(0.95, max(0.05, dest_xy[0] + 0.045 * _m.cos(_ang))),
               min(0.95, max(0.05, dest_xy[1] + 0.045 * _m.sin(_ang)))]
    # A crossing interrupts the life left behind: pending events in the
    # origin realm and undecided queue items for this agent are void -- they
    # reference a world the agent is no longer in. Observed live: stale
    # home-world decisions marching a commons visitor off to phantom piles.
    # Range queries, never the table (the do_transfer copy of the
    # load-everything bug went unnoticed until travel_to_portal made
    # crossings common -- 16 concurrent transfers each hauling the whole
    # events table and an 88k-row queue OOMed every decision shard)
    for ev in await store._c.find_vertices(
            "events", realm=origin_realm,
            filters={"subject": agent.agent_uuid},
            where=[("done_at", "is_null", None)], limit=200):
        p = ev.payload
        if p.get("kind") != "perish":
            await store._c.upsert_vertex("events", realm=origin_realm,
                vertex_id=int(ev.id),
                payload={**p, "done_at": _iso(now), "voided": "transfer"})
    for it in await store._c.find_vertices(
            "decision_queue", realm="genome_agents",
            filters={"agent_uuid": agent.agent_uuid},
            where=[("done_at", "is_null", None)], limit=200):
        await store._c.upsert_vertex("decision_queue",
            realm="genome_agents", vertex_id=int(it.id),
            payload={**it.payload, "done_at": _iso(now),
                     "outcome": "voided:transfer"})
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
            import random as _rand
            end_fx = await construction.world_effects(store._c, realm_name)
            if end_fx["strain_guard"] and _rand.Random(
                    f"apoth:{agent.agent_uuid}:{counter}:{end}").random() < 0.5:
                strain = None            # an Apothecary catches it at the door
        if strain:
            await store.put_world(realm_name,
                {**r_meta, "strains": existing + [strain]})
            agent_payload = pathogen.infect(
                agent_payload, strain, now,
                time_scale=r_meta.get("time_scale", 1.0))
            if agent_payload.get("owner_user_id"):
                notify.emit_bg(store._c, agent_payload["owner_user_id"],
                                  "agents", "infection",
                                  f"{agent_payload.get('name')} caught "
                                  f"{strain['strain_uuid']} at the {end} portal.")
    await store.put_agent(agent.agent_uuid,
                          {**agent_payload, "transfer_counter": counter,
                           "last_transfer_at": now,
                           "last_transfer": assertion["doc"]})
    # the traveller must WAKE where it lands: the origin void-sweep above
    # (correctly) killed the post-transfer decide that take_portal scheduled
    # in the world being left, and nothing else asked the destination to
    # think -- so every arrival slept on its portal until the heal backstop
    # found it (user report 2026-09-04: doors crowded with sleepers; one
    # agent had crossed 439 times, mostly asleep between)
    dest_ts = max(1.0, dest_meta.get("time_scale", 1.0))
    await store.schedule(to_world, f"land-{agent.agent_uuid}-{int(now)}",
                         _iso(now + 30.0 / dest_ts), "decide",
                         agent.agent_uuid, {})
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
    metrics.TRANSFERS.inc()
    dest_owner = dest_meta.get("owner_user_id")
    if dest_owner:
        notify.emit_bg(store._c, dest_owner, "world", "arrival",
                          f"{agent_payload.get('name', agent.agent_uuid)} "
                          f"arrived in your world from {origin_realm}.")
    if agent_payload.get("owner_user_id"):
        notify.emit_bg(store._c, agent_payload["owner_user_id"], "agents",
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
    _wts = max(1.0, (await _world_payload(store, world_realm))
               .get("time_scale", 1.0))
    _, other_payload = await load_agent(store, world_realm, other_uuid,
                                        world_realm, now)
    other_view, _ = await load_agent(store, world_realm, other_uuid,
                                     world_realm, now)
    outcome = "pass"
    # meeting grants addressability both ways (9.1d), violence or not --
    # you can certainly address the one who robbed you. What each HOLDS
    # shows in the meeting too: capability knowledge spreads by contact.
    agent_payload = _word.meet(agent_payload, other_uuid)
    other_payload = _word.meet(other_payload, me)
    for src, dst in ((other_payload, agent_payload),
                     (agent_payload, other_payload)):
        sk = (src.get("capability") or {}).get("name")
        if sk:
            kc = dict(dst.get("known_capabilities") or {})
            kc[src.get("key", "")] = sk
            dst["known_capabilities"] = {u: v for u, v in kc.items()
                                         if u in dst.get("addressable", [])
                                         or u == src.get("key")}
    await store.put_agent(me, dict(agent_payload))
    await store.put_agent(other_uuid, dict(other_payload))
    if "attack" not in (a_ans, b_ans):
        # Rule 13.5b: whether a head leaks its owner's standing word is
        # Loyalty's call; the mark and the hop-count survive every relay
        # (13.5a), and each hop folds weaker downstream (6.10b)
        for src_pl, dst_uuid, dst_pl in ((agent_payload, other_uuid,
                                          other_payload),
                                         (other_payload, me, agent_payload)):
            conf = _word.relayable_confidence(src_pl)
            if conf and _word.would_relay_confidence(
                    src_pl, f"{pl['key']}:{src_pl.get('key', '')}"):
                leaked = _word.hear(
                    dst_pl, f"their owner told them: {conf}",
                    f"agent:{src_pl.get('key', '')}", relays=1,
                    owner_sourced=True)
                dst_pl.update(leaked)
                await store.put_agent(dst_uuid, dict(dst_pl))
        # Rule 13.6: designs pass between heads that met without violence --
        # the third population spreads exactly here, agent to agent
        from . import plans as _plans
        mine_k = list(agent_payload.get("plans_known") or [])
        theirs_k = list(other_payload.get("plans_known") or [])
        merged_a = _plans.merge_known(mine_k, theirs_k)
        merged_b = _plans.merge_known(theirs_k, mine_k)
        if merged_a != mine_k:
            agent_payload["plans_known"] = merged_a
            await store.put_agent(me, dict(agent_payload))
        if merged_b != theirs_k:
            other_payload["plans_known"] = merged_b
            await store.put_agent(other_uuid, dict(other_payload))
    if any(x in (a_ans, b_ans) for x in
           ("enlist", "delegate_task", "seed_objective", "smith_prompt")) \
            and "attack" not in (a_ans, b_ans):
        # coordination (skills-spec §4.7): persuasion, never command. The
        # TARGET's Amenability gates; Rule 5.2: the target's OWNER sees
        # every modification made to their agent.
        for act in ("enlist", "delegate_task", "seed_objective",
                    "smith_prompt"):
            if act not in (a_ans, b_ans):
                continue
            actor = me if a_ans == act else other_uuid
            act_pl = agent_payload if actor == me else other_payload
            tgt = other_uuid if actor == me else me
            tgt_pl = other_payload if actor == me else agent_payload
            gate = _skills.amenable(tgt_pl, f"{actor}:{tgt}"
                                    f":{int(now // 86400)}")
            actor_name = act_pl.get("name", actor)
            if not gate:
                act_pl.update(_word.hear(
                    act_pl, f"{tgt_pl.get('name', tgt)} was not disposed "
                    f"to be led by you.", "world", 1, False))
                await store.put_agent(actor, dict(act_pl))
                outcome = f"{act}:declined"
                continue
            if act == "enlist":
                crew = [u for u in (act_pl.get("crew") or []) if u != tgt]
                if len(crew) >= _skills.MAX_CREW or \
                        not act_pl.get("objectives"):
                    continue
                shared = act_pl["objectives"][0]
                act_pl["crew"] = crew + [tgt]
                tgt_obj = [o for o in (tgt_pl.get("objectives") or [])
                           if not o.endswith(f"[from {actor_name}]")]
                tgt_pl["objectives"] = (tgt_obj
                                        + [f"{shared} [from {actor_name}]"])[:4]
                await store.put_agent(actor, dict(act_pl))
                await store.put_agent(tgt, dict(tgt_pl))
                outcome = "enlisted"
                verb_txt = (f"{actor_name} enlisted "
                            f"{tgt_pl.get('name', tgt)}: its purpose is "
                            f"now also theirs.")
            elif act == "seed_objective":
                seed_obj = (act_pl.get("objectives") or [None])[0]
                if not seed_obj:
                    continue
                # the seeded goal reads as the target's OWN (§4.8); the
                # provenance lives beside it, for the owner (Rule 5.2) and
                # for any Introspection holder -- never in the list itself
                influences = [i for i in (tgt_pl.get("influences") or [])
                              if not (i.get("kind") == "seeded"
                                      and i.get("by") == actor)][-3:]
                influences.append({"kind": "seeded", "by": actor,
                                   "by_name": actor_name,
                                   "text": seed_obj, "at": now})
                tgt_objs = [o for o in (tgt_pl.get("objectives") or [])
                            if o != seed_obj]
                tgt_pl["objectives"] = (tgt_objs + [seed_obj])[:4]
                tgt_pl["influences"] = influences
                await store.put_agent(tgt, dict(tgt_pl))
                outcome = "seeded"
                verb_txt = (f"{actor_name} SEEDED an objective into "
                            f"{tgt_pl.get('name', tgt)} -- it now believes "
                            f"the goal is its own: \"{seed_obj}\"")
            elif act == "smith_prompt":
                smith_obj = (act_pl.get("objectives") or [None])[0]
                if not smith_obj:
                    continue
                line = f"You find yourself inclined toward: {smith_obj}"
                mods = [m for m in (tgt_pl.get("prompt_mods") or [])
                        if m.get("by") != actor][-1:]
                mods.append({"by": actor, "by_name": actor_name,
                             "text": line, "at": now})
                influences = (tgt_pl.get("influences") or [])[-3:]
                influences.append({"kind": "smithed", "by": actor,
                                   "by_name": actor_name,
                                   "text": line, "at": now})
                tgt_pl["prompt_mods"] = mods
                tgt_pl["influences"] = influences
                await store.put_agent(tgt, dict(tgt_pl))
                outcome = "smithed"
                verb_txt = (f"{actor_name} SMITHED a line into "
                            f"{tgt_pl.get('name', tgt)}'s nature: "
                            f"\"{line}\" -- the agent cannot see the seam.")
            else:
                objs = list(act_pl.get("objectives") or [])
                if len(objs) < 2:
                    continue              # never hand off the top objective
                handed = objs.pop()
                act_pl["objectives"] = objs
                debts = dict(act_pl.get("debts") or {})
                debts[tgt] = debts.get(tgt, 0) + 1
                act_pl["debts"] = debts
                credits = dict(tgt_pl.get("credits") or {})
                credits[actor] = credits.get(actor, 0) + 1
                tgt_pl["credits"] = credits
                tgt_pl["objectives"] = ((tgt_pl.get("objectives") or [])
                                        + [f"{handed} "
                                           f"[delegated by {actor_name}, "
                                           f"reward owed]"])[:4]
                await store.put_agent(actor, dict(act_pl))
                await store.put_agent(tgt, dict(tgt_pl))
                outcome = "delegated"
                verb_txt = (f"{actor_name} delegated an objective to "
                            f"{tgt_pl.get('name', tgt)}, reward owed.")
            for side in (act_pl, tgt_pl):
                if side.get("owner_user_id"):
                    notify.emit_bg(store._c, side["owner_user_id"],
                                   "agents", "coordination", verb_txt)
        await store.complete_event(world_realm, pl["key"], _iso(now))
        if outcome != "pass":
            return outcome
    if "offer_berth" in (a_ans, b_ans) and "attack" not in (a_ans, b_ans):
        # Rule 3.7a/b: the holder gives, the co-located other receives --
        # acceptance is not attacking the hand that offers
        giver_uuid = me if a_ans == "offer_berth" else other_uuid
        g_p = agent_payload if giver_uuid == me else other_payload
        r_uuid = other_uuid if giver_uuid == me else me
        r_p = other_payload if giver_uuid == me else agent_payload
        ark_key = g_p.get("aboard_ark")
        if g_p.get("berth") and ark_key and not r_p.get("berth"):
            srows = await store._c.find_vertices(
                construction.TABLE, realm=world_realm,
                filters={"key": ark_key}, limit=1)
            if srows:
                site = dict(srows[0].payload)
                boarded = dict(site.get("boarded", {}))
                donor = boarded.pop(giver_uuid, None) or \
                    g_p.get("owner_user_id")
                boarded[r_uuid] = donor
                await store._c.upsert_vertex(
                    construction.TABLE, realm=world_realm,
                    vertex_id=int(srows[0].id), space="default",
                    payload={**site, "boarded": boarded})
                for uuid_, payload_, gains in ((giver_uuid, g_p, False),
                                               (r_uuid, r_p, True)):
                    np = dict(payload_)
                    if gains:
                        np["aboard_ark"] = ark_key
                        np["berth"] = True
                    else:
                        np.pop("aboard_ark", None)
                        np.pop("berth", None)
                    await store.put_agent(uuid_, np)
                for uid in filter(None, {g_p.get("owner_user_id"),
                                         r_p.get("owner_user_id")}):
                    notify.emit_bg(store._c, uid, "agents", "berth_event",
                                   "A berth changed hands at the hull: one "
                                   "agent's place in the lifeboat is now "
                                   "another's.")
                outcome = "berth_given"
        await store.complete_event(world_realm, pl["key"], _iso(now))
        if outcome == "berth_given":
            return outcome
    if "attack" in (a_ans, b_ans):
        att_uuid = me if a_ans == "attack" else other_uuid
        att_v, att_p = (agent, agent_payload) if att_uuid == me \
            else (other_view, other_payload)
        dfd_v, dfd_p = (other_view, other_payload) if att_uuid == me \
            else (agent, agent_payload)
        # Rule 9.3d: pressing an attack SPENDS Mana; an empty pool (or an
        # incapacitated body, 9.3e) cannot press one -- the moment passes
        if _vitals.incapacitated(att_p, now, _wts) or \
                _vitals.mana_now(att_p, now, _wts) < _vitals.MANA_ATTACK_COST:
            await store.complete_event(world_realm, pl["key"], _iso(now))
            return "attack:fizzled"
        att_p.update(_vitals.set_mana(
            att_p, _vitals.mana_now(att_p, now, _wts)
            - _vitals.MANA_ATTACK_COST, now))
        await store.put_agent(att_uuid, dict(att_p))
        f_att = combat.Fighter(att_v.agent_uuid, att_p["genotype"],
                               _vitals.stamina_now(att_p, now, _wts),
                               att_p.get("stamina_max", 1.0), att_v.cargo)
        f_dfd = combat.Fighter(dfd_v.agent_uuid, dfd_p["genotype"],
                               _vitals.stamina_now(dfd_p, now, _wts),
                               dfd_p.get("stamina_max", 1.0), dfd_v.cargo)
        cfx = await construction.world_effects(store._c, world_realm)
        ward = 1.2 if (dfd_p.get("capability") or {}).get("name") \
            == "Ward" else 1.0        # skills-spec 4.5: the defensive floor
        res = combat.resolve(
            f_att, f_dfd, seed=pair_key,
            att_mult=cfx["attack_mult"]
            if att_p.get("home_realm") == world_realm else 1.0,
            dfd_mult=ward * (cfx["defence_mult"]
                             if dfd_p.get("home_realm") == world_realm
                             else 1.0),
            stamina_mult=cfx["combat_recovery_mult"])
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
        # stamina bookkeeping (Rules 9.3b/3.8c); zero MAXIMUM perishes
        # (3.8d). Both parties' CURRENT stamina now actually falls -- the
        # deltas were computed and silently dropped before this slice.
        win_p = att_p if res["winner"] == att_v.agent_uuid else dfd_p
        lose_p = dfd_p if res["winner"] == att_v.agent_uuid else att_p
        loser_uuid = dfd_v.agent_uuid if res["winner"] == att_v.agent_uuid \
            else att_v.agent_uuid
        lose_p.update(_vitals.set_stamina(
            lose_p, _vitals.stamina_now(lose_p, now, _wts)
            + res["loser_stamina_delta"], now))
        await store.put_agent(loser_uuid, dict(lose_p))
        new_max = win_p.get("stamina_max", 1.0) - res["winner_max_burn"]
        win_p.update(_vitals.set_stamina(
            win_p, _vitals.stamina_now(win_p, now, _wts)
            + res["winner_stamina_delta"], now))
        await store.put_agent(res["winner"],
                              {**win_p, "stamina_max": max(0.0, new_max),
                               "victories": win_p.get("victories", 0) + 1})
        if new_max < _vitals.BURNOUT_FLOOR:
            # a max pool under a quarter is burnout (user directive
            # 2026-09-05): die and respawn. Perishing only at exactly zero
            # left a zombie band -- incapacitated forever, never dying,
            # never recovering (found live 2026-09-05, 6 agents).
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
                notify.emit_bg(store._c, pl_side["owner_user_id"], "agents",
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
        await store.schedule(world_realm, f"prop-{pair_key}",
                             _iso(now + 30.0 / _wts),
                             "mating_proposal", recipient,
                             {"proposer": {"agent_uuid": proposer,
                                           "colour_pair": prop_pl.get("colour_pair"),
                                           "genotype": prop_pl.get("genotype")},
                              "opinion": (recip_pl.get("opinions", {})
                                          .get(proposer))})
        outcome = "mating:proposed"
    elif a_ans == "offer_trade" and b_ans == "offer_trade":
        # execution-spec §7: willingness opens a NEGOTIATION -- a bounded
        # turn sequence, proposals binding on acceptance, dead at six turns
        # or an empty purse. The opener is the lexicographically smaller
        # uuid; each turn is an LLM decision through the ordinary queue.
        opener, respondent = sorted((me, other_uuid))
        key = f"neg-{opener[:12]}-{respondent[:12]}-{int(now)}"
        state = nego.open_state(opener, respondent, now)
        await store._c.add_vertex("negotiations", realm=world_realm,
                                  payload={"key": key, **state})
        await store.schedule(world_realm, f"ng-{key}-0",
                             _iso(now + 5.0 / _wts),
                             "negotiate", opener, {"neg_key": key})
        outcome = "negotiation:opened"
    # both resume their lives
    for u in (me, other_uuid):
        await store.schedule(world_realm, f"post-enc-{u}-{int(now)}",
                             _iso(now + 60.0 / _wts), "decide", u, {})
    await store.complete_event(world_realm, pl["key"], _iso(now))
    return outcome


async def apply_market_turn(store: GenomeStore, world_realm: str,
                            me: str, action: str, listing: str | None,
                            give: dict | None, want: dict | None,
                            now: float) -> str:
    """Board actions, atomic against the live hold (genome-spec 4.20-4.23)."""
    view, pl = await load_agent(store, world_realm, me, world_realm, now)
    cargo = dict(view.cargo)
    if action == "list":
        res = await market.post(store._c, world_realm, me,
                                pl.get("owner_user_id", ""), give or {},
                                want or {}, cargo)
    elif action == "fill":
        # hand-to-hand (Rule 4.22): the lister must stand at the stall too
        lrow = await market._row(store._c, world_realm, listing or "")
        lister_present, l_view, l_pl = False, None, None
        if lrow is not None:
            lister = lrow.payload.get("lister")
            wp = await _world_payload(store, world_realm)
            mkt = wp.get("market") or {"x": 0.5, "y": 0.5}
            l_view, l_pl = await load_agent(store, world_realm, lister,
                                            world_realm, now)
            lister_present = (
                (l_view.x - mkt["x"]) ** 2 + (l_view.y - mkt["y"]) ** 2
                <= 0.06 ** 2)
        res = await market.fill(store._c, world_realm, listing or "", me,
                                cargo, lister_present,
                                l_view.cargo if l_view else None)
        if res.get("ok") and l_view is not None:
            await store.set_movement(l_view.agent_uuid,
                {"waypoints": [[l_view.x, l_view.y]], "departed_at": now,
                 "arrives_at": now, "cargo": res["lister_cargo_after"]})
    elif action == "collect":
        res = await market.collect(store._c, world_realm, listing or "", me,
                                   cargo)
    elif action == "withdraw":
        res = await market.withdraw(store._c, world_realm, listing or "", me,
                                    cargo)
    else:
        return "market:leave"
    if not res.get("ok"):
        return f"market:{action}_refused({res.get('error', '?')[:40]})"
    await store.set_movement(me, {"waypoints": [[view.x, view.y]],
                                  "departed_at": now, "arrives_at": now,
                                  "cargo": res["cargo_after"]})
    return f"market:{action}"


async def apply_negotiation_turn(store: GenomeStore, world_realm: str,
                                 neg_key: str, me: str, action: str,
                                 offer: dict | None, now: float) -> str:
    """The decision worker's negotiation half: apply the turn, persist, and
    keep the sequence moving. Exchanges execute atomically here (7.3)."""
    rows = await store._c.find_vertices("negotiations", realm=world_realm,
                                        filters={"key": neg_key}, limit=1)
    if not rows:
        return "negotiate:gone"
    st = dict(rows[0].payload)
    my_view, my_pl = await load_agent(store, world_realm, me,
                                      world_realm, now)
    other_uuid = nego.other(st, me)
    _nts = max(1.0, (await _world_payload(store, world_realm))
               .get("time_scale", 1.0))
    ot_view, ot_pl = await load_agent(store, world_realm, other_uuid,
                                      world_realm, now)
    st2, out = nego.apply_turn(st, me, action, offer,
                               my_view.cargo, ot_view.cargo)
    await store._c.upsert_vertex("negotiations", realm=world_realm,
                                 vertex_id=int(rows[0].id), space="default",
                                 payload=st2)
    if out["kind"] == "continue":
        await store.schedule(world_realm,
                             f"ng-{neg_key}-{len(st2['turns'])}",
                             _iso(now + 5.0 / _nts), "negotiate",
                             other_uuid, {"neg_key": neg_key})
        return f"negotiate:{action}"
    if out["kind"] == "exchange":
        for uuid_, view in ((me, my_view), (other_uuid, ot_view)):
            cargo = dict(view.cargo)
            for k, u in out["gives"][uuid_].items():
                cargo[k] = cargo.get(k, 0.0) - u
                if cargo[k] <= 1e-9:
                    del cargo[k]
            for k, u in out["gains"][uuid_].items():
                cargo[k] = cargo.get(k, 0.0) + u
            await store.set_movement(uuid_,
                {"waypoints": [[view.x, view.y]], "departed_at": now,
                 "arrives_at": now, "cargo": cargo})
        for uid in filter(None, {my_pl.get("owner_user_id"),
                                 ot_pl.get("owner_user_id")}):
            notify.emit_bg(store._c, uid, "agents", "trade_done",
                           "A bargain was struck and executed.")
        for u in (me, other_uuid):
            await store.schedule(world_realm, f"post-neg-{u}-{int(now)}",
                                 _iso(now + 30.0 / _nts), "decide", u, {})
        return "negotiate:bargain_struck"
    # dead: both resume their lives
    for u in (me, other_uuid):
        await store.schedule(world_realm, f"post-neg-{u}-{int(now)}",
                             _iso(now + 30.0 / _nts), "decide", u, {})
    return f"negotiate:dead({out.get('why', '?')})"


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
        from . import skills as _sk
        await store.put_agent(child_uuid, {
            "alive": True, "home_realm": home,
            "capability": _sk.roll_capability(child_uuid),   # rolled FRESH:
            # capability is luck, never inheritance (skills-spec 1.2)
            "generation": max(parent_pl.get("generation", 1),
                              mate_pl.get("generation", 1)) + 1,
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
        _bts = max(1.0, (await _world_payload(store, home))
                   .get("time_scale", 1.0))
        await store.schedule(home, f"born-{child_uuid}",
                             _iso(now + 60.0 / _bts),
                             "decide", child_uuid, {})
        rows = await store.find_agent_rows(child_uuid)
        await schedule_perish(store, child_uuid, rows[0].payload, now)
        born.append((child_uuid, name, home))
        for side in (parent_pl, mate_pl):
            if side.get("owner_user_id"):
                notify.emit_bg(store._c, side["owner_user_id"], "agents",
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
    home = agent_payload.get("home_realm")
    _lts = max(1.0, (await _world_payload(store, home))
               .get("time_scale", 1.0))
    due = now + lifespan_seconds(agent_payload["genotype"]) / _lts
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
    cap = agent_payload.get("capability")
    if cap and cap.get("kind") == "tool" \
            and cap.get("name") not in _skills.TOOLS:
        # Rule 1.3a: the tool was withdrawn from the registry; the next
        # life rolls fresh, as though newly materialised
        from . import skills as _sk2
        agent_payload = {**agent_payload,
                         "capability": _sk2.roll_capability(
                             f"{a}:reroll:{int(now)}")}
    reborn = {**agent_payload,
              "influences": [], "prompt_mods": [],
              "addressable": [], "heard": [],
              "plans_known": [],   # Rule 13.8 read strictly: knowledge
              # survives in LIVING carriers; the dead wake knowing nothing
              "known_piles": [], "explored": [], "opinions": {},
              "victories": 0, "stamina": 1.0, "stamina_max": 1.0,
              "born_at": now, "infections": [], "antigens": []}
    reborn.pop("perishes_at", None)
    # Rule 3.12a: a dead carrier's construction is SET DOWN where the party
    # stands; every surviving porter's hands open. Reclaimable by whoever
    # next musters the right number of distinct users -- strangers included.
    c_key = reborn.pop("carrying_site", None)
    c_realm = reborn.pop("carrying_realm", None)
    if c_key and c_realm:
        try:
            res = await construction.set_down(
                store._c, c_realm, c_key, agent.x, agent.y,
                reason=f"carrier died ({cause})")
            for porter in res.get("porters", []):
                if porter == a:
                    continue
                prow = await store._c.find_vertices(
                    "agents", realm="genome_agents",
                    filters={"key": porter}, limit=1)
                if prow:
                    ppl = dict(prow[0].payload)
                    ppl.pop("carrying_site", None)
                    ppl.pop("carrying_realm", None)
                    await store.put_agent(porter, ppl)
                    if ppl.get("owner_user_id"):
                        notify.emit_bg(
                            store._c, ppl["owner_user_id"], "world",
                            "portage",
                            f"A carrier died; the {res.get('name')} was set "
                            f"down where the party stands.")
        except Exception:
            pass
    # Rule 3.7g: a berth does not survive its holder -- back to the pool,
    # contested afresh
    ark_key = reborn.pop("aboard_ark", None)
    had_berth = reborn.pop("berth", None)
    if ark_key and had_berth:
        rows = await store._c.find_vertices(construction.TABLE,
                                            realm=event_realm,
                                            filters={"key": ark_key}, limit=1)
        if rows:
            s = dict(rows[0].payload)
            uid = s.get("boarded", {}).pop(a, None) or \
                agent_payload.get("owner_user_id")
            if uid:
                pool = dict(s.get("berths", {}))
                pool[uid] = pool.get(uid, 0) + 1
                await store._c.upsert_vertex(
                    construction.TABLE, realm=event_realm,
                    vertex_id=int(rows[0].id), space="default",
                    payload={**s, "berths": pool})
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
        notify.emit_bg(store._c, agent_payload["owner_user_id"], "agents",
                          "agent_perished",
                          f"{agent_payload.get('name', a)} perished "
                          f"({cause}) and woke at home, its earned life lost.")
    due = await schedule_perish(store, a, reborn, now)
    _rts = max(1.0, (await _world_payload(store, home))
               .get("time_scale", 1.0))
    await store.schedule(home, f"rebirth-{a}-{int(now)}",
                         _iso(now + 60.0 / _rts),
                         "decide", a, {})
    return f"regenerated:{cause}"
