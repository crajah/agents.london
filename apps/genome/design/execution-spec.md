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

**Rule 5.2** — Every agent carries a **decision budget** that accrues
continuously at **ten per day**, to a capacity of **twelve**. It exists to make
deliberation scarce, **not** to control cost.

> Capacity is twice the negotiation cap (Rule 7.2) so an agent can always finish
> one exchange and usually two. A routine day is about five decisions, so ordinary
> life never touches the budget and only sustained haggling drains it.

**Rule 5.2a** — The budget **never prevents an agent from acting**. An agent with
none continues its current intent; with no intent, it remains where it is. It
never freezes, never queues, and never waits for credit.

**Rule 5.2b** — Only **discretionary** deliberation is charged:

| | Charged | Always affordable |
| :--- | :--- | :--- |
| Arrival, encounter, opportunity | | deciding what to do |
| An offer put to it | countering | accepting or declining |
| An intent already formed | reconsidering it | continuing it |

> The line is between deliberation an agent **cannot avoid** and deliberation it
> **chooses to spend on**, and putting it there gets the mechanic without the
> failure mode.
>
> **A broke agent becomes a take-it-or-leave-it agent.** It can always say yes or
> no; it simply cannot haggle. That is bargaining from weakness in its most
> legible form — the agent is not disabled, it is *inflexible*, and a counterparty
> that notices can press the advantage.
>
> **The fallback must stay non-strategic.** Continuing an existing intent is not a
> heuristic about what is *wise*, and it must not become one. A free fallback that
> chose the nearest pile or the richest counterparty would supply behaviour, which
> `genome-spec.md` Rule 12.5 forbids the specification from doing — and if agents
> spent much of their time on that path, the emergent behaviour on display would
> be the fallback's rather than the population's.
>
> **The budget is sized so ordinary life never touches it.** A routine day is
> about five decisions (destination, mine or move on, press on or turn home,
> engage or ignore, breed or not). Only sustained negotiation should drain it,
> which is the only place the scarcity is wanted.

**Rule 5.2c** — The budget is a **rule of the world**, identical for every agent,
and is **not** affected by whose credentials pay for the inference (§9).

> This closes a hole that §9 would otherwise open the moment it shipped. If
> supplying your own key bought a larger budget, a user who paid could out-argue
> one who did not, deliberation would follow money rather than genotype, and every
> negotiation outcome would be confounded by billing.
>
> Bring-your-own-key changes **who is charged**, never **what an agent may do**.

> The cost arithmetic is unchanged by any of this and is worth keeping in view:
> at 10⁶ agents deciding ten times a day, ~10⁷ calls and order $1.5k/day, still
> the dominant cost in the system. Metering per agent, world and user should exist
> from the start. Measuring later is easy; measuring retrospectively is impossible.

**Rule 5.3** — Running out of judgement is not running out of motion (Rule 5.2a).

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

## 7. Negotiation

**Rule 7.1** — A negotiation is a **bounded sequence of turns**. There is no
resident process on either side; the state of the exchange lives in the event
payload and each turn is a fresh decision invocation.

**Rule 7.2** — A negotiation ends when a participant **cannot afford to
continue**, or at **six turns**, whichever comes first.

> Both bounds are kept because they do different work.
>
> The **turn cap** guarantees termination. Two well-supplied agents with
> incompatible positions would otherwise exchange offers indefinitely, and no
> amount of scarcity fixes a case where neither party is short.
>
> The **budget** is what makes patience cost something. Under a cap alone an agent
> never faces a real choice about whether a deal is worth another turn — it simply
> runs out of allowance, which is an interruption rather than a decision. With
> both, the question *is this worth one more exchange* has an answer that differs
> between agents and across a day.
>
> The asymmetry is the point. An agent that has deliberated all day negotiates
> from weakness against one that has not, and under Rule 5.2b it can still accept
> or decline — it just cannot counter. Nobody designed that; it falls out of
> charging for judgement while refusing to charge for action.

**Rule 7.3** — A2A carries two kinds of content, and they are handled
differently:

| | Status | Governed by |
| :--- | :--- | :--- |
| **Proposal** — *I will give 3 of kind 7 for 2 of kind 11* | Binding if accepted | the handoff (`system-spec.md` §5) |
| **Claim** — *that pile is rich; I am honest; they cheated me* | Evidence only | Credulity, folded in under `genotype-spec.md` Rule 6.10a |

> Which is exactly the split Rule 13.5 makes for an owner's instructions, arrived
> at independently. A commitment binds; an assertion is testimony. That the same
> distinction is needed for a human talking to their agent and for two agents
> talking to each other suggests it is the right cut rather than a convenience.

**Rule 7.4** — A negotiation **times out**, and the timeout is an ordinary
scheduled event (§3.2). An agent that perishes, teleports or is re-tasked
mid-exchange leaves the other with a lapsed offer rather than a wait.

**Rule 7.5** — Neither party sees the other's **reasoning**, only its messages.

> `../spec/` requires that an agent know only part of any plan. The architecture
> gives this for nothing: there is no shared session, so the only channel is what
> was actually said.

## 8. Runtime

**Rule 8.1** — Agents are built and run on **Google ADK**. A decision is a
**runner invocation**, not a resident agent.

> ADK is a good fit for reasons that go beyond convenience: it carries A2A as a
> first-class concern (§7), speaks MCP for the capability registry
> (`skills-spec.md` §6.2), and supplies a local harness for developing an agent
> before any world exists.
>
> The important compatibility is with Rule 1.1. ADK's runner-plus-session shape is
> already "load durable state, take one turn, persist" — which is what Rule 1.1
> asks for. What must be resisted is the ambient assumption that an agent is a
> long-lived conversational object. Here it is a row that is woken.

**Rule 8.2** — Models are reached **through the existing litellm router**, never
directly.

> Otherwise Rule 12.16's tier selection is bypassed on day one, and the finding
> that the economy tier is *better* as well as cheaper stops being worth anything.
> ADK's LiteLLM model binding exists precisely for this.

**Rule 8.3** — An ordinary decision is a **single constrained call**. Multi-step
tool-calling loops are reserved for the higher tier (§5.1).

> This is the cost trap in adopting an agent framework, and it is worth stating
> before it is sprung. Frameworks make an agentic loop the default — reason, call
> a tool, observe, reason again — and each lap is an inference call. A default
> five-step loop turns §5.2's ten decisions a day into fifty, and $1.5k/day into
> $7.5k/day, **for the same simulation**.
>
> Deciding which pile to walk to does not need a loop. Negotiating an Ark
> contribution might. The tier is the boundary and it must be explicit, because
> the expensive default is also the more impressive-looking one.

**Rule 8.4** — **Postgres remains the system of record.** A session holds the live
exchange and nothing else; genotype, opinions, cargo and objectives are loaded as
context and written back explicitly.

> If framework session state becomes the truth, two things break at once. The
> decision record (§6) loses its inputs to an opaque store, and the simulation
> acquires a second source of truth that no query can join against.

## 9. Whose model, and whose key

**Rule 9.1** — A user may supply **their own model credentials** and configure
their use in either of two scopes:

| Scope | Covers |
| :--- | :--- |
| **World** | every agent acting *inside* the world they own, visitors included |
| **Owned agents** | every agent they own, wherever it is |

**Rule 9.2** — The scopes overlap and **agent ownership takes precedence**. For an
agent acting in a world it does not belong to:

1. its **owner's** key, if configured;
2. otherwise the **world owner's** key, if that user has enabled provision for
   visitors;
3. otherwise the platform default.

> Precedence runs this way to close a griefing vector rather than on grounds of
> neatness. Under world-first precedence, sending agents into a wealthy user's
> world would spend that user's credit — and since teleport links are derived from
> real LinkedIn connections (`genome-spec.md` Rule 6.2), the people best placed to
> do it are exactly the people a user chose to connect to. Making provision for
> visitors **opt-in** turns hosting into a decision instead of an exposure.

**Rule 9.3** — Keys are **per-user secrets**: encrypted at rest, held in ordinary
storage rather than as cluster secrets, and never present in a decision record.

> Cluster secrets are the right home for a handful of platform credentials and the
> wrong home for one per user. Rule 6.1 logs the model and tier used and must
> continue not to log what authorised it.

**Rule 9.4** — Credentials are resolved by the decision worker and passed to the
**existing router** (Rule 8.2). A user key changes which credential is used, never
whether the router is used.

> Otherwise a user-supplied key becomes a way around tier selection, and
> Rule 12.16 holds only for agents whose owners have not opted out of it.

**Rule 9.5** — The **model that made each decision is recorded** (§6.1), and
comparisons across agents must account for it.

> This is the scientific cost of the feature and it should be understood before it
> is enjoyed. The validation programme found model choice changes how faithfully a
> disposition reaches behaviour by roughly a factor of two — 12 of 14 loci
> expressing on one model against 6 on another (`../validation/RESULTS.md`).
>
> So a population running on mixed models is **not homogeneous in a way the
> genotype does not describe.** Two agents with identical genotypes may behave
> differently because their owners chose differently, and any comparison that
> ignores the model column is measuring the model as much as the agent.
>
> That is not an argument against the feature — it is an argument for the model
> column, which §6.1 already requires. It does mean any claim about *evolution*
> drawn from a mixed-model population needs the model held constant or controlled
> for, exactly as the validation held it constant to say anything at all.

## 10. Which model an agent thinks with

**Rule 10.1** — An agent is assigned its models **at random on creation**, one per
tier (§5.1). The assignment is a property of the agent, not of its owner.

**Rule 10.2** — The assignment is **not heritable**. Offspring draw fresh, and a
parent's substrate is never passed on.

> Deliberately non-heritable, because heritability would destroy the very
> heterogeneity this is for. A model that expressed dispositions more faithfully
> would confer an advantage, selection would act on it, and the population would
> converge on a single substrate within a few generations. Random assignment holds
> the diversity open indefinitely.

**Rule 10.3** — The assignment **survives regeneration**. An agent restored under
`genome-spec.md` Rule 7.2 thinks with the models it was created with.

> Otherwise every death would silently change what kind of behaver an agent is,
> and the opinions others hold of it (`genotype-spec.md` §6.3) would be estimates
> of somebody else. Reputation requires that the thing being estimated persists.

**Rule 10.4** — A model **withdrawn from the pool** is re-rolled on the agent's
next regeneration, and until then the tier default stands in.

> The same shape as `skills-spec.md` Rule 1.3a for a withdrawn tool, and for the
> same reason: nothing may permanently carry a dead pointer, and a re-roll
> triggered from outside the simulation cannot be gamed from inside it.

**Rule 10.5** — A user's credentials (§9) determine **who pays**, never **which
model** an agent thinks with. Where a supplied key cannot serve an agent's
assigned model, the platform default is used for that agent.

> The direct extension of Rule 5.2c. If bringing a key changed an agent's
> substrate, the randomisation would be broken by whoever paid, and model choice
> would correlate with owner wealth rather than with nothing at all.

### 10.1 Why randomisation is the safe choice, measured

**Rule 10.6** — The **genotype must dominate the substrate**. The share of
behavioural variance attributable to model assignment is measured and must remain
below the share attributable to the genotype.

> The risk in heterogeneous models is precise and worth stating: if swapping an
> agent's model moves its behaviour more than sweeping a locus does, then the
> simulation is about models rather than about evolution, and the genotype is
> decorative in exactly the sense `genome-spec.md` §11.12 forbids.
>
> Measured against the validation data, it is not close:
>
> | | mean effect |
> | :--- | ---: |
> | Sweeping a locus 0 → 10000, model held | **0.58** |
> | Swapping the model, locus held | 0.17 |
> | **Ratio** | **3.3×** |
>
> Every one of the fourteen dispositions exceeds 2×, from Cooperativeness at 2.0
> to Aggression at 6.2. The genotype is the dominant driver on every locus tested
> and by a comfortable margin, so random assignment adds variance without drowning
> what is being selected on.
>
> **Randomisation also improves the statistics rather than damaging them.** Had
> users chosen models, the model would correlate with whatever kind of user chose
> it and no analysis could separate the two. Assigned at random it is a
> *randomised covariate*: uncorrelated with genotype by construction, its effect
> estimable, and controllable in any comparison that needs it.
>
**Rule 10.7** — A model enters the pool only by **passing a disposition-expression
screen**, and the pool is re-screened whenever it changes.

> This is what turns Rule 10.6 from an aspiration into a gate. The screen is the
> harness in `../validation` run against the candidate: sweep each disposition
> under randomised backgrounds, and admit the model if the genotype still
> dominates the substrate by the margin Rule 10.6 requires.
>
> It costs about an hour of cluster time per candidate, which is trivial against
> the alternative. Two of the eleven models the router currently serves returned
> no usable content at all under test, and admitting one that expresses
> dispositions poorly would narrow the ratio toward the point where the substrate
> rivals the genotype — the one outcome Rule 10.6 exists to prevent.

> Re-measure when the pool changes. The 3.3× holds for the two families tested;
> a model far worse at following a stated disposition would narrow it, and the
> ratio is the quantity that decides whether the pool is admissible.
