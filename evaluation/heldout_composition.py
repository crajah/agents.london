#!/usr/bin/env python3
"""Held-out composition evaluation for civilization.

The central claim (evaluation plan, C1): from a small founding set of agents, a
goal is met by COMPOSING a pipeline — none of the founders solves the whole task
alone. This harness tests that directly.

Each goal below is engineered to require >= 2 distinct capabilities (source +
compare + recommend; analyse + benchmark + memo), so success can only come from a
composed pipeline, and often from an agent CREATED on the fly for a stage no
founder covers.

It runs every goal through the live composition engine (/api/playground/stream),
records the pipeline structure and outcome, and — when a model-router key is
available (env MASTER) — scores each completed deliverable with a panel of judges
drawn from a DIFFERENT model family than the composer, so nothing grades its own
work.

What it measures, honestly:
  * decomposed        — the goal became a pipeline of >= 2 stages
  * completed         — the pipeline ran end to end and returned a real answer
                        (this is COMPLETION, not human-verified correctness)
  * used_onthefly     — the run materialised a new specialist for a stage
  * panel quality     — judges' mean of relevance / completeness / soundness (1-5)

Run:
    python3 evaluation/heldout_composition.py                 # completion only
    MASTER=$(kubectl get secret litellm-api-keys \
        -o jsonpath='{.data.GLOBAL_API_KEY}' | base64 -d) \
        python3 evaluation/heldout_composition.py             # + judge panel

Results are written to evaluation/results/<date>-heldout-composition-judged.json.
See evaluation/README.md for the metric definitions and the published result.
"""
import json, os, re, statistics as st, urllib.request
from datetime import date

ORG = os.getenv("EVAL_ORG", "org_default")
PROJ = os.getenv("EVAL_PROJECT", "proj_alpha_civilization")
BASE = os.getenv("EVAL_BASE", "https://agents.london")
STREAM = f"{BASE}/api/playground/stream"
ROUTER = f"{BASE}/proxy/v1/chat/completions"
MASTER = os.getenv("MASTER")  # model-router key; judging runs only if present
JUDGES = [m.strip() for m in
          os.getenv("JUDGE_MODELS", "MiniMax-M2.7,gemma-4-31B-it,gpt-oss-120b").split(",")
          if m.strip()]
OUT = os.path.join(os.path.dirname(__file__), "results",
                   f"{date.today().isoformat()}-heldout-composition-judged.json")

# Goals: each needs >= 2 distinct capabilities; none is a single-founder task.
GOALS = [
    "Source three suppliers of industrial lithium carbonate, compare their pricing and lead times, and draft a one-page sourcing recommendation.",
    "Assess a mid-market SaaS company's unit economics, benchmark its margins against sector norms, and write a short investment memo.",
    "Evaluate two cloud vendors for a data-residency-constrained workload, weigh the compliance risk, and produce a decision brief.",
    "Research the competitive landscape for battery recycling, identify the top three risks to a new entrant, and outline a go-to-market plan.",
    "Analyze a supplier's ESG disclosure, reconcile it against our procurement policy, and draft a compliance summary.",
    "Compare three logistics providers on cost and reliability, model the total landed cost, and recommend one with a rationale.",
    "Review a counterparty's last two annual reports for liquidity risk, benchmark their credit profile, and draft negotiation talking points.",
    "Survey the market for enterprise vector databases, score them on our five criteria, and write a shortlisting memo.",
    "Investigate a regional shortage in a key component, estimate its duration, and propose a dual-sourcing mitigation.",
    "Assess the tariff exposure of a bill of materials, quantify the cost impact, and draft a re-sourcing proposal.",
    "Research renewable-energy procurement options for a data centre, compare PPA vs on-site, and produce a recommendation.",
    "Analyze customer churn drivers from described metrics, prioritise the top three, and draft a retention plan.",
    "Compare three payment processors on fees and coverage, model annual cost at our volume, and recommend one.",
    "Evaluate a potential acquisition target's product overlap, assess integration risk, and write a preliminary thesis.",
    "Research packaging-material alternatives for cost and recyclability, weigh the trade-offs, and draft a switch proposal.",
    "Assess a vendor's SOC 2 report against our security requirements, flag the gaps, and draft a remediation ask.",
    "Compare two freight routes on cost, transit time and carbon, and recommend one with a short justification.",
    "Analyze a pricing experiment's described results, judge significance, and recommend a rollout decision.",
    "Research the regulatory outlook for a fintech product in two markets, compare the barriers, and draft an entry plan.",
    "Evaluate three contract-manufacturing partners on capability and risk, and produce a selection memo.",
]

RUBRIC = ('You grade whether a deliverable answers a business goal. Score each 1-5 '
          '(5 best): relevance (addresses the goal), completeness (covers the goal\'s '
          'parts), soundness (coherent, specific, no obvious fabrication). '
          'Return ONLY JSON: {"relevance":n,"completeness":n,"soundness":n}.')


def run(goal):
    body = json.dumps({"org_id": ORG, "project_id": PROJ, "prompt": goal}).encode()
    rq = urllib.request.Request(STREAM, data=body,
                                headers={"Content-Type": "application/json"}, method="POST")
    rec = {"goal": goal, "stages": 0, "matched": 0, "materialized": 0,
           "failed": None, "answer": "", "error": None}
    cur = None
    try:
        with urllib.request.urlopen(rq, timeout=240) as r:
            for raw in r:
                ln = raw.decode("utf-8", "replace").rstrip("\n")
                if ln.startswith("event:"):
                    cur = ln.split(":", 1)[1].strip()
                elif ln.startswith("data:") and cur:
                    try:
                        j = json.loads(ln.split(":", 1)[1].strip())
                    except Exception:
                        j = {}
                    if cur == "decomposed":
                        rec["stages"] = j.get("count") or len(j.get("stages", []))
                    elif cur == "matched":
                        rec["matched"] += 1
                    elif cur == "materialized":
                        rec["materialized"] += 1
                    elif cur == "complete":
                        rec["failed"] = bool(j.get("failed"))
                        rec["answer"] = str(j.get("answer") or "")
                        break
                    elif cur == "error":
                        rec["error"] = str(j.get("detail") or j)[:100]
                        break
    except Exception as e:
        rec["error"] = type(e).__name__
    return rec


def judge(goal, answer, model):
    body = json.dumps({"model": model, "temperature": 0.0, "max_tokens": 400,
                       "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": RUBRIC},
                                    {"role": "user",
                                     "content": f"GOAL:\n{goal}\n\nDELIVERABLE:\n{answer[:6000]}"}]}).encode()
    rq = urllib.request.Request(ROUTER, data=body, method="POST",
                                headers={"Content-Type": "application/json",
                                         "Authorization": f"Bearer {MASTER}"})
    try:
        with urllib.request.urlopen(rq, timeout=90) as r:
            txt = json.load(r)["choices"][0]["message"]["content"]
        txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
        o = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
        vals = [float(o.get(k, 0)) for k in ("relevance", "completeness", "soundness")]
        return sum(vals) / 3.0
    except Exception:
        return None


def main():
    results = []
    for i, g in enumerate(GOALS):
        r = run(g)
        if MASTER and r["failed"] is False and len(r["answer"]) > 50:
            scores = {}
            for m in JUDGES:
                s = judge(g, r["answer"], m)
                if s is not None:
                    scores[m] = round(s, 2)
            r["judge_scores"] = scores
            r["panel_mean"] = round(sum(scores.values()) / len(scores), 2) if scores else None
        r["answer"] = r["answer"][:400]
        results.append(r)
        print(f"[{i+1}/{len(GOALS)}] stages={r['stages']} made={r['materialized']} "
              f"failed={r['failed']} panel={r.get('panel_mean')} err={r['error']}", flush=True)
        json.dump({"results": results}, open(OUT, "w"), indent=1)

    n = len(results)
    composed = [r for r in results if (r["stages"] or 0) >= 2]
    done = [r for r in composed if r["failed"] is False and len(r["answer"]) > 50]
    made = [r for r in composed if r["materialized"] > 0]
    judged = [r for r in done if r.get("panel_mean") is not None]
    print("\n===== HELD-OUT COMPOSITION =====")
    print(f"goals: {n}")
    print(f"decomposed (>=2 stages): {len(composed)} ({round(100*len(composed)/n)}%)")
    print(f"completed end-to-end: {len(done)} ({round(100*len(done)/n)}%)")
    print(f"used on-the-fly agent: {len(made)}")
    summary = {"n": n, "composed": len(composed), "completed": len(done),
               "used_onthefly": len(made)}
    if judged:
        means = [r["panel_mean"] for r in judged]
        spreads = [st.pstdev(list(r["judge_scores"].values()))
                   for r in judged if len(r.get("judge_scores", {})) > 1]
        print(f"judged runs: {len(judged)} | panel quality mean={round(st.mean(means),2)} "
              f"(min {min(means)}, max {max(means)})")
        if spreads:
            print(f"inter-judge stdev: {round(st.mean(spreads),2)} (lower = more agreement)")
        summary.update({"judged": len(judged), "panel_mean": round(st.mean(means), 2)})
    json.dump({"results": results, "summary": summary}, open(OUT, "w"), indent=1)
    print("written:", OUT)


if __name__ == "__main__":
    main()
