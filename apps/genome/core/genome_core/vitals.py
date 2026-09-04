"""The pools — Stamina and Mana as CLOSED FORMS (a stored value that could
be derived is a defect). Each is (level, measured_at); the current value is
computed from the recovery rate and the clock, never ticked.

Recovery: reStamina/reMana set the pace (genotype-spec faculty table);
Immune Vigilance taxes stamina recovery -- the watch-cost of Rule 3.8e: a
vigilant immune system is a standing drain. Zero CURRENT stamina
incapacitates without killing (Rule 9.3e); zero MAXIMUM perishes (3.8d,
handled where it burns)."""
from __future__ import annotations

from .genotype import norm

# PROVISIONAL (calibration §4): a full pool returns in ~2 days at rate 1.0
STAMINA_RECOV_PER_DAY = 0.5
MANA_RECOV_PER_DAY = 0.5
WATCH_COST_PER_DAY = 0.15        # Rule 3.8e: vigilance taxes recovery
MANA_ATTACK_COST = 0.3           # Rule 9.3d: pressing an attack spends Mana
DAY = 86400.0


def _rate(g: dict, key: str, base: float) -> float:
    return norm(key, g.get(key, 0.5)) * base / DAY


def stamina_now(payload: dict, now: float,
                time_scale: float = 1.0) -> float:
    """time_scale: the world's clock. Combat drains at world pace, so
    recovery must run at world pace too -- without it a 60x demo world beat
    its whole population to the floor faster than real-time recovery could
    lift anyone (user report 2026-09-04: a dormant commons)."""
    g = payload.get("genotype") or {}
    level = payload.get("stamina", 1.0)
    at = payload.get("stamina_at", now)
    ts = max(1.0, time_scale)
    rate = (_rate(g, "reStamina", STAMINA_RECOV_PER_DAY)
            - norm("Immune Vigilance",
                   g.get("Immune Vigilance", 5000.0))
            * WATCH_COST_PER_DAY / DAY) * ts
    cap = payload.get("stamina_max", 1.0)
    return min(cap, max(0.0, level + rate * max(0.0, now - at)))


def mana_now(payload: dict, now: float, time_scale: float = 1.0) -> float:
    g = payload.get("genotype") or {}
    level = payload.get("mana", 1.0)
    at = payload.get("mana_at", now)
    rate = _rate(g, "reMana", MANA_RECOV_PER_DAY) * max(1.0, time_scale)
    return min(1.0, max(0.0, level + rate * max(0.0, now - at)))


def set_stamina(payload: dict, value: float, now: float) -> dict:
    return {**payload, "stamina": max(0.0, min(
        payload.get("stamina_max", 1.0), value)), "stamina_at": now}


def set_mana(payload: dict, value: float, now: float) -> dict:
    return {**payload, "mana": max(0.0, min(1.0, value)), "mana_at": now}


INCAP_FLOOR = 0.05               # the body moves again above 5% -- hours,
# not an instant, at the calibrated recovery pace


def incapacitated(payload: dict, now: float,
                  time_scale: float = 1.0) -> bool:
    """Rule 9.3e: an empty pool stops the body, never the heart. The floor
    keeps 'zero' from being a single tick: a beaten agent lies where it
    fell until real recovery has happened."""
    return stamina_now(payload, now, time_scale) < INCAP_FLOOR \
        and payload.get("stamina_max", 1.0) > 0.0


def pools(payload: dict, now: float, time_scale: float = 1.0) -> dict:
    return {"Stamina": round(stamina_now(payload, now, time_scale), 3),
            "Stamina max": round(payload.get("stamina_max", 1.0), 3),
            "Mana": round(mana_now(payload, now, time_scale), 3)}
