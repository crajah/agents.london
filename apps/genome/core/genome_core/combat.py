"""Combat resolution — genome-spec.md Rules 9.3a-9.3e, genotype-spec.md
Rules 3.8c/3.8e.

Attack against Attack, moderated by the defender's Agility, probabilistic.
Both lose Stamina, the loser more. The winner takes cargo up to its ceiling
(remainder stays, Rule 4.19a) and burns maximum Stamina by its Attrition
(intensity: it also hit harder for the same reason). Zero current Stamina
incapacitates; zero MAXIMUM perishes (Rule 3.8d) — the caller handles death.

Deterministic given a seed: the record must be able to replay a fight.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .genotype import faculties, norm

# PROVISIONAL calibration (calibration-spec §4): stamina cost of an exchange
LOSER_STAMINA_COST = 0.35      # share of loser's max
WINNER_STAMINA_COST = 0.15     # winner pays too (Rule 9.3b)


@dataclass(frozen=True)
class Fighter:
    agent_uuid: str
    genotype: dict
    stamina: float          # current
    stamina_max: float
    cargo: dict


def resolve(att: Fighter, dfd: Fighter, seed: str,
            att_mult: float = 1.0, dfd_mult: float = 1.0,
            stamina_mult: float = 1.0) -> dict:
    """One exchange. Returns the outcome and every delta the caller persists.
    att_mult/dfd_mult: a standing Forge arms a resident, a Rampart shields
    one (calibration §5); stamina_mult: an Infirmary halves the tolls."""
    fa, fd = faculties(att.genotype), faculties(dfd.genotype)
    # defender's Agility is escape (genotype §3.1): scales down hit chance
    agility = norm("Agility", dfd.genotype["Agility"])
    p_att = (fa["Attack"] * att_mult) / (
        fa["Attack"] * att_mult
        + fd["Attack"] * dfd_mult * (0.5 + agility))
    rng = random.Random(f"combat:{seed}:{att.agent_uuid}:{dfd.agent_uuid}")
    attacker_wins = rng.random() < p_att

    winner, loser = (att, dfd) if attacker_wins else (dfd, att)
    # spoils up to the winner's ceiling; remainder stays (Rule 9.3c/4.19a)
    room = max(0.0, 15.0 - sum(winner.cargo.values()))
    taken: dict[str, float] = {}
    for kind, units in sorted(loser.cargo.items()):
        t = min(units, room)
        if t > 0:
            taken[kind] = t
            room -= t
    # Attrition burns the WINNER's maximum (Rule 3.8c): 15 wins at locus 5000
    burn = (winner.genotype["Attrition"] / 5000.0) * (1.0 / 15.0)
    return {
        "attacker_wins": attacker_wins,
        "p_attacker": round(p_att, 4),
        "winner": winner.agent_uuid, "loser": loser.agent_uuid,
        "spoils": taken,
        "winner_stamina_delta": -WINNER_STAMINA_COST * winner.stamina_max
        * stamina_mult,
        "loser_stamina_delta": -LOSER_STAMINA_COST * loser.stamina_max
        * stamina_mult,
        "winner_max_burn": burn * winner.stamina_max,
    }
