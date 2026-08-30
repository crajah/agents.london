"""Genotype arithmetic — genotype-spec.md §2, §3.10, §4.

norm(v) = (v - min + 1)/(max - min + 1), never zero (Rules 2.1/2.2).
Budget:  share_i = norm(v_i)/Σ norm(v_j); expressed_i = B·share_i, B = N/2
         over budgeted loci (Rule 3.22-3.23a). Dispositions, preference
         weights, colour, Gender and Mutability are outside (Rule 3.23);
         everything else is inside, Longevity and the four additions included.
Faculties (Rule 4.2, table §4.5): reservoirs are arithmetic means over
normalised inputs; compound acts are harmonic; balances are geometric.
"""
from __future__ import annotations

import math
from statistics import fmean, harmonic_mean, geometric_mean

# (min, max) per locus. Ranges from genotype-spec.md §3.1-§3.4.
RANGES: dict[str, tuple[float, float]] = {
    # physiological (budgeted)
    "Intelligence": (1, 10000), "Knowledge": (1, 10000), "Wisdom": (1, 10000),
    "Dexterity": (1, 10000), "Agility": (1, 10000), "Charisma": (1, 10000),
    "Courage": (1, 10000), "Range": (1, 100), "Sight": (1, 100),
    "reStamina": (0, 1), "reMana": (0, 1),
    "Depletion Rate": (0, 10000),
    "Infection Propensity": (0, 10000), "Infection Resistance": (0, 10000),
    "Attrition": (0, 10000), "Maturation": (0, 10000),
    "Immune Vigilance": (0, 10000), "Synthesis Speed": (0, 10000),
    "Longevity": (0, 10000),  # budgeted deliberately (Rule 3.23a)
    # dispositions (outside the budget, Rule 3.23)
    "Cooperativeness": (0, 10000), "Reciprocity": (0, 10000),
    "Vindictiveness": (0, 10000), "Aggression": (0, 10000),
    "Honesty": (0, 10000), "Credulity": (0, 10000), "Amenability": (0, 10000),
    "Loyalty": (0, 10000), "Patience": (0, 10000), "Curiosity": (0, 10000),
    "Prudence": (0, 10000), "Wanderlust": (0, 10000), "Fecundity": (0, 10000),
    "Selectivity": (0, 10000),
    # meta (outside)
    "Gender": (0, 1), "Mutability": (0, 10000),
}

DISPOSITIONS = ["Cooperativeness", "Reciprocity", "Vindictiveness", "Aggression",
                "Honesty", "Credulity", "Amenability", "Loyalty", "Patience",
                "Curiosity", "Prudence", "Wanderlust", "Fecundity", "Selectivity"]
OUTSIDE_BUDGET = set(DISPOSITIONS) | {"Gender", "Mutability"}  # + colour, prefs
BUDGETED = [k for k in RANGES if k not in OUTSIDE_BUDGET]


def norm(locus: str, v: float) -> float:
    lo, hi = RANGES[locus]
    return (v - lo + 1.0) / (hi - lo + 1.0)


def expressed(genotype: dict[str, float]) -> dict[str, float]:
    """Budget allocation over the budgeted loci (Rule 3.22). Returns expressed
    values in (0, B]; dispositions and meta pass through unbudgeted."""
    loci = [k for k in BUDGETED if k in genotype]
    total = sum(norm(k, genotype[k]) for k in loci)
    b = len(loci) / 2.0
    out = {k: b * norm(k, genotype[k]) / total for k in loci}
    for k in genotype:
        if k not in out:
            out[k] = norm(k, genotype[k])
    return out


# --- derived faculties (§4.5 table), over EXPRESSED normalised inputs ---

def faculties(genotype: dict[str, float]) -> dict[str, float]:
    e = expressed(genotype)

    def h(*ks): return harmonic_mean([e[k] for k in ks])
    def g(*ks): return geometric_mean([e[k] for k in ks])
    def a(*ks): return fmean([e[k] for k in ks])

    out = {
        "Stamina": a("Knowledge", "Agility", "Courage"),
        "Mana": a("Intelligence", "Knowledge", "Wisdom"),
        "Attack": h("Intelligence", "Dexterity", "Courage"),
        "Counsel": g("Dexterity", "Agility"),
        "Occulmancy": g("Intelligence", "Knowledge"),
        "Safe Period": g_disp(genotype, "Knowledge", e, "Prudence"),
    }
    # Aggression is a further input to Attack (§4 faculty table): a violent
    # line hits harder, measurably. Attrition is intensity (Rule 3.8c).
    out["Attack"] *= 1.0 + 0.5 * norm("Aggression", genotype["Aggression"])
    out["Attack"] *= 1.0 + 0.5 * norm("Attrition", genotype["Attrition"])
    return out


def g_disp(genotype, budgeted_key, e, disp_key):
    """Geometric mean of one budgeted expressed value and one disposition norm
    (Safe Period spans the budget boundary: Knowledge is budgeted, Prudence is
    not — §3.7)."""
    return math.sqrt(e[budgeted_key] * norm(disp_key, genotype[disp_key]))


# --- life history ---

def stamina_max(base_stamina: float, age_days: float, maturation: float,
                victories: int, attrition: float) -> float:
    """Rule 3.8a: Stamina rises with age at a Maturation-set rate.
    Rule 3.8c: each victory permanently removes an Attrition share.
    Attrition at locus 5000 costs ~6.7%/win (calibration Rule 3.0b), linear.
    Maturation at locus 10000 doubles base over a 90-day life; scales linearly.
    """
    m = norm("Maturation", maturation)
    growth = 1.0 + m * (age_days / 90.0)
    # Linear in victories, as a share of BASE: at locus 5000, fifteen wins
    # exhaust the agent exactly, so Rule 3.8d's zero is reachable.
    burn = (attrition / 5000.0) * (1.0 / 15.0)
    return max(0.0, base_stamina * (growth - burn * victories))


def mana_max(base_mana: float, age_days: float, maturation: float) -> float:
    """Rule 3.8a: Mana falls with age at the same Maturation-set rate; floor at
    10% so a spent elder is weak, not null."""
    m = norm("Maturation", maturation)
    return base_mana * max(0.1, 1.0 - m * (age_days / 90.0))


def lifespan_days(longevity_expressed: float, b: float) -> float:
    """calibration-spec.md Rule 3.0: Longevity maps to 20-90 real days, linear
    across its EXPRESSED value (it is budgeted), where b is the budget constant
    so expressed/b spans (0,1]-ish."""
    f = min(1.0, longevity_expressed / b)
    return 20.0 + f * 70.0


# ---------------- heredity (genotype-spec §7, genome-spec §9.4) ----------------

MUTATION_STEP = 0.05          # calibration Rule 3.0a: ~5% of a locus range
EXCURSION_P = 0.02            # Rule 7.4a: rare large excursions
EXCURSION_STEP = 0.25


def crossover(a: dict, b: dict, seed: str) -> dict:
    """Uniform crossover locus-by-locus, then mutation gated by the CHILD's own
    inherited Mutability (Rule 7.4: an agent's own mutation probability)."""
    import random
    r = random.Random(f"cross:{seed}")
    child = {k: (a if r.random() < 0.5 else b)[k] for k in RANGES}
    p_mut = norm("Mutability", child["Mutability"])
    for k, (lo, hi) in RANGES.items():
        if r.random() < p_mut * 0.5:
            step = EXCURSION_STEP if r.random() < EXCURSION_P else MUTATION_STEP
            child[k] = min(hi, max(lo, child[k] + r.uniform(-1, 1) * step * (hi - lo)))
    return child


def child_colours(a_pair: list, b_pair: list, seed: str) -> list:
    """One colour from each parent, randomly picked (user decision, 9.6-era)."""
    import random
    r = random.Random(f"col:{seed}")
    return [r.choice(a_pair), r.choice(b_pair)]


def child_name(a_name: str, b_name: str, seed: str, first_names: list) -> str:
    """Rule 7.14: the SECOND last name of each parent, in random order; a fresh
    first name."""
    import random
    r = random.Random(f"name:{seed}")
    sa, sb = a_name.split()[-1], b_name.split()[-1]
    pair = [sa, sb]
    r.shuffle(pair)
    return " ".join([r.choice(first_names)] + pair)


def gender_of(genotype: dict) -> str:
    """Gender is a gate, not a virtue (Rule 6.4/6.5): the 0-1 locus splits at
    half. Never visible to other agents."""
    return "female" if genotype["Gender"] >= 0.5 else "male"


def breeding_cost_met(cargo_a: dict, cargo_b: dict) -> dict | None:
    """Rule 9.4: collectively 2 units each of 4 DIFFERENT kinds. Returns the
    per-kind spend split by contributor, or None."""
    pool: dict[str, float] = {}
    for c in (cargo_a, cargo_b):
        for k, u in c.items():
            pool[k] = pool.get(k, 0.0) + u
    kinds = [k for k, u in sorted(pool.items()) if u >= 2.0]
    if len(kinds) < 4:
        return None
    chosen = kinds[:4]
    spend = {"a": {}, "b": {}}
    for k in chosen:
        need = 2.0
        take_a = min(cargo_a.get(k, 0.0), need)
        if take_a > 0:
            spend["a"][k] = take_a
            need -= take_a
        if need > 0:
            spend["b"][k] = need
    return spend
