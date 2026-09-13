"""genome decision worker — the economy caste working its own queue.

system-spec Rule 8.4: the world queue never blocks on inference; this worker
owns the unordered global decision queue. execution-spec Rules 8.1-8.3: one
single constrained call per ordinary decision, through the litellm router,
with the agent's assigned model. Rule 4.2: stateless — everything needed to
decide AND apply rides in the queue item.

Rule 5.2a's fallback lives here too: a failed decision falls back to the first
option, the agent continues, never freezes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
# in the image, shared/ sits beside decision-worker/ (/srv/shared); in the
# checkout it is at the repository root. parents[] raises IndexError past
# the filesystem root, so each candidate is resolved defensively.
for _depth in (1, 3):
    try:
        _shared = Path(__file__).resolve().parents[_depth] / "shared"
    except IndexError:
        continue
    if _shared.is_dir():
        sys.path.insert(0, str(_shared))
        break
from post_graph import AsyncPostGraph
from genome_core import drain, engine
from genome_core.decider import llm_decider
from genome_core.store import GenomeStore, AGENTS_REALM

logger = logging.getLogger("genome.decision")

POLL_SECONDS = float(os.getenv("GENOME_DECISION_POLL", "3"))

import zlib


def _shard_index() -> int:
    if os.getenv("SHARD_INDEX"):
        return int(os.environ["SHARD_INDEX"])
    name = os.getenv("POD_NAME", "")
    tail = name.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


SHARD_COUNT = max(1, int(os.getenv("SHARD_COUNT", "1")))
SHARD_INDEX = _shard_index() % SHARD_COUNT


def mine(agent_uuid: str) -> bool:
    """Replica k of N owns agents where crc32(uuid) % N == k -- no two
    replicas ever answer for the same agent, so no claim protocol and no
    races. Negotiation turns alternate agents but are strictly sequential
    (the next turn is scheduled only after this one applies), so cross-shard
    hand-offs are safe."""
    return zlib.crc32(agent_uuid.encode()) % SHARD_COUNT == SHARD_INDEX
USE_LLM = os.getenv("GENOME_USE_LLM", "1") == "1"


def dsn() -> str:
    return os.getenv("POSTGRES_URI") or (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.getenv('POSTGRES_HOST', 'postgres-service')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.environ['POSTGRES_DB']}")


async def work_one(store: GenomeStore, client, item) -> str:
    pl = item.payload
    from genome_core.decider import WORLD_CTX
    WORLD_CTX.set(pl.get("world_realm", "?"))
    now = time.time()
    req = engine.DecisionRequest(
        agent_uuid=pl["agent_uuid"], situation=pl["situation"],
        options=tuple(pl["options"]), context=pl["context"])
    rows = await client.find_vertices("agents", realm=AGENTS_REALM,
                                      filters={"key": pl["agent_uuid"]}, limit=1)
    agent_payload = rows[0].payload if rows else {}
    g = agent_payload.get("genotype")
    if pl["situation"] == "market":
        from genome_core.decider import market_decider
        action, det, model = ("leave", {}, "stub")
        if USE_LLM and g:
            action, det, model = market_decider(
                req, g, seed=int(now),
                objectives=agent_payload.get("objectives"))
        outcome = await drain.apply_market_turn(
            store, pl["world_realm"], pl["agent_uuid"], action,
            det.get("listing"), det.get("give"), det.get("want"), now)
        from genome_core.decider import LAST_PROMPT as _LP
        await store.record_decision(pl["agent_uuid"], {
            "at": drain._iso(now), "situation": "market",
            **({"prompt": _LP.get()} if model != "stub" and _LP.get()
               else {}),
            "options": list(req.options), "choice": action,
            "detail": det, "model": model, "tier": "deliberative"})
        await client.upsert_vertex("decision_queue", realm=AGENTS_REALM,
                                   vertex_id=int(item.id),
                                   payload={**pl, "done_at": drain._iso(now),
                                            "outcome": outcome})
        return outcome
    if pl["situation"] == "negotiate":
        from genome_core.decider import negotiate_decider
        from genome_core import budget as bdg
        from genome_core import negotiation as nego
        _wm = await drain._world_payload(store, pl["world_realm"])
        bucket = bdg.accrue(
            bdg.Bucket(agent_payload.get("budget_level", bdg.CAPACITY),
                       agent_payload.get("budget_at", now)), now,
            time_scale=_wm.get("time_scale", 1.0))
        can_counter = bucket.level >= 1.0
        action = offer = None
        model = "stub"
        if USE_LLM and g:
            action, offer, model = negotiate_decider(
                req, g, seed=int(now),
                objectives=agent_payload.get("objectives"),
                can_counter=can_counter)
        if action is None:
            state = {"participants": [pl["agent_uuid"], ""],
                     "turns": ([{"offer": req.context["last_offer"]}]
                               if req.context.get("last_offer") else []),
                     "status": "open"}
            action, offer = nego.fallback_turn(
                state, pl["agent_uuid"], req.context.get("my_cargo", {}))
        if action == "counter":
            bucket, _ = bdg.charge(bucket, "counter_offer", now)
        if rows:
            await client.upsert_vertex(
                "agents", realm=AGENTS_REALM, vertex_id=int(rows[0].id),
                space=pl["agent_uuid"],
                payload={**agent_payload, "budget_level": bucket.level,
                         "budget_at": bucket.updated_at})
        outcome = await drain.apply_negotiation_turn(
            store, pl["world_realm"], req.context["neg_key"],
            pl["agent_uuid"], action, offer, now)
        from genome_core.decider import LAST_PROMPT as _LP
        await store.record_decision(pl["agent_uuid"], {
            "at": drain._iso(now), "situation": "negotiate",
            **({"prompt": _LP.get()} if model != "stub" and _LP.get()
               else {}),
            "options": list(req.options), "choice": action,
            "offer": offer, "model": model, "tier": "deliberative"})
        await client.upsert_vertex("decision_queue", realm=AGENTS_REALM,
                                   vertex_id=int(item.id),
                                   payload={**pl, "done_at": drain._iso(now),
                                            "outcome": outcome})
        return outcome
    _prompt = None
    if USE_LLM and g:
        from genome_core import pathogen
        eff = pathogen.phenotype(agent_payload, now) \
            if agent_payload.get("infections") else g
        from genome_core import vitals as _vt

        # NON-BLOCKING decider (2026-09-13): llm_decider calls the router with
        # BLOCKING urllib, which froze this worker's event loop -- so sem=16
        # concurrency was wasted and decisions ran ONE at a time per worker, the
        # bottleneck that backed the queue up to 2000+ and stalled worlds. Run it
        # off the loop in a thread so all 16 slots issue LLM calls concurrently.
        # LAST_PROMPT is a contextvar (won't propagate back from the thread), so
        # capture it INSIDE the thread and return it alongside the choice.
        def _decide():
            from genome_core.decider import LAST_PROMPT as _LP
            c = llm_decider(req, eff, seed=int(now),
                            pools=_vt.pools(agent_payload, now),
                            objectives=agent_payload.get("objectives"),
                            heard=agent_payload.get("heard"),
                            capability=agent_payload.get("capability"),
                            prompt_mods=agent_payload.get("prompt_mods"),
                            influences=agent_payload.get("influences"))
            return c, _LP.get()
        (choice, model), _prompt = await asyncio.to_thread(_decide)
    else:
        choice, model = engine.stub_decider(req, int(now)), "stub"
    outcome = await drain.apply_decided(
        store, pl["world_realm"], pl["agent_uuid"], choice, model,
        pl["situation"], pl["options"], pl.get("event_payload", {}), now,
        prompt=_prompt if model != "stub" else None)
    await client.upsert_vertex("decision_queue", realm=AGENTS_REALM,
                               vertex_id=int(item.id),
                               payload={**pl, "done_at": drain._iso(now),
                                        "outcome": outcome})
    return outcome


async def reseed_decisions(client, rq) -> int:
    """Rebuild the Redis decision queue from PG's undone decision_queue rows
    (startup / Redis loss). Idempotent ZADD. Runs on shard 0."""
    rows = await client.find_vertices("decision_queue", realm=AGENTS_REALM,
                                      where=[("done_at", "is_null", None)],
                                      limit=100000)
    members = []
    for v in rows:
        pl = v.payload
        try:
            score = float(pl.get("queued_at") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        members.append((rq.decision_member(pl.get("agent_uuid", ""),
                                            pl["key"]), score))
    from genome_core import redisq as _rq
    return await rq.reseed(members, key=_rq.DECISIONS_KEY)


async def process_redis_decisions(store, client, rq) -> int:
    """Competing-consumer decisions: claim pending ones (whole-agent, atomic),
    load the durable PG row by key, and run work_one -- so any worker takes any
    agent's decision, no SHARD_COUNT. One agent's decisions stay serial."""
    claimed = await rq.claim_decisions(max_subjects=64)
    if not claimed:
        return 0
    groups: dict = {}
    for d in claimed:
        groups.setdefault(d.get("subject") or "", []).append(d)
    sem = asyncio.Semaphore(16)
    done = 0

    async def _work_agent(items):
        nonlocal done
        async with sem:
            for d in items:
                key = d.get("key")
                if not key:
                    continue
                rows = await client.find_vertices(
                    "decision_queue", realm=AGENTS_REALM,
                    filters={"key": key},
                    where=[("done_at", "is_null", None)], limit=1)
                if not rows:
                    continue                 # already done / pruned
                try:
                    outcome = await work_one(store, client, rows[0])
                    logger.info("%s %s -> %s (redis)",
                                rows[0].payload.get("world_realm"),
                                rows[0].payload.get("agent_uuid"), outcome)
                    done += 1
                except Exception:
                    logger.exception("redis decision failed for %s",
                                     d.get("subject"))
                    try:
                        await client.upsert_vertex(
                            "decision_queue", realm=AGENTS_REALM,
                            vertex_id=int(rows[0].id),
                            payload={**rows[0].payload,
                                     "done_at": drain._iso(time.time()),
                                     "outcome": "error"})
                    except Exception:
                        pass
    await asyncio.gather(*(_work_agent(v) for v in groups.values()))
    return done


async def main() -> None:
    from genome_core import metrics as _metrics
    _metrics.serve(9100)   # pod annotation scrape (marty infra/telemetry)
    client = AsyncPostGraph(dsn=dsn(), pool_min_size=1, pool_max_size=4,
                            statement_cache_size=0)  # pgbouncer; SCHEMA_PER_REALM unset
    await client.connect()
    store = GenomeStore(client)
    # Write-through to the Redis event queue (Phase 2): decisions this worker
    # applies schedule follow-up events (mining_done, arrival, ...); with the
    # queue on Redis those must mirror there too, so store.schedule reaches it.
    if os.getenv("GENOME_QUEUE", "pg") == "redis":
        from genome_core import redisq
        if await redisq.init():
            logger.info("redis queue: connected (decision consumer)")
            if SHARD_INDEX == 0:
                try:
                    n = await reseed_decisions(client, redisq.queue())
                    logger.info("redis decisions: reseeded %d pending", n)
                except Exception:
                    logger.exception("decision reseed failed")
        else:
            logger.warning("redis unreachable -- decision-worker on pg poll")
    # Consumption accounting: genome inference lands in the platform ledger
    # like every other processing action. A DEDICATED schema-per-realm
    # client keeps the ledger in the platform_system schema regardless of
    # this worker's own realm-as-column mode; accounting must never stop
    # the worker (AG Rule 12.2).
    meter = None
    try:
        from contextlib import asynccontextmanager as _acm
        from metering import configure as _meter_configure

        @_acm
        async def _meter_client(org_id: str):
            c = AsyncPostGraph(dsn=dsn(), schema_per_realm=True,
                               pool_min_size=0, pool_max_size=2,
                               statement_cache_size=0)
            await c.connect()
            try:
                yield c
            finally:
                await c.close()

        meter = _meter_configure(_meter_client)
        await meter.start()
    except Exception:
        logger.exception("metering unavailable; decisions run unmetered")
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    logger.info("decision worker up: shard %d/%d llm=%s",
                SHARD_INDEX, SHARD_COUNT, USE_LLM)
    try:
        prune_at = 0.0
        while not stop.is_set():
            # shard-0 prunes done decision_queue rows hourly (both queue modes)
            if SHARD_INDEX == 0 and time.time() > prune_at:
                prune_at = time.time() + 3600
                try:
                    cutoff = drain._iso(time.time() - 86400)
                    n = await client.delete_vertices(
                        "decision_queue", realm=AGENTS_REALM,
                        where=[("done_at", "not_null", None),
                               ("done_at", "<", cutoff)])
                    if n:
                        logger.info("pruned %d done queue rows", n)
                except Exception:
                    logger.exception("queue prune failed")
            # Phase 2b: when the Redis decision queue is active, consume it
            # continuously (any worker, any agent, no SHARD_COUNT). Else the
            # legacy PG poll (agent-hash shard) below -- also the redis fallback.
            from genome_core import redisq as _rq
            _q = _rq.queue()
            if _q is not None:
                n = await process_redis_decisions(store, client, _q)
                if n == 0:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.25)
                    except (TimeoutError, asyncio.TimeoutError):
                        pass
                continue
            try:
                rows = await client.find_vertices(
                    "decision_queue", realm=AGENTS_REALM,
                    where=[("done_at", "is_null", None)], limit=500)
                items = [v for v in rows
                         if mine(v.payload.get("agent_uuid", ""))]
            except Exception:
                # a re-dialing tunnel resets connections; survive it
                logger.exception("queue poll failed; retrying")
                items = []
            # constant-motion revision: decisions run IN PARALLEL, capped,
            # but never two for the same agent at once -- oldest question
            # per agent this cycle, the rest next poll
            per_agent: dict[str, object] = {}
            for item in sorted(items, key=lambda v: v.payload["queued_at"]):
                per_agent.setdefault(item.payload["agent_uuid"], item)
            sem = asyncio.Semaphore(16)

            async def _work(item):
                async with sem:
                    try:
                        outcome = await work_one(store, client, item)
                        logger.info("%s %s -> %s",
                                    item.payload["world_realm"],
                                    item.payload["agent_uuid"], outcome)
                    except Exception:
                        logger.exception("decision failed for %s",
                                         item.payload.get("agent_uuid"))
                        await client.upsert_vertex(
                            "decision_queue", realm=AGENTS_REALM,
                            vertex_id=int(item.id),
                            payload={**item.payload,
                                     "done_at": drain._iso(time.time()),
                                     "outcome": "error"})
            await asyncio.gather(*(_work(i) for i in per_agent.values()))
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
            except TimeoutError:
                pass
    finally:
        if meter:
            await meter.stop()
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())
