"""User-facing world reads — interface-spec.md Rule 1.1's OTHER path.

Deliberately does NOT import GenomeStore: the simulation store fails closed on
missing scope because agents must never read across worlds; a USER may read any
world (genome-spec Rule 13.2), so this module has its own queries with opposite
rules. The wire carries intents and closed-form anchors, never frames
(interface-spec Rule 2.2): the client derives positions from the same forms.
"""
from __future__ import annotations

from typing import Any

AGENTS_REALM = "genome_agents"


async def world_snapshot(client: Any, world_realm: str) -> dict:
    """Everything a client needs to render a world and interpolate it forward:
    meta (kinds, colours, terrain, stock), pile anchors, present agents with
    their latest movement intents. Rule 13.1: any agent's genotype is visible
    to a user — the inspector fetches it separately, not in the hot snapshot."""
    meta_rows = await client.find_vertices("world_meta", realm=world_realm,
                                           filters={"key": world_realm}, limit=1)
    meta = meta_rows[0].payload if meta_rows else {}
    piles = [v.payload for v in
             await client.get_vertices("piles", realm=world_realm)]
    present = [v.payload["key"] for v in
               await client.get_vertices("presence", realm=world_realm)
               if v.payload.get("present") is True]
    agents = []
    for uuid in present:
        rows = await client.find_vertices("agents", realm=AGENTS_REALM,
                                          filters={"key": uuid}, limit=1)
        payload = rows[0].payload if rows else {}
        intent = None
        if rows:
            latest = await client.get_latest_vertex_data(
                "agents", realm=AGENTS_REALM, vertex_id=int(rows[0].id))
            if latest is not None and "waypoints" in latest.payload:
                intent = {k: latest.payload[k]
                          for k in ("waypoints", "departed_at", "arrives_at")}
        agents.append({"agent_uuid": uuid,
                       "colour_pair": payload.get("colour_pair"),
                       "name": payload.get("name"),
                       "infected": bool(payload.get("infections")),
                       "movement": intent})
    return {"realm": world_realm,
            "kinds": meta.get("kinds"), "colours": meta.get("colours"),
            "terrain": meta.get("terrain", []),
            "portals": meta.get("portals", []),
            "stock": meta.get("stock", {}),
            "muster_points": meta.get("muster_points", []),
            "constructions": meta.get("constructions", []),
            "time_scale": meta.get("time_scale", 1.0),
            "piles": [{k: p.get(k) for k in
                       ("pile_uuid", "kind", "x", "y", "qty_at",
                        "measured_at", "rate", "cap")} for p in piles],
            "agents": agents}


async def agent_inspect(client: Any, agent_uuid: str) -> dict:
    """Rule 13.1: a user may see ANY agent's genotype and its expression.
    Faculties and expressed values are computed server-side so the client never
    reimplements genotype arithmetic."""
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "core"))
    from genome_core.genotype import faculties, expressed, DISPOSITIONS
    rows = await client.find_vertices("agents", realm=AGENTS_REALM,
                                      filters={"key": agent_uuid}, limit=1)
    if not rows:
        return {"error": "not found"}
    payload = rows[0].payload
    g = payload.get("genotype") or {}
    out = {"agent_uuid": agent_uuid, "name": payload.get("name"),
           "colour_pair": payload.get("colour_pair"),
           "home_realm": payload.get("home_realm"),
           "parents": payload.get("parents"),
           "infected": bool(payload.get("infected"))}
    if g:
        out["dispositions"] = {d: g[d] for d in DISPOSITIONS if d in g}
        out["faculties"] = faculties(g)
        out["expressed"] = expressed(g)
    return out


async def agent_decisions(client: Any, agent_uuid: str, limit: int = 20) -> list[dict]:
    """The experimental record, per agent, newest first (execution-spec §6) —
    a user may always read why their world looks the way it does."""
    rows = await client.find_vertices("decisions", realm=AGENTS_REALM,
                                      filters={"key": agent_uuid}, limit=1)
    if not rows:
        return []
    recs = await client.get_vertex_data("decisions", realm=AGENTS_REALM,
                                        vertex_id=int(rows[0].id), limit=limit)
    return [r.payload for r in recs]


async def world_events(client: Any, world_realm: str, since: str) -> list[dict]:
    """Completed events after `since` — the client's incremental feed."""
    rows = await client.get_vertices("events", realm=world_realm)
    done = [v.payload for v in rows
            if v.payload.get("done_at") and v.payload["done_at"] > since]
    return sorted(done, key=lambda p: p["done_at"])
