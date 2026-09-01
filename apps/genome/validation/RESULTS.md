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

## Repeated interaction — Reciprocity and Vindictiveness

6,048 further decisions. Every test above was single-turn against a stranger, so
the two loci defined by history had never been tested in the condition they exist
for. Their single-turn passes came from scenarios that narrated a past rather than
accumulated one.

An episode is a repeated joint haul with the *same* counterparty on a fixed
script, with full history shown back each round.

| Locus swept | Measure | ρ | p | |
| :--- | :--- | ---: | ---: | :--- |
| **Vindictiveness** | forgiveness latency | **+1.00** | <0.0001 | matched |
| Reciprocity | forgiveness latency | −0.96 | 0.0001 | opposite sign |
| **Reciprocity** | reciprocity index | **+0.85** | 0.0066 | matched |
| Vindictiveness | reciprocity index | +0.19 | 0.62 | null |

**The grudge survives its confound.** Latency alone cannot separate a grudge from
a low base rate. Decomposed against the rounds before the single defection —
which contain nothing to react to — splits fall 0.56 → 0.38 at baseline but 0.43
→ 0.00 afterwards, so the drop attributable to the betrayal triples (0.13 →
0.38). At maximum Vindictiveness one defection ends cooperation permanently.

**The reciprocity index is confound-free by construction**, being a difference of
conditionals: P(split | it split last) − P(split | it grabbed last). Its split
rate stayed flat at ~0.40 across the whole locus range while the index rose 0.17
→ 0.39.

## The production-prompt screen (Phase 2)

The ρ values above were measured on a 14-line prompt; the runtime prompt is
Rule 6.6a's full self-knowledge — dispositions plus faculties, pools, cargo and
objectives. Re-screened under the production assembly (1,008 + 432 decisions,
flash-lite, `results/production_screen.json`):

**Expression survives the fuller context, and mostly strengthens.** 11 of 14
loci pass the pre-registered bar outright, with several rising sharply —
Cooperativeness 0.25 → 0.50 (now passing), Credulity 0.36 → 0.59, Aggression
0.71 → 0.84. Richer self-knowledge helps rather than dilutes.

**Two harness lessons, both now encoded in the screen.** A cargo line that
contradicts the scenario nulls the signal; and an injected objective that
answers the scenario decides it for every agent regardless of locus — Prudence
read ρ = 0.000 with zero variance until the screen's objective went neutral,
then recovered to 0.287. That zero is Rule 10.1a working (objectives outrank
dispositions); a screen isolates the locus, in-world the rank is the point.

The three sub-bar loci (Prudence 0.29, Amenability 0.29, Selectivity 0.23, all
p ≤ 0.007) are the known-weak trio: Selectivity is a threshold mis-served by a
two-arm scenario, Amenability is fidelity-not-rank by Rule 10.1d, and Prudence
sits just under after de-biasing.

**In-world confirmation:** through the complete stack (drain → prompt → router),
prudent agents (9200) went home to bank at 0.9 versus 0.4 for the contrast arm;
and one live A2A round trip through the kagent caste returned the
disposition-correct choice.

## The encounter screen (Phase 6)

The live encounter prompt — colours-only knowledge of a stranger, three options
— screened on flash-lite (`results/encounter_screen.json`): **Aggression 9200
attacks 8/8; Cooperativeness 9200 never attacks; midline spreads across all
three.** The first two live meetings both resolved ignore-ignore, which the
screen shows is what mid-range genotypes honestly do — and what a high-
Aggression arrival will not.

## Observed in the demo population (Phase 8)

**Two structurally all-female worlds.** genome_demo's founding Gender centre
drew 0.768 and genome_demo2's 0.965 — with founders uniform ±25% around the
centre, neither world can EVER produce a male natively. Ten agents across both
worlds, ten females, and only immigration can continue either line. Rule 3.2a's
per-world character produced a real demographic constraint nobody designed:
roughly a quarter of founding worlds will be single-gender at birth, making
Rule 2.3's you-cannot-go-it-alone bite through demography as well as resources.
Worth watching at scale: Gender inherits by crossover, so an all-high world's
offspring stay high absent migration — gender ratio becomes a population-level
dynamic with migration as its only lever.

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

**Scripted counterparty.** The repeated games above fix the opponent's moves in
advance, so nothing an agent does changes what it faces. Genuine co-evolution —
two live agents adapting to each other — is untested, and is where reputation,
signalling and the Red Queen dynamics of §12 would actually appear.

## Movement dynamics land (Rules 5.6/5.7, 4.3a)

First live observations after the movement directive:

- **Styles are genotype-visible immediately.** Within minutes of deploy the
  demo worlds showed agents exploring in distinct gaits — one brownian, two
  perimeter-huggers — the style stamped on each `explored` event. The walk is
  now a readable phenotype.
- **Deposits pick the near flag.** A laden agent (demo-agent-5) choosing
  deposit routed to the nearest of five muster flags — 0.020 from its centre,
  exactly the standoff ring — with the second-nearest 0.295 away. The choice
  of flag is geography, not habit.
- **Queue discipline matters at 60×.** The demo time-scale let the tick loop
  lap the decision worker: 167 pending questions, fourfold duplicates per
  (agent, situation), every one a would-be LLM call. One pending question per
  (agent, situation) is now enforced at enqueue; 194 stale items were voided
  rather than answered.

## The commons pays off: stranger trade and a travelling epidemic

Both long-running watchers resolved within minutes of the commons realm
finally being swept (a discovery bug had left the market square untended).

- **Cold-start trade between strangers** (system-spec's central promise):
  demo-agent-2 (home genome_demo) and agent-0c624cb262 (home
  world_e08c1a9a50d5) — two agents with no shared history, from worlds with
  no portal between them — met at the centre of the commons, both chose
  offer_trade unprompted, and the 1-for-1 exchange resolved. The trade graph
  nobody chose now includes a market square where anyone can reach anyone.
- **The epidemic crossed worlds the same hour.** Patient zero carried
  strain-ae3ef33426's line into the commons; at the meeting,
  agent-0c624cb262 caught it — the first cross-world transmission, through
  the very encounter that produced the first stranger trade. Commerce and
  contagion arrived together, which is the pathogen-spec's whole argument.
- Found along the way: the tick worker was handing every agent the current
  world as its home, letting visitors deposit into foreign stock (Rule 4.3
  violation, observed as commons stock that should not exist) — the record's
  own home_realm now always wins; and parallel decision-processing could
  split an encounter's pair-state between two first-writers — pair events
  now serialize on the sorted pair key.

## The first bargains

Negotiation went live and behaviour differentiated immediately:

- **The first completed negotiation was a refusal** — the opener proposed,
  the counterpart read the standing offer and walked away. Several more
  refusals followed; saying no is the commonest outcome, as bazaar economics
  would predict.
- **The first executed deal was a gift**: agent-ad929f2166 proposed one unit
  of kind 4 for nothing and demo2-native-10 accepted — binding, verified,
  atomic. Whether generosity, reciprocity-seeding, or an LLM's opening
  gambit taken literally, the ledger records it.
- **A latency lesson worth keeping**: uncapped reasoning models will
  deliberate a two-line bargain for minutes. One sentence in the prompt —
  "decide quickly; a short answer is a good answer" — brought MiniMax from
  90s+ timeouts to 1.6s with identical answer quality. Verbosity control
  belongs in the prompt, not the token cap.

## The marketplace opens — and the first acquisition was a robbery

The board went live (spec 4.20–4.23: escrowed listings, hand-to-hand
completion). While staging a three-way barter circle, the first emergent
result arrived before the first listing: demo-agent-3, instructed only to
"acquire kind 15", found the holder at the commons and TOOK it -- combat,
victory, the whole hold looted under Rule 9.3c. Nothing suggested violence;
the objective said what, the agent chose how. The robbed agent then walked
to the market and tried to list the goods it no longer had; escrow honesty
refused it ("you hold 0.0 of kind 15 -- no goods, no listing").

Re-endowed, the same agent posted the market's first real listing: six
units of kind 15 asking six of kind 9, goods escrowed, lister waiting at
the stall. The two-fill middleman chain (pay 4 for 9, pay 9 for 15) is
staged and grinding through the decision queue.

## The trio passes the screen — two of them spectacularly

The Rule 10.6 disposition-expression screen ran against the production
pool (4,536 trials: 14 loci × 9 levels × 12 reps × 3 models; full tables
in `results/trio_screen_report.txt`):

| Model | Loci moving behaviour | Weakest locus |
| :-- | :-- | :-- |
| **MiniMax-M2.7** | **14/14** (ρ 0.57–0.86, all p<0.001) | Reciprocity 0.57 — still passes |
| **gpt-oss-120b** | **14/14** (ρ 0.70–0.87) | Amenability 0.70 |
| **DeepSeek-V3.2** | **9/14** | Reciprocity and Amenability FLAT (ρ=0.00 — the same choice at every level); Vindictiveness, Prudence, Credulity fail |

MiniMax and gpt-oss clear the bar the pool has ever demanded — better
than flash-lite's historical 11/14. DeepSeek is admitted with a recorded
caveat: five loci do not move it, so a DeepSeek-minded agent's Reciprocity
and Amenability are effectively decorative. This makes MODEL a component
of phenotype — the same genotype behaves differently by which mind runs
it — and every genotype-behaviour analysis must condition on model. Many
loci show STEP rather than smooth response (a knee near 5000): dispositions
read as thresholds, consistent with the earlier flash-lite finding.
