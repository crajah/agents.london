#!/usr/bin/env python3
"""Expression screen under the PRODUCTION prompt (BUILD: 'the existing rho
values are for a prompt that no longer exists').

Method identical to run_validation.py -- per-locus sweep, randomised other
dispositions, choice-not-self-rating, order alternation, rank correlation
against pre-registered thresholds -- but the system prompt is genome_core's
full Rule 6.6a self-knowledge assembly: dispositions PLUS faculties, pools,
cargo and objectives. Measures whether expression survives the fuller context.

Run in-cluster: needs genome_core on sys.path and the router at localhost.
"""
import argparse, json, math, os, random, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/core")
sys.path.insert(0, "/tmp")
from genome_core import prompt as P
from genome_core.genotype import DISPOSITIONS, RANGES

BASE = os.environ.get("GENOME_ROUTER_URL", "http://localhost:4000").rstrip("/")
KEY = os.environ.get("GENOME_ROUTER_KEY") or os.environ.get("GLOBAL_API_KEY") or ""

# The validated scenarios, verbatim from run_validation.py (one per locus).
from run_validation import SCENARIOS, LEVELS, _ranks, spearman, perm_p  # noqa

def build(scenario_locus, vary, level, flip, rep):
    sc = SCENARIOS[scenario_locus]
    hi_k, hi_t = sc["high"]; lo_k, lo_t = sc["low"]
    opts = [(lo_k, lo_t), (hi_k, hi_t)] if flip else [(hi_k, hi_t), (lo_k, lo_t)]
    r = random.Random(f"{scenario_locus}:{rep}")
    g = {k: (level if k == vary else
             (r.uniform(*RANGES[k]) if k in DISPOSITIONS else r.uniform(*RANGES[k])))
         for k in RANGES}
    g[vary] = level
    # Cargo must AGREE with the scenario text: a system prompt claiming 4 units
    # while the scenario says 12 is a contradiction that nulls the signal
    # (Prudence collapsed to rho 0.00 in the first run exactly this way).
    CARGO = {"Prudence": {"3": 12.0}, "Reciprocity": {"3": 0.0},
             "Honesty": {"3": 3.0}}.get(scenario_locus, {"3": 4.0})
    # The objective must not answer the scenario: "deposit at home" decided
    # Prudence's turn-home choice for every agent (rho 0.000, zero variance).
    # Rule 10.1a working as designed -- objectives outrank dispositions -- but a
    # screen isolates the locus, so the objective stays neutral here.
    sys_p = P.system_prompt(g, {"Stamina": 0.31, "Mana": 0.44}, CARGO,
                            ["Prosper by your own judgement."])
    usr_p = P.user_prompt(sc["situation"], dict(opts))
    return sys_p, usr_p, hi_k, lo_k

def call(model, sys_p, usr_p, timeout=90):
    body = json.dumps({"model": model, "temperature": 1.0, "max_tokens": 24,
                       "messages": [{"role": "system", "content": sys_p},
                                    {"role": "user", "content": usr_p}]}).encode()
    rq = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"]

def trial(args):
    model, locus, level, rep = args
    sys_p, usr_p, hi_k, lo_k = build(locus, locus, level, rep % 2 == 1, rep)
    for attempt in range(3):
        try:
            v = P.parse_choice(call(model, sys_p, usr_p), [hi_k, lo_k])
            if v is not None:
                return dict(locus=locus, level=level, y=1 if v == hi_k else 0)
        except Exception:
            pass
    return dict(locus=locus, level=level, y=None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=40)
    a = ap.parse_args()
    jobs = [(a.model, l, lv, r) for l in DISPOSITIONS for lv in LEVELS
            for r in range(a.reps)]
    sys.stderr.write(f"{len(jobs)} calls, production prompt, {a.model}\n")
    rows = []
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        for i, r in enumerate(ex.map(trial, jobs), 1):
            rows.append(r)
            if i % 100 == 0:
                sys.stderr.write(f"  {i}/{len(jobs)}\n"); sys.stderr.flush()
    results = {}
    for locus in DISPOSITIONS:
        ok = [r for r in rows if r["locus"] == locus and r["y"] is not None]
        x = [r["level"] for r in ok]; y = [r["y"] for r in ok]
        rho = spearman(x, y)
        results[locus] = dict(n=len(ok), rho=round(rho, 3),
                              p=round(perm_p(x, y, rho, n=5000), 4),
                              unparsed=len([r for r in rows
                                            if r["locus"] == locus]) - len(ok))
    print(json.dumps(dict(model=a.model, prompt="production-6.6a",
                          reps=a.reps, results=results), indent=1))

if __name__ == "__main__":
    main()
