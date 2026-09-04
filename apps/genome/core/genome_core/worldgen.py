"""World generation — calibration-spec.md Rules 3.0c-3.0e, genome-spec.md §2/§4.

Deterministic per seed, so the determinism harness (BUILD testing strategy) can
replay a world exactly.
"""
from __future__ import annotations

import random
import uuid as uuidlib

from .genotype import RANGES
from . import path as pathmod

# Material A100 palette, genome-spec Rule 4.9 (20 kinds -> 20 hues; the pair a
# world holds is its identity). Indexed by kind 0..19.
A100 = ["#FF8A80", "#FF80AB", "#EA80FC", "#B388FF", "#8C9EFF", "#82B1FF",
        "#80D8FF", "#84FFFF", "#A7FFEB", "#B9F6CA", "#CCFF90", "#F4FF81",
        "#FFFF8D", "#FFE57F", "#FFD180", "#FF9E80", "#D7CCC8", "#CFD8DC",
        "#F5F5F5", "#B2FFFF"]  # 20th: Light Cyan (user decision)

MIN_SPACING = 0.08
FIRST_NAMES = [
    "Asha", "Bren", "Cato", "Dara", "Eryn", "Falk", "Gale", "Hesper",
    "Iris", "Joss", "Kiva", "Lorn", "Mira", "Noor", "Orin", "Pia",
    "Quill", "Rune", "Sable", "Tarn",
    "Alba", "Birch", "Cove", "Dew", "Ember", "Fife", "Gorse", "Hale",
    "Ilka", "Juno", "Kael", "Lark", "Moss", "Nyra", "Oleander", "Perry",
    "Qadira", "Reed", "Senna", "Thistle", "Ulla", "Vesper", "Wren",
    "Xanthe", "Yarrow", "Zephyr", "Amos", "Briar", "Cedar", "Dahlia",
    "Elm", "Fern", "Grove", "Hazel", "Indigo", "Jasper", "Koa", "Linden",
    "Marlow", "Nettle", "Oriel", "Pike", "Quince", "Rowan", "Sorrel",
    "Teal", "Umber", "Vale", "Willow", "Yew"]
SURNAMES = [
    "Ashfall", "Brightwater", "Coldmere", "Dunhollow", "Emberlee",
    "Fenwick", "Greyvale", "Hollowell", "Ironwood", "Kestrel",
    "Larkspur", "Mosswood", "Nightvale", "Oakhurst", "Pryor",
    "Quickstep", "Ravenshaw", "Stonebrook", "Thornbury", "Wrenfield",
    "Aldergate", "Blackbriar", "Cinderfell", "Dovewick", "Eastmarsh",
    "Farrowdown", "Gladehart", "Hawthorne", "Islegrove", "Junipers",
    "Kilnworth", "Lowbridge", "Marrowick", "Northreach", "Otterby",
    "Pinewatch", "Quernstone", "Redmoor", "Saltwick", "Tanglewood",
    "Underhill", "Veilwater", "Westfall", "Yarrowgate", "Ashenford",
    "Briarholm", "Cloudrest", "Dampfield", "Elderbrook", "Foxglove",
    "Gullswater", "Heathersedge", "Ivyholt", "Jackdaw", "Kingsmere",
    "Longfen", "Mistleford", "Nettlebank", "Oxwold", "Puddlefoot",
    "Rookery", "Shadowmere", "Tidewell", "Vantage", "Whistledown"]


def _spaced_points(r: random.Random, n: int) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for _ in range(n * 50):
        if len(pts) == n:
            break
        x, y = r.uniform(0.05, 0.95), r.uniform(0.05, 0.95)
        if all((x - px) ** 2 + (y - py) ** 2 >= MIN_SPACING ** 2
               for px, py in pts):
            pts.append((x, y))
    while len(pts) < n:                       # degenerate seeds still terminate
        pts.append((r.uniform(0.05, 0.95), r.uniform(0.05, 0.95)))
    return pts


HOME_XY = (0.5, 0.5)


def _terrain(r: random.Random) -> list[dict]:
    """Impassable terrain (genome-spec Rule 5.3): circular obstacles, fixed at
    creation. Kept clear of the home point so a world can never trap its own
    deposit spot."""
    rocks = []
    for _ in range(r.randint(5, 9)):
        for _try in range(30):
            o = {"x": r.uniform(0.08, 0.92), "y": r.uniform(0.08, 0.92),
                 "r": r.uniform(0.03, 0.09)}
            if (o["x"] - HOME_XY[0]) ** 2 + (o["y"] - HOME_XY[1]) ** 2                     > (o["r"] + 0.06) ** 2:
                rocks.append(o)
                break
    return rocks


def generate_world(seed: int, owner_user_id: str) -> dict:
    """kinds: uniformly random pair of the 190 (Rule 3.0c). Piles: 6-10 per
    kind, min-spaced, capacities 15-50 summing near the 250 ceiling (3.0d).
    Terrain first (Rule 5.3); piles placed outside it and guaranteed reachable
    from home. Founding centre drawn and RECORDED (genotype-spec Rule 3.2b)."""
    r = random.Random(f"world:{seed}")
    kinds = r.sample(range(20), 2)
    terrain = _terrain(r)
    piles = []
    for kind in kinds:
        n = r.randint(6, 10)
        caps = [r.uniform(15, 50) for _ in range(n)]
        scale = min(1.0, 250.0 / sum(caps))   # near, never over, the ceiling
        pts = [q for q in _spaced_points(r, n * 2)
               if not any((q[0] - o["x"]) ** 2 + (q[1] - o["y"]) ** 2
                          < (o["r"] + pathmod.INFLATE) ** 2 for o in terrain)
               and pathmod.find_path(terrain, *HOME_XY, *q) is not None][:n]
        while len(pts) < n:                    # degenerate seeds still fill
            q = (r.uniform(0.08, 0.92), r.uniform(0.08, 0.92))
            if pathmod.find_path(terrain, *HOME_XY, *q) is not None:
                pts.append(q)
        for (x, y), cap in zip(pts, caps):
            piles.append({
                "pile_uuid": str(uuidlib.UUID(int=r.getrandbits(128))),
                "kind": kind, "x": x, "y": y, "cap": cap * scale,
                "measured_at": 0.0,
                "qty_at": (q0 := cap * scale * r.uniform(0.4, 1.0)),
                "qty_origin": q0,          # the flood reverts to this (4.4)
                "rate": r.uniform(0.5, 2.0) / 3600.0,   # units/sec (Rule 4.6)
            })
    centre = {k: r.uniform(*RANGES[k]) for k in RANGES}
    # Portal SLOTS: random positions fixed at creation (genome-spec Rule 6.2e),
    # clear of terrain; linking them to destinations happens when connections
    # form. Slot 0 is reserved for the commons (Rule 6.2f).
    portal_slots = []
    for _ in range(4):
        for _try in range(60):
            q = (r.uniform(0.08, 0.92), r.uniform(0.08, 0.92))
            if any((q[0]-o["x"])**2 + (q[1]-o["y"])**2 < (o["r"]+0.03)**2
                   for o in terrain):
                continue
            # portals never overlap: clean mutual separation (user directive)
            if any((q[0]-s["x"])**2 + (q[1]-s["y"])**2 < 0.10**2
                   for s in portal_slots):
                continue
            portal_slots.append({"x": q[0], "y": q[1]})
            break
    muster = muster_points(r, terrain)
    # the marketplace (Rule 4.20): one board, terrain-clear, near the middle
    market = {"x": 0.5, "y": 0.5}
    for _try in range(40):
        q = (r.uniform(0.35, 0.65), r.uniform(0.35, 0.65))
        if not any((q[0]-o["x"])**2 + (q[1]-o["y"])**2
                   < (o["r"]+pathmod.INFLATE)**2 for o in terrain) \
                and pathmod.find_path(terrain, *HOME_XY, *q) is not None:
            market = {"x": round(q[0], 4), "y": round(q[1], 4)}
            break
    return {"realm": f"world_{uuidlib.UUID(int=r.getrandbits(128)).hex[:12]}",
            "owner_user_id": owner_user_id, "kinds": kinds,
            "colours": [A100[kinds[0]], A100[kinds[1]]],
            "founding_centre": centre, "piles": piles, "terrain": terrain,
            "portal_slots": portal_slots, "muster_points": muster,
            "market": market}


def muster_points(r: random.Random, terrain: list[dict]) -> list[dict]:
    """Exactly five muster flags per world (user directive): the drop points
    where agents deliver their load. Spaced, terrain-clear, reachable from the
    world's centre so no flag is ever walled off."""
    out: list[dict] = []
    for q in _spaced_points(r, 15):
        if len(out) == 5:
            break
        if not any((q[0] - o["x"]) ** 2 + (q[1] - o["y"]) ** 2
                   < (o["r"] + pathmod.INFLATE) ** 2 for o in terrain)                 and pathmod.find_path(terrain, *HOME_XY, *q) is not None:
            out.append({"x": q[0], "y": q[1]})
    while len(out) < 5:                       # degenerate seeds still fill
        q = (r.uniform(0.1, 0.9), r.uniform(0.1, 0.9))
        if pathmod.find_path(terrain, *HOME_XY, *q) is not None:
            out.append({"x": q[0], "y": q[1]})
    return out


def founder_genotype(world: dict, seed: int) -> dict:
    """Uniform within the world about its recorded centre (Rule 3.2a): each
    locus drawn within ±25% of range around the centre, clamped."""
    r = random.Random(f"founder:{world['realm']}:{seed}")
    g = {}
    for k, (lo, hi) in RANGES.items():
        c = world["founding_centre"].get(k)
        if c is None:                     # locus younger than the world
            c = r.uniform(*RANGES[k])
        w = (hi - lo) * 0.25
        g[k] = min(hi, max(lo, r.uniform(c - w, c + w)))
    return g


def founder_name(seed: int) -> str:
    """Three words; founders draw two fresh surnames and root lineages
    (calibration Rule 3.0e)."""
    r = random.Random(f"name:{seed}")
    return " ".join([r.choice(FIRST_NAMES), r.choice(SURNAMES),
                     r.choice(SURNAMES)])
