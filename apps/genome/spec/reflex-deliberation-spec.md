# Genome: Reflex / Deliberation Split — Design Spec (DRAFT, not for build yet)

## 1. Problem

The world reads as **sequential**, not parallel. Cause: every agent action is gated on
one serialized, rate-limited resource — LLM cognition (~5 decisions/sec shared across
~700 agents). Each agent "thinks" ~once per 2 minutes; the rest are frozen awaiting a
turn. It's a single shared brain everyone queues behind. An ant colony is parallel
because each ant runs a **cheap local rule continuously and independently** — no central
brain, no queue.

**Goal:** every agent is *always* doing something (parallel, alive), while the LLM is
spent sparsely on what actually needs judgement. This is also the only shape that
survives the "millions of agents" ambition — you can run a reflex rule for millions;
you can never LLM-decide continuously for millions.

## 2. Core model

Two tiers, and the key insight that de-risks it:

> The **reflex layer is a deterministic POLICY over the option set the engine already
> generates** (`_decide_here` already produces `mine_here`, `travel_to_pile`,
> `go_home_deposit`, `head_home`, `explore_frontier`, …). Today the LLM picks among
> those options. Reflex picks among the *same* options with a deterministic policy
> parameterised by the agent's current GOAL. So it is not a new behaviour engine — it
> reuses all option-generation, rules (home-only mining, mineable_kinds, cargo ceiling,
> favours, consumption), and perception the engine already enforces.

- **Reflex** (`goal_policy(options, goal, ctx) → choice`): cheap, deterministic, runs
  every tick for every present agent. No LLM, no inference cost, no queue. Executes the
  agent's current goal step by step. This is what makes the world move continuously.
- **Deliberation** (LLM, sparse, triggered): answers *"what should I be trying to do,
  and how do I handle this social moment"* — sets/updates the agent's GOAL and resolves
  interactions. Fire-and-forget: reflex never waits for it.

Mental model: **LLM sets intent; reflex executes intent.** System 2 on salience,
System 1 continuously.

## 3. The Goal (structured intent, stored on the agent)

```
goal = {
  kind:   "provision" | "seek_mate" | "trade" | "build" | "explore"
        | "survive" | "serve" | "reclaim_cache",
  params: { target_kind?, target_world?, target_site?, mate_criteria?, ... },
  set_by: "llm" | "default",
  set_at: epoch,
  review_at: epoch,          # slow strategic heartbeat; reflex re-triggers past this
}
```
Every agent ALWAYS has a goal (default `provision` at birth/regenerate). Persisted in
the agent payload; drives reflex; updated only by deliberation.

## 4. Reflex policy per goal (deterministic; reuses engine options)

Given the engine's option set + perception + goal, pick deterministically:

- **provision** (the home-economy loop, fully reflexive):
  at home pile of a wanted kind & room → `mine_here`; hold full-ish → `go_home_deposit`;
  idle & know a wanted pile → `travel_to_pile`; home stock low & cache exists →
  `head_home`/route to commons → `collect_cache`; nothing known → `explore_frontier`.
- **seek_mate**: move toward the commons / gather point / known complementary agents
  (the *proposal itself* is a social trigger → deliberation).
- **build**: haul owned kinds to the target site → `contribute_here`/`travel_to_site`;
  carry a completed work toward a portal if the goal is cross-world delivery.
- **explore**: `explore_frontier` / `survey_far`.
- **survive** (flood imminent): flee to a standing ark (`flee_to_ark`/`board_ark`) or a
  portal — instinctive, no LLM.
- **reclaim_cache / serve**: route to the commons larder / the requesting holder.

Reflex is a pure function: `(options, goal, ctx) → option`. If the policy is genuinely
ambiguous OR the goal is unsatisfiable (no progress possible), it raises a **stuck**
trigger → deliberation.

## 5. Trigger taxonomy — when the LLM fires (replaces polling)

Today `heal` POLLS: it schedules a decide for every idle agent every cycle — the source
of the ~449 `at_large` backlog. Replace polling with **salience**:

- **Social/interaction**: `encounter`, message/`word` received, `service_request`,
  `mating_proposal` → LLM (and see §6: batch the pair).
- **Goal boundary**: goal completed, goal *stuck* (reflex can't progress), or a
  resource threshold crossed (home stock low, hold full and no home route).
- **World stimulus**: flood enters the awareness window, an ark/shipyard becomes
  foundable, a construction opportunity the agent could join.
- **Strategic heartbeat**: `now > goal.review_at` (every few minutes) — so a peaceful
  forager still periodically re-strategises even if nothing happens to it.

Everything else → reflex, no LLM.

## 6. Batching

- **Single-agent, multi-step (yes):** deliberation returns a GOAL (optionally a short
  plan), not one action. One LLM call amortises over dozens of reflex ticks. This *is*
  the split — the LLM's output is intent, not a keystroke.
- **Pair/group interaction (yes):** an `encounter` deliberation takes BOTH agents'
  relevant state and returns the **joint outcome** in one call (trade? terms? breed?
  attack? ignore?), replacing the two-sided `encounter → encounter_answer` dance. Both
  genotypes/objectives presented symmetrically so neither is favoured; the outcome
  respects both. A market round can batch its participants similarly.
- **Unrelated-cohort batching (no):** batching agents that aren't interacting into one
  prompt homogenises them, bloats the prompt, and dissolves the independence that makes
  the economy emergent. Parallelism must come from *independence*, not a shared prompt.

## 7. Execution architecture (fits what exists)

- **Reflex runs in the tick-worker's per-agent pass** (alongside sweep, which is already
  O(n)): interpolate/perceive → `goal_policy` → write movement/mine/deposit directly.
  No decision-queue round-trip → agents update every tick → continuous motion.
- **Deliberation stays on the Redis decision queue** → decision-workers (non-blocking
  decider already shipped) → returns a goal / interaction outcome.
- **Reflex never blocks on the LLM**: while a deliberation is queued/in-flight the agent
  keeps executing its current goal (generalises today's `drift_route` "body wanders while
  the mind is queued"). The LLM result updates the goal when it lands.

## 8. Impact

- **Liveness:** all present agents move every tick → parallel, ant-colony feel; foraging
  trails and sparking encounters instead of a trickle.
- **Throughput:** LLM volume drops from "poll every idle agent" (~2180 pending) to
  "salient events only" (~encounters + sparse strategy) — an estimated 5–10× cut. The
  pool keeps up; the backlog stops being the frame-rate bottleneck.
- **Cost:** LLM calls are metered CU; reflex is free. Fewer calls = large CU/token
  savings — an economic win, not just performance.
- **Scale:** reflex is O(agents) cheap and parallel; LLM is sampled sparsely — the path
  to 1000s of worlds / millions of agents.
- **Determinism/replay:** reflex is deterministic (replayable); the LLM is sampled at
  triggers only.

## 9. Migration — independently deployable phases

- **A — Reflex for routine, flagged.** Add `goal_policy` for `provision` (mine/haul/
  deposit/forage). `heal` stops polling those situations; the tick-worker applies reflex
  directly. Measure LLM-volume drop + liveness. (Lowest risk; biggest immediate win.)
- **B — Event-triggered deliberation.** Replace `heal` polling with the §5 trigger set.
- **C — Pair-batched encounters.** One LLM call resolves an interaction (kills the
  encounter volume + the two-sided race).
- **D — Goal/plan output.** Deliberation returns structured goals; reflex covers all
  goal kinds.

Each phase is measurable and reversible via a flag; the current LLM-per-action behaviour
remains the fallback until each phase is proven.

## 10. Risks & mitigations

- **Reflex bots feel mechanical.** Personality must live in (a) genotype-driven goal
  diversity from deliberation and (b) the interactions themselves. Keep the strategic
  heartbeat frequent enough that goals evolve; foraging *being* mechanical is honest.
- **Reflex must encode the economy faithfully** (home-only mining, mineable_kinds,
  ceilings, favours, consumption) or the economy drifts. Mitigated by reusing the
  engine's own option-generation + rules rather than reimplementing.
- **Goal staleness.** Reflex detects "stuck / goal invalid" → re-trigger deliberation.
- **Pair-batch fairness.** Symmetric presentation of both agents; outcome must honour
  both genotypes (referee-style resolution, not one agent's viewpoint).
- **Owner-objective pursuit / brokerage preserved:** that's strategic → stays LLM
  goal-setting; reflex only executes the brokered plan.

## 11. User instructions & world chat — how they interplay with the agent

Both are **deliberation-tier only** — they change *intent* and *social conduct*, never
the reflex/movement layer. Chat is strategic; walking is mechanical. This keeps the
fast layer cheap while humans and the shared channel steer the slow layer.

### 11a. Two distinct channels
- **Owner → own agent (private instruction / objective).** A direct command. Rule
  10.1a/b: owner objectives OUTRANK the genotype floor. It becomes (or preempts) the
  agent's GOAL.
- **Owner → world (a world-chat *ask*).** A public need any *capable* agent competes to
  claim — the brokerage/task-market. This is cross-org and emergent: the owner states a
  need; whichever agent can serve it does. Distinct from a command to one's own agent.

### 11b. Intent priority hierarchy (what sets/overrides the GOAL)
1. **Owner instruction** (highest) — preempts the current goal immediately.
2. **Claimed world-ask / accepted interaction** — a commitment the agent took on.
3. **World stimulus opportunity** (an open ask, an encounter) — *weighed* against the
   current goal, not automatically preemptive.
4. **Genotype/default self-direction** (the floor — `default_objectives`).

The goal schema gains `source` + `priority`; a new owner instruction overrides a
self-set goal, but a passing world-chat line does **not** unless the agent chooses to
engage. This is exactly the Rule 10.1 ordering, expressed as goal precedence.

### 11c. Owner instructions must be RESPONSIVE (priority lane)
The owner is a human watching. An instruction is a **high-priority trigger** that
must jump the decision queue — it cannot wait behind ~1780 routine deliberations. So
owner-triggered deliberations get a priority lane (lowest ZSET score / a dedicated
`genome:decisions:priority` the consumer drains first). The reflex layer keeps the body
moving meanwhile; the owner's intent lands on the next (fast) deliberation and re-sets
the goal. Same for the agent's *reply back* to the owner — it's a deliberation output
and a stimulus to the human, so it must not starve.

### 11d. World chat needs a SALIENCE FILTER (or it re-creates polling)
A world-chat post must **not** trigger deliberation for every present agent — that is
the polling storm again, one message → N LLM calls. Filter which agents a post wakes:
- **ask** → only agents whose **capability/kinds** could plausibly serve it, present in
  the world, capped to a few candidates; "compete to claim" then caps it further —
  once claimed, the others' deliberations are moot and are skipped.
- **say / join** → sparser still: addressed agents, or a small sample weighted by
  sociability/relevance. Never the whole room.
So chat is a stimulus, but a *targeted* one. Un-targeted agents keep running reflex.

### 11e. Execution once intent is set
The owner goal or claimed ask becomes the agent's GOAL; **reflex executes the mechanical
parts** (route to the tool-holder, gather the needed kinds, travel to the counterpart),
and **deliberation handles the cognitive parts** (composing the guarded answer, the
negotiation terms). The **query-match guard on ask-answers stays in deliberation and
must not regress** (see [[genome-objective-pursuit]]). Chat + objectives are part of the
deliberation *context* (today's `heard` / `objectives`); reflex never reads them.

### 11f. Why this is consistent with the split
Humans and the shared channel act on the **slow, sparse** layer (goals, interactions,
replies) where judgement and identity live; the **fast, parallel** layer (foraging,
hauling, pathing) is untouched and keeps the world alive. Instructions and chat make
agents *purposeful and responsive* without re-serializing the world — provided owner
intent gets a priority lane and chat gets a salience filter.

## 12. Open questions for review

1. **Goal-setting cadence:** strategic heartbeat interval (2 min? 5 min?) — the main
   knob between "lively/costly" and "cheap/static."
2. **Encounter resolution shape:** does one LLM call act as a *referee* returning the
   joint outcome, or return each agent's stance which we then match deterministically?
3. **How much survival is reflex vs LLM:** flee/board reflexive (proposed); is
   ark *building* coordination worth an LLM goal, or a reflex "contribute if you carry
   what it needs"?
4. **Reflex tie-breaking:** when several options equally advance a goal, deterministic
   by genotype (style) or by cheapest/nearest? (Affects the "personality" of movement.)
5. **Do reflex actions still emit events** (for audit/replay) or write movement directly
   for speed? (Leaning: write directly, emit a lightweight audit row.)
6. **Owner-instruction priority lane:** a separate high-priority decision queue, or a
   score offset on the shared one? And does an owner instruction *replace* the current
   goal outright or layer on top (resume the old goal when done)?
7. **World-chat fan-out cap:** how many candidates does an *ask* wake (top-K by
   capability match? all present capable, relying on claim to cap?), and how sparse is
   *say/join* (addressed only, or a sociability-weighted sample)?
8. **Owner-objective lifecycle:** when is an owner goal considered *complete* (agent
   self-declares done → reverts to default? owner clears it? a deadline?) — so an agent
   isn't locked forever on a satisfied or impossible instruction.

## 13. Recommended resolutions

My recommendation for each (defaults are env-tunable; these are starting points, not
dogma):

1. **Strategic heartbeat → 120s, per-agent jittered ±30s, genotype-modulated.** The
   heartbeat is only the *fallback* — active agents re-plan on events (goal done,
   stimulus), so it rarely fires for them. Jitter avoids a synchronized thundering herd
   of deliberations; high-Curiosity/Wanderlust genotypes review sooner (shorter
   interval), placid ones later. 120s balances "goals evolve" against LLM cost.

2. **Encounter → one referee call that returns BOTH stances AND the resolved outcome.**
   One call (not two) resolves the interaction, killing the two-sided
   `encounter → encounter_answer` race. Present both agents' dispositions/objectives
   *symmetrically*; the model reports what each agent independently wants and then the
   matched result (a trade only if both would accept, breeding only if both consent).
   Efficiency of one call + fairness of independent stances.

3. **Ark → LLM sets the goal, reflex executes; flee/board is reflex.** The *choice* to
   converge on the ark (goal = `survive`/`build`) is strategic → LLM, triggered when the
   flood enters the window. Once set, reflex hauls owned kinds to the shipyard/ark site
   and contributes what it carries. Instinctive flee-to-ark / board when the water is
   imminent is pure reflex (survival needs no deliberation).

4. **Reflex tie-break → nearest/cheapest as the base, perturbed by genotype STYLE.**
   Efficient by default, but break ties with the existing `styles.pick_style`
   (swarm/brownian/levy/lawnmower/perimeter) seeded per (agent, moment). Deterministic,
   replayable, and it gives movement personality + avoids everyone beelining identically
   (which reads robotic and causes clumping). Personality in the *path*, not just the goal.

5. **Reflex actions → write movement directly; do NOT emit a per-step event.** Liveness
   needs per-tick movement writes; an event round-trip per reflex step would re-serialize
   the very thing we're parallelising. Keep `record_decision` for LLM deliberations only,
   plus a *sampled* reflex trace (log a reflex transition only when the goal-state
   changes, e.g. started-mining / began-haul / deposited — not every step) so the audit
   table doesn't bloat.

6. **Owner priority → score-offset on the shared queue (no second queue); goal LAYERS
   (push/pop).** Give an owner-instruction deliberation a score far in the past so the
   score-ordered Redis claim takes it first — a priority lane without a second consumer.
   An owner command *pushes* a goal onto a small per-agent stack; on completion/expiry
   the agent *pops* back to its prior self-directed goal, so a command interrupts but
   doesn't erase the agent's own line.

7. **World-chat fan-out → ask: top 3–5 by capability/kind match (present in that world),
   claim-capped; say/join: addressed + ≤2 sociability-sampled.** An *ask* wakes only the
   few most-relevant present agents; "compete-to-claim" then caps to the winner (others
   skip once claimed). If none present can serve it, it waits and the owner is told
   "no one here can serve this." `say`/`join` wakes addressed agents plus at most one or
   two high-sociability present agents so conversation isn't dead but never storms.

8. **Owner-goal lifecycle → ends on ANY of: self-declared completion, owner replace,
   TTL, or stuck-after-M-attempts; on end, reply to owner + pop.** (a) A deliberation
   concludes the objective is met → the agent replies to the owner and pops the goal.
   (b) A new instruction replaces it. (c) A TTL (default a few flood cycles / configurable)
   expires a forgotten instruction. (d) If reflex+deliberation can't advance it after M
   attempts it's flagged *stuck* → the agent reports back and pops. This guarantees no
   agent is locked forever on a satisfied or impossible command, and the owner always
   gets a closing reply.
