"""genome tick worker — drains due events for the realms it leases.

system-spec.md §4, §8: a worker owns many worlds (never a process per world),
ownership is a revocable lease, and the world queue never blocks on inference —
events needing a decision are handed to the decision queue and the drain moves
on. Redis schedules; post-graph is the source of truth, so a flushed queue is
rebuilt with one query (Rule 8.3).

Phase 0 skeleton: lifecycle, lease loop shape, clean shutdown. Redis leasing
and the drain arrive in Phase 1.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from post_graph import AsyncPostGraph

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "core"))
from genome_core.store import GenomeStore

logger = logging.getLogger("genome.tick")

DB_URI = os.getenv("POSTGRES_URI", "")
TICK_SECONDS = float(os.getenv("GENOME_TICK_SECONDS", "5"))


async def drain_realm(store: GenomeStore, world_realm: str, now_iso: str) -> int:
    """Drain one leased world's due events. Grows in Phase 1; the contract is
    fixed now: never call a model from here (system-spec Rule 8.4)."""
    events = await store.due_events(world_realm, now_iso)
    for _ev in events:
        pass  # Phase 1: arrival -> decision request -> intent -> next event
    return len(events)


async def main() -> None:
    # SCHEMA_PER_REALM deliberately not passed (see genome_core/store.py).
    client = AsyncPostGraph(dsn=DB_URI)
    await client.connect()
    store = GenomeStore(client)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    logger.info("tick worker up; leasing arrives in Phase 1")
    try:
        while not stop.is_set():
            # Phase 1: acquire/renew leases, drain each leased realm.
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass  # tick elapsed; loop
    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
