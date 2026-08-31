"""Closed forms. execution-spec.md §2: anything derivable from an intent and a
clock is derived, never stored.

All times are UNIX seconds (float). All coordinates live on the unit square
[0,1]² (calibration-spec.md Rule 1.2); crossing it edge to edge takes
CROSSING_SECONDS, so speed is 1/CROSSING_SECONDS in map units per second.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# calibration-spec.md Rule 1.2 (revised twice): ~six MINUTES to cross a
# world at base pace. Six hours was imperceptible, one hour still crawled
# (user: "extremely slow... at least 10x"); at 360s a journey is something
# you watch happen, not something you check back on.
CROSSING_SECONDS = 360.0
SPEED = 1.0 / CROSSING_SECONDS  # map units per second


@dataclass(frozen=True)
class Movement:
    """A movement intent (execution-spec.md Rule 2.1). Two writes per journey:
    one at departure, one at arrival. Nothing is written in between."""
    from_x: float
    from_y: float
    to_x: float
    to_y: float
    departed_at: float
    arrives_at: float


def arrival_time(fx: float, fy: float, tx: float, ty: float, departed_at: float) -> float:
    """When an agent departing (fx,fy) at departed_at reaches (tx,ty)."""
    return departed_at + math.dist((fx, fy), (tx, ty)) / SPEED


def position(m: Movement, now: float) -> tuple[float, float]:
    """Position as a pure function of the intent and the clock
    (execution-spec.md Rule 2.2)."""
    if now <= m.departed_at:
        return (m.from_x, m.from_y)
    if now >= m.arrives_at:
        return (m.to_x, m.to_y)
    f = (now - m.departed_at) / (m.arrives_at - m.departed_at)
    return (m.from_x + (m.to_x - m.from_x) * f,
            m.from_y + (m.to_y - m.from_y) * f)


def heading(m: Movement) -> float:
    """Bearing in radians, derived from the intent (interface-spec.md Rule 6.9b).
    A stationary agent keeps the heading it arrived on, which is this value for
    its last movement."""
    return math.atan2(m.to_y - m.from_y, m.to_x - m.from_x)


@dataclass(frozen=True)
class PileState:
    """A pile's stored state (execution-spec.md Rule 2.3). Written only when
    mined; quantity at any instant is derived."""
    qty_at: float        # quantity at measured_at
    measured_at: float
    rate: float          # units per second of regeneration (genome-spec.md Rule 4.6)
    cap: float           # this pile's own capacity


def pile_quantity(p: PileState, now: float, world_regen_halted: bool = False) -> float:
    """Quantity in closed form, clamped to the pile's cap.

    world_regen_halted implements genome-spec.md Rules 4.13/4.14: regeneration
    pauses while the world's aggregate stock for this kind is at its ceiling.
    The caller supplies that fact; this function stays pure. While halted the
    quantity holds at qty_at.
    """
    if world_regen_halted:
        return min(p.qty_at, p.cap)
    dt = max(0.0, now - p.measured_at)
    return min(p.cap, p.qty_at + p.rate * dt)


def mine(p: PileState, now: float, want: float,
         world_regen_halted: bool = False) -> tuple[PileState, float]:
    """Mine up to `want` units. Returns the new stored state and the amount
    actually taken. Resources are mined in fractions (genome-spec.md Rule 4.11).
    This is one of the two writes a pile ever sees."""
    q = pile_quantity(p, now, world_regen_halted)
    taken = max(0.0, min(want, q))
    return PileState(qty_at=q - taken, measured_at=now, rate=p.rate, cap=p.cap), taken


@dataclass(frozen=True)
class Route:
    """A waypoint route (genome-spec.md Rule 5.4): computed once at decision
    time, position derived piecewise ever after (execution-spec Rule 2.2).

    If arrives_at is given (from a stored movement record), leg times are
    NORMALISED to span (departed_at, arrives_at) -- so a route compressed by
    time_scale or hastened by the Speed pool interpolates at its true pace.
    Without it, legs run at the base SPEED. The stored record's span is the
    single source of truth; base SPEED is only the scheduler's starting bid.
    """
    waypoints: tuple[tuple[float, float], ...]
    departed_at: float
    arrives_at_hint: float | None = None

    def leg_times(self) -> list[float]:
        """Cumulative arrival time at each waypoint."""
        t = self.departed_at
        out = [t]
        for k in range(len(self.waypoints) - 1):
            t += math.dist(self.waypoints[k], self.waypoints[k + 1]) / SPEED
            out.append(t)
        if self.arrives_at_hint is not None and out[-1] > out[0]:
            span = self.arrives_at_hint - self.departed_at
            base = out[-1] - out[0]
            out = [self.departed_at + (x - self.departed_at) * span / base
                   for x in out]
        return out

    @property
    def arrives_at(self) -> float:
        return self.leg_times()[-1]


def route_position(r: Route, now: float) -> tuple[float, float]:
    """Piecewise-linear position along the route — still a pure function of the
    intent and the clock, still zero writes in transit."""
    times = r.leg_times()
    if now <= times[0]:
        return r.waypoints[0]
    if now >= times[-1]:
        return r.waypoints[-1]
    for k in range(len(times) - 1):
        if now <= times[k + 1]:
            f = (now - times[k]) / (times[k + 1] - times[k])
            ax, ay = r.waypoints[k]
            bx, by = r.waypoints[k + 1]
            return (ax + (bx - ax) * f, ay + (by - ay) * f)
    return r.waypoints[-1]


def route_heading(r: Route, now: float) -> float:
    """Bearing of the current leg (interface-spec Rule 6.9b)."""
    times = r.leg_times()
    for k in range(len(times) - 1):
        if now <= times[k + 1]:
            ax, ay = r.waypoints[k]
            bx, by = r.waypoints[k + 1]
            return math.atan2(by - ay, bx - ax)
    ax, ay = r.waypoints[-2]
    bx, by = r.waypoints[-1]
    return math.atan2(by - ay, bx - ax)
