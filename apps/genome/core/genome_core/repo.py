"""Realm-scoped repository — BUILD.md Phase 0.3, the highest-risk primitive.

genome-spec.md Rule 3.5 / system-spec.md Rule 3.2: realms are logical, so a
read that forgets to scope by realm is a cross-world leak, not an empty result.
Here that is structural: every method takes realm as its first required
argument, and every SQL string is checked — touching a realm-scoped table
without a realm_id predicate raises before reaching the database.

interface-spec.md Rule 1.1: agent-facing and user-facing reads must not share a
path. This module is the SIMULATION path. User-facing reads (which may see any
world, Rule 13.2) live in the api service and must not import RealmRepo.
"""
from __future__ import annotations

import re
from typing import Any

# Tables whose rows belong to a realm. decision and model_key are global by
# design; opinion is agent-keyed, not realm-keyed.
REALM_TABLES = {"world", "agent", "movement", "pile", "event"}
_TABLE_RE = re.compile(r"genome\.(\w+)")


class UnscopedQueryError(RuntimeError):
    """SQL touched a realm-scoped table without a realm_id predicate."""


def assert_scoped(sql: str) -> None:
    touched = set(_TABLE_RE.findall(sql)) & REALM_TABLES
    if touched and "realm_id" not in sql:
        raise UnscopedQueryError(
            f"query touches realm-scoped table(s) {sorted(touched)} "
            f"without a realm_id predicate: {sql[:120]!r}")


class RealmRepo:
    """All simulation reads and writes go through here."""

    def __init__(self, conn: Any):
        self._conn = conn

    def _exec(self, realm: str, sql: str, params: dict | None = None) -> Any:
        """Named parameters only; the realm binds %(realm)s. Positional SQL is
        rejected so realm can never be silently reordered."""
        if realm is None:
            raise UnscopedQueryError("realm is required and was None")
        if "%(realm)s" not in sql:
            raise UnscopedQueryError("SQL must bind the realm via %(realm)s")
        assert_scoped(sql)
        cur = self._conn.cursor()
        cur.execute(sql, {"realm": realm, **(params or {})})
        return cur

    # --- what Phase 1 needs; each phase grows this surface ---

    def due_events(self, realm: str, now, limit: int = 100):
        return self._exec(realm, """
            SELECT event_id, kind, subject_uuid, payload FROM genome.event
            WHERE realm_id = %(realm)s AND due_at <= %(now)s AND done_at IS NULL
            ORDER BY due_at LIMIT %(limit)s""",
            {"now": now, "limit": limit}).fetchall()

    def complete_event(self, realm: str, event_id: int, now) -> None:
        self._exec(realm, """
            UPDATE genome.event SET done_at = %(now)s
            WHERE realm_id = %(realm)s AND event_id = %(eid)s""",
            {"now": now, "eid": event_id})

    def schedule(self, realm: str, due_at, kind: str, subject, payload: dict) -> None:
        """Events are scheduled when the intent implying them is created
        (execution-spec.md Rule 3.2)."""
        self._exec(realm, """
            INSERT INTO genome.event (realm_id, due_at, kind, subject_uuid, payload)
            VALUES (%(realm)s, %(due)s, %(kind)s, %(subj)s, %(payload)s)""",
            {"due": due_at, "kind": kind, "subj": subject, "payload": payload})

    def agents_in(self, realm: str):
        return self._exec(realm, """
            SELECT a.agent_uuid, a.owner_user_id, a.home_realm, a.cargo,
                   m.from_x, m.from_y, m.to_x, m.to_y, m.departed_at, m.arrives_at
            FROM genome.agent a
            LEFT JOIN genome.movement m ON m.agent_uuid = a.agent_uuid
            WHERE a.realm_id = %(realm)s AND a.alive""").fetchall()

    def set_movement(self, realm: str, agent_uuid, fx, fy, tx, ty,
                     departed_at, arrives_at) -> None:
        """One of the two writes a journey ever makes (execution-spec Rule 2.2)."""
        self._exec(realm, """
            INSERT INTO genome.movement
                (agent_uuid, realm_id, from_x, from_y, to_x, to_y, departed_at, arrives_at)
            VALUES (%(a)s, %(realm)s, %(fx)s, %(fy)s, %(tx)s, %(ty)s, %(d)s, %(ar)s)
            ON CONFLICT (agent_uuid) DO UPDATE SET
                realm_id=%(realm)s, from_x=%(fx)s, from_y=%(fy)s, to_x=%(tx)s,
                to_y=%(ty)s, departed_at=%(d)s, arrives_at=%(ar)s""",
            {"a": agent_uuid, "fx": fx, "fy": fy, "tx": tx, "ty": ty,
             "d": departed_at, "ar": arrives_at})

    def rebuild_queue_source(self, realm: str):
        """Everything Redis needs to rebuild this realm's queue after a flush
        (system-spec.md Rule 8.3)."""
        return self._exec(realm, """
            SELECT event_id, due_at, kind, subject_uuid FROM genome.event
            WHERE realm_id = %(realm)s AND done_at IS NULL
            ORDER BY due_at""").fetchall()
