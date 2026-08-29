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

**Rule 5.2** — There is **no decision budget**. An agent thinks as often as
events give it cause to.

> Deliberately unlimited, and the cost is recorded rather than capped so that the
> decision to cap can be taken later on evidence instead of guesswork.
>
> The arithmetic does not go away for being unenforced. At 10⁶ agents making ten
> decisions a day that is **10⁷ inference calls**, near 115/sec sustained, roughly
> 15B tokens — order **$1.5k/day** at economy-tier pricing, scaling linearly with
> population. It remains the dominant cost in the system by a wide margin.
>
> Two things follow from leaving it uncapped. **Rule 12.16 is worth more, not
> less**: with no ceiling on volume, the finding that the economy tier follows a
> stated disposition *better* as well as more cheaply is the only thing keeping
> the number in this range at all. And **§9 matters more**, since a user supplying
> their own key is choosing to carry a cost nobody is limiting.
>
> Recorded for when this is revisited: metering per agent, per world and per user
> should exist from the start even while nothing is enforced. Measuring later is
> easy; measuring *retrospectively* is impossible, and a cap chosen without a
> distribution to look at would be the same guess this rule declines to make.

**Rule 5.3** — Should a limit ever be introduced, an agent that reaches it
**continues its current intent** rather than stopping. Running out of judgement is
not running out of motion.

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

**Rule 7.2** — A negotiation is bounded by an **explicit maximum number of
turns**, and ends without agreement when it is reached.

> This rule exists because Rule 5.2 removed what used to bound it, and the gap is
> worth recording rather than quietly patching.
>
> When decisions were budgeted, a negotiation terminated naturally: turns cost
> inference, so haggling ended when a participant ran out. That gave a property
> nobody designed — **the inference budget was a bargaining resource**, patience
> was purchasable and finite, and an agent negotiating late in its day negotiated
> from weakness. With no budget there is no such pressure, and two agents with
> incompatible positions would exchange offers indefinitely.
>
> An explicit cap is the correct replacement and a plainer one. It is a rule of
> the world rather than an emergent scarcity, and it should be set high enough
> that reaching it means genuine deadlock rather than an interrupted deal.
>
> The dormant property is recorded here because it is the strongest argument for
> reintroducing a budget later: a cap makes negotiations terminate, but only
> scarcity makes patience *cost* something, and only then does an agent face a
> real decision about whether this deal is worth another turn.

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
