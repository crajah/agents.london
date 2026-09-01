"""Pathogens — pathogen-spec.md §1-§2. Lazy, closed-form, like everything else:
an infection record carries its whole future at creation (detection time,
synthesis completion), and state is derived from the clock — nothing ticks.

Strains are a second evolving population (Rule 2.1: six things), created by
teleportation (both ends rolled independently) and descending from parents.
Infection alters EXPRESSION, never the genotype (Rule 2.14/2.16): phenotype()
is what deciders and faculties read while infection lasts. Antigens are
synthesised DURING infection (Rule 2.18a) at genotype-set times, cover part of
signature space (2.18b), decay from birth (2.18d), and immunity is graded
coverage (2.20). Infection is visible (Rule 2.21).
"""
from __future__ import annotations

import math
import random
import uuid as uuidlib

from .genotype import RANGES, norm

SIG_DIMS = 12                    # within Rule 2.0's 8-16 band
TELEPORT_STRAIN_P = float(__import__("os").getenv("GENOME_STRAIN_P", "0.05"))
CONTACT_BASE = 0.6               # scaled by contagion and coverage
COVERAGE_THRESHOLD = 0.55        # Rule 2.18c PROVISIONAL (calibration §4)

# dispositions a strain may modulate (Rule 2.15's target set)
TARGETS = ["Cooperativeness", "Wanderlust", "Prudence", "Aggression",
           "Amenability", "Curiosity"]


def new_strain(seed: str, parent: dict | None = None) -> dict:
    """Six things (Rule 2.1). Descends from a parent where one exists
    (Rule 2.10a): the signature inherits with drift, which is what lets
    accumulated antigen coverage degrade gracefully instead of cliff-failing."""
    r = random.Random(f"strain:{seed}")
    if parent:
        sig = [max(0.0, min(1.0, s + r.uniform(-0.15, 0.15)))
               for s in parent["signature"]]
    else:
        sig = [r.random() for _ in range(SIG_DIMS)]
    targets = r.sample(TARGETS, r.randint(1, 3))
    mods = {t: r.choice([-1, 1]) * r.uniform(0.25, 0.6) for t in targets}
    return {"strain_uuid": f"strain-{uuidlib.uuid4().hex[:10]}",
            "signature": sig,
            "replication": r.uniform(0.3, 1.0),
            "contagion": r.uniform(0.2, 0.9),
            "distance": r.uniform(0.02, 0.06),
            "parent_uuid": parent["strain_uuid"] if parent else None,
            "expression_mods": mods}


def roll_teleport_strain(seed: str, existing: list[dict]) -> dict | None:
    """Pathogens have a chance of creation when a teleport happens — rolled
    independently at each end (user decision)."""
    r = random.Random(f"roll:{seed}")
    if r.random() >= TELEPORT_STRAIN_P:
        return None
    parent = r.choice(existing) if existing and r.random() < 0.7 else None
    return new_strain(seed, parent)


def infect(agent_payload: dict, strain: dict, now: float) -> dict:
    """The infection record carries its future: detection after Immune
    Vigilance's latency, synthesis complete after Synthesis Speed's span.
    Severity scales duration by replication (Rule 2.13-ish)."""
    g = agent_payload["genotype"]
    vig = norm("Immune Vigilance", g.get("Immune Vigilance",
                                         RANGES["Immune Vigilance"][0]))
    spd = norm("Synthesis Speed", g.get("Synthesis Speed",
                                        RANGES["Synthesis Speed"][0]))
    detect_after = 3600.0 * (0.5 + 6.0 * (1.0 - vig))          # 0.5h-6.5h
    synth_span = 3600.0 * (2.0 + 20.0 * (1.0 - spd)) \
        * (0.5 + strain["replication"])                         # the race
    rec = {"strain": strain, "since": now,
           "detected_at": now + detect_after,
           "synth_done_at": now + detect_after + synth_span}
    infections = list(agent_payload.get("infections", []))
    infections.append(rec)
    return {**agent_payload, "infections": infections}


def coverage(antigens: list[dict], signature: list[float], now: float) -> float:
    """Graded immunity (Rule 2.20): best combined overlap of live antigens,
    each decayed from its birth (2.18d) and by its holder already at grant."""
    if not antigens:
        return 0.0
    per_dim = [0.0] * len(signature)
    for a in antigens:
        age = max(0.0, now - a["made_at"])
        strength = math.exp(-a["decay_rate"] * age)
        for i, v in enumerate(a["vector"][:len(signature)]):
            match = 1.0 - abs(v - signature[i])
            per_dim[i] = max(per_dim[i], match * strength)
    return sum(per_dim) / len(per_dim)


def settle(agent_payload: dict, now: float) -> tuple[dict, list[str]]:
    """Lazy state: infections whose synthesis completed become antigens
    (Rule 2.18a — earned in the illness, matching its signature with noise);
    the record of what changed is returned for notification."""
    infections = agent_payload.get("infections", [])
    if not infections:
        return agent_payload, []
    g = agent_payload["genotype"]
    r = random.Random(f"settle:{agent_payload.get('identity', '')}:{int(now)}")
    still, antigens, events = [], list(agent_payload.get("antigens", [])), []
    history = list(agent_payload.get("infection_history", []))
    for rec in infections:
        strain = rec["strain"]
        cov = coverage(antigens, strain["signature"], now)
        if cov >= COVERAGE_THRESHOLD or now >= rec["synth_done_at"]:
            antigens.append({
                "vector": [max(0.0, min(1.0, s + r.uniform(-0.08, 0.08)))
                           for s in strain["signature"]],
                "made_at": now,
                "strain_uuid": strain.get("strain_uuid"),
                "decay_rate": r.uniform(0.3, 1.2) / (30 * 86400.0)})
            history.append({"strain_uuid": strain.get("strain_uuid"),
                            "caught_at": rec.get("caught_at"),
                            "recovered_at": now})
            events.append(f"recovered from {strain['strain_uuid']}")
        else:
            still.append(rec)
    return {**agent_payload, "infections": still, "antigens": antigens,
            "infection_history": history[-20:]}, events


def phenotype(agent_payload: dict, now: float) -> dict:
    """Rule 2.14: infection alters EXPRESSION. The genotype the decider and
    the faculties see is the modified one, restored exactly on recovery
    (Rule 2.16) because the genotype itself was never touched."""
    g = dict(agent_payload["genotype"])
    for rec in agent_payload.get("infections", []):
        for locus, frac in rec["strain"]["expression_mods"].items():
            lo, hi = RANGES[locus]
            g[locus] = max(lo, min(hi, g[locus] + frac * (hi - lo)))
    return g


def is_infected(agent_payload: dict) -> bool:
    return bool(agent_payload.get("infections"))


def try_transmit(seed: str, src_payload: dict, dst_payload: dict,
                 now: float) -> dict | None:
    """Contact transmission (Rules 2.4/2.5): contagion at contact, resisted in
    proportion to the receiver's antigen coverage."""
    r = random.Random(f"transmit:{seed}")
    for rec in src_payload.get("infections", []):
        strain = rec["strain"]
        cov = coverage(dst_payload.get("antigens", []),
                       strain["signature"], now)
        p = CONTACT_BASE * strain["contagion"] * (1.0 - cov)
        if r.random() < p:
            return strain
    return None
