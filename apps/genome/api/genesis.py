"""First login → a world and its free first agent (Rules 2.1/2.2/7.1).

Idempotent per user: the world seed derives from the user id, so logging in
again finds the same world. The world is certified under the root held in the
trust store; the first agent is the genesis exemption -- unpaid, founder-drawn
from the world's own centre, with its perish appointment booked at birth.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from genome_core import drain, identity as I, worldgen
from genome_core.store import GenomeStore, ensure_world_realm


async def user_world_realm(client: Any, user_id: str) -> str | None:
    rows = await client.find_vertices("agents", realm="genome_agents",
                                      filters={"key": f"user:{user_id}"},
                                      limit=1)
    return rows[0].payload.get("world_realm") if rows else None


async def ensure_user_world(client: Any, user_id: str) -> dict:
    existing = await user_world_realm(client, user_id)
    if existing:
        return {"world_realm": existing, "created": False}

    store = GenomeStore(client)
    seed = int(hashlib.sha256(user_id.encode()).hexdigest()[:12], 16)
    w = worldgen.generate_world(seed, user_id)
    realm = w["realm"]
    now = time.time()
    await ensure_world_realm(client, realm)

    root_rows = await client.find_vertices("trust", realm="genome_agents",
                                           filters={"key": "root"}, limit=1)
    cert = root_public = None
    if root_rows:
        root = {"doc": root_rows[0].payload["doc"],
                "private_pem": root_rows[0].payload["private_pem"]}
        cert = I.issue_world_cert(root, realm)
        root_public = root["doc"]["public_pem"]

    await store.put_world(realm, {
        "owner_user_id": user_id, "kinds": w["kinds"], "colours": w["colours"],
        "terrain": w["terrain"], "founding_centre": w["founding_centre"],
        "portal_slots": w["portal_slots"], "portals": [], "stock": {},
        "cert": cert, "root_public_pem": root_public})
    for p in w["piles"]:
        await store.put_pile(realm, p["pile_uuid"], p)

    a = f"agent-{hashlib.sha256((user_id + ':first').encode()).hexdigest()[:10]}"
    g = worldgen.founder_genotype(w, 0)
    ident = I.identity_hash(g, realm, a)
    payload = {"alive": True, "home_realm": realm, "owner_user_id": user_id,
               "name": worldgen.founder_name(seed),
               "genotype": g, "colour_pair": w["colours"],
               "identity": ident,
               "cert": I.issue_agent_cert(cert, a, ident) if cert else None,
               "transfer_counter": 0, "known_piles": [], "explored": [[3, 3]],
               "born_at": now}
    await store.put_agent(a, payload)
    await store.set_presence(realm, a, True)
    await store.set_movement(a, {"waypoints": [[0.5, 0.5]], "departed_at": now,
                                 "arrives_at": now, "cargo": {}})
    await drain.schedule_perish(store, a, payload, now)
    await store.schedule(realm, f"genesis-{a}", drain._iso(now + 60.0),
                         "decide", a, {})
    # the user record maps login -> world
    await client.add_vertex("agents", realm="genome_agents",
                            payload={"key": f"user:{user_id}",
                                     "world_realm": realm,
                                     "first_agent": a, "created_at": now})
    return {"world_realm": realm, "created": True, "first_agent": a}
