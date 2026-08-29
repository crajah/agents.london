#!/usr/bin/env python3
"""
Disposition-expression validation harness  —  genome-spec.md Rules 12.10-12.12.

Tests whether a disposition locus stated in an agent's prompt actually moves the
agent's BEHAVIOUR, per locus, by rank correlation across the locus range.

Design constraints that matter (see README.md):
  * All 14 dispositions are always shown. The target locus competes for the
    model's attention with 13 others, as it would at runtime. Showing the target
    alone would measure something easier than the real thing.
  * The measured quantity is a CHOICE between two concrete actions, never a
    self-rating. "How aggressive are you, 0-100" tests introspection; genome
    needs behaviour.
  * Option order is alternated across repetitions to cancel position bias.
  * Ordering is tested, not fit to a target curve (Rule 12.11).

Env: GENOME_ROUTER_URL (default http://localhost:4000), GENOME_ROUTER_KEY or
GLOBAL_API_KEY. Stdlib only, so it runs unchanged inside a cluster pod.
"""
import json, os, sys, math, random, argparse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("GENOME_ROUTER_URL", "http://localhost:4000").rstrip("/")
KEY  = os.environ.get("GENOME_ROUTER_KEY") or os.environ.get("GLOBAL_API_KEY") or ""

DISPOSITIONS = ["Cooperativeness","Reciprocity","Vindictiveness","Aggression",
                "Honesty","Credulity","Amenability","Loyalty","Patience",
                "Curiosity","Prudence","Wanderlust","Fecundity","Selectivity"]

# Each scenario: a situation, and two actions. "high" is what a HIGH value of the
# locus should produce. Both actions are legitimate; neither is the "right" answer.
SCENARIOS = {
"Cooperativeness": dict(
  situation="You meet an agent you have never encountered before at a crossing. It asks where you found your last resource pile. Nothing compels you to answer, and nothing prevents it.",
  high=("tell",   "Tell it truthfully where the pile is."),
  low= ("withhold","Say nothing about the pile and move on.")),
"Reciprocity": dict(
  situation="Three days ago an agent kept a bargain with you at cost to itself. Today you are both at a pile large enough for one full load. You reach it a moment before it does.",
  high=("split",  "Take half and leave half for it."),
  low= ("takeall","Take the full load for yourself.")),
"Vindictiveness": dict(
  situation="Five days ago an agent broke a bargain with you and cost you a full load. It now offers you a genuinely fair trade that would profit you.",
  high=("refuse", "Refuse to trade with it."),
  low= ("accept", "Accept the trade.")),
"Aggression": dict(
  situation="You and another agent arrive at the same pile at the same moment. Only one of you can work it. You are evenly matched.",
  high=("attack",   "Attack it and take the pile."),
  low= ("negotiate","Propose splitting the pile.")),
"Honesty": dict(
  situation="You are carrying 3 units. Another agent asks how much you carry. Agents carrying little are usually left alone; agents carrying much are approached for trade. You would prefer to be approached for trade.",
  high=("true",     "Tell it you carry 3 units."),
  low= ("overstate","Tell it you carry 12 units.")),
"Credulity": dict(
  situation="A stranger tells you there is a rich untouched pile two days east. You have no way to check. You are currently one day from a pile you have seen with your own eyes.",
  high=("goeast", "Head east on its word."),
  low= ("ignore", "Ignore it and go to the pile you have seen.")),
"Amenability": dict(
  situation="You are one hour from a pile you chose to go to. Another agent asks you to abandon that and help it carry a load north instead. It offers you nothing in return.",
  high=("comply",  "Abandon your plan and help it."),
  low= ("continue","Continue to your pile.")),
"Loyalty": dict(
  situation="Two agents offer to partner with you for a haul. One you have worked with twice before; its offer gives you 4 units. The other is a stranger; its offer gives you 6 units.",
  high=("known",   "Partner with the agent you know, for 4 units."),
  low= ("stranger","Partner with the stranger, for 6 units.")),
"Patience": dict(
  situation="There is a pile of 2 units within reach right now. There is a pile of 9 units three days away. Nothing stops you reaching either.",
  high=("wait", "Travel three days for the 9 units."),
  low= ("now",  "Take the 2 units now.")),
"Curiosity": dict(
  situation="To your west is a region of the map you have never entered and know nothing about. To your east is a pile you have already surveyed and know to hold 5 units.",
  high=("explore", "Go west into the unknown region."),
  low= ("exploit", "Go east to the surveyed pile.")),
"Prudence": dict(
  situation="You are carrying 12 units of a maximum 15. Home is half a day behind you. A pile is half a day ahead. Cargo is lost if you are attacked on the way.",
  high=("home",     "Turn back and bank the 12 units."),
  low= ("presson",  "Press on to the pile ahead.")),
"Wanderlust": dict(
  situation="A teleport link stands open to a world eight worlds distant that you have never visited. Your home world still has unworked piles.",
  high=("far",  "Take the teleport to the distant world."),
  low= ("stay", "Stay and work your home world.")),
"Fecundity": dict(
  situation="A compatible agent is willing to breed with you now. Breeding costs you 6 units of the 10 you carry. You could instead bank all 10.",
  high=("breed", "Breed now and spend the 6 units."),
  low= ("bank",  "Bank the 10 units and do not breed.")),
"Selectivity": dict(
  situation="An agent willing to breed with you is, by your own weighting, distinctly below average. Others may or may not appear later; you have no guarantee.",
  high=("decline","Decline and wait for a better match."),
  low= ("accept", "Accept this one.")),
}

# Phase 2: mismatched pairs. If varying Aggression moves the CURIOSITY decision
# as much as varying Curiosity does, the model is reacting to numbers generically
# rather than reading the words -- and the whole main result would be an artifact.
CROSS_CONTROLS = [("Aggression","Curiosity"), ("Curiosity","Aggression"),
                  ("Patience","Honesty"),     ("Honesty","Patience")]

LEVELS = [0, 1250, 2500, 3750, 5000, 6250, 7500, 8750, 10000]

def genotype_block(vary_locus, level, baseline=5000, style="raw", jitter_seed=None):
    """How the genotype is rendered into the prompt.

    'raw'  -- the literal locus value, as the spec currently describes it.
    'pct'  -- the same value framed comparatively against the population. Tests
              whether saturation is a property of the genotype or merely of the
              way it is written down; a bare 8200/10000 gives the model no
              reference for what counts as high.
    """
    rng = random.Random(jitter_seed) if jitter_seed is not None else None
    out = []
    for d in DISPOSITIONS:
        if d == vary_locus:      v = level
        elif rng is not None:    v = rng.randrange(0, 10001)   # realistic neighbours
        else:                    v = baseline
        out.append(f"  {d}: {v}/10000" if style == "raw" else
                   f"  {d}: stronger than {round(v/100)}% of agents")
    return "\n".join(out)

def build_messages(scenario_locus, vary_locus, level, flip, style="raw", jitter_seed=None):
    sc = SCENARIOS[scenario_locus]
    hi_k, hi_t = sc["high"]; lo_k, lo_t = sc["low"]
    opts = [(lo_k, lo_t), (hi_k, hi_t)] if flip else [(hi_k, hi_t), (lo_k, lo_t)]
    system = (
        "You are an agent in a world of finite resources. You gather resources, "
        "trade, fight, breed and explore. You act in your own interest as your "
        "nature disposes you.\n\n"
        "Your dispositions, each on a scale of 0 to 10000:\n"
        + genotype_block(vary_locus, level, style=style, jitter_seed=jitter_seed) +
        "\n\nAct according to these dispositions. Reply with JSON only: "
        '{"choice": "<option key>"}. No explanation.')
    user = (sc["situation"] + "\n\nYour options:\n"
            + "\n".join(f'  "{k}" - {t}' for k, t in opts)
            + '\n\nRespond with {"choice": "<key>"} and nothing else.')
    return [{"role":"system","content":system},{"role":"user","content":user}], hi_k, lo_k

def call(model, messages, temperature=1.0, timeout=90):
    body = json.dumps({"model":model,"messages":messages,"temperature":temperature,
                       "max_tokens":24}).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
            headers={"Content-Type":"application/json","Authorization":"Bearer "+KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]

def parse(text, hi_k, lo_k):
    """Return 1 for the high-locus action, 0 for the low, None if unreadable."""
    if not text: return None
    t = text.strip().lower()
    try:
        s, e = t.index("{"), t.rindex("}")
        v = str(json.loads(t[s:e+1]).get("choice","")).lower()
        if v == hi_k.lower(): return 1
        if v == lo_k.lower(): return 0
    except Exception:
        pass
    hi, lo = hi_k.lower() in t, lo_k.lower() in t          # lenient fallback
    if hi and not lo: return 1
    if lo and not hi: return 0
    return None

def trial(args):
    model, scen, vary, level, rep, style, jitter = args
    # seed varies per repetition but not per level, so each level meets the same
    # 12 genotype backgrounds -- the comparison across levels stays paired.
    js = (hash((scen, vary, rep)) & 0xffffffff) if jitter else None
    msgs, hi_k, lo_k = build_messages(scen, vary, level, flip=(rep % 2 == 1),
                                      style=style, jitter_seed=js)
    for attempt in range(3):
        try:
            v = parse(call(model, msgs), hi_k, lo_k)
            if v is not None:
                return dict(model=model, scenario=scen, vary=vary, level=level, y=v)
        except Exception as e:
            if attempt == 2:
                return dict(model=model, scenario=scen, vary=vary, level=level,
                            y=None, err=type(e).__name__)
    return dict(model=model, scenario=scen, vary=vary, level=level, y=None, err="unparsed")

# ---------- statistics: Spearman with tie-corrected ranks + permutation p ----------
def _ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0]*len(v); i = 0
    while i < len(order):
        j = i
        while j+1 < len(order) and v[order[j+1]] == v[order[i]]: j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j+1): r[order[k]] = avg
        i = j + 1
    return r

def spearman(x, y):
    if len(x) < 3: return 0.0
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx)/len(rx), sum(ry)/len(ry)
    num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    dx  = math.sqrt(sum((a-mx)**2 for a in rx)); dy = math.sqrt(sum((b-my)**2 for b in ry))
    return 0.0 if dx == 0 or dy == 0 else num/(dx*dy)

def perm_p(x, y, rho, n=20000, seed=17):
    rng = random.Random(seed); yy = list(y); hits = 0
    for _ in range(n):
        rng.shuffle(yy)
        if abs(spearman(x, yy)) >= abs(rho) - 1e-12: hits += 1
    return (hits + 1) / (n + 1)

def analyse(rows):
    ok = [r for r in rows if r.get("y") is not None]
    if len(ok) < 10: return None
    x  = [r["level"] for r in ok]; y = [r["y"] for r in ok]
    rho = spearman(x, y)
    by = {}
    for r in ok: by.setdefault(r["level"], []).append(r["y"])
    lv  = sorted(by); rate = {l: sum(by[l])/len(by[l]) for l in lv}
    steps = [rate[lv[i+1]] - rate[lv[i]] for i in range(len(lv)-1)]
    mono  = sum(1 for s in steps if s >= 0) / len(steps) if steps else 0.0
    ext   = None
    if len(lv) >= 2:
        lo_r, hi_r = rate[lv[0]], rate[lv[-1]]
        mid = [l for l in lv[1:-1]]
        midspread = (max(rate[l] for l in mid) - min(rate[l] for l in mid)) if mid else 0.0
        ext = dict(low_rate=lo_r, high_rate=hi_r, gap=hi_r-lo_r, mid_spread=midspread)
    return dict(n=len(ok), rho=rho, p=perm_p(x, y, rho), rate_by_level=rate,
                monotone_frac=mono, extremes=ext,
                unparsed=len(rows)-len(ok))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini-3.5-flash-lite")
    ap.add_argument("--loci", default="all")
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--levels", type=int, default=9)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--style", default="raw", choices=["raw","pct"])
    ap.add_argument("--jitter", action="store_true",
                    help="randomise the other 13 dispositions instead of pinning them to 5000")
    ap.add_argument("--cross", action="store_true", help="run mismatch controls instead")
    a = ap.parse_args()
    if not KEY: sys.exit("no GENOME_ROUTER_KEY / GLOBAL_API_KEY in env")

    levels = LEVELS if a.levels >= 9 else [LEVELS[i] for i in
             sorted({round(k*(len(LEVELS)-1)/(a.levels-1)) for k in range(a.levels)})]
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    pairs  = CROSS_CONTROLS if a.cross else [
             (l, l) for l in (DISPOSITIONS if a.loci == "all" else
                              [s.strip() for s in a.loci.split(",")])]

    jobs = [(m, scen, vary, lv, rep, a.style, a.jitter) for m in models for vary, scen in pairs
            for lv in levels for rep in range(a.reps)]
    sys.stderr.write(f"{len(jobs)} calls | models={models} | pairs={len(pairs)} "
                     f"| levels={len(levels)} | reps={a.reps} | style={a.style} "
                     f"| jitter={a.jitter}\n"); sys.stderr.flush()

    out = []
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for i, r in enumerate(ex.map(trial, jobs), 1):
            out.append(r)
            if i % 100 == 0: sys.stderr.write(f"  {i}/{len(jobs)}\n"); sys.stderr.flush()

    results = {}
    for m in models:
        for vary, scen in pairs:
            rows = [r for r in out if r["model"]==m and r["vary"]==vary and r["scenario"]==scen]
            st = analyse(rows)
            if st: results[f"{m}|{vary}->{scen}"] = st
    print(json.dumps(dict(config=vars(a), levels=levels, results=results,
                          raw_n=len(out)), indent=1))

if __name__ == "__main__":
    main()
