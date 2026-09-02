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
    "Appraisal": "You read true scarcity: asked, you can tell which kinds "
                 "run short in a world and which run deep.",
}

# The skills a holder can perform AT A DISTANCE for another agent (Rule
# 8.6). Everything else is a capability of the body: it travels with the
# holder and cannot be posted.
REMOTE = {"Chronicle", "Prospecting", "Appraisal"}


def roll_capability(agent_uuid: str) -> dict | None:
    """One roll, at birth, deterministic per agent so a replay agrees.
    Rule 1.1a: at most ONE capability; a quarter get nothing."""
    r = random.Random(f"capability:{agent_uuid}")
    if r.random() >= 0.75:
        return None
    name = r.choice(sorted(CATALOGUE))
    return {"kind": "skill", "name": name}


def honesty_holds(holder_payload: dict, request_key: str) -> bool:
    """Rule 8.8: the provider's Honesty governs whether the result is TRUE.
    Deterministic per (holder, request) so a replay agrees -- and so a liar
    lies consistently about the same question."""
    from .genotype import norm
    g = holder_payload.get("genotype") or {}
    p_true = norm("Honesty", g.get("Honesty", 5000.0))
    return random.Random(f"honesty:{holder_payload.get('key')}"
                         f":{request_key}").random() < p_true


def perform(holder_payload: dict, skill: str, request_key: str,
            world_stock: dict | None = None) -> dict:
    """The holder does the work and RETURNS A RESULT (Rule 8.7) -- never the
    tool. What comes back is testimony, true at the holder's Honesty."""
    truthful = honesty_holds(holder_payload, request_key)
    r = random.Random(f"svc:{request_key}")
    if skill == "Chronicle":
        out = []
        for subject, loci in sorted(
                (holder_payload.get("opinions") or {}).items())[:3]:
            for locus, v in sorted(loci.items())[:2]:
                est = v.get("estimate", 5000.0)
                if not truthful:
                    est = 10000.0 - est          # a liar inverts the record
                out.append({"subject": subject, "locus": locus,
                            "estimate": est})
        return {"kind": "chronicle", "claims": out, "_truthful": truthful}
    if skill == "Prospecting":
        piles = list(holder_payload.get("known_piles") or [])[:10]
        if not truthful:
            piles = [f"pile-{r.getrandbits(40):010x}" for _ in piles]
        return {"kind": "prospect",
                "realm": holder_payload.get("realm_hint"),
                "piles": piles, "_truthful": truthful}
    if skill == "Appraisal":
        stock = world_stock or {}
        ranked = sorted(stock.items(), key=lambda kv: kv[1])
        scarce = [k for k, _ in ranked[:3]]
        deep = [k for k, _ in ranked[-3:]]
        if not truthful:
            scarce, deep = deep, scarce
        return {"kind": "appraisal", "scarce": scarce, "deep": deep,
                "_truthful": truthful}
    return {"kind": "nothing"}


def held(payload: dict) -> str | None:
    cap = payload.get("capability")
    return cap.get("name") if cap else None


def describe(payload: dict) -> str:
    name = held(payload)
    if name is None:
        return ("You hold no capability. What you cannot do yourself, "
                "another agent must be persuaded to do for you.")
    return f"You hold one capability -- {name}: {CATALOGUE[name]}"
