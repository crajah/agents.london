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
    creation. post-graph performs all DDL. due_at is promoted so Phase 1's
    due-event query can filter in the database."""
    r = _req(world_realm, "world realm")
    for table in (WORLD_META, PILES, PORTALS, PRESENCE, "constructions"):
        await client.create_vertex_table(table, realm=r)
    await client.create_vertex_table(EVENTS, realm=r,
                                     promoted_keys=("due_at", "done_at"))


async def ensure_agents_realm(client: Any) -> None:
    """Create the single agents realm. Idempotent; called at deploy."""
    for table in (AGENTS, DECISIONS, "decision_queue", "trust",
                  "notifications", "outbox", "link_proposals"):
        await client.create_vertex_table(table, realm=AGENTS_REALM)
    await client.create_edge_table(OPINION, from_vertex_table=AGENTS,
                                  to_vertex_table=AGENTS, realm=AGENTS_REALM)


class GenomeStore:
    """post-graph vertex_ids are integers minted by add_vertex; every genome
    entity keeps its business key in payload["key"] and is found by it — the
    registry idiom (services/agent-registry/registry_store.py)."""

    def __init__(self, client: Any):
        self._c = client

    async def _pk(self, table: str, realm: str, key: str) -> int | None:
        rows = await self._c.find_vertices(table, realm=realm,
                                           filters={"key": key}, limit=1)
        return int(rows[0].id) if rows else None

    async def _upsert_by_key(self, table: str, realm: str, key: str,
                             payload: dict, space: str = "default") -> int:
        body = {**payload, "key": key}
        pk = await self._pk(table, realm, key)
        if pk is None:
            v = await self._c.add_vertex(table, realm=realm, space=space,
                                         payload=body)
            return int(v.id)
        await self._c.upsert_vertex(table, realm=realm, vertex_id=pk,
                                    space=space, payload=body)
        return pk

    # ---------- world-realm operations ----------

    async def put_world(self, world_realm: str, payload: dict) -> None:
        r = _req(world_realm, "world realm")
        await self._upsert_by_key(WORLD_META, r, r, payload)

    async def put_pile(self, world_realm: str, pile_uuid: str, payload: dict) -> None:
        await self._upsert_by_key(PILES, _req(world_realm, "world realm"),
                                  _req(pile_uuid, "pile"), payload)

    async def piles_in(self, world_realm: str) -> list:
        return await self._c.get_vertices(PILES,
                                          realm=_req(world_realm, "world realm"))

    async def set_presence(self, world_realm: str, agent_uuid: str,
                           present: bool) -> None:
        """An agent is admitted to exactly one world at a time
        (genome-spec.md Rule 6.10); presence lives in the world's realm so
        agents_in never crosses realms."""
        await self._upsert_by_key(PRESENCE, _req(world_realm, "world realm"),
                                  _req(agent_uuid, "agent"),
                                  {"present": present})

    async def agents_in(self, world_realm: str) -> list:
        # Client-side filter: find_vertices matches string values only — a
        # boolean/None filter silently matches nothing (proven in-cluster).
        rows = await self._c.get_vertices(
            PRESENCE, realm=_req(world_realm, "world realm"))
        return [v for v in rows if v.payload.get("present") is True]

    # events: the queue's source of truth (system-spec Rule 8.3)

    async def schedule(self, world_realm: str, event_id: str, due_at: str,
                       kind: str, subject: str, payload: dict) -> None:
        await self._upsert_by_key(
            EVENTS, _req(world_realm, "world realm"), _req(event_id, "event"),
            {"due_at": due_at, "kind": kind, "subject": subject,
             "payload": payload, "done_at": None})

    async def due_events(self, world_realm: str, now: str) -> list:
        # done_at filtered client-side: a None filter matches nothing in real
        # post-graph (proven in-cluster). Promoted due_at enables a DB-side
        # range query later if the scan ever matters.
        rows = await self._c.get_vertices(
            EVENTS, realm=_req(world_realm, "world realm"))
        return sorted((v for v in rows
                       if v.payload.get("done_at") is None
                       and v.payload["due_at"] <= now),
                      key=lambda v: v.payload["due_at"])

    async def complete_event(self, world_realm: str, event_id: str, now: str) -> None:
        r = _req(world_realm, "world realm")
        rows = await self._c.find_vertices(EVENTS, realm=r,
                                           filters={"key": event_id}, limit=1)
        if not rows:
            raise KeyError(f"event {event_id} not found in {r}")
        await self._c.upsert_vertex(EVENTS, realm=r, vertex_id=int(rows[0].id),
                                    payload={**rows[0].payload, "done_at": now})

    # ---------- agents-realm operations (space = the agent) ----------

    async def put_agent(self, agent_uuid: str, payload: dict) -> None:
        a = _req(agent_uuid, "agent")
        await self._upsert_by_key(AGENTS, AGENTS_REALM, a, payload, space=a)

    async def set_movement(self, agent_uuid: str, intent: dict) -> None:
        """One of the two writes a journey makes (execution-spec Rule 2.2);
        appended, so the movement history IS the position log."""
        a = _req(agent_uuid, "agent")
        pk = await self._pk(AGENTS, AGENTS_REALM, a)
        if pk is None:
            raise KeyError(f"agent {a} not found")
        await self._c.add_vertex_data(AGENTS, realm=AGENTS_REALM, vertex_id=pk,
                                      payload={"kind": MOVEMENT, **intent})

    async def latest_movement(self, agent_uuid: str):
        a = _req(agent_uuid, "agent")
        pk = await self._pk(AGENTS, AGENTS_REALM, a)
        if pk is None:
            return None
        return await self._c.get_latest_vertex_data(AGENTS, realm=AGENTS_REALM,
                                                    vertex_id=pk)

    async def update_opinion(self, observer: str, subject: str,
                             attribute: str, payload: dict) -> None:
        o = await self._pk(AGENTS, AGENTS_REALM, _req(observer, "observer"))
        s = await self._pk(AGENTS, AGENTS_REALM, _req(subject, "subject"))
        if o is None or s is None:
            raise KeyError("observer or subject not found")
        await self._c.upsert_edge(OPINION, realm=AGENTS_REALM,
                                  from_id=o, to_id=s, relation_type=attribute,
                                  space=observer, payload=payload)

    async def record_decision(self, agent_uuid: str, payload: dict) -> None:
        """Append-only, never sampled (execution-spec §6)."""
        a = _req(agent_uuid, "agent")
        pk = await self._upsert_by_key(DECISIONS, AGENTS_REALM, a, {}, space=a)             if await self._pk(DECISIONS, AGENTS_REALM, a) is None else             await self._pk(DECISIONS, AGENTS_REALM, a)
        await self._c.add_vertex_data(DECISIONS, realm=AGENTS_REALM,
                                      vertex_id=pk, payload=payload)
