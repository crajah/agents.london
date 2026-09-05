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
        "muster_points": w["muster_points"],
        "cert": cert, "root_public_pem": root_public})
    for p in w["piles"]:
        await store.put_pile(realm, p["pile_uuid"], p)

    a = f"agent-{hashlib.sha256((user_id + ':first').encode()).hexdigest()[:10]}"
    g = worldgen.founder_genotype(w, 0)
    ident = I.identity_hash(g, realm, a)
    from genome_core import skills as _sk
    payload = {"alive": True, "home_realm": realm, "owner_user_id": user_id,
               "capability": _sk.roll_capability(a),   # skills-spec 1.1
               "generation": 1,
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
    await link_to_commons(client, realm)
    await link_random_worlds(client, realm, want=5)
    await notify.emit(client, user_id, "platform", "world_created",
                      f"Your world {realm} exists. Your first agent, "
                      f"{payload['name']}, is awake in it.")
    return {"world_realm": realm, "created": True, "first_agent": a}


async def _user_row(client: Any, user_id: str):
    rows = await client.find_vertices("agents", realm="genome_agents",
                                      filters={"key": f"user:{user_id}"},
                                      limit=1)
    return rows[0] if rows else None


async def is_verified(client: Any, user_id: str) -> bool:
    row = await _user_row(client, user_id)
    return bool(row and row.payload.get("email_verified"))


async def mark_verified(client: Any, user_id: str) -> None:
    """The address is proven held -- by following its magic link, or by an
    OAuth provider attesting it."""
    row = await _user_row(client, user_id)
    if row is not None and not row.payload.get("email_verified"):
        await client.upsert_vertex("agents", realm="genome_agents",
                                   vertex_id=int(row.id), space="default",
                                   payload={**row.payload,
                                            "email_verified": True})


def _free_slot(meta: dict) -> dict | None:
    used = {(round(p["x"], 4), round(p["y"], 4))
            for p in meta.get("portals", [])}
    for s in meta.get("portal_slots", []):
        if (round(s["x"], 4), round(s["y"], 4)) not in used:
            return s
    return None


def _grow_slot(meta: dict, seed: str) -> dict | None:
    """One more portal slot, clear of terrain and standing slots -- the same
    constraints worldgen applies, seeded so re-runs agree."""
    import random as _rnd
    r = _rnd.Random(seed)
    terrain = meta.get("terrain", [])
    slots = meta.get("portal_slots", [])
    for _try in range(120):
        q = (r.uniform(0.08, 0.92), r.uniform(0.08, 0.92))
        if any((q[0] - o["x"]) ** 2 + (q[1] - o["y"]) ** 2
               < (o.get("r", 0.0) + 0.03) ** 2 for o in terrain):
            continue
        if any((q[0] - t["x"]) ** 2 + (q[1] - t["y"]) ** 2 < 0.10 ** 2
               for t in slots):
            continue
        return {"x": round(q[0], 4), "y": round(q[1], 4)}
    return None


async def _user_world_realms(client: Any) -> list[str]:
    """Every LIVING world born through genesis: tombstoned and paused
    worlds are memorials, not destinations -- a door into one strands
    whoever steps through (found live 2026-09-05)."""
    out = set()
    for v in await client.get_vertices("agents", realm="genome_agents"):
        if v.payload.get("key", "").startswith("user:") and                 v.payload.get("world_realm"):
            out.add(v.payload["world_realm"])
    store = GenomeStore(client)
    living = []
    for w in sorted(out):
        meta = await drain._world_payload(store, w)
        if not (meta.get("tombstoned") or meta.get("paused")):
            living.append(w)
    return living


async def link_random_worlds(client: Any, realm: str, want: int = 5) -> list:
    """Teleport links to `want` random OTHER user worlds (user directive
    2026-09-05: a new world joins five at birth). Deterministic per realm;
    already-linked pairs are permanent and skipped."""
    import random as _rnd
    store = GenomeStore(client)
    meta = await drain._world_payload(store, realm)
    linked = {p.get("to_world") for p in meta.get("portals", [])}
    candidates = [w for w in await _user_world_realms(client)
                  if w != realm and w not in linked
                  and not w.startswith("genome_commons")]
    r = _rnd.Random(f"randlinks:{realm}")
    r.shuffle(candidates)
    made = []
    for w in candidates:
        if len(made) >= want:
            break
        if await link_worlds(client, realm, w):
            made.append(w)
    return made


async def topup_portals(client: Any, minimum: int = 5) -> dict:
    """Every user world up to at least `minimum` teleport points (commons
    included in the count -- it is a portal like any other)."""
    store = GenomeStore(client)
    out = {}
    for w in await _user_world_realms(client):
        meta = await drain._world_payload(store, w)
        n = len(meta.get("portals", []))
        if n >= minimum:
            continue
        made = await link_random_worlds(client, w, want=minimum - n)
        out[w] = {"had": n, "added": made}
    return out


async def link_worlds(client: Any, realm_a: str, realm_b: str) -> bool:
    """A teleport link, both ways, at each world's next free slot
    (Rules 6.2e/6.3a: fixed positions, permanent)."""
    store = GenomeStore(client)
    meta_a = await drain._world_payload(store, realm_a)
    meta_b = await drain._world_payload(store, realm_b)
    if any(p.get("to_world") == realm_b for p in meta_a.get("portals", [])):
        return False                              # already linked (permanent)
    sa, sb = _free_slot(meta_a), _free_slot(meta_b)
    # Rule 6.2e fixed the slots at creation, but connectivity outgrew four
    # (user directive 2026-09-05: every world holds at least five portals),
    # so a full world mints one more slot -- placed by the same constraints
    # the generator used, deterministic per (realm, slot count)
    if sa is None:
        sa = _grow_slot(meta_a, f"slot:{realm_a}:"
                                f"{len(meta_a.get('portal_slots', []))}")
        if sa:
            meta_a = {**meta_a,
                      "portal_slots": meta_a.get("portal_slots", []) + [sa]}
    if sb is None:
        sb = _grow_slot(meta_b, f"slot:{realm_b}:"
                                f"{len(meta_b.get('portal_slots', []))}")
        if sb:
            meta_b = {**meta_b,
                      "portal_slots": meta_b.get("portal_slots", []) + [sb]}
    if not (sa and sb):
        return False
    from genome_core import construction as _con
    sa = dict(zip(("x", "y"), _con.clear_spot(
        sa["x"], sa["y"], await _con.obstacle_points(client, realm_a),
        min_d=0.04, seed=f"portal:{realm_a}:{realm_b}")))
    sb = dict(zip(("x", "y"), _con.clear_spot(
        sb["x"], sb["y"], await _con.obstacle_points(client, realm_b),
        min_d=0.04, seed=f"portal:{realm_b}:{realm_a}")))
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
            f"sign in with Google or Microsoft using this address to "
            f"enter it: {web}")
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


COMMONS = "genome_commons_0"          # shard 0; assignment stable by creation
COMMONS_COLOURS = ["#F5F5F5", "#CFD8DC"]


async def ensure_commons(client: Any) -> str:
    """Rules 6.2f/6.2h: the ownerless world -- no piles, never floods."""
    store = GenomeStore(client)
    meta = await drain._world_payload(store, COMMONS)
    if meta:
        return COMMONS
    await ensure_world_realm(client, COMMONS)
    root_rows = await client.find_vertices("trust", realm="genome_agents",
                                           filters={"key": "root"}, limit=1)
    cert = root_public = None
    if root_rows:
        root = {"doc": root_rows[0].payload["doc"],
                "private_pem": root_rows[0].payload["private_pem"]}
        cert = I.issue_world_cert(root, COMMONS)
        root_public = root["doc"]["public_pem"]
    await store.put_world(COMMONS, {
        "is_commons": True, "owner_user_id": None,
        "kinds": [], "colours": COMMONS_COLOURS,
        "terrain": [], "portals": [], "portal_slots": [], "stock": {},
        "cert": cert, "root_public_pem": root_public})
    await client.add_vertex("agents", realm="genome_agents",
                            payload={"key": f"commons:{COMMONS}",
                                     "world_realm": COMMONS})
    return COMMONS


def commons_rim_xy(realm: str, taken: list[dict] | None = None) -> list[float]:
    """A deterministic spot on the commons rim for a world's door — hashed
    from the realm name, then stepped by the golden angle past any door
    already standing within 0.07 (portals never overlap)."""
    import hashlib as _h
    import math as _m
    a = int(_h.sha256(realm.encode()).hexdigest()[:8], 16) / 0xffffffff
    ang = a * 2 * _m.pi
    golden = 2.399963229728653
    for _ in range(64):
        x = 0.5 + 0.40 * _m.cos(ang)
        y = 0.5 + 0.40 * _m.sin(ang)
        if all((x - q["x"]) ** 2 + (y - q["y"]) ** 2 >= 0.07 ** 2
               for q in (taken or [])):
            return [round(x, 4), round(y, 4)]
        ang += golden
    return [round(x, 4), round(y, 4)]


async def link_to_commons(client: Any, realm: str) -> bool:
    """Slot 0 is the commons door (Rule 6.2f). TWO-WAY (user directive
    2026-08-31, revising 6.2g): the commons lists an outbound door for every
    linked world, placed on its rim."""
    store = GenomeStore(client)
    await ensure_commons(client)
    meta = await drain._world_payload(store, realm)
    changed = False
    if not any(p.get("to_world") == COMMONS
               for p in meta.get("portals", [])):
        slots = meta.get("portal_slots") or [{"x": 0.15, "y": 0.15}]
        from genome_core import construction as _con
        s0 = dict(zip(("x", "y"), _con.clear_spot(
            slots[0]["x"], slots[0]["y"],
            await _con.obstacle_points(client, realm),
            min_d=0.04, seed=f"door:{realm}")))
        cmeta0 = await drain._world_payload(store, COMMONS)
        portal = {"x": s0["x"], "y": s0["y"], "to_world": COMMONS,
                  "dest_xy": commons_rim_xy(realm, cmeta0.get("portals", [])),
                  "dest_colours": COMMONS_COLOURS}
        await store.put_world(realm, {**meta, "portals":
                                      meta.get("portals", []) + [portal]})
        changed = True
    cmeta = await drain._world_payload(store, COMMONS)
    if not any(p.get("to_world") == realm
               for p in cmeta.get("portals", [])):
        rim = commons_rim_xy(realm, cmeta.get("portals", []))
        back = {"x": rim[0], "y": rim[1], "to_world": realm,
                "dest_xy": [meta.get("portal_slots", [{"x": .15, "y": .15}])[0]["x"],
                            meta.get("portal_slots", [{"x": .15, "y": .15}])[0]["y"]],
                "dest_colours": meta.get("colours")}
        await store.put_world(COMMONS, {**cmeta, "portals":
                                        cmeta.get("portals", []) + [back]})
        changed = True
    return changed
