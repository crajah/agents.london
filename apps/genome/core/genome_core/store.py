"""Genome storage on post-graph — never raw DDL, realms one-to-one.

Substrate mapping (system-spec.md Rules 3.2a/3.2b):

    genome realm            post-graph realm          holds
    -----------------       ----------------------    ------------------------------
    each world              its own realm (uuid)      world meta, piles, portals,
                                                      events, presence
    the agents realm        "genome_agents"           agent vertices, opinion edges,
      (spec §3 Rule 3.1)                              movement + decision history;
                                                      each agent a SPACE, private
                                                      knowledge via post-graph-rag

Whether a post-graph realm is a physical schema or a logical column is the
deployment flag SCHEMA_PER_REALM — post-graph's own toggle — so genome-spec.md
Rule 3.5's "decide later whether schema per realm is needed" stays decided
later, as configuration rather than architecture. **Genome does not set the
flag** (user decision, 2026-08-29): services construct AsyncPostGraph without
passing schema_per_realm, deferring entirely to the environment and post-graph's
own default. Do not copy the registries' `os.getenv(..., "1")` default here.

Fail-closed (BUILD Phase 0.3): every world method takes the world realm first,
every agent method the agent uuid; missing either raises. No defaults, ever.
Simulation path only (interface-spec.md Rule 1.1) — user-facing reads must not
import GenomeStore.
"""
from __future__ import annotations

from typing import Any

AGENTS_REALM = "genome_agents"

# Vertex tables in each WORLD realm
WORLD_META, PILES, PORTALS, EVENTS, PRESENCE = (
    "world_meta", "piles", "portals", "events", "presence")
# Vertex/edge tables in the AGENTS realm
AGENTS, DECISIONS = "agents", "decisions"
OPINION = "opinion_of"
MOVEMENT = "movement"      # append-only vertex data on the agent


class UnscopedError(RuntimeError):
    """A call reached the store without its realm or agent scope."""


def _req(value: str | None, what: str) -> str:
    if not value:
        raise UnscopedError(f"{what} is required and was missing")
    return value


async def ensure_world_realm(client: Any, world_realm: str) -> None:
    """Create one world's tables in its own realm. Idempotent; called at world
    creation. post-graph performs all DDL."""
    for table in (WORLD_META, PILES, PORTALS, EVENTS, PRESENCE):
        await client.create_vertex_table(table, realm=_req(world_realm, "world realm"))


async def ensure_agents_realm(client: Any) -> None:
    """Create the single agents realm. Idempotent; called at deploy."""
    for table in (AGENTS, DECISIONS):
        await client.create_vertex_table(table, realm=AGENTS_REALM)
    await client.create_edge_table(OPINION, AGENTS, AGENTS, realm=AGENTS_REALM)


class GenomeStore:
    def __init__(self, client: Any):
        self._c = client

    # ---------- world-realm operations ----------

    async def put_world(self, world_realm: str, properties: dict) -> None:
        r = _req(world_realm, "world realm")
        await self._c.upsert_vertex(WORLD_META, key=r, realm=r,
                                    properties=properties)

    async def put_pile(self, world_realm: str, pile_uuid: str, properties: dict) -> None:
        await self._c.upsert_vertex(PILES, key=pile_uuid,
                                    realm=_req(world_realm, "world realm"),
                                    properties=properties)

    async def piles_in(self, world_realm: str) -> list:
        return await self._c.get_vertices(PILES, realm=_req(world_realm, "world realm"))

    async def set_presence(self, world_realm: str, agent_uuid: str,
                           present: bool) -> None:
        """An agent is admitted to exactly one world at a time
        (genome-spec.md Rule 6.10); presence lives in the world's realm so
        agents_in never crosses realms."""
        await self._c.upsert_vertex(PRESENCE, key=_req(agent_uuid, "agent"),
                                    realm=_req(world_realm, "world realm"),
                                    properties={"present": present})

    async def agents_in(self, world_realm: str) -> list:
        rows = await self._c.get_vertices(
            PRESENCE, realm=_req(world_realm, "world realm"))
        return [r for r in rows if r["properties"].get("present")]

    # events: the queue's source of truth (system-spec Rule 8.3)

    async def schedule(self, world_realm: str, event_id: str, due_at: str,
                       kind: str, subject: str, payload: dict) -> None:
        await self._c.upsert_vertex(
            EVENTS, key=event_id, realm=_req(world_realm, "world realm"),
            properties={"due_at": due_at, "kind": kind, "subject": subject,
                        "payload": payload, "done_at": None})

    async def due_events(self, world_realm: str, now: str) -> list:
        rows = await self._c.get_vertices(
            EVENTS, realm=_req(world_realm, "world realm"))
        return sorted((r for r in rows
                       if r["properties"]["due_at"] <= now
                       and r["properties"]["done_at"] is None),
                      key=lambda r: r["properties"]["due_at"])

    async def complete_event(self, world_realm: str, event_id: str, now: str) -> None:
        await self._c.upsert_vertex(EVENTS, key=event_id,
                                    realm=_req(world_realm, "world realm"),
                                    properties={"done_at": now}, merge=True)

    # ---------- agents-realm operations (space = the agent) ----------

    async def put_agent(self, agent_uuid: str, properties: dict) -> None:
        a = _req(agent_uuid, "agent")
        await self._c.upsert_vertex(AGENTS, key=a, realm=AGENTS_REALM,
                                    space=a, properties=properties)

    async def set_movement(self, agent_uuid: str, intent: dict) -> None:
        """One of the two writes a journey makes (execution-spec Rule 2.2);
        appended, so the movement history IS the position log."""
        a = _req(agent_uuid, "agent")
        await self._c.add_vertex_data(AGENTS, key=a, realm=AGENTS_REALM,
                                      space=a, record={"kind": MOVEMENT, **intent})

    async def update_opinion(self, observer: str, subject: str,
                             attribute: str, record: dict) -> None:
        await self._c.add_edge(OPINION, src=_req(observer, "observer"),
                               dst=_req(subject, "subject"), realm=AGENTS_REALM,
                               space=observer,
                               properties={"attribute": attribute, **record})

    async def record_decision(self, agent_uuid: str, record: dict) -> None:
        """Append-only, never sampled (execution-spec §6)."""
        a = _req(agent_uuid, "agent")
        await self._c.add_vertex_data(DECISIONS, key=a, realm=AGENTS_REALM,
                                      space=a, record=record)
