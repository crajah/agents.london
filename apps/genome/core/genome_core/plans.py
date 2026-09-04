"""Plans — genome-spec.md Rules 13.6–13.8. A user authors a TREE of items
conversationally; agents discover it at a drawing post, carry it as
knowledge, gossip it at encounters, and raise it anywhere the materials can
be gathered. A built plan is a structure and nothing else (Rule 13.7): the
grammar below cannot express an effect, which is the whole safety argument.

Definitions are immutable vertices in the agents realm; a PLACED plan is a
drawing post in the world's constructions table (a fixture, drowned by
floods like any structure) -- but the KNOWLEDGE survives in every carrier
(Rule 13.8)."""
from __future__ import annotations

import time
import uuid as uuidlib
from typing import Any

PLANS_TABLE = "plans"                 # agents realm: immutable definitions
POST_NAME = "plan_post"               # world fixture bearing a drawing
AGENTS_REALM = "genome_agents"
MAX_NODES = 20
MAX_KNOWN = 12                        # a head holds only so many drawings
NODE_FIELDS = {"item", "needs", "after", "contributors"}


def validate_tree(tree: Any) -> str | None:
    """The grammar: items, bills, dependencies, hands. NOTHING else -- a
    field this schema does not name is rejected, so an effect cannot even be
    written down (Rule 13.7 by construction). Returns an error or None."""
    if not isinstance(tree, list) or not 1 <= len(tree) <= MAX_NODES:
        return f"a plan is 1..{MAX_NODES} nodes"
    items = set()
    for n in tree:
        if not isinstance(n, dict):
            return "each node is an object"
        extra = set(n) - NODE_FIELDS
        if extra:
            return f"unknown field(s) {sorted(extra)} -- plans are " \
                   f"structures, not rules"
        item = n.get("item")
        if not isinstance(item, str) or not 1 <= len(item) <= 40 \
                or ":" in item:
            return "each node needs an item name (1-40 chars, no colon)"
        if item in items:
            return f"duplicate item {item!r}"
        items.add(item)
        needs = n.get("needs")
        if not isinstance(needs, dict) or not needs:
            return f"{item}: needs a bill of materials"
        for k, u in needs.items():
            if not (isinstance(k, str) and k.isdigit() and 0 <= int(k) <= 19):
                return f"{item}: kinds are '0'..'19'"
            if not isinstance(u, (int, float)) or not 0 < u <= 100:
                return f"{item}: units are 0..100"
        c = n.get("contributors", 1)
        if not isinstance(c, int) or not 1 <= c <= 8:
            return f"{item}: contributors is 1..8"
    for n in tree:
        for a in n.get("after", []):
            if a not in items:
                return f"{n['item']}: depends on unknown item {a!r}"
            if a == n["item"]:
                return f"{n['item']}: depends on itself"
    # cycle check: repeatedly remove satisfiable nodes
    remaining = {n["item"]: set(n.get("after", [])) for n in tree}
    while remaining:
        free = [i for i, deps in remaining.items()
                if not deps & set(remaining)]
        if not free:
            return "the dependency graph has a cycle"
        for i in free:
            del remaining[i]
    return None


def depth_of(tree: list[dict], item: str) -> int:
    """1 + the longest dependency chain below -- the build-time tier."""
    by = {n["item"]: n for n in tree}

    def d(i, seen=()):
        deps = by[i].get("after", [])
        if not deps or i in seen:
            return 1
        return 1 + max(d(a, seen + (i,)) for a in deps)
    return min(6, d(item))


async def author(client: Any, user_id: str, name: str, tree: list) -> dict:
    err = validate_tree(tree)
    if err:
        return {"error": err}
    key = f"plan-{uuidlib.uuid4().hex[:10]}"
    await client.add_vertex(PLANS_TABLE, realm=AGENTS_REALM, payload={
        "key": key, "name": name[:60], "tree": tree,
        "author": user_id, "authored_at": time.time()})
    return {"ok": True, "plan_key": key}


async def get_plan(client: Any, plan_key: str) -> dict | None:
    rows = await client.find_vertices(PLANS_TABLE, realm=AGENTS_REALM,
                                      filters={"key": plan_key}, limit=1)
    return rows[0].payload if rows else None


async def place_post(client: Any, realm: str, plan_key: str,
                     plan_name: str, x: float, y: float) -> dict:
    """The drawing goes up in the world: a fixture agents can find. It is a
    STRUCTURE (complete from birth, confers nothing, drowns with the world);
    the knowledge it teaches is what survives (13.8)."""
    from . import construction as C
    x, y = C.clear_spot(x, y, await C.obstacle_points(client, realm),
                        seed=f"post:{plan_key}")
    site = {"key": f"post-{uuidlib.uuid4().hex[:10]}", "name": POST_NAME,
            "branch": "plan", "tier": 1, "x": x, "y": y,
            "needs": {}, "delivered": {}, "contributors": {},
            "required_users": 1, "complete": True,
            "plan_key": plan_key, "plan_name": plan_name,
            "founded_at": time.time()}
    await client.add_vertex(C.TABLE, realm=realm, payload=site)
    return {"ok": True, "post": site["key"]}


def learnable(sites: list[dict], x: float, y: float,
              known: list[str], reach: float = 0.05) -> list[tuple[str, str]]:
    """Drawing posts within reach whose plan this head does not yet hold."""
    out = []
    for s in sites:
        if s.get("name") == POST_NAME and s.get("plan_key") \
                and s["plan_key"] not in known \
                and (s["x"] - x) ** 2 + (s["y"] - y) ** 2 < reach ** 2:
            out.append((s["plan_key"], s.get("plan_name", "a design")))
    return out


def merge_known(mine: list[str], theirs: list[str]) -> list[str]:
    """Encounter gossip (13.6: agents share designs): union, oldest first,
    capped -- a drawing spreads because heads keep choosing to keep it."""
    out = list(mine)
    for k in theirs:
        if k not in out:
            out.append(k)
    return out[:MAX_KNOWN]


def foundable_items(plan: dict, sites: list[dict]) -> list[str]:
    """Which nodes of this plan may break ground HERE: dependencies standing
    complete in this world (13.6a's order made local), no live duplicate."""
    tree = plan.get("tree", [])
    done = {s.get("plan_item") for s in sites
            if s.get("plan_key") == plan["key"] and s.get("complete")
            and not s.get("destroyed")}
    live = {s.get("plan_item") for s in sites
            if s.get("plan_key") == plan["key"] and not s.get("destroyed")}
    out = []
    for n in tree:
        if n["item"] in live:
            continue
        if all(a in done for a in n.get("after", [])):
            out.append(f"plan:{plan['key']}:{n['item']}")
    return out
