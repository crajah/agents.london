"""genome tick worker — the live loop.

system-spec §4/§8: drains due events for its realms; never calls a model from
the world queue path (the decider runs inline here for now, moving onto the
decision queue when multi-worker arrives — Rule 8.4's separation is about a
busy world stalling its own queue, tolerable at demo scale, noted).

Self-healing (system-spec Rule 8.3 in spirit): an agent that is present, has
arrived, and has no pending event gets a decide scheduled — so a seeded or
recovered world always resumes, and a flushed queue rebuilds from post-graph
by construction.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
import uuid as uuidlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from post_graph import AsyncPostGraph
from genome_core import drain
from genome_core import flood as _flood
from genome_core import drain as _d
from genome_core.decider import make_decider
from genome_core.store import GenomeStore

logger = logging.getLogger("genome.tick")

REALMS = [r for r in os.getenv("GENOME_REALMS", "").split(",") if r]
TICK_SECONDS = float(os.getenv("GENOME_TICK_SECONDS", "5"))
USE_LLM = os.getenv("GENOME_USE_LLM", "1") == "1"
INLINE = os.getenv("GENOME_INLINE_DECIDER", "0") == "1"   # tests only:
# system-spec Rule 8.4 -- production never decides on the world queue


def dsn() -> str:
    return os.getenv("POSTGRES_URI") or (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.getenv('POSTGRES_HOST', 'postgres-service')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.environ['POSTGRES_DB']}")


async def heal(store: GenomeStore, realm: str, now: float) -> int:
    """Schedule a decide for any present agent with nothing pending."""
    pending_subjects = {v.payload.get("subject")
                        for v in await store._c.get_vertices("events", realm=realm)
                        if v.payload.get("done_at") is None}
    # an agent whose question sits in the decision queue is NOT idle -- without
    # this, heal scheduled a fresh decide every tick while the decider worked,
    # and the event table grew a 279-deep backlog of stale questions
    pending_subjects |= {v.payload.get("agent_uuid")
                        for v in await store._c.get_vertices("decision_queue",
                                                             realm="genome_agents")
                        if v.payload.get("done_at") is None
                        and v.payload.get("world_realm") == realm}
    healed = 0
    for v in await store.agents_in(realm):
        a = v.payload["key"]
        rows = await store._c.find_vertices("agents", realm="genome_agents",
                                            filters={"key": a}, limit=1)
        apl = rows[0].payload if rows else {}
        if apl.get("genotype") and "perishes_at" not in apl:
            await _d.schedule_perish(store, a, apl, now)   # the reaper learns
        if a in pending_subjects:
            continue
        latest = await store.latest_movement(a)
        if latest and latest.payload.get("arrives_at", 0) > now:
            continue                      # still travelling; arrival comes
        await store.schedule(realm, f"heal-{uuidlib.uuid4().hex[:8]}",
                             drain._iso(now), "decide", a, {})
        healed += 1
    return healed


CONTACT_RADIUS = 0.02          # Rule 5.5: contact is what makes an encounter
_recent_pairs: dict[str, float] = {}


async def sweep(store: GenomeStore, realm: str, now: float) -> int:
    """Proximity sweep (execution-spec Rule 3.3): interpolate every present
    agent, schedule an encounter for pairs in contact. A pair cools down so a
    lingering pair does not re-collide every tick."""
    from genome_core import drain as _d, forms as _f
    positions = {}
    metas = {}
    for v in await store.agents_in(realm):
        a = v.payload["key"]
        latest = await store.latest_movement(a)
        if latest is None or "waypoints" not in latest.payload:
            continue
        pl = latest.payload
        r = _f.Route(tuple(tuple(q) for q in pl["waypoints"]),
                     pl["departed_at"], pl.get("arrives_at"))
        positions[a] = _f.route_position(r, now)
        rows = await store._c.find_vertices("agents", realm="genome_agents",
                                            filters={"key": a}, limit=1)
        metas[a] = rows[0].payload if rows else {}
    agents = sorted(positions)
    hits = 0
    for i, a in enumerate(agents):
        for b in agents[i + 1:]:
            ax, ay = positions[a]; bx, by = positions[b]
            if (ax - bx) ** 2 + (ay - by) ** 2 > CONTACT_RADIUS ** 2:
                continue
            pair = f"{realm}|{a}|{b}"
            if now - _recent_pairs.get(pair, 0) < 1800:
                continue
            _recent_pairs[pair] = now
            # contagion at contact (Rules 2.4/2.5): each may infect the other
            from genome_core import pathogen as _pg
            for src, dst in ((a, b), (b, a)):
                strain = _pg.try_transmit(f"{pair}:{int(now)}",
                                          metas[src], metas[dst], now)
                if strain:
                    infected = _pg.infect(metas[dst], strain, now)
                    await store.put_agent(dst, infected)
                    metas[dst] = infected
                    if infected.get("owner_user_id"):
                        from genome_core import notify as _nf
                        await _nf.emit(store._c, infected["owner_user_id"],
                                       "agents", "infection",
                                       f"{infected.get('name', dst)} caught "
                                       f"{strain['strain_uuid']} in a meeting.")
            for me, other in ((a, b), (b, a)):
                om = metas[other]
                await store.schedule(
                    realm, f"meet-{me}-{int(now)}", _d._iso(now), "encounter",
                    me, {"other": {"agent_uuid": other,
                                   "colour_pair": om.get("colour_pair"),
                                   "infected": bool(om.get("infected"))},
                         "opinion": (metas[me].get("opinions", {})
                                     .get(other))})
            hits += 1
    return hits


async def tick_once(store: GenomeStore, realm: str, decider) -> int:
    now = time.time()
    happened = await _flood.tick(store, realm, now)
    if happened:
        logger.info("%s: %s", realm, happened)
    await sweep(store, realm, now)
    await heal(store, realm, now)
    done = 0
    for ev in await store.due_events(realm, drain._iso(now)):
        outcome = await drain.drain_one(store, realm, realm, ev, decider,
                                        seed=int(now))
        logger.info("%s %s -> %s", realm, ev.payload.get("subject"), outcome)
        done += 1
    return done


async def main() -> None:
    if not REALMS:
        raise SystemExit("set GENOME_REALMS")
    client = AsyncPostGraph(dsn=dsn())   # SCHEMA_PER_REALM deliberately unset
    await client.connect()
    store = GenomeStore(client)
    decider = make_decider(USE_LLM) if INLINE else None
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    logger.info("tick worker up: realms=%s llm=%s", REALMS, USE_LLM)
    try:
        while not stop.is_set():
            # user worlds are born at login (genesis) -- discover them each
            # cycle so a new user's world starts ticking without a deploy
            realms = list(REALMS)
            try:
                for v in await client.get_vertices("agents",
                                                   realm="genome_agents"):
                    wr = v.payload.get("world_realm")
                    if wr and v.payload.get("key", "").startswith("user:")                             and wr not in realms:
                        realms.append(wr)
            except Exception:
                logger.exception("realm discovery failed")
            for realm in realms:
                try:
                    n = await tick_once(store, realm, decider)
                    if n:
                        logger.info("%s: drained %d", realm, n)
                except Exception:
                    logger.exception("tick failed for %s", realm)
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass
    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())
