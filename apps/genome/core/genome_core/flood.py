"""The flood — construction-spec §4.1/§4.2, slice two.

Every world carries an undisclosed clock (Rule 4.7): a draw between 15 and
30 days, divided by the world's demo time_scale so scaled worlds flood on
scaled calendars. Two days out (scaled likewise) the countdown becomes
visible to everyone present (Rule 4.8). When the water arrives it kills every
agent in the world, native or visitor (Rule 4.9) — except those ABOARD a
completed Ark holding a berth (Rules 4.10/4.10a) — resets the world to its
nascent state (Rule 4.4), keeps the Ark hull partial or spends it whole
(Rules 4.4a/4.4b), and redraws the clock.

Pile reversion note: worlds founded before this slice did not record their
original quantities, so their piles revert to 70% of capacity — PROVISIONAL,
recorded in calibration §5. Worlds founded from now on carry `qty_origin`.
"""
from __future__ import annotations

import random
import time
from typing import Any

from . import construction, drain, engine, notify

FLOOD_MIN_DAYS = 15.0
FLOOD_MAX_DAYS = 30.0
COUNTDOWN_DAYS = 2.0                      # Rule 4.8
NASCENT_FILL = 0.7                        # PROVISIONAL pile reversion
ARK_RADIUS = 0.05                         # being aboard means being HERE


def draw_flood_at(now: float, time_scale: float, seed: str) -> float:
    r = random.Random(f"flood:{seed}")
    days = r.uniform(FLOOD_MIN_DAYS, FLOOD_MAX_DAYS)
    return now + days * 86400.0 / max(1.0, time_scale)


async def ensure_clock(store, realm: str, meta: dict, now: float) -> dict:
    """Backfill: a world without a clock gets one, drawn from its own name so
    re-runs agree. The draw is never exposed by snapshot until the window."""
    if meta.get("flood_at"):
        return meta
    scale = meta.get("time_scale", 1.0)
    meta = {**meta, "flood_at": draw_flood_at(now, scale,
                                              f"{realm}:{int(now)}"),
            "flood_count": meta.get("flood_count", 0)}
    await store.put_world(realm, meta)
    return meta


def countdown_window(meta: dict) -> float:
    return COUNTDOWN_DAYS * 86400.0 / max(1.0, meta.get("time_scale", 1.0))


def countdown_visible(meta: dict, now: float) -> float | None:
    """Seconds remaining, or None while the clock is a secret (Rule 4.7)."""
    at = meta.get("flood_at")
    if not at:
        return None
    remaining = at - now
    if remaining <= countdown_window(meta):
        return max(0.0, remaining)
    return None


async def tick(store, realm: str, now: float) -> str | None:
    """One clock check for one world; the tick worker calls this each cycle.
    Returns what happened, if anything."""
    meta = await drain._world_payload(store, realm)
    if not meta or meta.get("is_commons"):
        return None                        # the commons does not flood (6.2f)
    meta = await ensure_clock(store, realm, meta, now)
    remaining = countdown_visible(meta, now)
    if remaining is None:
        return None
    if remaining > 0:
        if not meta.get("countdown_notified"):
            await store.put_world(realm, {**meta, "countdown_notified": True})
            owners = {v.payload.get("owner_user_id")
                      for v in await store.agents_in(realm)}
            owners.add(meta.get("owner_user_id"))
            hours = remaining / 3600.0
            for uid in filter(None, owners):
                notify.emit_bg(store._c, uid, "world", "flood_countdown",
                                  f"The water is coming to {realm}: flood in "
                                  f"{hours:.1f}h. Agents present will die "
                                  f"unless aboard an Ark or elsewhere.")
            return "countdown"
        return None
    return await execute(store, realm, meta, now)


async def execute(store, realm: str, meta: dict, now: float) -> str:
    """The water arrives."""
    client = store._c
    # who is aboard a completed Ark with a berth? (Rules 4.10/4.10a)
    ark = next((v.payload for v in await construction.sites_in(client, realm)
                if v.payload["name"] == "ark" and v.payload.get("complete")
                and not v.payload.get("spent")), None)
    saved: set[str] = set()
    drowned = 0
    import asyncio as _aio
    sem = _aio.Semaphore(6)

    async def _judge(a):
        nonlocal drowned
        async with sem:
            rows = await client.find_vertices("agents",
                                              realm="genome_agents",
                                              filters={"key": a}, limit=1)
            if not rows:
                return
            await _one(a, rows[0].payload)

    keys = [v.payload["key"] for v in await store.agents_in(realm)
            if not v.payload["key"].startswith("user:")]

    async def _one(a, pl):
        nonlocal drowned
        if ark and pl.get("aboard_ark") == ark["key"] and pl.get("berth"):
            # holding a berth is not being in it (Rule 4.10): the body must
            # stand at the hull when the water arrives
            mv = await store.latest_movement(a)
            at_hull = False
            if mv is not None and "waypoints" in mv.payload:
                mp = mv.payload
                from . import forms as _forms
                x, y = _forms.route_position(
                    _forms.Route(tuple(tuple(q) for q in mp["waypoints"]),
                                 mp["departed_at"], mp.get("arrives_at")),
                    now)
                at_hull = (x - ark["x"]) ** 2 + (y - ark["y"]) ** 2 \
                    <= ARK_RADIUS ** 2
            if at_hull:
                saved.add(a)
                return
            # wandered off with a boarding pass: it drowns like anyone else,
            # and the berth returns to the pool via regenerate (Rule 3.7g)
        if not pl.get("genotype"):
            # a record with no genotype cannot regenerate (Rule 7.3 has
            # nothing to carry over); the water simply removes it
            await store.set_presence(realm, a, False)
            drowned += 1
            return
        view = engine.AgentView(a, pl.get("home_realm", realm), realm,
                                0.5, 0.5, {})
        await drain.regenerate(store, realm, view, pl, now, cause="flood")
        drowned += 1

    if ark and any(n > 0 for n in ark.get("berths", {}).values()):
        # the scramble (Rule 3.7f): unclaimed berths fall to whoever stands
        # at the hull, nearest first, whoever they belong to
        from . import forms as _forms
        standers = []
        for a in keys:
            rows = await client.find_vertices("agents",
                                              realm="genome_agents",
                                              filters={"key": a}, limit=1)
            if not rows or rows[0].payload.get("berth"):
                continue
            mv = await store.latest_movement(a)
            if mv is None or "waypoints" not in mv.payload:
                continue
            mp = mv.payload
            x, y = _forms.route_position(
                _forms.Route(tuple(tuple(q) for q in mp["waypoints"]),
                             mp["departed_at"], mp.get("arrives_at")), now)
            d2 = (x - ark["x"]) ** 2 + (y - ark["y"]) ** 2
            if d2 <= ARK_RADIUS ** 2:
                standers.append((d2, a, rows[0]))
        pool = dict(ark.get("berths", {}))
        boarded = dict(ark.get("boarded", {}))
        for _, a, row in sorted(standers, key=lambda q: (q[0], q[1])):
            donor = next((u for u, n in pool.items() if n > 0), None)
            if donor is None:
                break
            pool[donor] -= 1
            boarded[a] = donor
            await client.upsert_vertex("agents", realm="genome_agents",
                                       vertex_id=int(row.id), space="default",
                                       payload={**row.payload,
                                                "aboard_ark": ark["key"],
                                                "berth": True})
        srows = await client.find_vertices(construction.TABLE, realm=realm,
                                           filters={"key": ark["key"]},
                                           limit=1)
        if srows:
            await client.upsert_vertex(construction.TABLE, realm=realm,
                                       vertex_id=int(srows[0].id),
                                       space="default",
                                       payload={**srows[0].payload,
                                                "berths": pool,
                                                "boarded": boarded})
            ark = {**ark, "berths": pool, "boarded": boarded}
    await _aio.gather(*(_judge(a) for a in keys))
    # the world reverts to its nascent state (Rule 4.4)
    for v in await store.piles_in(realm):
        p = v.payload
        origin = p.get("qty_origin", p["cap"] * NASCENT_FILL)
        await store.put_pile(realm, p["key"], {**p, "qty_at": origin,
                                               "measured_at": now})
    for v in await construction.sites_in(client, realm):
        s = v.payload
        if s["name"] == "ark":
            if s.get("spent"):
                # last cycle's wreck: this flood washes it away entirely
                # (user directive; consistent with 4.4b's decaying hull)
                await client.upsert_vertex(construction.TABLE, realm=realm,
                    vertex_id=int(v.id), space="default",
                    payload={**s, "destroyed": True})
            elif s.get("complete") and saved:
                # a voyage with passengers spends the hull (Rule 4.4b)
                await client.upsert_vertex(construction.TABLE, realm=realm,
                    vertex_id=int(v.id), space="default",
                    payload={**s, "spent": True, "wreck_at": now})
            # otherwise the hull -- partial or unused -- persists (4.4a/4.4c)
            continue
        if s.get("manifested") and ark and saved:
            # carried in the hold (Rule 4.3a): re-established intact in the
            # nascent world, its manifest flag spent with the voyage
            await client.upsert_vertex(construction.TABLE, realm=realm,
                vertex_id=int(v.id), space="default",
                payload={**s, "manifested": False})
            continue
        await client.upsert_vertex(construction.TABLE, realm=realm,
            vertex_id=int(v.id), space="default",
            payload={**s, "destroyed": True, "complete": False,
                     "delivered": {}, "contributors": {}})
    from . import market as _market
    await _market.flood_wipe(client, realm)   # Rule 4.23: the board drowns
    scale = meta.get("time_scale", 1.0)
    carried = dict((ark or {}).get("stock_manifest", {})) \
        if ark and saved else {}
    await store.put_world(realm, {
        **meta, "stock": carried,
        "flood_at": draw_flood_at(now, scale, f"{realm}:{int(now)}"),
        "flood_count": meta.get("flood_count", 0) + 1,
        "countdown_notified": False,
        "last_flood_at": now})
    # survivors step off onto the shore of the reset world (Rule 4.3c)
    for a in saved:
        rows = await client.find_vertices("agents", realm="genome_agents",
                                          filters={"key": a}, limit=1)
        if rows:
            pl = rows[0].payload
            pl.pop("aboard_ark", None); pl.pop("berth", None)
            await store.put_agent(a, pl)
    owners = {meta.get("owner_user_id")}
    for uid in filter(None, owners):
        notify.emit_bg(client, uid, "world", "flood_arrived",
                          f"The flood took {realm}: {drowned} agents drowned "
                          f"and regenerate at home; {len(saved)} survived "
                          f"aboard the Ark. The world is nascent again.")
    return f"flood:{drowned}d/{len(saved)}s"
