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
from post_graph import AsyncPostGraph
from genome_core import drain, engine
from genome_core.decider import llm_decider
from genome_core.store import GenomeStore, AGENTS_REALM

logger = logging.getLogger("genome.decision")

POLL_SECONDS = float(os.getenv("GENOME_DECISION_POLL", "3"))
USE_LLM = os.getenv("GENOME_USE_LLM", "1") == "1"


def dsn() -> str:
    return os.getenv("POSTGRES_URI") or (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.getenv('POSTGRES_HOST', 'postgres-service')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.environ['POSTGRES_DB']}")


async def work_one(store: GenomeStore, client, item) -> str:
    pl = item.payload
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
        await store.record_decision(pl["agent_uuid"], {
            "at": drain._iso(now), "situation": "market",
            "options": list(req.options), "choice": action,
            "detail": det, "model": model, "tier": "deliberative"})
        await client.upsert_vertex("decision_queue", realm=AGENTS_REALM,
                                   vertex_id=int(item.id),
                                   payload={**pl, "done_at": drain._iso(now),
                                            "outcome": outcome})
        return outcome
    if pl["situation"] == "negotiate":
        from genome_core.decider import negotiate_decider
        from genome_core import negotiation as nego
        action = offer = None
        model = "stub"
        if USE_LLM and g:
            action, offer, model = negotiate_decider(
                req, g, seed=int(now),
                objectives=agent_payload.get("objectives"))
        if action is None:
            state = {"participants": [pl["agent_uuid"], ""],
                     "turns": ([{"offer": req.context["last_offer"]}]
                               if req.context.get("last_offer") else []),
                     "status": "open"}
            action, offer = nego.fallback_turn(
                state, pl["agent_uuid"], req.context.get("my_cargo", {}))
        outcome = await drain.apply_negotiation_turn(
            store, pl["world_realm"], req.context["neg_key"],
            pl["agent_uuid"], action, offer, now)
        await store.record_decision(pl["agent_uuid"], {
            "at": drain._iso(now), "situation": "negotiate",
            "options": list(req.options), "choice": action,
            "offer": offer, "model": model, "tier": "deliberative"})
        await client.upsert_vertex("decision_queue", realm=AGENTS_REALM,
                                   vertex_id=int(item.id),
                                   payload={**pl, "done_at": drain._iso(now),
                                            "outcome": outcome})
        return outcome
    if USE_LLM and g:
        from genome_core import pathogen
        eff = pathogen.phenotype(agent_payload, now) \
            if agent_payload.get("infections") else g
        choice, model = llm_decider(req, eff, seed=int(now),
                                    objectives=agent_payload.get("objectives"),
                                    heard=agent_payload.get("heard"))
    else:
        choice, model = engine.stub_decider(req, int(now)), "stub"
    outcome = await drain.apply_decided(
        store, pl["world_realm"], pl["agent_uuid"], choice, model,
        pl["situation"], pl["options"], pl.get("event_payload", {}), now)
    await client.upsert_vertex("decision_queue", realm=AGENTS_REALM,
                               vertex_id=int(item.id),
                               payload={**pl, "done_at": drain._iso(now),
                                        "outcome": outcome})
    return outcome


async def main() -> None:
    client = AsyncPostGraph(dsn=dsn())   # SCHEMA_PER_REALM deliberately unset
    await client.connect()
    store = GenomeStore(client)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    logger.info("decision worker up: llm=%s", USE_LLM)
    try:
        prune_at = 0.0
        while not stop.is_set():
            try:
                rows = await client.get_vertices("decision_queue",
                                                 realm=AGENTS_REALM)
                items = [v for v in rows
                         if v.payload.get("done_at") is None]
                if time.time() > prune_at:      # hourly ledger hygiene
                    prune_at = time.time() + 3600
                    cutoff = time.time() - 86400
                    n = 0
                    for v in rows:
                        d = v.payload.get("done_at")
                        if d and float(d) < cutoff:
                            await client.delete_vertex(
                                "decision_queue", realm=AGENTS_REALM,
                                vertex_id=str(v.id))
                            n += 1
                    if n:
                        logger.info("pruned %d done queue rows", n)
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
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())
