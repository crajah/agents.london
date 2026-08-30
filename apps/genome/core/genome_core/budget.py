"""The decision budget — execution-spec.md Rules 5.2/5.2a/5.2b/5.2c.

A token bucket accruing at ACCRUAL_PER_DAY to CAPACITY, identical for every
agent (5.2c), charging only DISCRETIONARY deliberation and never blocking
action (5.2a): `charge` reports whether the agent could afford it; the caller
offers or withholds the discretionary OPTION, never freezes the agent.

Nothing in Phase 1-2's decision surface is discretionary — arrival and
mining-done decisions are deliberation the agent cannot avoid. The charged
kinds arrive with negotiation (countering) and route reconsideration.
"""
from __future__ import annotations

from dataclasses import dataclass

ACCRUAL_PER_DAY = 10.0        # calibration via execution-spec Rule 5.2
CAPACITY = 12.0               # >= negotiation cap (Rule 7.2 coupling)
DISCRETIONARY = frozenset({"counter_offer", "reconsider_route"})


@dataclass(frozen=True)
class Bucket:
    level: float
    updated_at: float          # seconds


def accrue(b: Bucket, now: float) -> Bucket:
    dt_days = max(0.0, now - b.updated_at) / 86400.0
    return Bucket(min(CAPACITY, b.level + ACCRUAL_PER_DAY * dt_days), now)


def charge(b: Bucket, kind: str, now: float) -> tuple[Bucket, bool]:
    """Returns (new bucket, afforded). Non-discretionary kinds are always
    afforded and never charged (Rule 5.2b's left column)."""
    b = accrue(b, now)
    if kind not in DISCRETIONARY:
        return b, True
    if b.level >= 1.0:
        return Bucket(b.level - 1.0, now), True
    return b, False            # broke = take-it-or-leave-it, never frozen
