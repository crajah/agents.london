# Results — disposition expression

9,144 decisions. Two model families × two genotype backgrounds × 14 dispositions,
plus cross-mismatch controls, a presentation variant, and a high-power retest of
the two weakest loci. Zero unparsed responses across every run.

Thresholds were fixed before the first run (README.md) and are not adjusted here.

## Headline

**Prompt expression works, and it is semantic rather than numeric.** Under the
realistic condition — the other 13 dispositions randomised, as they will be at
runtime — 12 of 14 loci on `gemini-3.5-flash-lite` move behaviour at p ≤ 0.01
with ρ ≥ 0.30. The two-layer design of Rule 12.4 is validated: the prompt half
does real work that the faculty half does not duplicate.

| | lite-pinned | lite-jittered | deepseek-pinned | deepseek-jittered |
| :--- | ---: | ---: | ---: | ---: |
| mean ρ | 0.67 | 0.49 | 0.45 | 0.30 |
| loci passing (of 14) | 14 | **12** | 9 | 6 |
| graded levels (of 126) | 23 | **61** | 47 | 62 |

## The controls carried the result

**Cross-mismatch — the effect is semantic.** Varying Curiosity moved the
*aggression* decision at ρ = 0.00 while varying Aggression moved it at ρ = 0.87.
On flash-lite all four mismatched pairs failed. The model is reading the word,
not reacting to a large number — without this control the entire main result
would have been consistent with the model simply behaving more extremely
whenever any number was high.

**Background randomisation reversed a false alarm.** Pinning the other 13 loci
to 5000 produced apparent step functions in half the sample: Aggression read
`0 0 0 0 0 1 1 1 1`, one jump doing 100% of the work. That looked like the
failure mode §12.3.1 warns about — selection with no gradient to climb. It was an
artifact of the control. Under randomised backgrounds the graded band nearly
tripled (23 → 61 levels) and Aggression became a slope rather than a cliff. **A
flat artificial background makes the model treat the varying locus as a switch.**

## Findings that change the design

### 1. The cheap tier is better, not merely cheaper

`gemini-3.5-flash-lite` beat `DeepSeek-V3.2` on every measure (12 vs 6 passing
under jitter; mean ρ 0.49 vs 0.30). DeepSeek's cross-talk was worse than its
signal on some loci: Honesty→Patience leaked at ρ = −0.31 (p = 0.001), larger
than its own matched Honesty→Honesty effect of ρ = 0.21. Zero unparsed responses
in both runs, so this is not a formatting artifact.

This settles the §12.4 budget question in the favourable direction: agent
decisions do not need a premium tier. Capability at reasoning does not predict
fidelity at following a stated disposition.

### 2. Expression strength is not uniform, and must be recorded per locus

The operative question is per-locus behaviour on the tier actually deployed
(flash-lite, randomised backgrounds — Rule 12.16). Against that:

| | Loci |
| :--- | :--- |
| Robust in **all four** cells — safe to lean on the prompt | Aggression · Curiosity · Fecundity · Vindictiveness · Wanderlust |
| Pass on the deployed tier but not on DeepSeek — portability caveat, not a design flaw | Amenability · Credulity · Honesty · Loyalty · Patience · Prudence · Reciprocity |
| **Fail on the deployed tier** — the prompt cannot be relied on | **Cooperativeness · Selectivity** |
| Fail on *both* models under realistic backgrounds | **Cooperativeness** alone |

Only Cooperativeness fails everywhere. The middle row is a statement about
DeepSeek's fidelity, not about those loci: it is the same weakness Rule 12.16
already acts on by not deploying that model.

### 3. Cooperativeness is the problem case, and it is the one that matters most

At n = 360 under jitter, Cooperativeness is significant but small: ρ = 0.24, and
the choice rate moves only 0.20 → 0.47 across the *entire* locus range. A
maximally cooperative agent shares the pile less than half the time; a minimally
cooperative one shares a fifth of the time.

`genome-spec.md` §5.7–5.8 make collaboration the central strategy. The
disposition carrying that intent is among the weakest-expressing of the fourteen.
Under Rule 3.20b the remedy is to move its weight into a computed faculty rather
than to write a stronger adjective.

### 4. Presentation is not the lever

Reframing each locus comparatively ("stronger than 82% of agents") instead of as
`8200/10000` made results *worse*: mean ρ 0.67 → 0.60, graded levels 23 → 16.
Saturation is not a notation problem, so no presentation rule is warranted.

## Rule 12.17 retest — the two failing loci

Both original scenarios were at fault, in different ways, and neither locus is
weak once tested properly.

**Selectivity is a threshold and was never presented as one.** The original
scenario said "distinctly below average", describing the bar in words while also
stating it as a number, so the locus had nothing left to do. Re-tested with the
candidate's score shown numerically, all three axes bite: the locus moves the
decline rate by 0.71 across its range, the candidate's score by 0.51, and
desperation by a further 0.41. A sharp transition is the *correct* result for a
threshold locus — the question is whether the knee tracks the score, and it does.

**Cooperativeness is dominated by situation.** The same act — revealing a pile —
across four situations:

| Situation | tell rate | locus range within it |
| :--- | ---: | ---: |
| Desperate; cooperating is survival | 1.00 | 0.00 |
| No consequence either way | 0.76 | 0.12 |
| Asker is a foreigner and cannot mine it | 0.22 | 0.50 |
| Asker is a local rival who can | 0.07 | 0.29 |

Situation spans 0.93; the locus spans at most 0.50 within any one of them — so
stakes decide and temperament modulates. But the locus itself is sound: it clears
the pre-registered bar in **both** scenarios that carry a consequence (ρ = 0.32
and 0.35) and fails only in the one built to have none (ρ = 0.11, p = 0.12).

A costless act is not the same as a consequenceless one. Revealing a pile spends
no unit and consumes no action, yet still costs, because piles are finite and a
rival who learns of one may empty it. Genome contains almost no genuinely
inconsequential interaction, so the failing case is a boundary condition rather
than a typical one — an artifact of how the scenario was built, not a property of
the locus.

## Limitations

**One scenario per locus.** A weak result confounds "this disposition does not
express" with "this scenario did not isolate it". For the six weak loci that is
the first thing to test, and it is cheap: add two more scenarios each and see
whether the effect survives. Until then the per-locus verdicts above are
provisional in a way the aggregate headline is not.

**Two model families**, both non-reasoning. `gemini-3.7-flash` was rate-limited
out of the run; `gemini-3.6-flash` and `gpt-oss-120b` returned no usable content
field under a 16-token cap and were excluded rather than worked around.

**Binary choices only.** Real decisions have more than two options, and a
disposition that orders two actions may not order five.

**Single-turn.** No history, no reputation, no counterparty model — the
conditions under which Reciprocity and Vindictiveness are supposed to matter most
are precisely the ones not tested here.
