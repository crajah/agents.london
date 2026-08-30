"""Pathfinding — genome-spec.md Rules 5.3/5.4, execution-spec.md Rule 2.1a.

Routes are computed ONCE, when a journey is chosen; nothing here runs per tick.
Terrain is circular obstacles on the unit square. If the straight segment is
clear the route is direct; otherwise A* over a coarse grid, then smoothed by
line-of-sight so the polyline carries only the waypoints that matter.

Deterministic, pure, no I/O.
"""
from __future__ import annotations

import heapq
import math

GRID = 64
INFLATE = 0.012          # agent radius margin around terrain


def _blocked(x: float, y: float, obstacles: list[dict], inflate: float) -> bool:
    return any((x - o["x"]) ** 2 + (y - o["y"]) ** 2
               < (o["r"] + inflate) ** 2 for o in obstacles)


def segment_clear(ax: float, ay: float, bx: float, by: float,
                  obstacles: list[dict], inflate: float = INFLATE) -> bool:
    """True if the segment stays outside every inflated obstacle (distance from
    each circle centre to the segment exceeds its inflated radius)."""
    for o in obstacles:
        r = o["r"] + inflate
        px, py = o["x"] - ax, o["y"] - ay
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        t = 0.0 if d2 == 0 else max(0.0, min(1.0, (px * dx + py * dy) / d2))
        cx, cy = ax + t * dx, ay + t * dy
        if (cx - o["x"]) ** 2 + (cy - o["y"]) ** 2 < r * r:
            return False
    return True


def _cell(v: float) -> int:
    return min(GRID - 1, max(0, int(v * GRID)))


def _centre(i: int) -> float:
    return (i + 0.5) / GRID


def find_path(obstacles: list[dict], ax: float, ay: float,
              bx: float, by: float) -> list[tuple[float, float]] | None:
    """Waypoints from (ax,ay) to (bx,by), endpoints included. None only if the
    grid holds no route at all (terrain generation guards against this)."""
    if segment_clear(ax, ay, bx, by, obstacles):
        return [(ax, ay), (bx, by)]

    start, goal = (_cell(ax), _cell(ay)), (_cell(bx), _cell(by))
    blocked_cache: dict[tuple[int, int], bool] = {}

    def cell_blocked(c: tuple[int, int]) -> bool:
        if c not in blocked_cache:
            blocked_cache[c] = _blocked(_centre(c[0]), _centre(c[1]),
                                        obstacles, INFLATE)
        return blocked_cache[c]

    if cell_blocked(goal) or cell_blocked(start):
        # endpoint sits inside inflated margin (e.g. pile against a rock):
        # allow it, the margin is a comfort not a wall at endpoints
        blocked_cache[goal] = blocked_cache[start] = False

    openq: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
    g = {start: 0.0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    diag = math.sqrt(2.0)
    while openq:
        _, cur = heapq.heappop(openq)
        if cur == goal:
            cells = [cur]
            while cur in came:
                cur = came[cur]
                cells.append(cur)
            cells.reverse()
            pts = [(ax, ay)] + [(_centre(i), _centre(j)) for i, j in cells[1:-1]] \
                + [(bx, by)]
            return _smooth(pts, obstacles)
        cx, cy = cur
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                nxt = (cx + di, cy + dj)
                if not (0 <= nxt[0] < GRID and 0 <= nxt[1] < GRID):
                    continue
                if cell_blocked(nxt):
                    continue
                if di and dj and (cell_blocked((cx + di, cy)) or
                                  cell_blocked((cx, cy + dj))):
                    continue          # no cutting corners through terrain
                step = diag if di and dj else 1.0
                ng = g[cur] + step
                if ng < g.get(nxt, math.inf):
                    g[nxt] = ng
                    came[nxt] = cur
                    h = math.dist(nxt, goal)
                    heapq.heappush(openq, (ng + h, nxt))
    return None


def _smooth(pts: list[tuple[float, float]],
            obstacles: list[dict]) -> list[tuple[float, float]]:
    """Line-of-sight smoothing: keep only waypoints the route actually turns at."""
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not segment_clear(*pts[i], *pts[j], obstacles):
            j -= 1
        out.append(pts[j])
        i = j
    return out


def path_length(pts: list[tuple[float, float]]) -> float:
    return sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
