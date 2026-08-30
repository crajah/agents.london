"""genome api — user-facing reads and the owner channel.

interface-spec.md Rule 1.1: this service is the USER-FACING path. It may read
any world (genome-spec.md Rule 13.2) and must NOT import GenomeStore, whose
fail-closed scoping exists for the simulation path. The two paths have opposite
rules and therefore separate modules.

Phase 0 skeleton: health, client lifecycle, agents-realm bootstrap. Surfaces
grow with their phases (BUILD.md).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from post_graph import AsyncPostGraph

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "core"))
from genome_core import store  # ensure_agents_realm only; NOT GenomeStore
import snapshot

logger = logging.getLogger(__name__)

POSTGRES_USER = os.getenv("POSTGRES_USER", "")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres-service")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
DB_URI = os.getenv(
    "POSTGRES_URI",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")


def make_client() -> AsyncPostGraph:
    """SCHEMA_PER_REALM is deliberately NOT passed (user decision, recorded in
    genome_core/store.py): the environment and post-graph's default decide."""
    return AsyncPostGraph(dsn=DB_URI)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = make_client()
    await client.connect()
    app.state.pg = client
    await store.ensure_agents_realm(client)
    logger.info("agents realm ensured")
    try:
        yield
    finally:
        await client.close()


app = FastAPI(title="genome api", lifespan=lifespan)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "genome-api"}


@app.get("/worlds/{realm}/snapshot", tags=["World"])
async def get_snapshot(realm: str):
    """Any world, read-only (genome-spec Rule 13.2). Observation confers
    nothing on agents (Rule 13.3) — this path serves humans only."""
    return await snapshot.world_snapshot(app.state.pg, realm)


@app.get("/agents/{agent_uuid}", tags=["Agent"])
async def get_agent(agent_uuid: str):
    """Any agent, anywhere (genome-spec Rule 13.1): genotype AND expression."""
    return await snapshot.agent_inspect(app.state.pg, agent_uuid)


@app.get("/agents/{agent_uuid}/decisions", tags=["Agent"])
async def get_agent_decisions(agent_uuid: str, limit: int = 20):
    return await snapshot.agent_decisions(app.state.pg, agent_uuid, limit)


@app.get("/worlds/{realm}/events", tags=["World"])
async def get_events(realm: str, since: str = ""):
    return await snapshot.world_events(app.state.pg, realm, since)
