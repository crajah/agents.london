"""Constructions — construction-spec §3, first working slice.

The immutable Ark tree (Rule 3.9a), sites founded on the map, cargo
contributed straight from an agent's hold (Rule 3.5), distinct-user counting
(Rules 3.3/3.4), completion, and the first two live effects (calibration §5).
Berths, portage and the flood are the next slice.

Storage: a `constructions` vertex table in the WORLD's realm — a site is as
much a fixture of a world as a pile. Costs are resolved at founding and
recorded on the site, so the bill never drifts under a spec edit.
"""
from __future__ import annotations

import time
import uuid as uuidlib
from typing import Any

from . import notify

FAMILIES = {
    "life": [0, 1, 2, 3],
    "water": [4, 5, 6, 7, 19],
    "growth": [8, 9, 10, 11],
    "fire": [12, 13, 14, 15],
    "earth": [16, 17, 18],
}

# name -> (branch, tier, prerequisite construction in the same world, cost)
# cost: ("kinds", K, N) = K distinct family kinds, N units each
#       ("family_all", N)  = every family kind, N units each
#       ("one_per_family", N) = one kind from each family, N units each
#       ("all_kinds", N)   = every kind 0..19, N units each
TREE: dict[str, dict] = {
    "cairn":       {"branch": "earth",  "tier": 1, "after": None,        "cost": ("kinds", 1, 10)},
    "store":       {"branch": "earth",  "tier": 2, "after": "cairn",     "cost": ("kinds", 2, 15)},
    "rampart":     {"branch": "earth",  "tier": 3, "after": "store",     "cost": ("kinds", 2, 15)},
    "foundation":  {"branch": "earth",  "tier": 4, "after": "rampart",   "cost": ("family_all", 20)},
    "kiln":        {"branch": "fire",   "tier": 1, "after": None,        "cost": ("kinds", 1, 10)},
    "toolhouse":   {"branch": "fire",   "tier": 2, "after": "kiln",      "cost": ("kinds", 2, 15)},
    "forge":       {"branch": "fire",   "tier": 3, "after": "toolhouse", "cost": ("family_all", 20)},
    "grove":       {"branch": "growth", "tier": 1, "after": None,        "cost": ("kinds", 1, 10)},
    "granary":     {"branch": "growth", "tier": 2, "after": "grove",     "cost": ("kinds", 2, 15)},
    "orchard":     {"branch": "growth", "tier": 3, "after": "granary",   "cost": ("family_all", 20)},
    "apothecary":  {"branch": "life",   "tier": 1, "after": None,        "cost": ("kinds", 1, 10)},
    "infirmary":   {"branch": "life",   "tier": 2, "after": "apothecary","cost": ("kinds", 2, 15)},
    "sanatorium":  {"branch": "life",   "tier": 3, "after": "infirmary", "cost": ("family_all", 20)},
    "library":     {"branch": "water",  "tier": 1, "after": None,        "cost": ("kinds", 1, 10)},
    "beacon":      {"branch": "water",  "tier": 2, "after": "library",   "cost": ("kinds", 2, 15)},
    "observatory": {"branch": "water",  "tier": 3, "after": "beacon",    "cost": ("family_all", 20)},
    "shipyard":    {"branch": "convergence", "tier": 5,
                    "after": ("foundation", "forge", "orchard",
                              "sanatorium", "observatory"),
                    "cost": ("one_per_family", 10)},
    "ark":         {"branch": "convergence", "tier": 6, "after": "shipyard",
                    "cost": ("all_kinds", 10)},
}

# Rule 3.3: distinct contributors required, by construction
CONTRIBUTORS = {name: (8 if name == "ark" else 5 if name == "shipyard"
                       else min(spec["tier"], 3) if spec["tier"] <= 4 else 3)
                for name, spec in TREE.items()}
CONTRIBUTORS["foundation"] = 3           # capstone, though tier 4 in earth

TABLE = "constructions"

# Nothing founded may overlap anything standing (user directive
# 2026-09-04): sites, piles, muster flags and the market all keep this
# distance; a crowded candidate spot walks a deterministic spiral out.
SITE_SPACING = 0.05


def clear_spot(x: float, y: float, points: list[tuple],
               min_d: float = SITE_SPACING,
               seed: str = "") -> tuple[float, float]:
    import math as _m
    import random as _r
    if all((x - px) ** 2 + (y - py) ** 2 >= min_d * min_d
           for px, py in points):
        return x, y
    a0 = _r.Random(f"spot:{seed}").uniform(0, 2 * _m.pi)
    for ring in range(1, 9):
        rad = min_d * (0.9 + 0.55 * ring)
        for i in range(10):
            a = a0 + i * _m.pi / 5 + ring * 0.3
            cx = min(0.95, max(0.05, x + rad * _m.cos(a)))
            cy = min(0.95, max(0.05, y + rad * _m.sin(a)))
            if all((cx - px) ** 2 + (cy - py) ** 2 >= min_d * min_d
                   for px, py in points):
                return cx, cy
    return x, y                            # a map this full keeps its pile-up


async def obstacle_points(client: Any, realm: str) -> list[tuple]:
    """Everything standing that placement must respect."""
    pts = []
    for v in await sites_in(client, realm):
        if not v.payload.get("destroyed"):
            pts.append((v.payload["x"], v.payload["y"]))
    try:
        for v in await client.get_vertices("piles", realm=realm):
            pts.append((v.payload["x"], v.payload["y"]))
    except Exception:
        pass
    rows = await client.find_vertices("world_meta", realm=realm,
                                      filters={"key": realm}, limit=1)
    meta = rows[0].payload if rows else {}
    for m in meta.get("muster_points", []) or []:
        pts.append((m["x"], m["y"]))
    if meta.get("market"):
        pts.append((meta["market"]["x"], meta["market"]["y"]))
    for pt in meta.get("portals", []) or []:
        pts.append((pt["x"], pt["y"]))         # teleport points stand clear too
    return pts

# User directive 2026-09-02: a filled, fully-crewed site RISES over time --
# longer the higher the tier, never so long the watch goes stale. Divided by
# the world's time_scale like every other duration.
BUILD_MINUTES = {1: 15, 2: 30, 3: 60, 4: 90, 5: 120, 6: 180}

# User directive: the Ark is ASSEMBLED -- its sub-components must be dragged
# together (portage) before the convergence tier can be founded. Prereqs of a
# convergence construction must stand within this radius of the new ground.
ASSEMBLY_RADIUS = 0.15


def resolve_cost(name: str, world_kinds: list[int]) -> dict[str, float]:
    """Calibration §5: the world's own kinds where they qualify, lowest
    palette index otherwise. Returns {kind(str): units}."""
    branch = TREE[name]["branch"]
    cost = TREE[name]["cost"]
    if cost[0] == "all_kinds":
        return {str(k): float(cost[1]) for k in range(20)}
    if cost[0] == "one_per_family":
        picks = []
        for fam, kinds in FAMILIES.items():
            own = [k for k in world_kinds if k in kinds]
            picks.append(own[0] if own else kinds[0])
        return {str(k): float(cost[1]) for k in picks}
    fam_kinds = FAMILIES[branch]
    if cost[0] == "family_all":
        return {str(k): float(cost[1]) for k in fam_kinds}
    _, k_needed, units = cost
    own = [k for k in world_kinds if k in fam_kinds]
    picks = (own + [k for k in fam_kinds if k not in own])[:k_needed]
    return {str(k): float(units) for k in picks}


async def sites_in(client: Any, realm: str) -> list:
    try:
        return await client.get_vertices(TABLE, realm=realm)
    except Exception:
        return []                          # table minted on first founding


async def completed_names(client: Any, realm: str) -> set[str]:
    return {v.payload["name"] for v in await sites_in(client, realm)
            if v.payload.get("complete") and not v.payload.get("destroyed")
            and not v.payload.get("spent")
            and not v.payload.get("plan_key")}


def _prereqs(name: str) -> tuple:
    after = TREE[name]["after"]
    return (after,) if isinstance(after, str) else (after or ())


def foundable_names(sites: list[dict]) -> list[str]:
    """What may break ground here NOW: prerequisites standing complete (for
    the convergence tier, complete AND huddled within ASSEMBLY_RADIUS of one
    another -- the drag-the-components-together rule), and no live duplicate
    already under way or standing."""
    canon = [s for s in sites if not s.get("plan_key")]
    done = {s["name"]: s for s in canon
            if s.get("complete") and not s.get("destroyed")
            and not s.get("spent")}
    live = {s["name"] for s in canon
            if not s.get("destroyed") and not s.get("spent")}
    out = []
    for name in TREE:
        if name in live:
            continue
        need = _prereqs(name)
        if any(a not in done for a in need):
            continue
        if TREE[name]["branch"] == "convergence" and len(need) > 1:
            pts = [(done[a]["x"], done[a]["y"]) for a in need]
            cx = sum(q[0] for q in pts) / len(pts)
            cy = sum(q[1] for q in pts) / len(pts)
            if any((qx - cx) ** 2 + (qy - cy) ** 2 > ASSEMBLY_RADIUS ** 2
                   for qx, qy in pts):
                continue
        out.append(name)
    return out


async def found_site(client: Any, realm: str, user_id: str, name: str,
                     x: float, y: float, world_kinds: list[int]) -> dict:
    """Ground is broken by an AGENT for its line (user directive 2026-09-02:
    no human hand needed) or by the owner through the API -- either way the
    tree itself never bends: names come from TREE and only from TREE
    (Rule 3.9a; user plans are ADDITIVE trees, arriving with 13.6)."""
    if name.startswith("plan:"):
        # Rule 13.6d: a known plan raises anywhere. The node's bill and crew
        # were fixed at authoring; its tier is its depth in the tree.
        from . import plans as _plans
        try:
            _, plan_key, item = name.split(":", 2)
        except ValueError:
            return {"error": "malformed plan reference"}
        plan = await _plans.get_plan(client, plan_key)
        if plan is None:
            return {"error": "no such plan"}
        node = next((n for n in plan.get("tree", [])
                     if n["item"] == item), None)
        if node is None:
            return {"error": f"the plan has no item {item!r}"}
        sites = [v.payload for v in await sites_in(client, realm)
                 if not v.payload.get("destroyed")]
        if name.replace("plan:", "", 1) and any(
                s.get("plan_key") == plan_key and s.get("plan_item") == item
                for s in sites):
            return {"error": f"a {item} of this plan already stands here"}
        done = {s.get("plan_item") for s in sites
                if s.get("plan_key") == plan_key and s.get("complete")}
        missing = [a for a in node.get("after", []) if a not in done]
        if missing:
            return {"error": f"requires completed: {', '.join(missing)}"}
        x, y = clear_spot(x, y, await obstacle_points(client, realm),
                          seed=f"{realm}:{plan_key}:{item}")
        site = {"key": f"site-{uuidlib.uuid4().hex[:10]}",
                "name": item, "branch": "plan",
                "tier": _plans.depth_of(plan["tree"], item),
                "x": x, "y": y,
                "needs": {k: float(u) for k, u in node["needs"].items()},
                "delivered": {}, "contributors": {},
                "required_users": int(node.get("contributors", 1)),
                "plan_key": plan_key, "plan_item": item,
                "complete": False, "founded_by": user_id,
                "founded_at": time.time()}
        await client.add_vertex(TABLE, realm=realm, payload=site)
        return {"ok": True, "site": site["key"], "needs": site["needs"]}
    if name not in TREE:
        return {"error": f"no construction named {name}"}
    done_sites = {v.payload["name"]: v.payload
                  for v in await sites_in(client, realm)
                  if v.payload.get("complete")
                  and not v.payload.get("destroyed")
                  and not v.payload.get("spent")}
    done = set(done_sites)
    needs_after = _prereqs(name)
    missing = [a for a in needs_after if a not in done]
    if missing:
        return {"error": f"requires completed: {', '.join(missing)}"}
    if TREE[name]["branch"] == "convergence":
        # assembly: every sub-component dragged to the new ground
        far = [a for a in needs_after
               if (done_sites[a]["x"] - x) ** 2
               + (done_sites[a]["y"] - y) ** 2 > ASSEMBLY_RADIUS ** 2]
        if far:
            return {"error": f"the {name} is assembled from its parts: "
                    f"{', '.join(far)} stand too far from this ground "
                    f"-- carry them here first"}
    for v in await sites_in(client, realm):
        if v.payload["name"] == name and not v.payload.get("complete") \
                and not v.payload.get("destroyed"):
            return {"error": f"a {name} is already under way here"}
    x, y = clear_spot(x, y, await obstacle_points(client, realm),
                      seed=f"{realm}:{name}:{user_id}")
    site = {
        "key": f"site-{uuidlib.uuid4().hex[:10]}",
        "name": name, "branch": TREE[name]["branch"],
        "tier": TREE[name]["tier"], "x": x, "y": y,
        "needs": resolve_cost(name, world_kinds),
        "delivered": {}, "contributors": {},
        "required_users": CONTRIBUTORS[name],
        "complete": False, "founded_by": user_id, "founded_at": time.time(),
    }
    await client.add_vertex(TABLE, realm=realm, payload=site)
    return {"ok": True, "site": site["key"], "needs": site["needs"]}


def accepts(site: dict, cargo: dict[str, float]) -> dict[str, float]:
    """What of this cargo the site can still absorb (Rule 3.6: into the
    construction, never the host's stock)."""
    out = {}
    for kind, units in cargo.items():
        room = site.get("needs", {}).get(kind, 0.0) \
            - site.get("delivered", {}).get(kind, 0.0)
        if room > 1e-9 and units > 1e-9:
            out[kind] = min(units, room)
    return out


async def contribute(client: Any, realm: str, site_key: str,
                     user_id: str, agent_uuid: str,
                     cargo: dict[str, float],
                     time_scale: float = 1.0,
                     build_time_mult: float = 1.0) -> dict:
    """Pour an agent's hold into a site. Returns what was taken and whether
    the construction completed. Rule 3.4: the USER is counted, however many
    agents delivered."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": site_key}, limit=1)
    if not rows:
        return {"taken": {}, "complete": False, "error": "no such site"}
    site = dict(rows[0].payload)
    if site.get("complete"):
        return {"taken": {}, "complete": True}
    take = accepts(site, cargo)
    if not take:
        return {"taken": {}, "complete": False}
    # Reservation guard: never let the fill outrun the user count. Each
    # distinct user still missing (Rule 3.3) keeps 5 units of room held back,
    # so a rich early contributor cannot fill the site and strand it
    # complete-in-material but short-of-hands forever.
    contributors_now = set(site.get("contributors", {}))
    joining = contributors_now | ({user_id} if user_id else set())
    missing_after = max(0, site.get("required_users", 1) - len(joining))
    total_room = sum(site["needs"].values())         - sum(min(site.get("delivered", {}).get(k, 0.0), u)
              for k, u in site["needs"].items())
    allowed = total_room - 5.0 * missing_after
    if allowed <= 1e-9:
        return {"taken": {}, "complete": False, "reserved": True}
    scale = min(1.0, allowed / sum(take.values()))
    if scale < 1.0:
        take = {k: u * scale for k, u in take.items()}
    delivered = dict(site.get("delivered", {}))
    for kind, units in take.items():
        delivered[kind] = delivered.get(kind, 0.0) + units
    contributors = dict(site.get("contributors", {}))
    if user_id:
        contributors[user_id] = contributors.get(user_id, 0.0) \
            + sum(take.values())
    filled = all(delivered.get(k, 0.0) >= units - 1e-9
                 for k, units in site["needs"].items())
    enough_users = len(contributors) >= site.get("required_users", 1)
    starts_build = filled and enough_users and not site.get("building_until")
    building_until = site.get("building_until")
    if starts_build:
        # materials in, hands counted: now the thing RISES (user directive:
        # tiered build time, divided by the world's clock)
        mins = BUILD_MINUTES.get(int(site.get("tier", 1)), 60) \
            * max(0.1, build_time_mult)      # a Foundation halves the raising
        building_until = time.time() + mins * 60.0 / max(1.0, time_scale)
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**site, "delivered": delivered,
                                        "contributors": contributors,
                                        "complete": False,
                                        **({"building_until": building_until}
                                           if building_until else {})})
    if starts_build:
        for uid in contributors:
            notify.emit_bg(client, uid, "world", "construction_rising",
                              f"The {site['name']} rises -- complete in "
                              f"about {mins} minutes of world time.")
    return {"taken": take, "complete": False,
            "building_started": starts_build,
            "building_until": building_until,
            "site_name": site["name"]}


async def finalize(client: Any, realm: str, site_key: str, now: float) -> dict:
    """The build clock ran out: the construction stands. Idempotent; the Ark
    mints its berth pool here (Rule 3.7e)."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": site_key}, limit=1)
    if not rows:
        return {"error": "no such site"}
    site = dict(rows[0].payload)
    if site.get("complete") or site.get("destroyed"):
        return {"ok": True, "already": True}
    bu = site.get("building_until")
    if not bu or now + 1e-6 < bu:
        return {"error": "still rising"}
    contributors = site.get("contributors", {})
    extra = {}
    if site["name"] == "ark":
        extra["berths"] = allocate_berths(contributors)
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**site, "complete": True,
                                        "completed_at": now, **extra})
    if site["name"] == "orchard":
        # the orchard PLANTS: one fresh pile of each of the world's kinds,
        # rooted beside it -- new ground where there was none
        import random as _r
        wrows = await client.find_vertices("world_meta", realm=realm,
                                           filters={"key": realm}, limit=1)
        kinds = (wrows[0].payload.get("kinds") if wrows else None) or []
        rng = _r.Random(f"orchard:{realm}:{site['key']}")
        planted = await obstacle_points(client, realm)
        for i, kind in enumerate(kinds):
            ang = rng.uniform(0, 6.28318)
            px, py = clear_spot(
                min(0.95, max(0.05, site["x"] + 0.05 * (1 + i)
                              * __import__("math").cos(ang))),
                min(0.95, max(0.05, site["y"] + 0.05 * (1 + i)
                              * __import__("math").sin(ang))),
                planted, seed=f"orchard:{site['key']}:{i}")
            planted.append((px, py))
            await client.add_vertex("piles", realm=realm, payload={
                "key": f"pile-orchard-{site['key']}-{i}",
                "kind": int(kind),
                "x": px,
                "y": py,
                "qty_at": 15.0, "measured_at": now,
                "rate": 0.0015, "cap": 30.0, "qty_origin": 15.0})
    if site["name"] == "observatory":
        # the observatory WATCHES: the flood's countdown window doubles
        wrows = await client.find_vertices("world_meta", realm=realm,
                                           filters={"key": realm}, limit=1)
        if wrows:
            await client.upsert_vertex("world_meta", realm=realm,
                                       vertex_id=int(wrows[0].id),
                                       space="default",
                                       payload={**wrows[0].payload,
                                                "observatory_standing": True})
    for uid in contributors:
        notify.emit_bg(client, uid, "world", "construction_complete",
                          f"The {site['name']} is complete. "
                          f"{len(contributors)} users raised it."
                          + (f" {extra['berths'].get(uid, 0)} berths fall "
                             f"to your claim." if extra else ""))
    return {"ok": True, "name": site["name"]}


def manifest_slots_used(ark: dict, sites: list[dict]) -> int:
    """Rule 4.3b: twelve slots, everything priced against them -- an agent 1,
    a construction its contributor count, stock 1 per unit (stock later)."""
    used = len(ark.get("boarded", {}))
    used += sum(int(n) for n in ark.get("berths", {}).values())   # reserved
    used += sum(s.get("required_users", 1) for s in sites
                if s.get("manifested"))
    return used


async def manifest_construction(client: Any, realm: str, ark_key: str,
                                user_id: str, site_key: str) -> dict:
    """A berth-holding user gives up hold space for a building: the
    construction costs its contributor count in slots, paid by retiring
    that many of the user's unassigned berths (Rule 4.3b's exchange rate
    made literal -- your people or your works)."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": ark_key}, limit=1)
    if not rows or not rows[0].payload.get("complete") \
            or rows[0].payload.get("spent"):
        return {"error": "no ark to load here"}
    ark = dict(rows[0].payload)
    srows = await client.find_vertices(TABLE, realm=realm,
                                       filters={"key": site_key}, limit=1)
    if not srows or not srows[0].payload.get("complete") \
            or srows[0].payload.get("destroyed"):
        return {"error": "no completed construction by that name here"}
    site = dict(srows[0].payload)
    if site.get("manifested"):
        return {"error": "already aboard"}
    if site["name"] == "ark":
        return {"error": "the ark does not carry itself"}
    price = site.get("required_users", 1)
    pool = dict(ark.get("berths", {}))
    if pool.get(user_id, 0) < price:
        return {"error": f"carrying the {site['name']} costs {price} "
                f"berths; your claim holds {pool.get(user_id, 0)}"}
    pool[user_id] -= price
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**ark, "berths": pool})
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(srows[0].id),
                               space="default",
                               payload={**site, "manifested": True,
                                        "manifested_by": user_id})
    return {"ok": True, "slots_paid": price,
            "berths_left": pool[user_id]}


async def manifest_stock(client: Any, realm: str, ark_key: str,
                         user_id: str, stock: dict[str, float],
                         world_stock: dict[str, float]) -> dict:
    """Rule 4.3b's third cargo class: deposited stock rides at ONE SLOT PER
    UNIT, paid in the user's unassigned berths. Only stock actually standing
    in this world's store can be loaded, and loading removes it from the
    store -- it is in the hold now."""
    import math as _m
    want = {k: float(u) for k, u in (stock or {}).items() if float(u) > 0}
    if not want:
        return {"error": "nothing to load"}
    for k, u in want.items():
        if world_stock.get(k, 0.0) + 1e-9 < u:
            return {"error": f"the store holds {world_stock.get(k, 0.0):.1f} "
                    f"of kind {k}, not {u:.1f}"}
    price = _m.ceil(sum(want.values()))
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": ark_key}, limit=1)
    if not rows or not rows[0].payload.get("complete") \
            or rows[0].payload.get("spent"):
        return {"error": "no ark to load here"}
    ark = dict(rows[0].payload)
    pool = dict(ark.get("berths", {}))
    if pool.get(user_id, 0) < price:
        return {"error": f"{price} slots needed; your claim holds "
                f"{pool.get(user_id, 0)} berths"}
    pool[user_id] -= price
    hold = dict(ark.get("stock_manifest", {}))
    for k, u in want.items():
        hold[k] = hold.get(k, 0.0) + u
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**ark, "berths": pool,
                                        "stock_manifest": hold})
    remaining = {k: world_stock.get(k, 0.0) - want.get(k, 0.0)
                 for k in world_stock}
    return {"ok": True, "slots_paid": price, "hold": hold,
            "world_stock_after": {k: v for k, v in remaining.items()
                                  if v > 1e-9}}


async def board(client: Any, realm: str, ark_key: str, user_id: str,
                agent_uuid: str) -> dict:
    """An agent AT the Ark claims one of its owner's berths and steps aboard
    (Rules 3.7e, 4.10a). First-come within a user's own agents — the contest
    Rule 3.7e wants, settled by presence."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": ark_key}, limit=1)
    if not rows or not rows[0].payload.get("complete") \
            or rows[0].payload.get("spent"):
        return {"error": "no boardable ark here"}
    site = dict(rows[0].payload)
    pool = dict(site.get("berths", {}))
    if pool.get(user_id, 0) <= 0:
        return {"error": "your claim holds no berth"}
    pool[user_id] -= 1
    boarded = dict(site.get("boarded", {}))
    boarded[agent_uuid] = user_id
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**site, "berths": pool,
                                        "boarded": boarded})
    arows = await client.find_vertices("agents", realm="genome_agents",
                                       filters={"key": agent_uuid}, limit=1)
    if arows:
        await client.upsert_vertex("agents", realm="genome_agents",
                                   vertex_id=int(arows[0].id), space="default",
                                   payload={**arows[0].payload,
                                            "aboard_ark": ark_key,
                                            "berth": True})
    return {"ok": True, "berths_left": pool[user_id]}


def progress(site: dict) -> float:
    needs = site.get("needs", {})
    total = sum(needs.values())
    if total <= 0:
        return 1.0 if site.get("complete") else 0.0
    got = sum(min(site.get("delivered", {}).get(k, 0.0), u)
              for k, u in needs.items())
    return got / total


ARK_SLOTS = 12                            # Rule 4.3b


def allocate_berths(contributors: dict[str, float],
                    slots: int = ARK_SLOTS) -> dict[str, int]:
    """Rule 3.7: a proportional claim, allocated mechanically — largest
    remainder, ties to the larger contribution then the earlier key so the
    ledger is deterministic. Slice two carries agents only; constructions
    and stock join the manifest with Rule 4.3's exchange rate later."""
    total = sum(contributors.values())
    if total <= 0:
        return {}
    quotas = {u: slots * c / total for u, c in contributors.items()}
    out = {u: int(q) for u, q in quotas.items()}
    left = slots - sum(out.values())
    order = sorted(quotas, key=lambda u: (-(quotas[u] - out[u]),
                                          -contributors[u], u))
    for u in order[:left]:
        out[u] += 1
    return {u: n for u, n in out.items() if n > 0}


async def world_effects(client: Any, realm: str) -> dict:
    """Calibration §5, complete: every standing construction earns its keep."""
    return effects_from([v.payload for v in await sites_in(client, realm)])


def effects_from(sites: list[dict]) -> dict:
    """Pure form: effects from already-loaded site payloads. All neutral when
    nothing stands; the commons founds nothing, so it stays neutral forever."""
    done = {s["name"] for s in sites
            if s.get("complete") and not s.get("destroyed")
            and not s.get("spent") and not s.get("plan_key")}   # Rule 13.7:
    return {  # a plan item named "toolhouse" is still just a structure
        # earth: keeping
        "stock_ceiling_bonus": 25.0 if "store" in done else 0.0,
        "defence_mult": 1.2 if "rampart" in done else 1.0,
        "build_time_mult": 0.5 if "foundation" in done else 1.0,
        # fire: working
        "mine_stint_bonus": 2.0 if "kiln" in done else 0.0,
        "mine_rate_mult": 1.5 if "toolhouse" in done else 1.0,
        "attack_mult": 1.25 if "forge" in done else 1.0,
        # growth: renewing
        "regen_mult": 1.25 if "grove" in done else 1.0,
        "cargo_bonus": 5.0 if "granary" in done else 0.0,
        # (orchard acts once, at finalize: it plants)
        # life: healing
        "strain_guard": "apothecary" in done,
        "combat_recovery_mult": 0.5 if "infirmary" in done else 1.0,
        "recovery_mult": 2.0 if "sanatorium" in done else 1.0,
        # water: knowing
        "sight_mult": 1.25 if "cairn" in done else 1.0,
        "map_room": "library" in done,
        "pace_mult": 1.15 if "beacon" in done else 1.0,
        # (observatory acts on the flood clock via the world meta flag)
    }


# ---------------------------------------------------------------------------
# Caches — the commons' ONLY construction (user directive 2026-08-31). The
# commons has no muster points and no Ark tree; what an agent may raise there
# is a cache: cost FOUR DIFFERENT kinds, one unit each, paid from the hold.
# A cache wears its builder's parent-world colours, and no two caches may
# stand next to each other. Agents of the same colours may stash into and
# take from it — a larder in the market square.
# ---------------------------------------------------------------------------

CACHE_COST_KINDS = 4
CACHE_SPACING = 0.06


def cache_cost(cargo: dict[str, float]) -> dict[str, float] | None:
    """Four different kinds, one unit each — or nothing."""
    kinds = sorted(k for k, u in cargo.items() if u >= 1.0)
    if len(kinds) < CACHE_COST_KINDS:
        return None
    return {k: 1.0 for k in kinds[:CACHE_COST_KINDS]}


async def caches_in(client: Any, realm: str) -> list:
    return [v for v in await sites_in(client, realm)
            if v.payload.get("name") == "cache"
            and not v.payload.get("destroyed")]


def cache_spot_clear(caches: list, x: float, y: float) -> bool:
    return all((c.payload["x"] - x) ** 2 + (c.payload["y"] - y) ** 2
               >= CACHE_SPACING ** 2 for c in caches)


def cache_spot_clear_payloads(caches: list[dict], x: float, y: float) -> bool:
    return all((c["x"] - x) ** 2 + (c["y"] - y) ** 2
               >= CACHE_SPACING ** 2 for c in caches)


async def build_cache(client: Any, realm: str, agent_payload: dict,
                      x: float, y: float,
                      cargo: dict[str, float]) -> dict:
    cost = cache_cost(cargo)
    if cost is None:
        return {"error": "a cache costs four different kinds, one unit each"}
    caches = await caches_in(client, realm)
    if not cache_spot_clear(caches, x, y):
        return {"error": "too close to another cache"}
    x, y = clear_spot(x, y, await obstacle_points(client, realm),
                      min_d=CACHE_SPACING,
                      seed=f"cache:{agent_payload.get('key', '')}")
    import uuid as _u
    site = {"key": f"cache-{_u.uuid4().hex[:10]}",
            "name": "cache", "branch": "commons", "tier": 1,
            "x": x, "y": y, "needs": {}, "delivered": dict(cost),
            "contributors": {}, "required_users": 1, "complete": True,
            "colours": agent_payload.get("colour_pair"),
            "home_realm": agent_payload.get("home_realm"),
            "owner_user_id": agent_payload.get("owner_user_id"),
            "holdings": {}, "founded_at": time.time()}
    await client.add_vertex(TABLE, realm=realm, payload=site)
    return {"ok": True, "cache": site["key"], "cost": cost}


def cache_open_to(site: dict, agent_payload: dict) -> bool:
    """A cache opens to agents wearing its colours — the parent world's
    line, wherever its members were born since."""
    return site.get("colours") == agent_payload.get("colour_pair")


async def cache_exchange(client: Any, realm: str, cache_key: str,
                         agent_payload: dict, put: dict[str, float],
                         take_budget: float = 0.0) -> dict:
    """Stash and/or withdraw. take_budget caps what leaves the cache — the
    agent's free hold — so a full larder never overloads a small carrier."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": cache_key}, limit=1)
    if not rows:
        return {"error": "no such cache"}
    site = dict(rows[0].payload)
    if not cache_open_to(site, agent_payload):
        return {"error": "not your colours"}
    holdings = dict(site.get("holdings", {}))
    took: dict[str, float] = {}
    budget = take_budget
    for kind in sorted(holdings, key=lambda k: -holdings[k]):
        if budget <= 1e-9:
            break
        grab = min(holdings[kind], budget)
        took[kind] = grab
        budget -= grab
        holdings[kind] -= grab
        if holdings[kind] <= 1e-9:
            del holdings[kind]
    for kind, units in (put or {}).items():
        holdings[kind] = holdings.get(kind, 0.0) + units
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**site, "holdings": holdings})
    return {"ok": True, "took": took, "holdings": holdings}


# ---------------------------------------------------------------------------
# Portage — construction-spec Rules 3.10–3.13. A completed construction moves
# only on the shoulders of as many agents as it took distinct users to raise,
# and those agents must again be that many distinct users. Never dismantled
# (3.13); a carrier's death sets it down where the party stands (3.12a).
# ---------------------------------------------------------------------------

PORTABLE_EXCLUDED = {"cache"}       # a larder is dug in, not built up
PLEDGE_FRESH_S = 3600.0             # a take-up pledge goes stale in an hour


def portable(site: dict) -> bool:
    return bool(site.get("complete") and not site.get("destroyed")
                and not site.get("spent") and not site.get("manifested")
                and site.get("name") not in PORTABLE_EXCLUDED)


async def take_up(client: Any, realm: str, site_key: str, user_id: str,
                  agent_uuid: str, now: float,
                  time_scale: float = 1.0) -> dict:
    """Pledge a pair of hands. The construction lifts the moment the fresh
    pledges span the required number of DISTINCT users (Rule 3.10); until
    then pledges accumulate and quietly expire."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": site_key}, limit=1)
    if not rows:
        return {"error": "no such construction"}
    site = dict(rows[0].payload)
    if not portable(site):
        return {"error": f"the {site.get('name')} cannot be taken up"}
    if site.get("carried"):
        return {"error": "already aloft"}
    fresh = PLEDGE_FRESH_S / max(1.0, time_scale)   # a WORLD hour
    porters = {u: p for u, p in dict(site.get("porters", {})).items()
               if now - p.get("at", 0.0) < fresh}
    porters[agent_uuid] = {"user": user_id, "at": now}
    users = {p["user"] for p in porters.values() if p.get("user")}
    need = int(site.get("required_users", 1))
    carried = len(users) >= need
    site = {**site, "porters": porters, "carried": carried,
            **({"carried_at": now} if carried else {})}
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default", payload=site)
    return {"ok": True, "carried": carried, "site": site,
            "users": len(users), "need": need}


async def set_down(client: Any, realm: str, site_key: str,
                   x: float, y: float, reason: str = "") -> dict:
    """The construction comes to rest where the party stands (3.12a's clause
    covers death; a chosen set-down is the same motion). Whoever musters the
    right hands next may take it up again -- strangers included."""
    rows = await client.find_vertices(TABLE, realm=realm,
                                      filters={"key": site_key}, limit=1)
    if not rows:
        return {"error": "no such construction", "porters": []}
    site = dict(rows[0].payload)
    porters = list(site.get("porters", {}))
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**site, "porters": {}, "carried": False,
                                        "x": x, "y": y,
                                        **({"set_down_reason": reason}
                                           if reason else {})})
    return {"ok": True, "porters": porters, "name": site.get("name")}


async def portage_cross(client: Any, origin_realm: str, to_world: str,
                        site: dict, dest_xy: list) -> None:
    """The party stepped through: retire the origin vertex and raise the
    construction, still aloft, at the destination portal. Same key -- the
    thing itself travelled (3.13: it is never anything but itself)."""
    rows = await client.find_vertices(TABLE, realm=origin_realm,
                                      filters={"key": site["key"]}, limit=1)
    if rows:
        await client.upsert_vertex(TABLE, realm=origin_realm,
                                   vertex_id=int(rows[0].id), space="default",
                                   payload={**site, "destroyed": True,
                                            "portaged_to": to_world})
    await client.add_vertex(TABLE, realm=to_world, payload={
        **site, "x": float(dest_xy[0]), "y": float(dest_xy[1]),
        "portaged_from": origin_realm})
