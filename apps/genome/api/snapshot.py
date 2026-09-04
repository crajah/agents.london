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
    import asyncio as _aio

    async def _one_agent(uuid):
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
        return {"agent_uuid": uuid,
                "colour_pair": payload.get("colour_pair"),
                "name": payload.get("name"),
                "infected": bool(payload.get("infections")),
                "generation": payload.get("generation", 1),
                "movement": intent}
    agents = list(await _aio.gather(*(_one_agent(u) for u in present)))
    import time as _time
    from genome_core import construction as _con
    from genome_core import flood as _flood
    from genome_core import market as _mkt
    from genome_core.worldgen import A100
    def _branch_colour(s):
        fam = _con.FAMILIES.get(s.get("branch"), [])
        return A100[fam[0]] if fam else None
    site_views = [{"key": s.payload["key"], "name": s.payload["name"],
                   "colour": _branch_colour(s.payload),
                   "wreck": bool(s.payload.get("spent")),
                   "colours": s.payload.get("colours"),
                   "holdings": s.payload.get("holdings"),
                   "berths": s.payload.get("berths"),
                   "boarded": len(s.payload.get("boarded", {})),
                   "kind": "ark" if s.payload["name"] == "ark" else "stage",
                   "tier": s.payload["tier"], "x": s.payload["x"],
                   "y": s.payload["y"], "progress": _con.progress(s.payload),
                   "complete": s.payload.get("complete", False),
                   "building_until": s.payload.get("building_until"),
                   "carried": bool(s.payload.get("carried")),
                   "plan_name": s.payload.get("plan_name"),
                   "plan_key": s.payload.get("plan_key"),
                   "needs": s.payload.get("needs", {}),
                   "delivered": s.payload.get("delivered", {}),
                   "contributors": len(s.payload.get("contributors", {})),
                   "required_users": s.payload.get("required_users", 1)}
                  for s in await _con.sites_in(client, world_realm)
                  if not s.payload.get("destroyed")]
    return {"realm": world_realm,
            "kinds": meta.get("kinds"), "colours": meta.get("colours"),
            "terrain": meta.get("terrain", []),
            "portals": meta.get("portals", []),
            "stock": meta.get("stock", {}),
            "muster_points": meta.get("muster_points", []),
            "market": meta.get("market"),
            "market_open": await _open_listings(client, world_realm,
                                                agents),
            "constructions": meta.get("constructions", []) + site_views,
            "time_scale": meta.get("time_scale", 1.0),
            "flood_countdown": _flood.countdown_visible(meta, _time.time()),
            "flood_count": meta.get("flood_count", 0),
            "piles": [{k: p.get(k) for k in
                       ("pile_uuid", "kind", "x", "y", "qty_at",
                        "measured_at", "rate", "cap")} for p in piles],
            "agents": agents}


async def _open_listings(client: Any, world_realm: str,
                         agents: list[dict]) -> list[dict]:
    from genome_core import market as _mkt
    """The board with faces on it: every open listing carries its lister's
    NAME (user directive 2026-09-02), resolved from the room first and the
    agents realm for absentees."""
    names = {a.get("agent_uuid"): a.get("name") for a in agents}
    out = []
    for l in await _mkt.board(client, world_realm):
        if l.get("status") != "open":
            continue
        lister = l.get("lister")
        name = names.get(lister)
        if name is None and lister:
            rows = await client.find_vertices("agents", realm=AGENTS_REALM,
                                              filters={"key": lister},
                                              limit=1)
            name = rows[0].payload.get("name") if rows else None
        out.append({"key": l["key"], "give": l["give"], "want": l["want"],
                    "by": name or (lister or "?")[:14], "lister": lister})
    return out


async def agent_inspect(client: Any, agent_uuid: str) -> dict:
    """Rule 13.1: a user may see ANY agent's genotype and its expression.
    Faculties and expressed values are computed server-side so the client never
    reimplements genotype arithmetic."""
    import sys, pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / "core"))
    from genome_core.genotype import faculties, expressed, DISPOSITIONS, \
        DESCRIPTIONS
    rows = await client.find_vertices("agents", realm=AGENTS_REALM,
                                      filters={"key": agent_uuid}, limit=1)
    if not rows:
        return {"error": "not found"}
    payload = rows[0].payload
    g = payload.get("genotype") or {}
    from genome_core.models import assign_models, temperament
    out = {"agent_uuid": agent_uuid, "name": payload.get("name"),
           "models": assign_models(agent_uuid),
           "temperament": round(temperament(agent_uuid), 2),
           "colour_pair": payload.get("colour_pair"),
           "home_realm": payload.get("home_realm"),
           "parents": payload.get("parents"),
           "capability": payload.get("capability"),
           "generation": payload.get("generation", 1),
           "influences": payload.get("influences") or [],
           "prompt_mods": payload.get("prompt_mods") or [],
           "infected": bool(payload.get("infections"))}   # CURRENT
    # infections only -- a survivor wears its history, never the mark
    if g:
        out["dispositions"] = {d: g[d] for d in DISPOSITIONS if d in g}
        out["faculties"] = faculties(g)
        out["expressed"] = expressed(g)
    out["locus_help"] = DESCRIPTIONS
    import time as _t
    now = _t.time()
    out["infections"] = [
        {"strain_uuid": (i.get("strain") or {}).get("strain_uuid"),
         "signature": (i.get("strain") or {}).get("signature"),
         "mods": (i.get("strain") or {}).get("expression_mods"),
         "contagion": (i.get("strain") or {}).get("contagion"),
         "synth_done_at": i.get("synth_done_at"),
         "caught_at": i.get("caught_at"),
         "detected": bool(i.get("detected_at") and
                          i["detected_at"] <= now)}
        for i in (payload.get("infections") or [])]
    out["infection_history"] = payload.get("infection_history") or []
    out["antigens"] = [
        {"strain_uuid": a.get("strain_uuid"),
         "vector": a.get("vector"),
         "decay_rate": a.get("decay_rate"),
         "made_at": a.get("made_at"),
         "potency": max(0.0, 1.0 - a.get("decay_rate", 0.0)
                        * (now - a.get("made_at", now)))}
        for a in (payload.get("antigens") or [])]
    return out


async def agent_beliefs(client: Any, agent_uuid: str) -> dict:
    """Rule 4.1: belief beside truth. Every counterpart this agent holds an
    opinion about, each believed locus next to the subject's REAL value --
    the gap is the story."""
    rows = await client.find_vertices("agents", realm=AGENTS_REALM,
                                      filters={"key": agent_uuid}, limit=1)
    if not rows:
        return {"beliefs": []}
    opinions = rows[0].payload.get("opinions") or {}
    out = []
    for subject, loci in opinions.items():
        srow = await client.find_vertices("agents", realm=AGENTS_REALM,
                                          filters={"key": subject}, limit=1)
        spl = srow[0].payload if srow else {}
        truth = spl.get("genotype") or {}
        out.append({
            "subject": subject,
            "name": spl.get("name"),
            "colour_pair": spl.get("colour_pair"),
            "loci": [{"locus": k,
                      "believed": v.get("estimate"),
                      "weight": v.get("weight"),
                      "actual": truth.get(k)}
                     for k, v in loci.items()]})
    return {"beliefs": out}


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


async def world_timeline(client: Any, world_realm: str,
                         before: str = "", limit: int = 50) -> list[dict]:
    """Phase 11: the world's activity, readable BACK in time -- newest
    first, paginated by done_at. Built from the events table (Rule: the
    digest and the timeline come from the record, never a separate log)."""
    where = [("done_at", "not_null", None)]
    if before:
        where.append(("done_at", "<", before))
    rows = await client.find_vertices("events", realm=world_realm,
                                      where=where, order_by="done_at",
                                      descending=True,
                                      limit=max(1, min(int(limit), 200)))
    return [{"at": v.payload.get("done_at"),
             "kind": v.payload.get("kind"),
             "subject": v.payload.get("subject"),
             "voided": v.payload.get("voided")}
            for v in rows]


async def world_events(client: Any, world_realm: str, since: str) -> list[dict]:
    """Completed events after `since` — the client's incremental feed."""
    rows = await client.get_vertices("events", realm=world_realm)
    done = [v.payload for v in rows
            if v.payload.get("done_at") and v.payload["done_at"] > since]
    return sorted(done, key=lambda p: p["done_at"])
