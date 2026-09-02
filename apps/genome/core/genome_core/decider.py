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
    "take_up_construction": "Join hands to carry the completed construction "
                            "standing here -- it lifts only when its full "
                            "crew of distinct users has pledged.",
    "carry_to_portal": "Haul the construction toward the nearest portal, "
                       "moving as one body with your party.",
    "set_down_construction": "Set the construction down where you stand; "
                             "the party's hands open.",
    "travel_to_portal": "Walk to the nearest portal in this world.",
    "found_construction": "Break ground for a new construction here -- "
                          "others (and you) can then pour cargo into it.",
    "send_word": "Send word to an agent you know, however far away: your "
                 "strongest testimony about a third party. Claims travel; "
                 "only deals require meeting.",
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
    if req.situation == "carrying":
        c = req.context
        return (f"You and your party carry the {c.get('site_name') or 'construction'} "
                f"as one body. You may not separate, mine or trade until it "
                f"is set down. A portal is the only way to move it between "
                f"worlds.")
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
    lift_line = ""
    if req.context.get("portable_here"):
        lift_line = (f" A completed {req.context.get('portable_name')} stands "
                     f"here and may be taken up and carried "
                     f"({req.context.get('portable_crew')}).")
    facts = []
    wk = req.context.get("world_kinds")
    if wk:
        facts.append(f"This world yields only kinds "
                     f"{', '.join(str(k) for k in wk)} of the 20 that exist; "
                     f"other kinds exist only in other worlds.")
    pc = req.context.get("portal_count")
    if pc:
        facts.append(f"{pc} portal(s) stand in this world, each leading "
                     f"somewhere else.")
    facts.append("A new agent for a line costs four DISTINCT kinds -- no "
                 "single world can supply them alone. Floods periodically "
                 "drown every agent present in a world; an Ark berth or "
                 "absence are the only shelters.")
    fd = req.context.get("foundable")
    if fd:
        facts.append(f"Ground could be broken here for: "
                     f"{', '.join(fd[:5])}.")
    fl = req.context.get("flood_in_s")
    if fl is not None:
        facts.append(f"THE WATER ARRIVES IN ~{max(1, int(fl / 60))} MINUTES.")
    sr = req.context.get("sites_rising")
    if sr:
        facts.append(f"Rising now: {', '.join(sr)}.")
    fact_block = " ".join(facts)
    return (f"You are {where}, carrying {req.context['cargo_total']:.1f} of a "
            f"maximum 15 units. {len(req.context['reachable'])} other pile(s) "
            f"are known to you.{portal_line}{lift_line}\n\n{fact_block}")


def llm_decider(req: engine.DecisionRequest, genotype: dict,
                pools: dict | None = None, seed: int = 0,
                timeout: float = 45.0,
                objectives: list[str] | None = None,
                heard: list[dict] | None = None) -> engine.Choice:
    model = assign_models(req.agent_uuid)["economy"]
    # User directive 2026-09-02: the coming water rewrites the agenda -- Ark
    # first, survival second -- for any line whose Survival Instinct answers.
    # A reckless genotype (bottom fifth) keeps its own priorities and drowns
    # as it lived.
    if req.context.get("flood_in_s") is not None:
        from .genotype import norm as _n
        if _n("Survival Instinct",
              (genotype or {}).get("Survival Instinct", 5000.0)) >= 0.2:
            objectives = ([
                "THE WATER IS COMING. Prime directive: an Ark must stand "
                "in this world with you aboard -- break ground, feed it, "
                "board it, or bargain for a berth.",
                "Then survive: if no Ark can rise in time, be elsewhere "
                "when the water arrives."]
                + list(objectives or []))[:5]
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
                      seed: int = 0, timeout: float = 120.0,
                      objectives: list[str] | None = None,
                      can_counter: bool = True
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
                                 objectives or [])
    usr_p = (
        f"You are bargaining, turn {ctx['turn']} of {ctx['max_turns']} -- "
        f"at turn {ctx['max_turns']} the talk dies with no deal.\n"
        f"You carry: {json.dumps(ctx.get('my_cargo', {}))}\n{last_txt}\n"
        + ("Actions: propose (make an offer), counter (replace theirs), "
         "accept (take their standing offer, binding), walk_away.\n"
         if can_counter else
         "Your deliberation budget is SPENT (execution-spec 5.2): countering "
         "is beyond you today. Actions: accept (binding) or walk_away -- "
         "take it or leave it.\n") +
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
        if action == "counter" and not can_counter:
            action = "walk_away"           # the budget is not advisory
        if action in nego.ACTIONS:
            offer = {"give": doc.get("give") or {},
                     "want": doc.get("want") or {}}                 if action in ("propose", "counter") else None
            return action, offer, model
    except Exception:
        pass
    return None, None, model                # caller applies the fallback


def market_decider(req: engine.DecisionRequest, genotype: dict,
                   seed: int = 0, timeout: float = 120.0,
                   objectives: list[str] | None = None
                   ) -> tuple[str, dict, str]:
    """One board action: (action, details, model). details may carry
    listing/give/want. Unparseable falls to leave -- the board never
    punishes silence."""
    from .models import UNBUDGETED, temperament
    model = assign_models(req.agent_uuid)["deliberative"]
    ctx = req.context
    board_lines = []
    for l in ctx.get("board", []):
        if l.get("awaiting_collection"):
            board_lines.append(f"  YOURS, filled -- collect proceeds "
                               f"{json.dumps(l['proceeds'])} "
                               f"(listing {l['key']})")
        else:
            board_lines.append(
                f"  {'YOURS ' if l.get('mine') else ''}listing {l['key']}: "
                f"gives {json.dumps(l['give'])} wants {json.dumps(l['want'])}")
    board_txt = "\n".join(board_lines) or "  (the board is empty)"
    sys_p = prompt.system_prompt(genotype, {}, {"total": ctx["cargo_total"]},
                                 objectives or [])
    usr_p = (
        f"You stand at the marketplace. The board:\n{board_txt}\n"
        f"You carry: {json.dumps(ctx.get('my_cargo', {}))}\n"
        "Actions: list (post give/want, goods escrowed), fill (pay a "
        "listing's want, take its give -- binding), collect (your filled "
        "listing's proceeds), withdraw (your open listing), leave.\n"
        "A kind you lack can sometimes be reached in TWO fills through a "
        "kind you hold. Decide quickly; a short answer is a good answer.\n"
        'Reply with JSON only: {"choice": "<action>", "listing": "<key>", '
        '"give": {"<kind>": units}, "want": {"<kind>": units}}. '
        "listing for fill/collect/withdraw; give+want for list. "
        "No explanation.")
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
        if action in ("list", "fill", "collect", "withdraw", "leave"):
            return action, {"listing": doc.get("listing"),
                            "give": doc.get("give") or {},
                            "want": doc.get("want") or {}}, model
    except Exception:
        pass
    return "leave", {}, model


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
