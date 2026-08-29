"""Closed forms. execution-spec.md §2: anything derivable from an intent and a
clock is derived, never stored.

All times are UNIX seconds (float). All coordinates live on the unit square
[0,1]² (calibration-spec.md Rule 1.2); crossing it edge to edge takes
CROSSING_SECONDS, so speed is 1/CROSSING_SECONDS in map units per second.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# calibration-spec.md Rule 1.2: ~six hours to cross a world
CROSSING_SECONDS = 6 * 3600.0
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
