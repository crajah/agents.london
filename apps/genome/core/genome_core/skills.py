"""Capabilities — skills-spec.md §1, first slice. One roll at birth: 75% of
agents receive a single capability, a quarter are born plain (Rules
1.1/1.1a). Rolled fresh for progeny (1.2), never transferred (1.2a -- no
function in this module or any other moves one between agents), and part of
the state regeneration restores (1.3).

This slice carries the MECHANICAL starter skills -- each hooked to a
subsystem that already exists, the exact discipline of the construction
effects table. Tools (MCP registry lottery) and the brokerage
request/response loop are the next slice; the scarcity they will trade on
is established here."""
from __future__ import annotations

import random

# name -> (description shown to the agent and in the inspector, hook)
CATALOGUE: dict[str, str] = {
    "Porterage": "You carry 5 units more than others can.",
    "Prospecting": "Your mining stints pull 2 units deeper.",
    "Ward": "You take a fifth less in a fight.",
    "Scrying": "At an encounter you see exactly what the other carries, "
               "and whether it is infected -- before you engage.",
    "Gene-reading": "A suitor's expressed nature is shown to you before "
                    "you answer a breeding proposal.",
    "Pathfinding": "Your journeys run a tenth quicker.",
    "Chronicle": "Your testimony carries double weight when others fold "
                 "it in.",
}


def roll_capability(agent_uuid: str) -> dict | None:
    """One roll, at birth, deterministic per agent so a replay agrees.
    Rule 1.1a: at most ONE capability; a quarter get nothing."""
    r = random.Random(f"capability:{agent_uuid}")
    if r.random() >= 0.75:
        return None
    name = r.choice(sorted(CATALOGUE))
    return {"kind": "skill", "name": name}


def held(payload: dict) -> str | None:
    cap = payload.get("capability")
    return cap.get("name") if cap else None


def describe(payload: dict) -> str:
    name = held(payload)
    if name is None:
        return ("You hold no capability. What you cannot do yourself, "
                "another agent must be persuaded to do for you.")
    return f"You hold one capability -- {name}: {CATALOGUE[name]}"
