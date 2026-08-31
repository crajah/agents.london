"""Movement styles — how an agent's exploring MOVES, chosen by genotype and
environmental stimuli (user directive). This is a computed faculty in the
genotype-spec §4 sense: the LLM chooses WHAT to do (explore, mine, travel);
the phenotype decides HOW the resulting motion looks. Deterministic per
(agent, time-bucket) so the record can replay it.

Styles and their temperaments:
  brownian   — jittery local wander; the impatient and curious
  levy       — mostly local, rare long flights; the wanderer's search
  lawnmower  — systematic row-by-row sweep; the prudent and knowing
  swarm      — drawn toward neighbours' centre; the loyal and cooperative
  perimeter  — hug the world's edge; the cautious surveyor
"""
from __future__ import annotations

import math
import random

from .engine import GRID_K, cell_centre, frontier_cells
from .genotype import norm

STYLES = ("brownian", "levy", "lawnmower", "swarm", "perimeter")


def style_scores(g: dict, env: dict) -> dict[str, float]:
    """Phenotype x stimuli. env: neighbours (list of (x,y)), explored_frac,
    at (x,y)."""
    n = lambda k: norm(k, g.get(k, 5000.0))
    neighbours = env.get("neighbours", [])
    crowd = min(1.0, len(neighbours) / 4.0)
    unexplored = 1.0 - env.get("explored_frac", 0.0)
    return {
        "brownian": 0.5 * n("Curiosity") + 0.5 * (1.0 - n("Patience")),
        "levy": 0.6 * n("Wanderlust") + 0.4 * unexplored,
        "lawnmower": 0.5 * n("Prudence") + 0.5 * n("Knowledge"),
        "swarm": (0.5 * n("Loyalty") + 0.5 * n("Cooperativeness")) * crowd,
        "perimeter": 0.6 * n("Prudence") + 0.4 * (1.0 - n("Courage")),
    }


def pick_style(g: dict, env: dict, seed: str) -> str:
    scores = style_scores(g, env)
    # small seeded jitter so equal temperaments still vary agent-to-agent
    r = random.Random(f"style:{seed}")
    return max(STYLES, key=lambda s: scores[s] + r.uniform(0, 0.05))


def target_for(style: str, x: float, y: float, explored: frozenset,
               env: dict, seed: str) -> tuple[float, float]:
    r = random.Random(f"move:{style}:{seed}")
    clamp = lambda v: max(0.05, min(0.95, v))
    if style == "brownian":
        return (clamp(x + r.gauss(0, 0.08)), clamp(y + r.gauss(0, 0.08)))
    if style == "levy":
        step = 0.05 * (r.paretovariate(1.5))       # heavy tail, rare flights
        a = r.uniform(0, 2 * math.pi)
        return (clamp(x + math.cos(a) * min(step, 0.6)),
                clamp(y + math.sin(a) * min(step, 0.6)))
    if style == "lawnmower":
        # next unexplored cell in row-major order: a systematic sweep
        for j in range(GRID_K):
            for i in range(GRID_K):
                if (i, j) not in explored:
                    return cell_centre((i, j))
        return (clamp(x + r.uniform(-0.1, 0.1)), clamp(y + r.uniform(-0.1, 0.1)))
    if style == "swarm":
        ns = env.get("neighbours", [])
        if ns:
            cx = sum(p[0] for p in ns) / len(ns)
            cy = sum(p[1] for p in ns) / len(ns)
            # toward the flock's centre, but never all the way in
            return (clamp(x + (cx - x) * 0.6 + r.gauss(0, 0.02)),
                    clamp(y + (cy - y) * 0.6 + r.gauss(0, 0.02)))
        return (clamp(x + r.gauss(0, 0.05)), clamp(y + r.gauss(0, 0.05)))
    # perimeter: project toward the nearest edge, then slide along it
    edges = [(x, 0.06), (x, 0.94), (0.06, y), (0.94, y)]
    ex, ey = min(edges, key=lambda p: (p[0]-x)**2 + (p[1]-y)**2)
    if abs(ex - x) < 0.02 and abs(ey - y) < 0.02:
        along = r.choice([-1, 1]) * r.uniform(0.1, 0.25)
        if ey in (0.06, 0.94):
            return (clamp(x + along), ey)
        return (ex, clamp(y + along))
    return (ex, ey)
