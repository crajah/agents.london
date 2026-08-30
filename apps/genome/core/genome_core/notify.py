"""Notifications — interface-spec.md §7. The atoms of user visibility.

Fire-and-forget (Rule 7.4): emit() swallows its own failures so no simulation
event ever fails because its notification did. Levels: a user configures
`all` / `important` / `none` per source (world, agents, platform); the
always-important kinds (Rule 7.3) pierce `important`, and nothing pierces
`none` except an incoming invitation or link — those ARE the platform reaching
the user.
"""
from __future__ import annotations

import logging
import time
import uuid as uuidlib
from typing import Any

logger = logging.getLogger("genome.notify")

ALWAYS_IMPORTANT = {"invite_received", "link_created", "flood_countdown",
                    "agent_perished", "berth_event"}
PIERCE_NONE = {"invite_received", "link_created"}
DEFAULT_PREFS = {"world": "important", "agents": "important",
                 "platform": "all"}


def _wanted(kind: str, source: str, prefs: dict) -> bool:
    level = (prefs or DEFAULT_PREFS).get(source,
                                         DEFAULT_PREFS.get(source, "important"))
    if level == "all":
        return True
    if level == "important":
        return kind in ALWAYS_IMPORTANT or source == "platform"
    return kind in PIERCE_NONE


async def emit(client: Any, user_id: str, source: str, kind: str,
               message: str, data: dict | None = None) -> None:
    """One notification to one user, level-filtered, never raising."""
    try:
        rows = await client.find_vertices("agents", realm="genome_agents",
                                          filters={"key": f"user:{user_id}"},
                                          limit=1)
        prefs = (rows[0].payload.get("notification_prefs")
                 if rows else None) or DEFAULT_PREFS
        if not _wanted(kind, source, prefs):
            return
        await client.add_vertex("notifications", realm="genome_agents",
            payload={"key": f"nt-{uuidlib.uuid4().hex[:12]}",
                     "user_id": user_id, "source": source, "kind": kind,
                     "message": message, "data": data or {},
                     "at": time.time(), "read": False})
    except Exception:
        logger.exception("notification dropped (%s/%s to %s)",
                         source, kind, user_id)


async def feed(client: Any, user_id: str, limit: int = 50) -> list[dict]:
    rows = await client.find_vertices("notifications", realm="genome_agents",
                                      filters={"user_id": user_id}, limit=200)
    items = sorted((v.payload for v in rows), key=lambda p: -p["at"])[:limit]
    return items


async def mark_read(client: Any, user_id: str, keys: list[str]) -> int:
    rows = await client.find_vertices("notifications", realm="genome_agents",
                                      filters={"user_id": user_id}, limit=500)
    n = 0
    for v in rows:
        if v.payload["key"] in keys and not v.payload.get("read"):
            await client.upsert_vertex("notifications", realm="genome_agents",
                                       vertex_id=int(v.id),
                                       payload={**v.payload, "read": True})
            n += 1
    return n


async def outbox(client: Any, to_email: str, subject: str, body: str) -> None:
    """system-spec §10: durable row; the sender delivers (or logs, until SMTP)."""
    await client.add_vertex("outbox", realm="genome_agents",
        payload={"key": f"mail-{uuidlib.uuid4().hex[:12]}",
                 "to": to_email, "subject": subject, "body": body,
                 "queued_at": time.time(), "sent_at": None})
    logger.info("outbox <- %s: %s", to_email, subject)
