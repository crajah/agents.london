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
    for table in (WORLD_META, PILES, PORTALS, PRESENCE, "constructions",
                  "negotiations", "market_listings"):
        await client.create_vertex_table(table, realm=r)
    for key in ("due_at", "done_at"):
        await client.create_payload_index(EVENTS, realm=r, key=key)
    await client.create_vertex_table(EVENTS, realm=r,
                                     promoted_keys=("due_at", "done_at"))


async def ensure_agents_realm(client: Any) -> None:
    """Create the single agents realm. Idempotent; called at deploy."""
    for table in (AGENTS, DECISIONS, "decision_queue", "trust",
                  "notifications", "outbox", "link_proposals", "chats"):
        await client.create_vertex_table(table, realm=AGENTS_REALM)
    for key in ("done_at", "agent_uuid"):
        await client.create_payload_index("decision_queue",
                                          realm=AGENTS_REALM, key=key)
    await client.create_edge_table(OPINION, from_vertex_table=AGENTS,
                                  to_vertex_table=AGENTS, realm=AGENTS_REALM)


class GenomeStore:
    """post-graph vertex_ids are integers minted by add_vertex; every genome
    entity keeps its business key in payload["key"] and is found by it — the
    registry idiom (services/agent-registry/registry_store.py)."""

    def __init__(self, client: Any):
        self._c = client

    async def _pk(self, table: str, realm: str, key: str) -> int | None:
        # agents fast path: put_agent writes space == key, and (realm, space)
        # is a btree -- 0.06ms against the 36ms containment seq-scan that
        # kept the database at two cores (measured 2026-09-05). Containment
        # remains as the fallback for any row that predates the invariant.
        if table == AGENTS and realm == AGENTS_REALM:
            rows = await self._c.find_vertices(table, realm=realm,
                                               space=key, limit=1)
            if rows:
                return int(rows[0].id)
        rows = await self._c.find_vertices(table, realm=realm,
                                           filters={"key": key}, limit=1)
        return int(rows[0].id) if rows else None

    async def find_agent_rows(self, key: str) -> list:
        """One agent's row by key, via the indexed space column first."""
        rows = await self._c.find_vertices(AGENTS, realm=AGENTS_REALM,
                                           space=key, limit=1)
        if rows:
            return rows
        return await self._c.find_vertices(AGENTS, realm=AGENTS_REALM,
                                           filters={"key": key}, limit=1)

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
        r = _req(world_realm, "world realm")
        ev_payload = {"due_at": due_at, "kind": kind, "subject": subject,
                      "payload": payload, "done_at": None, "key": event_id}
        await self._upsert_by_key(EVENTS, r, _req(event_id, "event"),
                                  ev_payload)
        # write-through to the Redis delay queue (Phase 2). PG above is the
        # durable truth; this mirror is a cache the consumers drain, rebuilt
        # from PG if lost. Best-effort -- never let a queue hiccup fail a write.
        from . import redisq
        q = redisq.queue()
        if q is not None:
            try:
                await q.schedule(r, subject, float(due_at), event_id)
            except Exception:
                pass

    async def get_pending_event(self, world_realm: str, event_id: str):
        """The undone event row for a key, or None (done/gone). Used by the
        Redis consumer, which claims key-identified members and loads the
        durable payload here."""
        rows = await self._c.find_vertices(
            EVENTS, realm=_req(world_realm, "world realm"),
            filters={"key": event_id},
            where=[("done_at", "is_null", None)], limit=1)
        return rows[0] if rows else None

    async def due_events(self, world_realm: str, now: str,
                         limit: int = 500) -> list:
        # post-graph >= 1.2.0: the range query the schema was shaped for --
        # the table never travels, only the due slice, oldest first
        return await self._c.find_vertices(
            EVENTS, realm=_req(world_realm, "world realm"),
            where=[("done_at", "is_null", None), ("due_at", "<=", now)],
            order_by="due_at", limit=limit)

    async def complete_event(self, world_realm: str, event_id: str, now: str) -> None:
        r = _req(world_realm, "world realm")
        rows = await self._c.find_vertices(EVENTS, realm=r,
                                           filters={"key": event_id}, limit=1)
        if not rows:
            raise KeyError(f"event {event_id} not found in {r}")
        await self._c.upsert_vertex(EVENTS, realm=r, vertex_id=int(rows[0].id),
                                    payload={**rows[0].payload, "done_at": now})

    async def claim_due_events(self, now_s: str, lease_until_s: str,
                               batch: int = 64) -> list:
        """Competing-consumers claim (scale rewrite Phase 1, 2026-09-13): lease
        a batch of the oldest DUE, unleashed events ACROSS ALL REALMS in one
        atomic statement via FOR UPDATE SKIP LOCKED, so any worker drains any
        world -- work is no longer bound to a realm's shard. The lease
        (payload.lease_until) is a short expiry: a worker that dies leaves its
        events re-claimable once it lapses. Returns light event views carrying
        .realm and .payload (the same shape drain_one reads). Uses post-graph's
        raw fetch (its library API); a native claim primitive is the planned
        follow-up so the lease/due filter can ride a partial index at scale."""
        import json as _json
        from types import SimpleNamespace as _NS
        # Pick the oldest due, unleashed rows (SKIP LOCKED so workers take
        # disjoint rows), reduce to their SUBJECTS, then lease EVERY undone
        # event of those subjects -- so one agent's whole turn goes to one
        # worker (per-agent serialization). The `lease_until < now` guard in the
        # UPDATE + Postgres row-lock serialization makes whole-subject claiming
        # race-free: a second worker that picked the same subject re-evaluates
        # the guard against the freshly-leased value and simply skips it.
        rows = await self._c.fetch(
            "WITH picked AS ("
            "  SELECT DISTINCT subj FROM ("
            f"    SELECT payload->>'subject' AS subj FROM {EVENTS} ev"
            "     WHERE p_done_at IS NULL AND p_due_at <= $1"
            "       AND COALESCE(payload->>'lease_until', '') < $1"
            "       AND NOT EXISTS (SELECT 1 FROM world_meta wm"
            "                       WHERE wm.realm = ev.realm"
            "                         AND wm.payload->>'paused' = 'true')"
            "     ORDER BY p_due_at LIMIT $2 FOR UPDATE SKIP LOCKED) q)"
            f" UPDATE {EVENTS} e"
            "   SET payload = jsonb_set(e.payload, '{lease_until}',"
            "                           to_jsonb($3::text))"
            "  FROM picked"
            "  WHERE e.payload->>'subject' = picked.subj"
            "    AND e.p_done_at IS NULL"
            "    AND COALESCE(e.payload->>'lease_until', '') < $1"
            "  RETURNING e.realm AS realm, e.payload AS payload",
            now_s, int(batch), lease_until_s)
        out = []
        for r in rows:
            pl = r["payload"]
            if isinstance(pl, str):
                pl = _json.loads(pl)
            out.append(_NS(realm=r["realm"], payload=pl))
        return out

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
        from . import metrics
        sit = payload.get("situation", "?")
        if sit.startswith("at_"):        # per-pile labels would explode the
            sit = "at_large" if sit == "at_large" else "at_pile"   # cardinality
        metrics.DECISIONS.labels(sit, payload.get("model", "?")).inc()
        a = _req(agent_uuid, "agent")
        pk = await self._upsert_by_key(DECISIONS, AGENTS_REALM, a, {}, space=a)             if await self._pk(DECISIONS, AGENTS_REALM, a) is None else             await self._pk(DECISIONS, AGENTS_REALM, a)
        await self._c.add_vertex_data(DECISIONS, realm=AGENTS_REALM,
                                      vertex_id=pk, payload=payload)
