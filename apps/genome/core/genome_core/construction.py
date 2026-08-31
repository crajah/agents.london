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
            and not v.payload.get("spent")}


async def found_site(client: Any, realm: str, user_id: str, name: str,
                     x: float, y: float, world_kinds: list[int]) -> dict:
    """Owner breaks ground. Prerequisites are constructions standing COMPLETE
    in this world (Rule 3.2's transitivity arrives via the tree)."""
    if name not in TREE:
        return {"error": f"no construction named {name}"}
    done = await completed_names(client, realm)
    after = TREE[name]["after"]
    needs_after = (after,) if isinstance(after, str) else (after or ())
    missing = [a for a in needs_after if a not in done]
    if missing:
        return {"error": f"requires completed: {', '.join(missing)}"}
    for v in await sites_in(client, realm):
        if v.payload["name"] == name and not v.payload.get("complete") \
                and not v.payload.get("destroyed"):
            return {"error": f"a {name} is already under way here"}
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
                     cargo: dict[str, float]) -> dict:
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
    complete = filled and enough_users
    await client.upsert_vertex(TABLE, realm=realm, vertex_id=int(rows[0].id),
                               space="default",
                               payload={**site, "delivered": delivered,
                                        "contributors": contributors,
                                        "complete": complete,
                                        **({"completed_at": time.time()}
                                           if complete else {})})
    if filled and not enough_users:
        # the material is all there; only hands are missing (Rule 3.3)
        pass
    if complete:
        extra = {}
        if site["name"] == "ark":
            extra["berths"] = allocate_berths(contributors)   # Rule 3.7e:
            # the pool is per-user and UNASSIGNED; agents contest below
            await client.upsert_vertex(TABLE, realm=realm,
                                       vertex_id=int(rows[0].id),
                                       space="default",
                                       payload={**site, "delivered": delivered,
                                                "contributors": contributors,
                                                "complete": True,
                                                "completed_at": time.time(),
                                                **extra})
        for uid in contributors:
            await notify.emit(client, uid, "world", "construction_complete",
                              f"The {site['name']} is complete. "
                              f"{len(contributors)} users raised it."
                              + (f" {extra['berths'].get(uid, 0)} berths fall "
                                 f"to your claim." if extra else ""))
    return {"taken": take, "complete": complete}


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
    """Calibration §5 first wirings; everything else defaults to neutral."""
    done = await completed_names(client, realm)
    return {"stock_ceiling_bonus": 25.0 if "store" in done else 0.0,
            "mine_rate_mult": 1.5 if "toolhouse" in done else 1.0}
