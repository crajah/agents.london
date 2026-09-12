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
QUEUE = os.getenv("GENOME_QUEUE", "pg")   # "pg" (SKIP LOCKED) | "redis" (delay
# queue + atomic Lua claim, drained by a continuous consumer -- Phase 2)
INLINE = os.getenv("GENOME_INLINE_DECIDER", "0") == "1"   # tests only:
# system-spec Rule 8.4 -- production never decides on the world queue


def dsn() -> str:
    return os.getenv("POSTGRES_URI") or (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.getenv('POSTGRES_HOST', 'postgres-service')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.environ['POSTGRES_DB']}")


async def _payloads_for(store: GenomeStore, uuids: list) -> dict:
    """Every named agent's payload in ONE query. The per-agent containment
    lookup cost ~36ms of seq-scan CPU each; heal and sweep issuing one per
    agent per tick kept the database pinned after every other storm was
    out (measured 2026-09-05)."""
    if not uuids:
        return {}
    rows = await store._c.find_vertices(
        "agents", realm="genome_agents",
        where=[("key", "in", list(uuids))], limit=len(uuids))
    return {r.payload.get("key"): r.payload for r in rows}


async def heal(store: GenomeStore, realm: str, now: float) -> int:
    """Schedule a decide for any present agent with nothing pending."""
    pending_subjects = {v.payload.get("subject")
                        for v in await store._c.find_vertices(
                            "events", realm=realm,
                            where=[("done_at", "is_null", None)],
                            limit=2000)}
    # an agent whose question sits in the decision queue is NOT idle -- without
    # this, heal scheduled a fresh decide every tick while the decider worked,
    # and the event table grew a 279-deep backlog of stale questions
    pending_subjects |= {v.payload.get("agent_uuid")
                        for v in await store._c.find_vertices(
                            "decision_queue", realm="genome_agents",
                            filters={"world_realm": realm},
                            where=[("done_at", "is_null", None)],
                            limit=2000)}
    healed = 0
    present = [v.payload["key"] for v in await store.agents_in(realm)]
    payloads = await _payloads_for(store, present)
    for a in present:
        apl = payloads.get(a, {})
        from genome_core import pathogen as _pth
        if len(apl.get("antigens") or []) > _pth.ANTIGEN_CAP:
            # inert antigens cost storage and detoast CPU on every read;
            # the payload is already in hand here, so shrink it in passing
            apl = {**apl, "antigens": _pth.prune_antigens(apl["antigens"],
                                                          now)}
            await store.put_agent(a, apl)
        if apl.get("genotype") and "perishes_at" not in apl:
            await _d.schedule_perish(store, a, apl, now)   # the reaper learns
        if 0.0 < apl.get("stamina_max", 1.0) < 0.25 and apl.get("alive", True):
            # burnout band (user directive 2026-09-05: under a quarter of
            # max stamina the agent dies and respawns) -- send it through
            # the game's own death rather than leaving it limping forever
            await store.schedule(realm, f"burnout-{a}", drain._iso(now),
                                 "perish", a, {"cause": "attrition"})
        if a in pending_subjects:
            continue
        latest = await store.latest_movement(a)
        if latest and latest.payload.get("arrives_at", 0) > now:
            continue                      # still travelling; arrival comes
        # STABLE key per agent (dedup fix 2026-09-13): the random key let two
        # heal cycles that both saw the agent idle each add a decide, and the
        # key-based Redis member could not fold them; one key per agent upserts.
        await store.schedule(realm, f"decide-{a}",
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
    wmeta = await _d._world_payload(store, realm)
    positions = {}
    cargo_by: dict[str, dict] = {}
    present = [v.payload["key"] for v in await store.agents_in(realm)]
    metas = await _payloads_for(store, present)
    for a in present:
        latest = await store.latest_movement(a)
        if latest is None or "waypoints" not in latest.payload:
            metas.pop(a, None)
            continue
        pl = latest.payload
        r = _f.Route(tuple(tuple(q) for q in pl["waypoints"]),
                     pl["departed_at"], pl.get("arrives_at"))
        positions[a] = _f.route_position(r, now)
        cargo_by[a] = pl.get("cargo") or {}     # cache: no re-fetch on contact
        metas.setdefault(a, {})
    # Spatial-grid proximity (Phase 3): bucket agents into cells the size of the
    # contact radius, so any pair in contact lands in the same or an adjacent
    # cell. Checking the 9-cell neighbourhood is O(n) for a spread-out world
    # instead of the old all-pairs O(n^2) that made a 98-agent world's sweep the
    # tick's dominant cost.
    cell = max(CONTACT_RADIUS, 1e-6)
    grid: dict[tuple[int, int], list] = {}
    for a, (ax, ay) in positions.items():
        grid.setdefault((int(ax / cell), int(ay / cell)), []).append(a)
    from genome_core import pathogen as _pg
    hits = 0
    for a, (ax, ay) in positions.items():
        cx, cy = int(ax / cell), int(ay / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in grid.get((cx + dx, cy + dy), ()):
                    if other <= a:              # each unordered pair once
                        continue
                    ox, oy = positions[other]
                    if (ax - ox) ** 2 + (ay - oy) ** 2 > CONTACT_RADIUS ** 2:
                        continue
                    pair = f"{realm}|{a}|{other}"
                    if now - _recent_pairs.get(pair, 0) < 1800:
                        continue
                    _recent_pairs[pair] = now
                    # contagion at contact (Rules 2.4/2.5)
                    for src, dst in ((a, other), (other, a)):
                        strain = _pg.try_transmit(f"{pair}:{int(now)}",
                                                  metas[src], metas[dst], now)
                        if strain:
                            infected = _pg.infect(
                                metas[dst], strain, now,
                                time_scale=wmeta.get("time_scale", 1.0))
                            await store.put_agent(dst, infected)
                            metas[dst] = infected
                            if infected.get("owner_user_id"):
                                from genome_core import notify as _nf
                                await _nf.emit(
                                    store._c, infected["owner_user_id"],
                                    "agents", "infection",
                                    f"{infected.get('name', dst)} caught "
                                    f"{strain['strain_uuid']} in a meeting.")
                    for me, oth in ((a, other), (other, a)):
                        om = metas[oth]
                        await store.schedule(
                            realm, f"meet-{me}-{int(now)}", _d._iso(now),
                            "encounter", me,
                            {"other": {"agent_uuid": oth,
                                       "colour_pair": om.get("colour_pair"),
                                       "cargo": cargo_by.get(oth, {}),
                                       "infected": bool(om.get("infections"))},
                             "opinion": (metas[me].get("opinions", {})
                                         .get(oth))})
                    hits += 1
    return hits


PRUNE_AGE_S = 86400.0


async def prune_done(store: GenomeStore, realm: str, now: float) -> int:
    """Operational hygiene: done events older than a day leave the table.
    The queue polls load whole tables; without pruning, memory grows with
    history and the workers OOM on schedule (observed twice). The decision
    RECORD lives in the decisions table and is never touched (Rule 6.1)."""
    try:
        cutoff = drain._iso(now - PRUNE_AGE_S)
        return await store._c.delete_vertices(
            "events", realm=realm,
            where=[("done_at", "not_null", None), ("done_at", "<", cutoff)])
    except Exception:
        logger.exception("prune failed for %s", realm)
        return 0


MOVEMENT_RETENTION_S = float(os.getenv("MOVEMENT_RETENTION_S", str(48 * 3600)))
MOVEMENT_PRUNE_INTERVAL_S = float(os.getenv("MOVEMENT_PRUNE_INTERVAL_S", "600"))
MOVEMENT_PRUNE_BATCH = int(os.getenv("MOVEMENT_PRUNE_BATCH", "20000"))


async def prune_movement(store: GenomeStore, now: float) -> int:
    """agents_data is the append-only position log (store.set_movement appends
    a row per move); only the NEWEST row per agent is live state, read by
    latest_movement / find-latest. Left unbounded it reached 1.1M rows / 1.6GB
    for ~300 agents, and its per-agent key scans starved the pool until the sim
    froze (incident 2026-09-10). Trim rows past the retention window that are
    NOT an agent's newest — so current position (even for an agent idle beyond
    the window) and a recent tail are always kept — in one bounded batch that
    never locks the table for long. Shard 0 only; movement lives under the
    single 'genome_agents' realm, so this is global, not per-world."""
    try:
        status = await store._c.execute(
            "DELETE FROM public.agents_data WHERE ctid IN ("
            "  SELECT a.ctid FROM public.agents_data a"
            "  JOIN (SELECT realm, id, max(\"timestamp\") AS mx"
            "          FROM public.agents_data WHERE realm=$1"
            "          GROUP BY realm, id) m"
            "    ON a.realm = m.realm AND a.id = m.id"
            "  WHERE a.realm = $1"
            "    AND a.\"timestamp\" < now() - make_interval(secs => $2)"
            "    AND a.\"timestamp\" < m.mx"
            "  LIMIT $3)",
            "genome_agents", int(MOVEMENT_RETENTION_S), MOVEMENT_PRUNE_BATCH)
        try:                                   # asyncpg returns e.g. "DELETE 42"
            return int(str(status).rsplit(" ", 1)[-1])
        except (ValueError, IndexError):
            return 0
    except Exception:
        logger.exception("movement prune failed")
        return 0


AUDIT_RETENTION_S = float(os.getenv("AUDIT_RETENTION_S", str(7 * 86400)))
AUDIT_TRIM_INTERVAL_S = float(os.getenv("AUDIT_TRIM_INTERVAL_S", "3600"))


async def trim_audit(store: GenomeStore) -> int:
    """The *_audit tables are trigger-maintained forensic logs with no
    application reader; left unbounded they reached 462MB (truncated
    2026-09-10). Drop rows past the retention window from every public.*_audit
    table so the footprint never rebuilds. Table names come from the catalogue
    (LIKE '%_audit'), not user input. Shard 0 only."""
    total = 0
    try:
        tables = await store._c.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename LIKE '%\\_audit'")
        for row in tables:
            t = row["tablename"]
            status = await store._c.execute(
                f'DELETE FROM public."{t}" '
                "WHERE changed_at < now() - make_interval(secs => $1)",
                int(AUDIT_RETENTION_S))
            try:
                total += int(str(status).rsplit(" ", 1)[-1])
            except (ValueError, IndexError):
                pass
    except Exception:
        logger.exception("audit trim failed")
    return total


DONE_RETENTION_S = float(os.getenv("DONE_RETENTION_S", "900"))     # 15 min
DONE_PRUNE_INTERVAL_S = float(os.getenv("DONE_PRUNE_INTERVAL_S", "120"))
DONE_PRUNE_BATCH = int(os.getenv("DONE_PRUNE_BATCH", "20000"))


async def prune_done_rows(store: GenomeStore, now: float) -> int:
    """events and decision_queue accumulate DONE (already-processed) rows;
    nothing ever reads a done row (the drain only reads done_at IS NULL). The
    per-realm prune_done covered only events and did not keep up -- events
    reached 169k and decision_queue 49k, and the bloated reads stalled the sim
    (incident 2026-09-10). This is a GLOBAL, bounded delete of processed rows
    past a short retention window, across every realm, on shard 0 only. Batched
    by ctid so no single statement locks a table for long."""
    total = 0
    cutoff = drain._iso(now - DONE_RETENTION_S)
    for tbl, col in (("events", "p_done_at"),
                     ("decision_queue", "(payload->>'done_at')")):
        try:
            status = await store._c.execute(
                f"DELETE FROM public.{tbl} WHERE ctid IN ("
                f"  SELECT ctid FROM public.{tbl} "
                f"  WHERE {col} IS NOT NULL AND {col} < $1 LIMIT $2)",
                cutoff, DONE_PRUNE_BATCH)
            try:
                total += int(str(status).rsplit(" ", 1)[-1])
            except (ValueError, IndexError):
                pass
        except Exception:
            logger.exception("done-row prune failed for %s", tbl)
    return total


PRESENCE_RECONCILE_INTERVAL_S = float(
    os.getenv("PRESENCE_RECONCILE_INTERVAL_S", "60"))
CACHE_CONSOLIDATE_INTERVAL_S = float(
    os.getenv("CACHE_CONSOLIDATE_INTERVAL_S", "300"))
EVENT_LEASE_S = float(os.getenv("EVENT_LEASE_S", "30"))   # claim-queue lease:
# a worker that dies leaves its claimed events re-claimable after this lapses
REAP_INTERVAL_S = float(os.getenv("REAP_INTERVAL_S", "120"))
REAP_OVERDUE_S = float(os.getenv("REAP_OVERDUE_S", "1200"))   # 20 min past due
# Only the re-generable "about to think/meet" events are ever reaped -- an agent
# that misses one just idles a beat and the sweep hands it a fresh one. NEVER
# reap state-committing events (construction_done finalises a build, evacuate
# carries a flood/gather hop, mating_answer/negotiate close a pair-deal): those
# must FIRE, so capacity (more shards) drains them, not the flush.
REAPABLE_KINDS = {"decide", "arrival", "deposit_arrival", "encounter",
                  "encounter_answer", "mating_proposal", "mating_answer"}


async def reap_stale_events(store: GenomeStore, realm: str, now: float,
                            cap: int = 1000) -> int:
    """Resilience valve (user directive 2026-09-13): re-generable agent events
    left far past due are orphans -- their agent almost certainly drowned and
    regenerated a flood ago -- and keep a world 'stalled' forever. Complete the
    oldest such events so the queue drains; structural events are never touched.
    due_events is oldest-first, so once we reach a fresh one the rest are fresh."""
    cutoff = now - REAP_OVERDUE_S
    reaped = 0
    for ev in await store.due_events(realm, drain._iso(now), limit=cap):
        if float(ev.payload.get("due_at") or now) > cutoff:
            break
        if ev.payload.get("kind") in REAPABLE_KINDS:
            await store.complete_event(realm, ev.payload["key"], drain._iso(now))
            reaped += 1
    return reaped


async def recover_stale(store: GenomeStore, now: float) -> tuple[int, int]:
    """Phase 2c: re-add stale, undone rows back into the Redis queues so they
    DRAIN PROPERLY. The ZSET+ZREM claim has no lease -- a pod that restarts
    mid-claim removes an event/decision from Redis but leaves it undone in PG,
    stranding it. This re-seeds anything overdue by > REAP_OVERDUE_S from the
    durable PG truth (idempotent ZADD). Safe: fresh in-flight rows are younger
    than the threshold, so they are never re-added (no double-processing), and
    truly-stuck rows -- ANY kind, structural included -- get re-drained by
    drain_one instead of discarded. Redis mode only; shard 0."""
    from genome_core import redisq
    rq = redisq.queue()
    if rq is None:
        return (0, 0)
    import json as _json
    cutoff = drain._iso(now - REAP_OVERDUE_S)
    # events
    ev_rows = await store._c.fetch(
        "SELECT realm, payload FROM events "
        "WHERE p_done_at IS NULL AND p_due_at <= $1", cutoff)
    ev_members = []
    for r in ev_rows:
        pl = r["payload"]
        if isinstance(pl, str):
            pl = _json.loads(pl)
        try:
            due = float(pl.get("due_at") or 0.0)
        except (TypeError, ValueError):
            due = 0.0
        ev_members.append((rq.member(r["realm"], pl.get("subject") or "", pl["key"]),
                           due))
    n_ev = await rq.reseed(ev_members, key=redisq.SCHED_KEY)
    # decisions (payload-based filter: schema-agnostic on decision_queue)
    dq_rows = await store._c.fetch(
        "SELECT payload FROM decision_queue "
        "WHERE payload->>'done_at' IS NULL AND payload->>'queued_at' <= $1",
        cutoff)
    dq_members = []
    for r in dq_rows:
        pl = r["payload"]
        if isinstance(pl, str):
            pl = _json.loads(pl)
        try:
            qa = float(pl.get("queued_at") or 0.0)
        except (TypeError, ValueError):
            qa = 0.0
        dq_members.append((rq.decision_member(pl.get("agent_uuid", ""),
                                              pl["key"]), qa))
    n_dq = await rq.reseed(dq_members, key=redisq.DECISIONS_KEY)
    return (n_ev, n_dq)


async def reconcile_presence(store: GenomeStore) -> int:
    """Enforce Rule 6.10 -- an agent is present in exactly ONE world. Stale
    events in other realms fired transfers from the wrong origin, so old
    presence was never cleared and agents ended up present in up to 6 worlds at
    once (inflating populations to 100s, leaving ghost dots at teleport points).
    set_presence doesn't enforce the invariant, so shard 0 continuously does:
    keep each agent's most-recent present=true and clear every older one."""
    try:
        status = await store._c.execute(
            "UPDATE public.presence p "
            "SET payload = jsonb_set(p.payload,'{present}','false') "
            "WHERE p.payload->>'present'='true' AND EXISTS ("
            "  SELECT 1 FROM public.presence q "
            "  WHERE q.payload->>'key' = p.payload->>'key' "
            "    AND q.payload->>'present'='true' "
            "    AND q.updated_at > p.updated_at)")
        try:
            return int(str(status).rsplit(" ", 1)[-1])
        except (ValueError, IndexError):
            return 0
    except Exception:
        logger.exception("presence reconcile failed")
        return 0


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
    # Draining moved OFF the per-realm path (scale rewrite Phase 1, 2026-09-13):
    # events are now drained from a SHARED claim-queue by drain_claimed(), so a
    # hot world's events are worked by the whole pool, not the one worker that
    # owns its realm. tick_once is maintenance only (sweep/heal/flood/spawn).
    return 0


async def drain_claimed(store: GenomeStore, decider,
                        max_batches: int = 12, batch: int = 64) -> int:
    """Competing-consumers drain: pull leased batches of due events across ALL
    realms and process them, oldest-first. Whole-subject leasing keeps one
    agent's events on one worker (serial, in due order); DIFFERENT subjects run
    concurrently (capped). Any worker drains any world -- throughput scales with
    the pool, not with how realms are sharded."""
    done = 0
    for _ in range(max_batches):
        now = time.time()
        lease_until = drain._iso(now + EVENT_LEASE_S)
        claimed = await store.claim_due_events(drain._iso(now), lease_until,
                                               batch=batch)
        if not claimed:
            break
        groups: dict[str, list] = {}
        for ev in claimed:
            groups.setdefault(ev.payload.get("subject") or "", []).append(ev)
        sem = asyncio.Semaphore(8)

        async def _drain_subject(evs):
            nonlocal done
            async with sem:
                # one subject's events, oldest-first, serial
                for ev in sorted(evs, key=lambda e: e.payload.get("due_at", "")):
                    try:
                        outcome = await drain.drain_one(
                            store, ev.realm, ev.realm, ev, decider,
                            seed=int(time.time()))
                        logger.info("%s %s -> %s", ev.realm,
                                    ev.payload.get("subject"), outcome)
                        done += 1
                    except Exception:
                        logger.exception("drain failed for %s in %s",
                                         ev.payload.get("subject"), ev.realm)
        await asyncio.gather(*(_drain_subject(evs) for evs in groups.values()))
    return done


async def reseed_redis(store: GenomeStore, rq) -> int:
    """Rebuild the delay queue from PG's undone events (startup / Redis loss).
    PG is the durable truth; ZADD is idempotent so this is safe to re-run."""
    rows = await store._c.fetch(
        "SELECT realm, payload FROM events WHERE p_done_at IS NULL")
    import json as _json
    members = []
    for r in rows:
        pl = r["payload"]
        if isinstance(pl, str):
            pl = _json.loads(pl)
        try:
            due = float(pl.get("due_at") or 0.0)
        except (TypeError, ValueError):
            due = 0.0
        members.append((rq.member(r["realm"], pl.get("subject") or "", pl["key"]), due))
    return await rq.reseed(members)


async def redis_consumer_loop(store: GenomeStore, decider, stop) -> None:
    """Continuous competing-consumer: claim the oldest due events (whole-subject,
    atomic Lua) and drain them, with NO tick-cycle gate -- this is what fixes the
    idle-between-bursts throughput of the PG path. drain_one completes the PG
    event itself; the claim already removed the member from the queue."""
    from genome_core import redisq
    from types import SimpleNamespace as _NS
    sem = asyncio.Semaphore(8)
    idle = 0
    while not stop.is_set():
        rq = redisq.queue()
        if rq is None:
            await asyncio.sleep(1.0)
            continue
        claimed = await rq.claim(time.time(), max_subjects=64)
        if not claimed:
            idle = min(idle + 1, 5)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.1 * idle)
            except (TimeoutError, asyncio.TimeoutError):
                pass
            continue
        idle = 0
        groups: dict[str, list] = {}
        for d in claimed:
            groups.setdefault(d.get("subject") or "", []).append(d)

        async def _drain_subject(items):
            async with sem:
                # load each claimed event by key from the durable PG row; a key
                # already done/gone is skipped (dedup: duplicate members for one
                # event, or a member left over after completion, never re-run)
                for d in items:
                    key = d.get("key")
                    realm = d.get("realm")
                    if not key or not realm:
                        continue
                    ev = await store.get_pending_event(realm, key)
                    if ev is None:
                        continue
                    try:
                        outcome = await drain.drain_one(
                            store, realm, realm, ev, decider,
                            seed=int(time.time()))
                        logger.info("%s %s -> %s (redis)", realm,
                                    d.get("subject"), outcome)
                    except Exception:
                        logger.exception("redis drain failed for %s in %s",
                                         d.get("subject"), realm)
        await asyncio.gather(*(_drain_subject(v) for v in groups.values()))


async def main() -> None:
    from genome_core import metrics as _metrics
    _metrics.serve(9100)   # pod annotation scrape (marty infra/telemetry)
    if not REALMS:
        raise SystemExit("set GENOME_REALMS")
    client = AsyncPostGraph(dsn=dsn(), pool_min_size=1, pool_max_size=4,
                            statement_cache_size=0)  # pgbouncer; SCHEMA_PER_REALM unset
    await client.connect()
    store = GenomeStore(client)
    decider = make_decider(USE_LLM) if INLINE else None
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    logger.info("tick worker up: shard %d/%d, seed realms=%s llm=%s queue=%s",
                SHARD_INDEX, SHARD_COUNT, REALMS, USE_LLM, QUEUE)
    consumer_task = None
    if QUEUE == "redis":
        from genome_core import redisq
        if await redisq.init():
            logger.info("redis queue: connected")
            if SHARD_INDEX == 0:
                # one worker reseeds the durable PG backlog into the queue on
                # startup (idempotent ZADD); the rest just consume + write-through
                seeded = await reseed_redis(store, redisq.queue())
                logger.info("redis queue: reseeded %d undone events", seeded)
            consumer_task = asyncio.create_task(
                redis_consumer_loop(store, decider, stop))
        else:
            logger.warning("redis queue: unreachable -- falling back to pg drain")
    cycle = 0
    realms = list(REALMS)
    last_movement_prune = 0.0
    last_audit_trim = 0.0
    last_done_prune = 0.0
    last_presence_reconcile = 0.0
    last_cache_consolidate = 0.0
    last_reap = 0.0
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
            # shared claim-queue drain (Phase 1, PG SKIP LOCKED). Skipped when
            # the Redis queue (Phase 2) is active -- there a continuous consumer
            # task drains instead, ungated by this tick cycle. This path also
            # covers the redis-unreachable fallback.
            from genome_core import redisq as _rq
            if _rq.queue() is None:
                try:
                    drained = await drain_claimed(store, decider)
                    if drained:
                        logger.info("shared queue: drained %d events", drained)
                except Exception:
                    logger.exception("shared drain failed")
            if SHARD_INDEX == 0 and cycle % 5 == 0:
                # the postman rides with shard 0 (system-spec §10): a no-op
                # until GENOME_SMTP_HOST arrives, then the outbox drains
                try:
                    from genome_core import mailer
                    n = await mailer.send_pending(client)
                    if n:
                        logger.info("outbox: %d sent", n)
                except Exception:
                    logger.exception("outbox drain failed")
            due = time.time() - last_movement_prune > MOVEMENT_PRUNE_INTERVAL_S
            if SHARD_INDEX == 0 and due:
                last_movement_prune = time.time()
                pruned_rows = await prune_movement(store, time.time())
                if pruned_rows:
                    logger.info("movement history: pruned %d rows", pruned_rows)
            audit_due = time.time() - last_audit_trim > AUDIT_TRIM_INTERVAL_S
            if SHARD_INDEX == 0 and audit_due:
                last_audit_trim = time.time()
                trimmed = await trim_audit(store)
                if trimmed:
                    logger.info("audit tables: trimmed %d rows", trimmed)
            done_due = time.time() - last_done_prune > DONE_PRUNE_INTERVAL_S
            if SHARD_INDEX == 0 and done_due:
                last_done_prune = time.time()
                dr = await prune_done_rows(store, time.time())
                if dr:
                    logger.info("done rows: pruned %d (events+decision_queue)",
                                dr)
            pres_due = time.time() - last_presence_reconcile > \
                PRESENCE_RECONCILE_INTERVAL_S
            if SHARD_INDEX == 0 and pres_due:
                last_presence_reconcile = time.time()
                fixed = await reconcile_presence(store)
                if fixed:
                    logger.info("presence: cleared %d stale (agent in >1 world)",
                                fixed)
            cache_due = time.time() - last_cache_consolidate > \
                CACHE_CONSOLIDATE_INTERVAL_S
            if SHARD_INDEX == 0 and cache_due:
                # commons + construction-tree maintenance (user directive
                # 2026-09-12), idempotent so a tidy world is a no-op:
                #   - one larder per world (colour), capped 10/kind;
                #   - re-cost persisting sites to the relaxed tree so the ark
                #     path stops being blocked by grandfathered family_all costs.
                last_cache_consolidate = time.time()
                for cr in [r for r in realms if r.startswith("genome_commons")]:
                    try:
                        res = await drain.construction.consolidate_caches(
                            store._c, cr)
                        if res.get("merged") or res.get("destroyed") \
                                or res.get("capped"):
                            logger.info("commons %s: merged %d larders, "
                                        "destroyed %d dupes, capped %d kinds",
                                        cr, res["merged"], res["destroyed"],
                                        res["capped"])
                    except Exception:
                        logger.exception("cache consolidate failed: %s", cr)
                for r in realms:
                    try:
                        meta = await drain._world_payload(store, r)
                        if not meta or meta.get("is_commons"):
                            continue
                        rc = await drain.construction.recost_sites(
                            store._c, r, meta.get("kinds") or [], time.time())
                        if rc.get("recosted") or rc.get("completed"):
                            logger.info("recost %s: %d sites re-costed, "
                                        "%d completed", r, rc["recosted"],
                                        rc["completed"])
                    except Exception:
                        logger.exception("recost failed: %s", r)
                # uniform teleport layout (user directive 2026-09-13): lay every
                # world's doors out on concentric rings, like the commons.
                # Deterministic -> idempotent (a tidy map is a no-op).
                try:
                    moved = await drain.relayout_all_portals(store)
                    if moved:
                        logger.info("teleport layout: tidied %d worlds", moved)
                except Exception:
                    logger.exception("portal relayout failed")
            reap_due = time.time() - last_reap > REAP_INTERVAL_S
            if SHARD_INDEX == 0 and reap_due:
                last_reap = time.time()
                from genome_core import redisq as _rqr
                if _rqr.queue() is not None:
                    # Phase 2c: redis mode -- RE-SEED stale undone rows so they
                    # drain PROPERLY (recovers all kinds lost to restart, incl.
                    # structural), rather than discarding them like the reaper.
                    try:
                        n_ev, n_dq = await recover_stale(store, time.time())
                        if n_ev or n_dq:
                            logger.info("recovered %d stale events, %d stale "
                                        "decisions back into the queues",
                                        n_ev, n_dq)
                    except Exception:
                        logger.exception("recover_stale failed")
                else:
                    # pg mode: age+kind-gated flush of re-generable orphans so
                    # no world stays stalled on ancient stragglers.
                    total = 0
                    for r in realms:
                        try:
                            total += await reap_stale_events(store, r,
                                                             time.time())
                        except Exception:
                            logger.exception("reap failed: %s", r)
                    if total:
                        logger.info("reaped %d stale orphan events across %d "
                                    "realms", total, len(realms))
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
