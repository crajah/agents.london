"""Free agents — an ADMIN lever, not an economic act.

The owner-facing economy prices materialisation (Rule 2.1); this module is
the operator's hand on the dial instead: ownerless agents seeded into
worlds on a schedule to thicken the society. They are full citizens --
genotype from the world's founding centre, certificate, lifespan, a mind
from the pool -- but carry owner_user_id=None and spawned_free=True so
every analysis can include or exclude them deliberately.

Config lives on ONE vertex (agents realm, key "sim_config"):
  {"free_agent_spawn": bool, "spawn_interval_s": float,
   "spawn_cap_per_world": int}
"""
from __future__ import annotations

import hashlib
import time
import uuid as uuidlib
from typing import Any

from . import drain, identity as I, worldgen

CONFIG_KEY = "sim_config"
DEFAULTS = {"free_agent_spawn": False,
            "spawn_interval_s": 3600.0,
            "spawn_cap_per_world": 12}


async def get_config(client: Any) -> dict:
    try:
        rows = await client.find_vertices("agents", realm="genome_agents",
                                          filters={"key": CONFIG_KEY},
                                          limit=1)
    except Exception:
        return dict(DEFAULTS)
    if not rows:
        return dict(DEFAULTS)
    return {**DEFAULTS, **{k: v for k, v in rows[0].payload.items()
                           if k in DEFAULTS}}


async def set_config(client: Any, updates: dict) -> dict:
    rows = await client.find_vertices("agents", realm="genome_agents",
                                      filters={"key": CONFIG_KEY}, limit=1)
    clean = {k: updates[k] for k in DEFAULTS if k in updates}
    if rows:
        merged = {**rows[0].payload, **clean, "key": CONFIG_KEY}
        await client.upsert_vertex("agents", realm="genome_agents",
                                   vertex_id=int(rows[0].id),
                                   space="default", payload=merged)
    else:
        await client.add_vertex("agents", realm="genome_agents",
                                payload={"key": CONFIG_KEY, **clean})
    return await get_config(client)


async def spawn_free_agent(store, realm: str, meta: dict,
                           now: float) -> str | None:
    """One free citizen for this world: founding-centre genotype, cert from
    the world's own key, a name from the pool, and a first decision."""
    seed = int(hashlib.sha256(f"{realm}:{now}".encode()).hexdigest()[:8], 16)
    if not meta.get("founding_centre"):
        # older worlds never recorded a centre; draw one from the realm name
        # so the world's free-born share a heritage (Rule 3.2a's spirit)
        import random as _r
        rr = _r.Random(f"centre:{realm}")
        from .genotype import RANGES
        meta = {**meta, "founding_centre":
                {k: rr.uniform(*RANGES[k]) for k in RANGES}}
    a = f"agent-free-{uuidlib.uuid4().hex[:10]}"
    g = worldgen.founder_genotype({**meta, "realm": realm}, seed)
    ident = I.identity_hash(g, realm, a)
    cert = None
    if meta.get("cert"):
        try:
            cert = I.issue_agent_cert(meta["cert"], a, ident)
        except Exception:
            cert = None                    # unsigned worlds still populate
    from . import skills as _sk
    payload = {"alive": True, "home_realm": realm, "owner_user_id": None,
               "capability": _sk.roll_capability(a),   # skills-spec 1.1
               "spawned_free": True,
               "name": worldgen.founder_name(seed),
               "genotype": g, "colour_pair": meta.get("colours"),
               "identity": ident, "cert": cert, "transfer_counter": 0,
               "known_piles": [], "explored": [[3, 3]], "born_at": now}
    await store.put_agent(a, payload)
    await store.set_presence(realm, a, True)
    await store.set_movement(a, {"waypoints": [[0.5, 0.5]],
                                 "departed_at": now, "arrives_at": now,
                                 "cargo": {}})
    await drain.schedule_perish(store, a, payload, now)
    await store.schedule(realm, f"spawn-{a}", drain._iso(now + 10.0),
                         "decide", a, {})
    return a


async def maybe_spawn(store, realm: str, meta: dict, cfg: dict,
                      now: float) -> str | None:
    """Called each heal cycle. Spawns at most one agent per interval per
    world, never past the cap, never in the commons or a tombstone."""
    if not cfg.get("free_agent_spawn"):
        return None
    if meta.get("is_commons") or meta.get("tombstoned") or meta.get("paused"):
        return None
    if now - meta.get("last_free_spawn_at", 0.0) \
            < float(cfg.get("spawn_interval_s", 3600.0)):
        return None
    live = [v.payload["key"] for v in await store.agents_in(realm)
            if not v.payload["key"].startswith("user:")]
    if len(live) >= int(cfg.get("spawn_cap_per_world", 12)):
        return None
    a = await spawn_free_agent(store, realm, meta, now)
    if a:
        await store.put_world(realm, {**meta, "last_free_spawn_at": now})
    return a
