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
    "contribute_here": "Pour your cargo into the construction site here.",
    "build_cache": "Build a cache here (costs four different kinds, one "
                   "unit each) -- a larder only your colours can open.",
    "stash_cache": "Stash everything you carry into your line's cache.",
    "collect_cache": "Take what fits from your line's cache.",
    "board_ark": "Board the Ark and claim a berth -- the only shelter from "
                 "the coming flood.",
    "flee_to_ark": "Run for the Ark before the water arrives.",
    "travel_to_site": "Carry your cargo to a construction site that needs it.",
    "explore_frontier": "Push into the unexplored region nearest the edge of what you know.",
    "survey_far": "Mount an expedition to the farthest unexplored region.",
    "wait": "Stay where you are for an hour.",
    "offer_trade": "Offer to trade with this agent.",
    "attack": "Attack this agent and take what it carries.",
    "propose_breeding": "Propose to breed with this agent (costs resources; "
                        "compatibility is discovered only if it agrees).",
    "ignore": "Pass by without engaging.",
    "offer_berth": "Give this agent your Ark berth -- your place in the "
                   "lifeboat becomes theirs.",
    "accept_mate": "Accept: breed with this agent (spends pooled resources; "
                   "two offspring, one raised as yours).",
    "decline_mate": "Decline the proposal.",
    "take_portal": "Step through the portal to another world.",
}


def situation_text(req: engine.DecisionRequest) -> str:
    if req.situation == "mating_proposal":
        c = req.context
        op = c.get("opinion")
        opinion_line = (f" Your opinion of it: {op}." if op else
                        " You have never met it before.")
        return (f"An agent wearing colours {c.get('proposer_colours')} "
                f"proposes to breed with you.{opinion_line} Whether it is a "
                f"worthy mate is yours alone to judge.")
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
                objectives: list[str] | None = None,
                heard: list[dict] | None = None) -> engine.Choice:
    model = assign_models(req.agent_uuid)["economy"]
    # Rule 10.1a/10.1b: the owner's objectives outrank the standing floor and
    # MUST reach the prompt -- they were hardcoded empty once, and three
    # max-Wanderlust agents dutifully refused a portal because "deposit at
    # home" was the only telos they had ever been given.
    sys_p = prompt.system_prompt(genotype, pools or {},
                                 {"total": req.context["cargo_total"]},
                                 objectives or [], heard=heard)
    usr_p = prompt.user_prompt(situation_text(req),
                               {k: OPTION_TEXT.get(k, k) for k in req.options})
    from .models import UNBUDGETED
    from .models import temperament
    req_body = {"model": model, "temperature": temperament(req.agent_uuid),
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": usr_p}]}
    if model not in UNBUDGETED:
        req_body["max_tokens"] = 24        # budgeted models stay terse; the
        # flat-rate pair runs UNCAPPED (user decision)
    body = json.dumps(req_body).encode()
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


def negotiate_decider(req: engine.DecisionRequest, genotype: dict,
                      seed: int = 0, timeout: float = 120.0
                      ) -> tuple[str, dict | None, str]:
    """One bargaining turn: returns (action, offer, model). The prompt shows
    the standing offer and the purse; the reply is a single JSON object.
    Anything unparseable falls to the non-strategic default."""
    from . import negotiation as nego
    from .models import UNBUDGETED, temperament
    model = assign_models(req.agent_uuid)["deliberative"]
    ctx = req.context
    last = ctx.get("last_offer")
    last_txt = (f"Their standing offer: they give you "
                f"{json.dumps(last['give'])} and want "
                f"{json.dumps(last['want'])} from you."
                if last else "No offer stands yet; you open.")
    sys_p = prompt.system_prompt(genotype, {}, {"total": ctx["cargo_total"]},
                                 [])
    usr_p = (
        f"You are bargaining, turn {ctx['turn']} of {ctx['max_turns']} -- "
        f"at turn {ctx['max_turns']} the talk dies with no deal.\n"
        f"You carry: {json.dumps(ctx.get('my_cargo', {}))}\n{last_txt}\n"
        "Actions: propose (make an offer), counter (replace theirs), "
        "accept (take their standing offer, binding), walk_away.\n"
        "Decide quickly; a short answer is a good answer.\n"
        'Reply with JSON only: {"choice": "<action>", '
        '"give": {"<kind>": units}, "want": {"<kind>": units}}. '
        "give/want required for propose and counter, ignored otherwise. "
        "Offer only what you carry. No explanation.")
    req_body = {"model": model,
                "temperature": temperament(req.agent_uuid),
                "messages": [{"role": "system", "content": sys_p},
                             {"role": "user", "content": usr_p}]}
    if model not in UNBUDGETED:
        req_body["max_tokens"] = 200
    rq = urllib.request.Request(
        ROUTER + "/v1/chat/completions", data=json.dumps(req_body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            text = json.load(r)["choices"][0]["message"]["content"] or ""
        s, e = text.index("{"), text.rindex("}")
        doc = json.loads(text[s:e + 1])
        action = str(doc.get("choice", "")).lower()
        if action in nego.ACTIONS:
            offer = {"give": doc.get("give") or {},
                     "want": doc.get("want") or {}}                 if action in ("propose", "counter") else None
            return action, offer, model
    except Exception:
        pass
    return None, None, model                # caller applies the fallback


def make_decider(use_llm: bool):
    """The drain's decider contract: (req, agent_payload, seed) ->
    (Choice, model) or a bare Choice."""
    def decide(req, agent_payload, seed):
        g = agent_payload.get("genotype")
        if use_llm and g:
            from . import pathogen
            eff = pathogen.phenotype(agent_payload, __import__("time").time()) \
                if agent_payload.get("infections") else g
            return llm_decider(req, eff, seed=seed,
                               objectives=agent_payload.get("objectives"))
        return engine.stub_decider(req, seed)
    return decide
