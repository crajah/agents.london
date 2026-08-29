# Genome — system design

**Status: draft. Nothing is implemented.** Subordinate to `../spec/`; introduces
no game rule. Numbering is local to this document.

## 1. Substrate

**Rule 1.1** — Genome is **composed from services already running**, not built
beside them.

| In place | Role in genome |
| :--- | :--- |
| PostgreSQL 18 + pgvector 0.8.6 | worlds, agents, piles, events, opinions; per-agent knowledge vectors |
| post-graph | realm/space tenancy (`genome-spec.md` §3) |
| litellm-proxy (10 replicas, 14 models) | decision routing and complexity tiers (Rule 12.16) |
| tool-registry | the capability lottery (`skills-spec.md` §6.2) |
| agent-registry, document-registry | agent identity and document storage |
| redis | event queue, proximity index, subscription fan-out |
| Prometheus / Loki / Grafana | operations, distinct from the decision record |

> Worth stating plainly because it changes the estimate of what this costs to
> build: genome is closer to **composition than greenfield**. The expensive pieces
> — a routed multi-model gateway, a live MCP registry, vector-capable tenanted
> storage — exist and are serving traffic. What is missing is the simulation core,
> which is arithmetic, and the interface.

**Rule 1.2** — Genome's services are **added to the deploy matrix**, not deployed
by hand.

> `.github/workflows/deploy-gke.yml` builds a fixed matrix of named services and
> applies a fixed manifest list. Until genome appears in both, merging genome to
> `main` rebuilds the existing services and deploys nothing new. This is recorded
> because it is a silent no-op rather than a visible failure.

## 2. Time

**Rule 2.1** — A **day is a real day**. Flood clocks of 15–30 days
(`construction-spec.md` Rule 4.7), decay (`genome-spec.md` Rule 4.18) and
Longevity are wall-clock quantities.

**Rule 2.2** — The world runs **continuously**, unattended.

> Real time is what makes the architecture in `execution-spec.md` affordable:
> events are sparse because a journey takes hours rather than milliseconds, so a
> per-event cost model stays small. Accelerating time multiplies the inference
> bill by exactly the acceleration factor and buys nothing the design wanted.
>
> It also sets the shape of play. A user does not sit and watch a simulation run;
> they keep a world, and it carries on without them — which is the only reading
> under which an imported LinkedIn trade graph and a 15-to-30-day flood clock mean
> anything.

## 3. Tenancy and data

**Rule 3.1** — Realms are **logical** (`genome-spec.md` Rule 3.5): one schema,
realm as a column. Isolation is query discipline.

**Rule 3.2** — Every read is scoped by realm. A read that forgets is a
cross-world leak, not an empty result.

> Rule 3.5's note says this in the specification and it bears repeating in the
> design, because it is the class of bug this system is most likely to have.
> Worlds used to have a database guarantee and now have a convention. The
> mitigation is that no query reaches storage except through a repository layer
> that takes the realm as a required argument — never a default, never inferred
> from context.

**Rule 3.2a** — **All storage goes through post-graph and post-graph-rag. Direct
DDL is forbidden** — genome never issues CREATE TABLE, and a migration file is a
defect, not a convenience.

**Rule 3.2b** — Genome realms map to post-graph realms **one-to-one**: each
world is its own post-graph realm, and the single agents realm
(`genome-spec.md` §3 Rule 3.1) is the post-graph realm `genome_agents`, with
**each agent a space** in it and private knowledge on post-graph-rag. Whether a
realm is a physical schema or a logical column is post-graph's own
`SCHEMA_PER_REALM` deployment flag — so Rule 3.5's deferred
schema-per-realm decision stays deferred, as **configuration rather than
architecture**.

> Rule 3.5 of `genome-spec.md` chose logical realms in one schema precisely so
> scale stays a configuration question; post-graph spaces are that mechanism
> already built, hardened by the services running beside genome. Hand-rolled
> tables would have duplicated the substrate the design names (Rule 1.1) and
> quietly created a second tenancy model to keep consistent with the first —
> which was attempted once, caught, and deleted. (An intermediate one-realm-many-spaces mapping was also tried and replaced by the one-to-one rule above.)

**Rule 3.3** — The shapes that matter are **intents and events**, not states:

```
world      ( realm_id, uuid, kinds[2], colours[2], flood_at, aggregate_stock )
agent      ( uuid, realm_id, genotype, cargo, home_realm, alive, decision_budget )
movement   ( agent_id, from_xy, to_xy, departed_at, arrives_at )
pile       ( uuid, realm_id, kind, xy, qty_at, measured_at, rate, cap )
event      ( due_at, kind, subject_uuid, payload )          -- the queue
opinion    ( observer_uuid, subject_uuid, attribute, estimate, weight )
decision   ( agent_uuid, at, situation, inputs, model, tier, choice )
model_key  ( user_id, scope, provider, ciphertext, visitors_allowed )
```

> `opinion` is the row count to watch. It is O(agents met) per agent, not
> O(agents), and `genotype-spec.md` Rule 6.9 chose a running average over a
> Bayesian posterior precisely to keep it "a number and a weight". Rule 6.10a
> preserved that. The general opinion (Rule 6.9a) is one further row per agent,
> not per pair.

## 4. Workers

**Rule 4.1** — **Tick workers** own realms and drain due events
(`execution-spec.md` §3). Ownership is leased, so a lost worker's realms are
reclaimed rather than stalled.

**Rule 4.2** — **Decision workers** take decision requests, gather context, call
the router and write back an intent. They are stateless and scale with the
inference budget.

**Rule 4.3** — Agent-to-agent deliberation runs over **A2A**
(`genome-spec.md` Rule 8.5) between decision workers, not between processes
representing agents.

> There is no long-lived agent process to hold a conversation, so a negotiation is
> a sequence of decision invocations with the exchange carried in the event
> payload. That is a constraint worth noticing rather than resenting: it forces
> every negotiating position to be **written down** in the record (§6), which is
> exactly what a simulation about deception needs.

## 5. Transfers

**Rule 5.1** — A trade is a **two-phase handoff**. Cargo leaves one agent and
enters another atomically or not at all.

**Rule 5.2** — There is no intermediate custody. `genome-spec.md` Rule 4.2 says
resources move only inside agents; a transfer in flight would be a resource
existing outside one.

> The interesting failure is not the database transaction, which is ordinary. It
> is that both parties are LLM decisions taken at different moments, so the window
> between *agreeing* and *executing* is real and an agent can change its mind or
> perish inside it. That window is where defection lives, and it should be visible
> in the record rather than engineered away — a trade that fails because a
> counterparty walked off is a **result**, not an incident.

## 6. Two records, kept apart

**Rule 6.1** — The **decision record** (`execution-spec.md` §6) is experimental
data. It is append-only, retained for the life of the run, and never sampled.

**Rule 6.2** — **Operational telemetry** is Prometheus and Loki, retained on the
usual schedule, and may be sampled freely.

> Conflating them is the easy mistake. One is logs and the other is the
> experiment; a retention policy tuned for the first would quietly destroy the
> second, and the loss would only be discovered when somebody asked why a
> population collapsed six weeks ago.

## 7. Scale

**Rule 7.1** — Write cost is **per event**, not per agent (`execution-spec.md`
§2). Inference cost is per decision and dominates everything else.

**Rule 7.2** — Growth to millions is **organic**: nothing in the design forecloses
it and nothing is built for it in advance.

> The distinction matters. Rule 3.5 made realms logical so a million worlds is not
> a million schemas; Rule 2.2 made position a function so a million agents is not
> a million writes per tick; Rule 3.4 sharded the tick so no single process is the
> ceiling. Each removes a wall.
>
> None of them is an argument for building a million-agent system now. A first
> population of a hundred users is a different system in every practical respect,
> and the value of the three rules above is that discovering so does not require
> rewriting anything.

## 8. Queues

**Rule 8.1** — There is **one event queue per world**, in Redis.

> Partitioning by world is not arbitrary. It gives **time-ordering within a
> world** for free, which the simulation requires — an agent must arrive before it
> can mine — without needing any global order. It gives row locality, since every
> event in a world touches the same partition of the same tables. And it gives
> fairness: a world with two hundred agents cannot starve a world with three,
> because their queues are separate and scheduled independently.

**Rule 8.2** — A worker **owns many worlds**. There is never a process per world.

> A queue per world is correct and a *process* per world repeats the
> process-per-agent mistake one level up. At the populations this design allows
> for, a million users is a million worlds; a million resident consumers is the
> same unaffordable shape as a million resident agents.
>
> Ownership is by revocable lease (§4.1), so a lost worker's worlds are picked up
> rather than stalled — and a stalled world is invisible from outside, since a
> world where nothing happens looks exactly like a world where nothing was due.

**Rule 8.3** — Postgres is the **source of truth for events**; Redis is the
scheduler. The queue must be **reconstructible** from the `event` table at any
time.

> This is the rule that matters most operationally. A dropped arrival event is not
> a lost message, it is an agent that never arrives anywhere again — permanently
> stuck, holding cargo, with no mechanism that would ever notice. Redis is chosen
> for what it is good at, and made non-authoritative for exactly that reason: if
> it is flushed, a worker rebuilds its queues with one query over due events and
> the simulation resumes.

**Rule 8.4** — The world queue **never blocks on inference**. Draining an event
that requires a decision enqueues a **decision request** on a separate queue and
moves on.

> Inference takes a second or two; a world's events arrive in strict order. Doing
> the call inline would let one agent's deliberation stall every other agent in
> its world, and a busy world would run slower than a quiet one purely because it
> is interesting.
>
> Two queues with different shapes: the world queue is ordered and partitioned,
> the decision queue is unordered and global, sized to the inference budget rather
> than to the population.

**Rule 8.5** — **A2A endpoints belong to workers, not to agents.** Agent identity
travels in the message.

> The same scaling argument once more, and it is the one most likely to be got
> wrong when adopting a framework: the natural way to expose an agent over A2A is
> to give it an address, and an address implies something listening. Millions of
> listeners is not available. A worker holds one endpoint and routes by the agent
> UUID in the envelope.

## 9. Connection discovery

**Rule 9.1** — Contacts are a **discovery seed, never a link**. Importing a
contact list proposes connections; it does not create them.

**Rule 9.2** — Supported sources are **Google People API**
(`people/me/connections`, scope `contacts.readonly`) and **Microsoft Graph**
(`/me/contacts`, scope `Contacts.Read`). Both are ordinary OAuth.

**Rule 9.3** — Matching is by **hashed email**. A contact who is not a genome
user is **discarded immediately** and never stored.

**Rule 9.4** — A link exists only when **both users confirm**
(`genome-spec.md` Rule 6.2c). One side importing a contact list is not consent
from the other.

> Rule 9.4 is the one that has to be there, and the reason is consent rather than
> design tidiness.
>
> **A contact is unilateral; a connection is mutual.** I can hold your email
> without you holding mine. Teleport links are **bidirectional and permanent**
> (`genome-spec.md` Rule 6.3a), so treating a one-sided contact as a link would
> open a door into someone's world, forever, that they never agreed to. No game
> property is worth that, and there is no version of it that a user could later
> undo.
>
> **Contact lists are also exhaust rather than curation.** Mail providers save
> everyone you ever wrote to — newsletters, one-off transactions, support desks.
> Rule 6.2's premise is that the graph has a shape that means something, and
> unfiltered contact history has a shape that means considerably less. Requiring
> confirmation filters it for free: only contacts who are users, and who accept,
> become portals.
>
> **And it is why these sources beat the one originally named.** LinkedIn has not
> exposed connections to general developers for years and second-degree
> connections are unavailable by any legitimate route, so Rule 6.2's original
> wording depended on data that could not be obtained. Contacts can be, and after
> confirmation they yield exactly what the rule wanted: a graph of people who
> genuinely know each other.

**Rule 9.5** — Import is **re-runnable**. A user may import again as their
contacts or the user base grow, and previously declined proposals are not
re-raised automatically.
