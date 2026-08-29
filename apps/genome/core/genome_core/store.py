"""Genome storage on post-graph — never raw DDL.

Substrate mapping (system-spec.md §1, §3; genome-spec.md Rule 3.5):

    post-graph realm  "genome"   -> ONE schema for all worlds        (physical)
    post-graph space  <world>    -> each world, a column predicate   (logical)
    post-graph-rag    per agent  -> private knowledge stores (genome-spec §8)

genome-spec.md's own word "realm" (a world) is a post-graph SPACE — the naming
collision is resolved here and only here. Rule 3.5 wanted all worlds in one
schema discriminated logically; post-graph spaces are exactly that mechanism.

The Phase 0.3 fail-closed property survives the substrate change: every method
takes the world space as its first required argument and None raises. A read
that forgets its space is a cross-world leak (system-spec Rule 3.2), so there
is no default, ever.

This module is the SIMULATION path (interface-spec.md Rule 1.1). User-facing
reads live in the api service and must not import GenomeStore.
"""
from __future__ import annotations

from typing import Any

REALM = "genome"

# Vertex tables (created once per deployment via ensure_schema, idempotent —
# the registry idiom; post-graph owns all DDL).
WORLDS, AGENTS, PILES, PORTALS, EVENTS = "worlds", "agents", "piles", "portals", "events"
DECISIONS = "decisions"          # append-only via add_vertex_data (exec-spec §6)
# Edge tables
OPINION = "opinion_of"           # observer -> subject, attribute data (genotype §6.3)
MOVEMENT = "movement"            # stored as vertex data on the agent: the intent


class UnscopedError(RuntimeError):
    """A call reached the store without a world space."""


def _require(space: str | None) -> str:
    if not space:
        raise UnscopedError("world space is required and was missing")
    return space


async def ensure_schema(client: Any) -> None:
    """Create genome's vertex and edge tables in the one realm. Idempotent.
    post-graph performs the DDL; nothing here issues CREATE TABLE."""
    for table in (WORLDS, AGENTS, PILES, PORTALS, EVENTS, DECISIONS):
        await client.create_vertex_table(table, realm=REALM)
    await client.create_edge_table(OPINION, AGENTS, AGENTS, realm=REALM)


class GenomeStore:
    """All simulation reads and writes. Space-first, fail-closed."""

    def __init__(self, client: Any):
        self._c = client

    # --- worlds ---

    async def put_world(self, space: str, properties: dict) -> None:
        await self._c.upsert_vertex(WORLDS, key=_require(space), realm=REALM,
                                    space=space, properties=properties)

    # --- agents ---

    async def put_agent(self, space: str, agent_uuid: str, properties: dict) -> None:
        await self._c.upsert_vertex(AGENTS, key=agent_uuid, realm=REALM,
                                    space=_require(space), properties=properties)

    async def agents_in(self, space: str) -> list:
        return await self._c.get_vertices(AGENTS, realm=REALM,
                                          space=_require(space))

    async def set_movement(self, space: str, agent_uuid: str, intent: dict) -> None:
        """One of the two writes a journey makes (execution-spec Rule 2.2).
        Appended as vertex data, so the movement history IS the position log."""
        await self._c.add_vertex_data(AGENTS, key=agent_uuid, realm=REALM,
                                      space=_require(space),
                                      record={"kind": MOVEMENT, **intent})

    # --- piles ---

    async def put_pile(self, space: str, pile_uuid: str, properties: dict) -> None:
        await self._c.upsert_vertex(PILES, key=pile_uuid, realm=REALM,
                                    space=_require(space), properties=properties)

    async def piles_in(self, space: str) -> list:
        return await self._c.get_vertices(PILES, realm=REALM, space=_require(space))

    # --- events: the queue's source of truth (system-spec Rule 8.3) ---

    async def schedule(self, space: str, event_id: str, due_at: str,
                       kind: str, subject: str, payload: dict) -> None:
        await self._c.upsert_vertex(
            EVENTS, key=event_id, realm=REALM, space=_require(space),
            properties={"due_at": due_at, "kind": kind,
                        "subject": subject, "payload": payload, "done_at": None})

    async def due_events(self, space: str, now: str) -> list:
        rows = await self._c.get_vertices(EVENTS, realm=REALM, space=_require(space))
        return sorted((r for r in rows
                       if r["properties"]["due_at"] <= now
                       and r["properties"]["done_at"] is None),
                      key=lambda r: r["properties"]["due_at"])

    async def complete_event(self, space: str, event_id: str, now: str) -> None:
        await self._c.upsert_vertex(EVENTS, key=event_id, realm=REALM,
                                    space=_require(space),
                                    properties={"done_at": now}, merge=True)

    # --- opinions (agent-keyed; the space is the OBSERVER's world) ---

    async def update_opinion(self, space: str, observer: str, subject: str,
                             attribute: str, record: dict) -> None:
        await self._c.add_edge(OPINION, src=observer, dst=subject, realm=REALM,
                               space=_require(space),
                               properties={"attribute": attribute, **record})

    # --- the experimental record: append-only, never sampled (exec-spec §6) ---

    async def record_decision(self, space: str, agent_uuid: str, record: dict) -> None:
        await self._c.add_vertex_data(DECISIONS, key=agent_uuid, realm=REALM,
                                      space=_require(space), record=record)
