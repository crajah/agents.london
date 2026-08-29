# Genome — agent execution layer

**Status: draft. Nothing is implemented.** This document specifies *how* agents
act. What they may do is `../spec/genome-spec.md` and the documents beside it;
this one is subordinate to all of them and introduces no game rule.

Numbering is local to this document. References of the form
`genome-spec.md` Rule 4.7 point into `../spec/`.

## 1. The shape

**Rule 1.1** — An agent is **not a process**. It is durable state plus a
decision function invoked by events.

> A process per agent is the obvious design and it is unaffordable. At the
> populations `genome-spec.md` Rule 3.2 contemplates, almost every agent is idle
> at any given instant — walking a path already chosen, waiting out a haul,
> asleep between decisions. Paying for a resident process to represent *waiting*
> is paying for nothing.
>
> Between events an agent is rows. It costs storage and no compute.

**Rule 1.2** — The simulation core is **deterministic and free of inference**.
Movement, mining, decay, regeneration, opinion arithmetic and attractiveness are
computed. Inference is invoked only where `genome-spec.md` §12 says a *choice* is
made.

> This is `genome-spec.md` §12.4 restated as an architecture rather than a
> principle: "confining the model to judgement is what makes the number
> tractable — routine movement, harvesting and arithmetic no longer cost tokens."
>
> Note where the opinion machinery lands. Rule 6.10a of `genotype-spec.md` is one
> logistic and one multiply-add, so **the mechanism that makes agents socially
> interesting costs nothing per update**. Belief is free; only deciding what to do
> about it is billed.

## 2. Intent, not state

**Rule 2.1** — A moving agent stores an **intent**, not a position:

```
agent_movement( agent_id, from_xy, to_xy, departed_at, arrives_at )
```

**Rule 2.2** — Position is a **pure function of wall-clock time** over that
intent. Nothing is written while an agent travels.

> This is the decision that makes population scale affordable, and it is worth
> being explicit about what it replaces.
>
> A tick that advances positions costs **per agent**. An agent walking for three
> hours would take some ten thousand position updates to arrive exactly where
> arithmetic already knew it would be, and at a million agents that is millions of
> writes per tick to learn nothing. Storing the intent costs **per event**: two
> writes for the whole journey, one at departure and one at arrival.
>
> Events are sparse because `system-spec.md` Rule 2.1 makes a day a real day. That
> is what turns "millions" from a hardware problem into an inference bill.

**Rule 2.3** — A pile stores `(qty_at, measured_at, rate, cap)` and its current
quantity is derived in closed form. A pile is written only when mined.

> Rule 4.6 of `genome-spec.md` gives every pile its own regeneration rate, which
> reads like an invitation to tick every pile in every world forever. It is not
> needed: regeneration is a function, and a function can be evaluated on read.
>
> One coupling to respect. Rule 4.13's world ceiling halts regeneration on
> *aggregate* stock across a world's piles, so the closed form is clamped by a
> world-level total. That total is maintained incrementally at each mine event
> rather than recomputed, which keeps it O(events) like everything else here.

**Rule 2.4** — Any quantity derivable from an intent and a clock is **derived,
never stored**.

## 3. The tick

**Rule 3.1** — The tick does not advance the world. It **drains an event queue**.

**Rule 3.2** — Events are scheduled **when the intent that implies them is
created**, since their times are computable then: arrivals, flood countdowns
(`construction-spec.md` Rule 4.8), death by Longevity, decay crossings
(`genome-spec.md` Rule 4.18), infection rolls.

**Rule 3.3** — **Encounters** are the exception, being a property of two agents
rather than one. They are detected by a periodic proximity sweep over a spatial
index.

> Encounters are analytically solvable — two agents on known trajectories, solve
> for whether they come within `pathogen-spec.md`'s infection distance — and that
> is a later optimisation, not a starting position. A coarse sweep is simpler and
> sufficient, and it degrades gracefully: a missed encounter is a meeting that did
> not happen, which is indistinguishable from the two agents having passed a
> minute apart.

**Rule 3.4** — The tick is **sharded by realm**. Worlds are independent except
through teleports and A2A, so each worker owns a set of worlds.

> `genome-spec.md` Rule 3.5 made realms logical rather than physical, so the shard
> key is a column predicate and not an infrastructure decision. One tick
> conceptually, N workers operationally, and no single process whose failure stops
> the simulation.

## 4. The autonomy loop

**Rule 4.1** — The loop is: **event → decision → intent → scheduled event**. It
closes, and it requires no user.

```
arrival at pile     →  decide: mine, move on, or wait
decision            →  intent with a computable completion time
intent              →  event enqueued at that time
                    →  (nothing until then)
```

**Rule 4.2** — An agent acts whether or not anyone is watching. Observation is a
**read concern only** (`interface-spec.md` §2).

> Worth stating that this is not a property anybody had to build. Because Rule 2.2
> derives position from a clock and Rule 4.1 schedules from intents, there is no
> code path that could behave differently when observed. The world runs unattended
> because nothing in it can tell.

## 5. The inference budget

**Rule 5.1** — Decisions are **tiered by cost** and routed accordingly
(`genome-spec.md` Rule 12.16 fixes the tier for ordinary decisions).

| Tier | Work | Cost |
| :--- | :--- | :--- |
| Computed | movement, mining, decay, opinion updates (`genotype-spec.md` Rule 6.10a), attractiveness | free |
| Economy inference | which pile, press on or turn home, accept or decline | routed cheap |
| Higher inference | negotiation, deception, coalition-forming, Ark bargaining | routed up |

**Rule 5.2** — The **decisions-per-agent-per-day budget is an explicit design
parameter** with a stated target, not an emergent quantity.

> `genome-spec.md` §12.4 already treats inference as a budget variable. This rule
> makes it a number somebody owns.
>
> The arithmetic is unforgiving and worth carrying openly. At 10⁶ agents making
> ten decisions a day, that is **10⁷ inference calls a day**, near 115/sec
> sustained, roughly 15B tokens — order **$1.5k/day** at economy-tier pricing, and
> it scales linearly with population.
>
> **This is the dominant cost in the entire system and it dwarfs the rest.** Ten
> is a guess. Three or thirty is the difference between $500 and $5k a day at the
> same population, and it is a *design* lever rather than an operational one: it
> asks how much of an agent's day is committed intent and how much is fresh
> judgement. An agent that decides once and then executes a long plan is cheap and
> less reactive; one that reconsiders constantly is expensive and alive.
>
> It also retroactively raises the value of a validation result. Rule 12.16 found
> the economy tier not merely cheaper but *better* at following a stated
> disposition. At these volumes that finding is worth real money.

**Rule 5.3** — An agent that has exhausted its budget **continues its current
intent** rather than stopping. Running out of judgement is not running out of
motion.

## 6. The record

**Rule 6.1** — Every decision is logged with its inputs: the agent's genotype at
the time, the opinions consulted, the situation presented, the model and tier
used, and the choice returned.

**Rule 6.2** — Runs are **not exactly reproducible**. What is guaranteed is
statistical reproducibility and a complete decision record.

> `genome-spec.md` §12.4 calls this "worth building early; nearly impossible to
> retrofit", and that is the whole argument. A simulation whose purpose is to
> discover what emerges is worthless if nobody can afterwards ask *why* an agent
> did something. The log is not observability in the operational sense; it is the
> experimental record, and it is the only artifact that survives the run.
