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
from genome_core import drain, identity as I, notify, worldgen
from genome_core.store import GenomeStore, ensure_world_realm


async def user_world_realm(client: Any, user_id: str) -> str | None:
    rows = await client.find_vertices("agents", realm="genome_agents",
                                      filters={"key": f"user:{user_id}"},
                                      limit=1)
    return rows[0].payload.get("world_realm") if rows else None


async def ensure_user_world(client: Any, user_id: str,
                            email: str | None = None) -> dict:
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
                                     "world_realm": realm, "email": email,
                                     "first_agent": a, "created_at": now})
    await notify.emit(client, user_id, "platform", "world_created",
                      f"Your world {realm} exists. Your first agent, "
                      f"{payload['name']}, is awake in it.")
    return {"world_realm": realm, "created": True, "first_agent": a}


def _free_slot(meta: dict) -> dict | None:
    used = {(round(p["x"], 4), round(p["y"], 4))
            for p in meta.get("portals", [])}
    for s in meta.get("portal_slots", []):
        if (round(s["x"], 4), round(s["y"], 4)) not in used:
            return s
    return None


async def link_worlds(client: Any, realm_a: str, realm_b: str) -> bool:
    """A teleport link, both ways, at each world's next free slot
    (Rules 6.2e/6.3a: fixed positions, permanent)."""
    store = GenomeStore(client)
    meta_a = await drain._world_payload(store, realm_a)
    meta_b = await drain._world_payload(store, realm_b)
    if any(p.get("to_world") == realm_b for p in meta_a.get("portals", [])):
        return False                              # already linked (permanent)
    sa, sb = _free_slot(meta_a), _free_slot(meta_b)
    if not (sa and sb):
        return False
    pa = {"x": sa["x"], "y": sa["y"], "to_world": realm_b,
          "dest_xy": [sb["x"], sb["y"]], "dest_colours": meta_b.get("colours")}
    pb = {"x": sb["x"], "y": sb["y"], "to_world": realm_a,
          "dest_xy": [sa["x"], sa["y"]], "dest_colours": meta_a.get("colours")}
    await store.put_world(realm_a, {**meta_a,
                                    "portals": meta_a.get("portals", []) + [pa]})
    await store.put_world(realm_b, {**meta_b,
                                    "portals": meta_b.get("portals", []) + [pb]})
    return True


async def invite_user(client: Any, inviter_id: str, email: str) -> dict:
    """Rule 6.2j, whole flow: identity from the email hash, world eagerly,
    login link to the outbox, portals linked, both sides notified."""
    import auth as auth_mod
    invitee_id = auth_mod.user_id_from_email(email)
    if invitee_id == inviter_id:
        return {"error": "that is your own address"}
    inviter_realm = await user_world_realm(client, inviter_id)
    if not inviter_realm:
        return {"error": "inviter has no world"}
    result = await ensure_user_world(client, invitee_id, email=email)
    invitee_realm = result["world_realm"]
    linked = await link_worlds(client, inviter_realm, invitee_realm)
    import os
    web = os.getenv("GENOME_WEB_BASE", "http://localhost:5173")
    if result["created"]:
        await notify.outbox(client, email, "A world awaits you in genome",
            f"You were invited to genome. Your world already exists -- "
            f"sign in with this address to enter it: {web}")
    # notifications only when something actually happened (a re-invite of an
    # already-linked pair changes nothing and says nothing)
    if linked:
        await notify.emit(client, invitee_id, "platform", "invite_received",
                          f"You were invited; a portal now links your world "
                          f"to {inviter_realm}.")
        await notify.emit(client, inviter_id, "platform", "link_created",
                          f"Your world is now linked to {invitee_realm}"
                          f" ({email}).")
    return {"ok": True, "invitee_world": invitee_realm,
            "world_created": result["created"], "linked": linked,
            "already_linked": not linked and not result["created"]}
