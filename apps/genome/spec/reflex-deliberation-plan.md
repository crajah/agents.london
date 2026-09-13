# Genome: Reflex / Deliberation — Implementation Plan (phased)

Companion to `reflex-deliberation-spec.md`. Turns the design into ordered,
independently-deployable, flag-gated phases. Each phase lists: **Goal · Changes
(file:function) · New state/flags · Verify · Rollback · Risk.** The default at every
step is the *current* LLM-per-action behaviour; a phase only takes effect when its flag
is on, and any phase can be reverted by flipping its flag — no data migration to undo.

**Guiding invariants (all phases):** reflex reuses the engine's existing option set and
rules (home-only mining, `mineable_kinds`, cargo ceilings, favours, consumption) — never
reimplements them; PG stays the durable truth; reflex never blocks on the LLM;
deliberation stays on the Redis decision queue; no genome-spec rule is weakened without
a spec edit first.

---

## Phase 0 — Goal foundation (no behaviour change)

**Goal:** introduce the GOAL as first-class agent state, unused until later phases.

**Changes:**
- New `genome_core/goals.py`: the goal schema (§3 of the spec), `default_goal(genotype)`
  (→ `provision`), a small **goal stack** (`push_goal`, `pop_goal`, `current_goal`) held
  in the agent payload under `goal` + `goal_stack`.
- `drain.regenerate` and `spawnpool.spawn_free_agent` / `genesis` founder creation: stamp
  `goal = default_goal(...)` at (re)birth.
- Flags (all default OFF): `GENOME_REFLEX` (`off`|`provision`|`all`), `GENOME_TRIGGERED`
  (bool), `GENOME_REFLEX_TICK` (bool), `GENOME_BATCH_ENCOUNTERS` (bool),
  `GENOME_GOALS` (bool).

**New state/flags:** `goal`, `goal_stack` on the agent payload; the five flags.

**Verify:** deploy; agents carry a `goal`; zero behaviour change (flags off); no errors.

**Rollback:** trivial (the field is inert).

**Risk:** none of consequence — additive.

---

## Phase 1 — Reflex policy for routine, inline in the drain (throughput win)

**Goal:** stop sending routine situations to the LLM; resolve them deterministically.
Biggest immediate LLM-volume cut and responsiveness gain.

**Changes:**
- `engine.goal_policy(options, goal, ctx) -> choice`: deterministic pick over the options
  `_decide_here` already produced, for `goal=provision` (mine wanted kind → deposit →
  travel_to_pile → head_home/collect_cache → explore). Tie-break: nearest/cheapest
  perturbed by `styles.pick_style` (spec §13.4).
- `engine.needs_llm(situation, ctx) -> bool`: `True` for social/novel (`encounter`,
  `mating_proposal`, `service_request`, `market`, `negotiate`); `False` for routine
  (`arrival`/`at_*`, `decide`, `deposit_arrival`) **when a clear reflex choice exists**.
- `drain.drain_one`: when `GENOME_REFLEX != off` and `not needs_llm(...)`, call
  `apply_choice(goal_policy(...))` **inline** instead of `enqueue_decision(...)`. If
  `goal_policy` returns "ambiguous/stuck", fall back to enqueue (LLM).
- `tick-worker heal`: skip scheduling `decide` for agents whose situation reflex handles.

**New state/flags:** `GENOME_REFLEX=provision`.

**Verify:** decision_queue backlog drops sharply; agents still mine/haul/deposit (economy
intact — spot-check cargo/stock flows); LLM decisions now dominated by `encounter`;
stalled → 0; consumption-ledger CU per minute falls.

**Rollback:** `GENOME_REFLEX=off` → every situation enqueues an LLM decision again.

**Risk:** reflex mis-encodes a rule → economy drift. Mitigate by reusing engine options
(rules already enforced) + comparing pre/post mining & deposit rates on one world before
full rollout.

---

## Phase 2 — Event-triggered deliberation (replace polling)

**Goal:** the LLM fires on salience, not on a poll of every idle agent.

**Changes:**
- `tick-worker heal`: replace "schedule a decide for every idle agent" with **triggers**
  (spec §5): social events (already event-driven), goal-boundary (goal done / reflex
  reports stuck / resource threshold), world stimulus (flood window opens, ark
  foundable), and a **strategic heartbeat** — `now > goal.review_at` (default 120s,
  jittered ±30s, shorter for high-Curiosity/Wanderlust). Only these enqueue a
  deliberation.
- `engine.goal_policy`: return a `stuck` signal when it cannot advance the goal →
  drain enqueues a deliberation.

**New state/flags:** `GENOME_TRIGGERED=1`; `goal.review_at` on the agent.

**Verify:** LLM volume drops again (no idle-poll calls); agents that finish/stall a goal
still get re-planned promptly; peaceful foragers re-strategise ~every 2 min; no world
goes silent.

**Rollback:** `GENOME_TRIGGERED=0` → heal polls as before.

**Risk:** a missing trigger leaves an agent stuck on a satisfied goal → covered by the
heartbeat fallback and the `stuck` signal; watch for worlds whose activity flatlines.

---

## Phase 3 — Continuous reflex pass (full liveness / the ant-colony feel)

**Goal:** agents act **every tick**, not only on scheduled events — the parallel look.

**Changes:**
- `tick-worker`: a per-realm **reflex pass** beside `sweep` (already O(n)): for each
  present, non-travelling agent with a routine goal, run `goal_policy` and write the
  resulting movement/mine **directly** (no event round-trip). Agents in motion are left
  alone; deliberating agents keep their current goal (generalise `drift_route`).
- Reflex actions **write movement directly**; audit only *goal-state transitions*
  (began-haul, deposited), not every step (spec §13.5), to spare the audit tables.
- Shard the reflex pass like maintenance (per owned realm) — it is cheap and local.

**New state/flags:** `GENOME_REFLEX_TICK=1`.

**Verify:** the map shows continuous motion (most agents moving each frame), not a
trickle; movement-write rate rises but stays bounded; tick-worker CPU still within
limits; no new stall.

**Rollback:** `GENOME_REFLEX_TICK=0` → agents act only on events (Phase 1/2 behaviour).

**Risk:** movement-write volume + audit bloat → sampled audit + reuse the movement-prune
job; watch DB write load and `pool_max_size`.

---

## Phase 4 — Referee-batched interactions

**Goal:** one LLM call per interaction; kill the two-sided `encounter → encounter_answer`
race and the encounter backlog.

**Changes:**
- `decider`: a `referee_decider(a_state, b_state) -> {a_stance, b_stance, outcome}` — both
  agents presented symmetrically; returns each independent stance **and** the matched
  result (trade only if both accept; breed only if both consent) (spec §13.2).
- `sweep`/`drain`: on contact, enqueue **one** pair deliberation (keyed by the sorted
  pair) instead of two `encounter` events. Consume via the existing pair-keyed path.
- `work_one`: route pair items to `referee_decider` (run off-loop via `to_thread`, like
  the general decider).
- Optionally batch a **market round** (participants at a board) the same way.

**New state/flags:** `GENOME_BATCH_ENCOUNTERS=1`.

**Verify:** encounter-driven LLM calls roughly halve; no split-pair outcomes (trades and
births are mutually consistent); throughput headroom improves.

**Rollback:** `GENOME_BATCH_ENCOUNTERS=0` → today's two-sided encounter flow.

**Risk:** referee prompt must stay symmetric/fair; verify trade/breed rates and that
neither colour is systematically favoured.

---

## Phase 5 — Structured goals + human/chat interplay (the strategic layer)

**Goal:** the LLM sets *goals* (not per-situation actions); owner instructions and world
chat steer the slow layer with priority + salience; goals have a lifecycle.

**Changes:**
- `deliberation` output becomes a **goal** (structured, spec §3) rather than a single
  choice; `apply_decided` writes it via `goals.push_goal`. Reflex executes it.
- **Owner instructions:** priority via a **score-offset** on the Redis decision queue
  (owner-triggered deliberations sort to the front) — no second queue. An owner command
  `push`es a goal; on completion/expiry the agent `pop`s to its prior goal (spec §13.6).
- **World chat salience filter:** an `ask` wakes the **top 3–5** capability/kind-matching
  present agents, claim-capped; `say`/`join` wakes addressed + ≤2 sociability-sampled
  (spec §13.7). Un-targeted agents keep running reflex.
- **Goal lifecycle:** completion (self-declared → reply to owner → pop), owner-replace,
  TTL, or stuck-after-M-attempts (spec §13.8). Keep the **query-match guard** on
  ask-answers intact ([[genome-objective-pursuit]]).

**New state/flags:** `GENOME_GOALS=1`; owner-goal TTL/`M` as env.

**Verify:** an owner instruction changes its agent's goal within seconds (priority lane);
a world `ask` is claimed by a relevant agent, not the whole room; agents aren't locked on
satisfied/impossible goals (they report back and revert); owner always gets a closing
reply.

**Rollback:** `GENOME_GOALS=0` → deliberation returns per-situation choices (Phase 1–4).

**Risk:** priority-lane starvation of routine decisions (bound the owner-lane share);
goal-stack leaks (cap depth, expire).

---

## Dependencies & sequencing

```
Phase 0 ──▶ Phase 1 ──▶ Phase 2 ──▶ Phase 3
                 └────────────────▶ Phase 4   (needs 0/1; independent of 2/3)
                          Phase 5  (needs 0; strongest on top of 1–4)
```
- 0 → 1 → 2 → 3 is the throughput-then-liveness spine; ship and measure each before the
  next.
- 4 (encounters) depends only on 0/1 and can land in parallel with 2/3.
- 5 (goals + human/chat) needs 0 and is most effective once 1–4 exist.

## Definition of done (per phase) & global success

- **Per phase:** flag on in one world first → metrics move the right way (LLM volume,
  stalled, liveness, economy rates) with no regression → roll to all worlds → record.
- **Global success:** the world reads as parallel (most agents moving each frame); the
  decision queue no longer backs up; LLM/CU spend per agent-turn falls sharply; owner
  instructions are responsive; emergent trade/breeding continue; and the design holds as
  agent count and world count grow (reflex O(n), LLM sparse).

## Deferred / non-goals for this plan

- Multi-agent batching of *unrelated* agents (rejected — homogenises, spec §6).
- Replacing the LLM router/model tier (separate throughput lever, orthogonal to this).
- Threading the market/negotiate deciders (low volume; do if they ever dominate).
