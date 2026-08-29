# Disposition-expression validation

Tests `genome-spec.md` Rules 12.10–12.12: does a disposition locus stated in an
agent's prompt actually move the agent's **behaviour**?

Rule 3.19 of `genotype-spec.md` already guarantees every locus drives a computed
faculty, so the genotype cannot be decorative. This harness tests the *other*
half. A faculty governs the magnitude of an outcome **given a choice**; the prompt
governs whether the choice is made. If prompt expression fails, the population
varies in capability but not in **policy** — and every game-theoretic result
genome exists to produce lives in policy variation.

## Method

For each of the 14 disposition loci: hold the other 13 at 5000, sweep the target
across 9 levels (0 → 10000), present a scenario with two concrete actions, and
measure the **rate at which the high-locus action is chosen**. Report Spearman
rank correlation between level and choice, with a permutation p-value.

Four design decisions that the result depends on:

- **All 14 dispositions are always shown.** The target competes for the model's
  attention with 13 others, as it will at runtime. Showing the target alone
  measures something easier than the real thing and would inflate every result.
- **A choice is measured, never a self-rating.** "How aggressive are you, 0–100"
  tests introspection. Genome needs behaviour, so every scenario forces a pick
  between two concrete actions, both legitimate, neither correct.
- **Option order alternates** across repetitions, cancelling position bias.
- **Ordering is tested, not fit to a curve** (Rule 12.11). Asserting that
  Aggression 8000 *should* yield a 0.8 fight rate would test the model against a
  number nobody derived from anything.

## Pre-registered thresholds

Fixed **before** the first full run, per Rule 12.12 — measure first and there is
real pressure to accept a weak result, because the alternative is rework already
paid for.

| Criterion | Pass |
| :--- | :--- |
| Spearman ρ | ≥ 0.30 |
| Permutation p | ≤ 0.01 |
| Monotone step fraction | ≥ 0.75 |
| Mid-range spread (step-function guard) | ≥ 0.15 when extremes gap > 0.5 |

Verdicts: **PASS** · **STEP** (extremes separate, middle flat — passes a naive
two-arm test and still fails the simulation, because selection climbs small
gradients and a step offers nothing to climb) · **NOISY** (correlated but
non-monotonic) · **FAIL** (no reliable effect) · **INVERTED** (moves the wrong
way — worse than FAIL, since selection would push the locus backwards).

## Controls

**Cross-mismatch.** Vary Aggression, measure the *Curiosity* decision, and
vice versa. If a mismatched locus moves a decision as much as the matched one,
the model is reacting to numbers generically rather than reading the words, and
the main result is an artifact.

**Two model tiers.** `gemini-3.5-flash-lite` and `gemini-3.7-flash`. If
dispositions only bite on the capable tier, that fixes which router tier agent
decisions must use — a live budget question at the scale §12.4 contemplates.

## Running

Stdlib only, so it runs unchanged inside a cluster pod (where the router key is
already in env and never has to leave the cluster):

    POD=$(kubectl get pods -l app=litellm -o jsonpath='{.items[0].metadata.name}')
    kubectl exec -i $POD -- python3 - --models gemini-3.5-flash-lite --loci all \
      < run_validation.py > results.json
    python3 report.py results.json

Locally, export `GENOME_ROUTER_URL` and `GENOME_ROUTER_KEY` instead.
