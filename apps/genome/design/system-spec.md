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

**Rule 3.3** — The shapes that matter are **intents and events**, not states:

```
world      ( realm_id, uuid, kinds[2], colours[2], flood_at, aggregate_stock )
agent      ( uuid, realm_id, genotype, cargo, home_realm, alive, decision_budget )
movement   ( agent_id, from_xy, to_xy, departed_at, arrives_at )
pile       ( uuid, realm_id, kind, xy, qty_at, measured_at, rate, cap )
event      ( due_at, kind, subject_uuid, payload )          -- the queue
opinion    ( observer_uuid, subject_uuid, attribute, estimate, weight )
decision   ( agent_uuid, at, situation, inputs, model, tier, choice )
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
