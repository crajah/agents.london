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
from genome_core import spawnpool as _spawn
from genome_core import drain as _d
from genome_core.decider import make_decider
from genome_core.store import GenomeStore

logger = logging.getLogger("genome.tick")

REALMS = [r for r in os.getenv("GENOME_REALMS", "").split(",") if r]

# Horizontal sharding: replica k of N owns realms where crc32(realm) % N == k.
# Worlds are independent (realm-per-world), so static sharding needs no
# coordination; the ordinal comes from the StatefulSet pod name.
import zlib


def _shard_index() -> int:
    if os.getenv("SHARD_INDEX"):
        return int(os.environ["SHARD_INDEX"])
    name = os.getenv("POD_NAME", "")
    tail = name.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


SHARD_COUNT = max(1, int(os.getenv("SHARD_COUNT", "1")))
SHARD_INDEX = _shard_index() % SHARD_COUNT


def mine(realm: str) -> bool:
    return zlib.crc32(realm.encode()) % SHARD_COUNT == SHARD_INDEX
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


PRUNE_AGE_S = 86400.0


async def prune_done(store: GenomeStore, realm: str, now: float) -> int:
    """Operational hygiene: done events older than a day leave the table.
    The queue polls load whole tables; without pruning, memory grows with
    history and the workers OOM on schedule (observed twice). The decision
    RECORD lives in the decisions table and is never touched (Rule 6.1)."""
    gone = 0
    try:
        for v in await store._c.get_vertices("events", realm=realm):
            pl = v.payload
            done = pl.get("done_at")
            if done and float(done) < now - PRUNE_AGE_S:
                await store._c.delete_vertex("events", realm=realm,
                                             vertex_id=str(v.id))
                gone += 1
    except Exception:
        logger.exception("prune failed for %s", realm)
    return gone


async def tick_once(store: GenomeStore, realm: str, decider,
                    do_heal: bool = True) -> int:
    now = time.time()
    meta = await drain._world_payload(store, realm)
    if meta.get("paused"):
        return 0                            # Phase 13: a paused world rests
    if do_heal:
        pruned = await prune_done(store, realm, now)
        if pruned:
            logger.info("%s: pruned %d done events", realm, pruned)
        try:
            cfg = await _spawn.get_config(store._c)
            born = await _spawn.maybe_spawn(store, realm, meta, cfg, now)
            if born:
                logger.info("%s: free agent %s joins the world", realm, born)
        except Exception:
            logger.exception("free spawn failed for %s", realm)
    happened = await _flood.tick(store, realm, now)
    if happened:
        logger.info("%s: %s", realm, happened)
    await sweep(store, realm, now)
    if do_heal:
        await heal(store, realm, now)
    done = 0
    # parallelise-everything: events for DIFFERENT agents drain concurrently
    # (capped); one agent's events stay serial in due order -- state races
    # are per-agent, never cross-agent
    groups: dict[str, list] = {}
    for ev in await store.due_events(realm, drain._iso(now)):
        key = ev.payload.get("subject")
        if ev.payload.get("kind") in ("encounter_answer", "mating_answer"):
            # pair events must serialize with their COUNTERPART, not just
            # their own agent -- two first-writers raced and split the pair
            other = (ev.payload.get("payload", {}).get("other", {})
                     .get("agent_uuid")) or \
                (ev.payload.get("payload", {}).get("proposer", {})
                 .get("agent_uuid")) or ""
            key = "pair:" + "|".join(sorted((key or "", other)))
        groups.setdefault(key, []).append(ev)
    sem = asyncio.Semaphore(8)

    async def _drain_agent(evs):
        nonlocal done
        async with sem:
            for ev in evs:
                try:
                    outcome = await drain.drain_one(store, realm, realm, ev,
                                                    decider, seed=int(now))
                    logger.info("%s %s -> %s", realm,
                                ev.payload.get("subject"), outcome)
                    done += 1
                except Exception:
                    logger.exception("drain failed for %s",
                                     ev.payload.get("subject"))
    await asyncio.gather(*(_drain_agent(evs) for evs in groups.values()))
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
    logger.info("tick worker up: shard %d/%d, seed realms=%s llm=%s",
                SHARD_INDEX, SHARD_COUNT, REALMS, USE_LLM)
    cycle = 0
    realms = list(REALMS)
    try:
        while not stop.is_set():
            # user worlds are born at login (genesis) -- rediscover every
            # tenth cycle; heal is a backstop and runs every fifth. The
            # realms tick IN PARALLEL: a slow world no longer starves the
            # others of event latency (constant-motion revision).
            if cycle % 10 == 0:
                try:
                    realms = list(REALMS)
                    for v in await client.get_vertices("agents",
                                                       realm="genome_agents"):
                        wr = v.payload.get("world_realm")
                        # user worlds AND the commons: the market square has
                        # its own events and encounters -- it went unswept
                        # for a day because discovery only knew "user:" rows
                        if wr and v.payload.get("key", "").startswith(
                                ("user:", "commons:")) and wr not in realms:
                            realms.append(wr)
                except Exception:
                    logger.exception("realm discovery failed")

            async def _tick(realm):
                try:
                    n = await tick_once(store, realm, decider,
                                        do_heal=(cycle % 5 == 0))
                    if n:
                        logger.info("%s: drained %d", realm, n)
                except Exception:
                    logger.exception("tick failed for %s", realm)
            await asyncio.gather(*(_tick(r) for r in realms if mine(r)))
            cycle += 1
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
