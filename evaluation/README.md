# Evaluation

How we test — not assert — the two claims agents.london rests on. This directory
holds the harnesses, the goal sets, and the recorded results, version-controlled
so any run is reproducible and any number on the public
[evaluation page](../docs/evaluation.html) can be traced to the experiment that
produced it.

The full programme (every claim, its experiment, the metric borrowed from the
literature) is written up at **<https://crajah.github.io/agents.london/evaluation.html>**.
This directory is where those experiments actually run.

## What "prove" means here

A live LLM-agent simulation can't be proven like a theorem. The target is
**mechanism sufficiency under stated conditions** — showing an outcome *grows*
from the agents' own decisions, reported as distributions over many runs against
an explicit baseline, with prompt- and model-version perturbation, not just RNG
seeds. Results are stated as what they measure, never more.

## Harnesses

| File | Claim | What it does |
|------|-------|--------------|
| `heldout_composition.py` | Civilization **C1** — composition creates capability no founder has alone | Runs 20 goals, each needing ≥2 distinct capabilities, through the live composition engine; records whether each decomposed into a pipeline, completed end-to-end, and created an agent on the fly; optionally scores each completed deliverable with a judge panel. |

Planned next (see the evaluation page): the genome mechanism-ablation (is the
cooperation emergent?), the compute-matched single-vs-pipeline test (C2), and the
deadline phase-transition sweep.

## Running it

```bash
# completion only (no key needed — hits the public composition API)
python3 evaluation/heldout_composition.py

# with the judge panel (needs the model-router key)
MASTER=$(kubectl get secret litellm-api-keys -o jsonpath='{.data.GLOBAL_API_KEY}' | base64 -d) \
  python3 evaluation/heldout_composition.py
```

Environment overrides: `EVAL_BASE`, `EVAL_ORG`, `EVAL_PROJECT`, `JUDGE_MODELS`.
Each run writes `results/<date>-heldout-composition-judged.json` incrementally.

## Metric definitions

- **decomposed** — the goal became a pipeline of ≥2 stages (not answered directly).
- **completed** — the pipeline ran end to end and returned a real answer. This is
  **completion, not human-verified correctness.**
- **used on-the-fly** — the run materialised a new specialist for a stage no
  founder covered.
- **panel quality (1–5)** — mean of relevance / completeness / soundness, scored
  by a panel (`MiniMax-M2.7`, `gemma-4-31B-it`, `gpt-oss-120b`) drawn from a
  **different model family than the composer** (`gemini-3.6-flash`), so nothing
  grades its own work. Position/self-preference bias is the reason the judge
  family is held distinct from the composer.
- **inter-judge stdev** — spread across the three judges per run; lower means the
  judges agree.

## Results

`results/` (newest first):

- **`2026-09-10-heldout-composition-judged.json`** — gemini-3.6 composer, judged.
  **90% decomposed · 70% completed · panel quality 4.17/5** (12 judged, inter-judge
  σ 0.22).
- **`2026-09-10-heldout-composition-baseline.json`** — the earlier run on the
  MiniMax planner (completion only): 80% decomposed, 45% completed. Kept as the
  before/after that motivated moving the composer to gemini-3.6.

### Honest bounds on the headline result

- Quality is **not uniform** — the lowest-scored deliverable was 1.67/5.
- One goal still **halted at a stage**; depth reliability improved but isn't perfect.
- "Completed + panel-judged" is **not human-verified correctness**; a human
  spot-check on a calibration slice is the next step before any stronger claim.
- 20 goals is a first pass, not a large sample — treat the percentages as
  directional and re-run for confidence intervals.

## Why this lives in the repo, not in scratch

An evaluation you can't reproduce can't be believed. Harness, goal set, and raw
results are committed together so the claim, the method, and the number stay
attached to each other. Pushes here are exempt from the deploy pipeline
(`evaluation/**` in the workflow's `paths-ignore`), so running an eval never
rebuilds the platform.
