"""The router decider — the economy caste's decision function.

Calls the litellm router (execution-spec Rule 8.2: never a provider directly)
with the agent's ASSIGNED model (Rule 10.5: credentials decide who pays, never
which model thinks). One single constrained call per ordinary decision
(Rule 8.3): temperature 1.0, tiny max_tokens, JSON-only reply — the validated
shape. Falls back to continuing the current intent on failure (Rule 5.2a:
running out of judgement is not running out of motion).

Stdlib only, sync (the drain awaits via a thread when needed); kagent Agent CRs
wrap this same prompt contract in the deploy manifests.
"""
from __future__ import annotations

import json
import os
import urllib.request

from . import engine, prompt
from .genotype import RANGES
from .models import assign_models

ROUTER = os.getenv("GENOME_ROUTER_URL", "http://localhost:4000").rstrip("/")
KEY = os.getenv("GENOME_ROUTER_KEY") or os.getenv("GLOBAL_API_KEY") or ""

OPTION_TEXT = {
    "mine_here": "Mine this pile.",
    "travel_to_pile": "Travel to another pile you know of.",
    "go_home_deposit": "Return home and deposit your cargo.",
    "explore_frontier": "Push into the unexplored region nearest the edge of what you know.",
    "survey_far": "Mount an expedition to the farthest unexplored region.",
    "wait": "Stay where you are for an hour.",
    "offer_trade": "Offer to trade with this agent.",
    "attack": "Attack this agent and take what it carries.",
    "propose_breeding": "Propose to breed with this agent (costs resources; "
                        "compatibility is discovered only if it agrees).",
    "ignore": "Pass by without engaging.",
    "take_portal": "Step through the portal to another world.",
}


def situation_text(req: engine.DecisionRequest) -> str:
    if req.situation == "encounter":
        c = req.context
        op = c.get("opinion")
        opinion_line = (f" Your opinion of it: {op}." if op else
                        " You have never met it.")
        inf = " It is visibly infected." if c.get("other_infected") else ""
        return (f"You meet another agent. You can see only its colours: "
                f"{c.get('other_colours')}.{inf}{opinion_line} "
                f"You carry {c['cargo_total']:.1f} units.")
    at = req.context.get("at_pile")
    where = "at a resource pile" if at else "in open country"
    # The situation must PRESENT what is here (the 12.17 lesson: an option the
    # situation never mentions is an option the model rightly ignores).
    portal_line = ""
    if req.context.get("portal_to"):
        cols = req.context.get("portal_colours")
        portal_line = (f" A teleport portal stands here, wearing the colours "
                       f"{cols} of another world you have never entered — its "
                       f"piles, agents and terrain are entirely unknown to you.")
    return (f"You are {where}, carrying {req.context['cargo_total']:.1f} of a "
            f"maximum 15 units. {len(req.context['reachable'])} other pile(s) "
            f"are known to you.{portal_line}")


def llm_decider(req: engine.DecisionRequest, genotype: dict,
                pools: dict | None = None, seed: int = 0,
                timeout: float = 45.0,
                objectives: list[str] | None = None) -> engine.Choice:
    model = assign_models(req.agent_uuid)["economy"]
    # Rule 10.1a/10.1b: the owner's objectives outrank the standing floor and
    # MUST reach the prompt -- they were hardcoded empty once, and three
    # max-Wanderlust agents dutifully refused a portal because "deposit at
    # home" was the only telos they had ever been given.
    sys_p = prompt.system_prompt(genotype, pools or {},
                                 {"total": req.context["cargo_total"]},
                                 objectives or [])
    usr_p = prompt.user_prompt(situation_text(req),
                               {k: OPTION_TEXT.get(k, k) for k in req.options})
    body = json.dumps({"model": model, "temperature": 1.0, "max_tokens": 24,
                       "messages": [{"role": "system", "content": sys_p},
                                    {"role": "user", "content": usr_p}]}).encode()
    rq = urllib.request.Request(
        ROUTER + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
        opt = prompt.parse_choice(text, list(req.options))
    except Exception:
        opt = None
    if opt is None:
        # Rule 5.2a fallback: never strategic — first option is "continue-ish"
        opt = req.options[0]
    target = None
    if opt == "travel_to_pile" and req.context["reachable"]:
        import random
        target = random.Random(f"{seed}:{req.agent_uuid}").choice(
            req.context["reachable"])
    return engine.Choice(option=opt, target=target), model


def make_decider(use_llm: bool):
    """The drain's decider contract: (req, agent_payload, seed) ->
    (Choice, model) or a bare Choice."""
    def decide(req, agent_payload, seed):
        g = agent_payload.get("genotype")
        if use_llm and g:
            return llm_decider(req, g, seed=seed,
                               objectives=agent_payload.get("objectives"))
        return engine.stub_decider(req, seed)
    return decide
