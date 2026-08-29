"""Opinion arithmetic — genotype-spec.md §6.3. A number and a weight, never a
distribution (Rule 6.9's note). All of this is in the free tier of
execution-spec.md Rule 5.1: belief costs nothing, only deciding does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Opinion:
    estimate: float   # 0..10000, same scale as loci
    weight: float     # accumulated evidence weight


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def update_event(op: Opinion, acted_high: bool, theta: float, k: float,
                 kappa: float = 1.0 / 2500.0) -> Opinion:
    """Rule 6.10a: where evidence is a discrete act, the estimate predicts the
    act and the update is the surprise.

        p  = σ(κ·(E − θ))
        E' = E + K·(S − p) · SCALE

    theta is the situation's difficulty on the locus scale — how hard it was to
    act well. kappa maps locus units onto the logistic's input; 1/2500 puts the
    curve's active region across the 0..10000 range.
    """
    p = logistic(kappa * (op.estimate - theta))
    s = 1.0 if acted_high else 0.0
    e = op.estimate + k * (s - p) * 10000.0
    return Opinion(estimate=min(10000.0, max(0.0, e)), weight=op.weight + 1.0)


def update_value(op: Opinion, observed: float, k: float) -> Opinion:
    """Rule 6.9: evidence that arrives as a value folds into the average."""
    e = op.estimate + k * (observed - op.estimate)
    return Opinion(estimate=min(10000.0, max(0.0, e)), weight=op.weight + 1.0)


def decay_toward(op: Opinion, neutral: float, rate: float, dt: float) -> Opinion:
    """Rule 6.10: exponential decay of evidence, rate governed by the observer's
    Vindictiveness. Owner-sourced evidence uses an accelerated, per-relay
    compounded rate (Rule 6.10b) — the caller supplies the effective rate."""
    f = math.exp(-rate * dt)
    return Opinion(estimate=neutral + (op.estimate - neutral) * f,
                   weight=op.weight * f)
