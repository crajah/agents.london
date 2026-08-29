"""genome decision worker — takes decision requests, gathers context, calls the
router, writes back an intent.

execution-spec.md §8: an agent is a runner invocation, not a resident process;
an ordinary decision is a single constrained call; models are reached through
the existing litellm router, never directly (Rule 8.2), with credentials
resolved per execution-spec §9 deciding who PAYS, never which model thinks.
Postgres (via post-graph) stays the system of record (Rule 8.4).

Phase 0 skeleton. The stub decider lands in Phase 1 so the loop is provable
without an LLM; ADK arrives in Phase 2.
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

logger = logging.getLogger("genome.decision")

DB_URI = os.getenv("POSTGRES_URI", "")
ROUTER_URL = os.getenv("GENOME_ROUTER_URL", "http://litellm-service/proxy")


async def main() -> None:
    client = AsyncPostGraph(dsn=DB_URI)  # SCHEMA_PER_REALM deliberately unset
    await client.connect()
    _store = GenomeStore(client)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    logger.info("decision worker up; stub decider arrives in Phase 1")
    try:
        await stop.wait()
    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
