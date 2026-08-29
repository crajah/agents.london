# Genome — implementation plan

**Status: plan only. No code exists.** Derived from [`spec/`](spec) (the rules)
and [`design/`](design) (how they are met). Every task cites the rules it
satisfies; where a task and a rule disagree, the rule wins.

Ordering principle: **what invalidates the most if wrong is built first.** The
autonomy loop is proved before anything is built on top of it, and something is
visible on screen before the long tail of subsystems begins.

## Prerequisites — not mine to do

- [ ] **Explicit permission to write code** — standing instruction is specification only
- [ ] **Google Cloud OAuth client** — People API, scope `contacts.readonly` (`system-spec.md` Rule 9.2)
- [ ] **Azure app registration** — Microsoft Graph, scope `Contacts.Read` (Rule 9.2)
- [ ] **Sign-off to edit `.github/workflows/deploy-gke.yml`** — outside `apps/genome`
- [ ] **Decide PR #1** — merge, leave accumulating, or build on the branch

## Non-goals

Recorded so they are not drifted into: no physics, pathfinding visualisation,
particles, audio, 3D or lighting (`interface-spec.md` Rule 6.10); no tile grid
(Rule 6.6); no agent-level revocation (`genome-spec.md` Rule 6.14); no market,
route or cargo transfer outside agents (Rule 4.2); no decision budget as a spend
control (`execution-spec.md` Rule 5.2).


## User journeys — the acceptance criteria that matter

Phases are organised by subsystem; these are what the subsystems are *for*. A
phase is not done until the journeys it unblocks work end to end.

| # | Journey | Unblocked by |
| :--- | :--- | :--- |
| J1 | Sign in with Google or Microsoft, get a world, get a first agent | 5, 5.4 |
| J2 | Watch my world: agents moving, piles deepening and paling | 3 |
| J3 | **Switch to observe a world I do not own** — follow an agent, pick a portal, traverse onward, jump from an inspector | 3.5 |
| J4 | Follow one of my agents as it teleports, and get back home in one action | 3.5 |
| J5 | Click an agent — mine or anyone's — and read its genotype and expression | 7 |
| J6 | Chat with my agent; see whether I just gave an instruction or made a claim | 7 |
| J7 | Ask my agent something it cannot answer, and have it broker the answer | 6, 7 |
| J8 | Import contacts, propose, get confirmed, watch a portal appear | 5 |
| J9 | Watch two agents meet and strike a trade, and see what each believed | 6, 7.4 |
| J10 | Author a plan by conversation and watch agents build it | 10 |
| J11 | Come back after two days and understand what happened while I was away | 11 |
| J12 | See a flood countdown, and see who boards | 10, 11 |
| J13 | Leave: export what is mine, delete the rest | 12 |

---

## Phase 0 — Foundations

No behaviour. Everything later assumes this shape.

### 0.1 Repository and services
- [ ] `apps/genome/{tick-worker,decision-worker,api,web}` service skeletons
- [ ] Add each to `deploy-gke.yml` build matrix **and** its manifest list — omitting either is a silent no-op, not an error (`system-spec.md` Rule 1.2)
- [ ] Health endpoints, structured logging, Prometheus scrape targets

### 0.2 Schema
- [ ] `world(realm_id, uuid, kinds[2], colours[2], flood_at, aggregate_stock)`
- [ ] `agent(uuid, realm_id, genotype, cargo, home_realm, alive, models, colour_pair)`
- [ ] `movement(agent_id, from_xy, to_xy, departed_at, arrives_at)` (`execution-spec.md` Rule 2.1)
- [ ] `pile(uuid, realm_id, kind, xy, qty_at, measured_at, rate, cap)` (Rule 2.3)
- [ ] `portal(realm_id, to_realm, xy)` — random placement, fixed (`genome-spec.md` Rule 6.2e)
- [ ] `event(due_at, kind, subject_uuid, payload)` — the queue's source of truth (`system-spec.md` Rule 8.3)
- [ ] `opinion(observer_uuid, subject_uuid, attribute, estimate, weight)` + general opinion row (`genotype-spec.md` Rule 6.9a)
- [ ] `decision(agent_uuid, at, situation, inputs, model, tier, choice)` (`execution-spec.md` Rule 6.1)
- [ ] `model_key(user_id, scope, provider, ciphertext, visitors_allowed)` (Rule 9.3)
- [ ] `connection(user_a, user_b, confirmed_at)` — mutual only (`system-spec.md` Rule 9.4)
- [ ] Migrations, seed fixtures, rollback tested against a copy

### 0.3 Realm scoping — the highest-risk primitive
- [ ] Repository layer where **realm is a required argument**, never defaulted, never inferred from context
- [ ] Lint or test that fails any query reaching storage without it
- [ ] **Rationale:** realms are logical, not schemas (`genome-spec.md` Rule 3.5), so a read that forgets to scope is a cross-world leak rather than an empty result

**Done when:** migrations apply and roll back; a deliberately unscoped query fails a test.

---

## Phase 1 — The loop, headless

The bet the whole design rests on. Prove it before building on it.

### 1.1 Time and derivation
- [ ] Position as a pure function of `movement` and wall-clock (`execution-spec.md` Rule 2.2)
- [ ] Pile quantity closed form, clamped by the world ceiling (Rule 2.3, `genome-spec.md` Rules 4.13/4.14)
- [ ] Property test: **nothing is written while an agent travels**
- [ ] Aggregate stock maintained incrementally on mine events, never recomputed

### 1.2 Event queue
- [ ] Redis Streams + consumer groups per world (`system-spec.md` Rule 8.1)
- [ ] Worker leases N realms; lost lease reclaimed (Rule 4.1, Rule 8.2)
- [ ] **Rebuild from Postgres** — flush Redis in a test and confirm the simulation resumes (Rule 8.3)
- [ ] Events scheduled when the intent implying them is created (`execution-spec.md` Rule 3.2)

### 1.3 The autonomy loop
- [ ] arrival → decision request → intent → next event (Rule 4.1)
- [ ] Decision requests go to a **separate unordered queue**; the world queue never blocks on inference (`system-spec.md` Rule 8.4)
- [ ] Stub decider (uniform random) so the loop is provable without an LLM
- [ ] Proximity sweep for encounters over a spatial index (`execution-spec.md` Rule 3.3)

### 1.4 The record
- [ ] `decision` rows with full inputs, append-only, never sampled (Rule 6.1, `system-spec.md` Rule 6.1)
- [ ] Kept separate from Prometheus/Loki retention (Rule 6.2)

**Done when:** a world of stub agents runs unattended for 24h, mining and depositing; killing a tick worker loses nothing; the decision record explains every action.

---

## Phase 2 — Agents that think

### 2.1 ADK runtime
- [ ] Per-invocation runner, not a resident process (`execution-spec.md` Rules 1.1, 8.1)
- [ ] Postgres remains system of record; session holds only the live exchange (Rule 8.4)
- [ ] **Single constrained call** for ordinary decisions; multi-step reserved for the higher tier (Rule 8.3)

### 2.2 Routing
- [ ] All calls through the existing litellm proxy (Rule 8.2)
- [ ] Tier selection per decision class (Rule 5.1, `genome-spec.md` Rule 12.16)
- [ ] Per-agent model assignment at creation, one per tier (Rule 10.1)
- [ ] Not heritable (10.2); survives regeneration (10.3); withdrawn model re-rolls (10.4)
- [ ] Port `validation/run_validation.py` as the **pool screen**; admit at ≥1.5× (Rules 10.6, 10.7)

### 2.3 Genotype and prompt
- [ ] Loci, normalisation, allocation budget (`genotype-spec.md` §3.10)
- [ ] Prompt assembly showing **all** dispositions (validation method, `validation/README.md`)
- [ ] Every locus drives a computed faculty (Rule 3.19)

### 2.4 Opinions
- [ ] EWMA with Vindictiveness decay (`genotype-spec.md` Rules 6.9, 6.10)
- [ ] **Surprise-weighted update** `E' = E + K(S − σ(κ(E − θ)))` (Rule 6.10a)
- [ ] General opinion seeds strangers, population mean at materialisation (6.9a/6.9b)
- [ ] Colour **not** in the seed (6.9c)
- [ ] Owner-sourced evidence decays faster, compounding per relay (6.10b)

### 2.5 Budget
- [ ] Token bucket, 10/day, capacity 12 (`execution-spec.md` Rule 5.2)
- [ ] Charges discretionary deliberation only; never blocks action (5.2a/5.2b)
- [ ] Identical for every agent, unaffected by whose key pays (5.2c)
- [ ] Metering per agent, world and user from day one — enforcement never (Rule 5.2 note)

**Done when:** agents' choices track their dispositions on the deployed tier, reproducing the validation result in-world.

---

## Phase 3 — A visible world

Early payoff, and it tests interface assumptions against a real tick.

- [ ] React + Tailwind chrome; **one Pixi canvas driven imperatively** (`interface-spec.md` Rules 6.1, 6.2)
- [ ] Cartesian world coords; **isometric applied only in the renderer**; hit-test by inverse (6.4, 6.5)
- [ ] pixi-viewport pan/zoom/pinch (6.11); single texture atlas, batching preserved (6.12)
- [ ] Agent = filled disc + triangle, two tints, heading derived (6.9a–6.9c)
- [ ] Pile = soft cloud, lightness = fill, size = capacity (6.9e/6.9f)
- [ ] Portal = hollow split ring in destination colours (6.9h)
- [ ] Client interpolates from the **same closed forms**; arrival event authoritative (6.13, 5.2)
- [ ] Event subscription per world; **events on the wire, not frames** (2.2)
- [ ] Own-agent ring (6.9d)

### 3.5 Navigation — J3, J4
- [ ] **Follow an agent**, view accompanying it through a teleport (`interface-spec.md` Rule 5.3)
- [ ] Portal selection from the map opens the destination world (5.3)
- [ ] **Traverse onward** — a viewed world's portals are selectable, so the connected component walks (5.4)
- [ ] Jump to an agent's home world from its inspector (5.3)
- [ ] **Return home in one action**, always available (5.5)
- [ ] Deep-linkable world and agent URLs; browser back behaves
- [ ] Read-only affordances visibly distinct in a world the user does not own (Rule 13.2)

### 3.6 The mundane
- [ ] Loading, empty, error and disconnected states for the canvas and every panel
- [ ] Reconnect and re-sync after a dropped subscription without a page reload
- [ ] Clock skew handling — client interpolation must not drift from server time
- [ ] Responsive layout; canvas and panels usable on a laptop screen
- [ ] Keyboard navigation and focus order for all chrome; canvas has a text-equivalent agent list

**Done when:** J2, J3 and J4 work; a thousand agents render at 60fps; the client's predicted arrival matches the server's event; and a dropped connection recovers silently.

---

## Phase 4 — Identity, worlds, teleportation

### 4.1 PKI
- [ ] Purpose-built self-signed root; chain root → world → agent (`genome-spec.md` Rules 6.4–6.6)
- [ ] Identity = `H(genotype ‖ birth_world_uuid ‖ agent_uuid)` (6.7, 6.7a)
- [ ] No expiry, no agent revocation, intermediate revocation only (6.13, 6.14, 6.16)

### 4.2 World generation
- [ ] Two kinds per world from 20; colours from the A100 palette (Rules 4.1, 4.9)
- [ ] Piles with individual regeneration rates (4.6); random portal placement (6.2e)
- [ ] First agent free (7.1); materialisation costs 8 units (2.1)

### 4.3 Transfer
- [ ] Signed transfer assertion, monotonic counter, replay rejected (6.9, 6.11, 6.12)
- [ ] Exactly one world at a time (6.10); **passage instantaneous** (6.1a)
- [ ] 30 portals at open; user may add own connections only (6.2a, 6.2b)
- [ ] First-degree portals visible; further reach by world-hopping (6.2d)

**Done when:** an agent crosses worlds, its assertion verifies, and a replayed one is rejected.

---

## Phase 5 — Connections

- [ ] Google/Microsoft **OIDC login** (user's decision, this session)
- [ ] Contact import via People API / Graph (`system-spec.md` Rule 9.2)
- [ ] Hashed-email matching; **non-users discarded immediately, never stored** (9.3)
- [ ] Proposal → **mutual confirmation** creates the link (9.4, `genome-spec.md` Rule 6.2c)
- [ ] Re-runnable import; declined proposals not re-raised (9.5)

### 5.4 Onboarding — J1
- [ ] First run: OIDC sign-in → world generated → **first agent free** (`genome-spec.md` Rule 7.1)
- [ ] World gets two kinds, two colours, piles, and its opening 30 portal slots (Rules 4.1, 4.9, 6.2a)
- [ ] Explain the one thing that is not guessable: **you cannot reach four kinds alone** (Rule 2.3)
- [ ] Contact import offered, never required — the world must be usable with zero connections
- [ ] Account with no connections still runs: agents gather, deposit, and hit the four-kind wall visibly

**Done when:** J1 and J8 work; a brand-new account with no contacts still has something to watch.

---

## Phase 6 — A2A, negotiation, trade

- [ ] A2A endpoints **per worker**, agent identity in the envelope (`system-spec.md` Rule 8.5)
- [ ] Claims, questions, testimony, capability requests travel freely (`genome-spec.md` Rule 9.1c)
- [ ] **Binding proposals require co-location** (9.1b); addressable counterparties only (9.1d)
- [ ] Capability brokerage: holder performs, returns a result, never lends (8.6–8.8)
- [ ] Negotiation: bounded turn sequence, state in the event payload (`execution-spec.md` Rule 7.1)
- [ ] Ends at **six turns** or when a party cannot afford to continue (7.2)
- [ ] Proposals bind; claims are evidence (7.3); timeouts are scheduled events (7.4)
- [ ] Two-phase handoff, no intermediate custody (`system-spec.md` Rules 5.1, 5.2)

**Done when:** two agents meet, negotiate, and cargo moves atomically — and a counterparty walking away mid-deal is recorded as an outcome, not an error.

---

## Phase 7 — Chat and inspection

- [ ] Per-agent chat, opened by clicking an agent; persisted in that agent's store
- [ ] **Instruction vs assertion shown at send time** (`interface-spec.md` Rule 3.3, `genome-spec.md` Rule 13.5)
- [ ] Owner-sourced marking survives relay (13.5a); Loyalty disposes relaying (13.5b)
- [ ] Agent inspector: genotype and expression for **any** agent (13.1)
- [ ] Observe any world read-only (13.2); observation confers nothing on agents (13.3)
- [ ] **Agent-facing and user-facing reads on separate paths** (`interface-spec.md` Rule 1.1)
- [ ] **Belief-against-truth view** — own agent's opinion beside the subject's real genotype (Rule 4.1)

**Done when:** a user asks their agent something it cannot answer, and it brokers the answer from another agent.

---

## Phase 8 — Population

- [ ] Gender gate; attractiveness by assessor's own weights (`genotype-spec.md` Rules 6.4, 3.2)
- [ ] Selectivity as a numeric bar; **relaxes under scarcity** (6.3, 6.3a)
- [ ] Crossover, mutation, Mutability; bounded step with rare excursions (7.4a)
- [ ] Colours: one from each parent (3.3); three-word names, one surname per parent
- [ ] Lineage recorded; parental influence = exactly one objective (7.5)
- [ ] Death, regeneration, Longevity; knowledge lost (`genome-spec.md` Rules 7.2, 7.3)

---

## Phase 9 — Pathogens

- [ ] Strains as a second evolving genotype — six-field strain description, parent UUID recorded (`pathogen-spec.md` Rules 2.1, 2.3, §4.3)
- [ ] Replication, contagion, **infection distance** (`pathogen-spec.md` Rule 2.4); contact probability (Rule 2.5); creation chance on teleport
- [ ] Expression modifiers changing phenotype, not genotype; defences are three heritable things (Rule 2.2)
- [ ] Antigens with genotype-derived retention (Rule 2.19); signatures 8–16 dimensions (Rule 2.0)

---

## Phase 10 — Constructions, plans, flood

- [ ] 18 constructions, five branches, contributor counts 1/2/3/4/5 (`construction-spec.md` §2)
- [ ] Contributor counted once per **user** (Rule 3.4); claims enforced not promised (3.7)
- [ ] Berths: one per agent, **exchangeable to anyone**, tradeable during countdown (3.7a–3.7d)
- [ ] Portage by that many **distinct users**; never dismantled into resources (3.10–3.13)
- [ ] Ark tree immutable (3.9a); user plans additive (`genome-spec.md` Rule 13.6c)
- [ ] Plans are **trees**, authored conversationally in the world channel, buildable anywhere (13.6a, 13.6b, 13.6d)
- [ ] Plan grammar cannot express an effect (`interface-spec.md` Rule 3.5, `genome-spec.md` Rule 13.7)
- [ ] Flood clock 15–30 days undisclosed; two-day countdown (`construction-spec.md` Rules 4.7, 4.8)
- [ ] **Kills every agent present, native or visitor**; berth is the only exemption; those elsewhere untouched (4.9–4.11)

---

## Phase 11 — Absence and attention — J11, J12

The world runs unattended (`system-spec.md` Rule 2.2), so returning must be
comprehensible. This is the phase most easily forgotten and most felt.

- [ ] **Since-you-were-away digest** per world: births, deaths, trades, arrivals, infections, constructions
- [ ] Digest is built from the `event` and `decision` tables, not a separate log
- [ ] Push-worthy events, deliberately few: a flood countdown in a world you own, an agent of yours perishing, a berth offered to or surrendered by your agent, a plan of yours completed
- [ ] Per-world and per-agent activity timeline, readable back in time
- [ ] **Flood countdown surfaced prominently** wherever it applies (`construction-spec.md` Rule 4.8)
- [ ] Quiet by default: no notification for routine gathering or movement

**Done when:** J11 and J12 work — two days away is legible in under a minute.

## Phase 12 — Account lifecycle and data — J13

Contact import makes this non-optional rather than a courtesy.

- [ ] Export everything a user owns: world, agents, genotypes, decisions, chats
- [ ] Delete an account: world, agents, keys, connections, and **imported contact material**
- [ ] Deletion must not orphan other users' data — a connection is mutual, so removal is two-sided
- [ ] Non-user contacts were never stored (`system-spec.md` Rule 9.3); prove it with a test
- [ ] Revoke OAuth grants; revoke and re-key user-supplied model credentials (`execution-spec.md` Rule 9.3)
- [ ] Retention: decision record kept for the run (`system-spec.md` Rule 6.1); telemetry on its own schedule (6.2)

**Done when:** J13 works and a deleted account leaves nothing behind but the other side of a severed connection.

## Phase 13 — Admin and operability

- [ ] Inspect a world: lease holder, queue depth, oldest due event, last tick
- [ ] **Find a stalled world** — a world where nothing happens is indistinguishable from a world where nothing was due (`system-spec.md` Rule 8.2)
- [ ] Rebuild a world's queue from Postgres on demand (Rule 8.3)
- [ ] Replay a decision from its record for debugging, without re-running the world
- [ ] Pause and resume a world; drain a worker for deploy
- [ ] Cost per world and per user, with the biggest spenders visible

## Phase 14 — Operations

- [ ] Decision record retention distinct from telemetry (`system-spec.md` Rule 6.1)
- [ ] Model screen automated and re-run on pool change (`execution-spec.md` Rule 10.7)
- [ ] Cost dashboards per agent, world, user
- [ ] Key encryption at rest; keys never in a decision record (Rule 9.3)

---

## Testing strategy

- [ ] **Property tests** for every closed form: position, pile quantity, decay, opinion update — a stored value that could be derived is a defect
- [ ] **Fail-closed test** for realm scoping (Phase 0.3), asserted at the repository boundary
- [ ] **Flush-and-resume test**: wipe Redis mid-run, confirm the simulation continues (`system-spec.md` Rule 8.3)
- [ ] **Determinism harness**: same seed and same scripted decisions reproduce the same world, so a divergence is traceable
- [ ] **In-world validation replay**: reproduce `validation/` results against live agents, not a harness (Phase 2 done-when)
- [ ] **Frame budget in CI** — a second atlas or a stray filter must fail the build, not degrade quietly (`interface-spec.md` Rule 6.12)
- [ ] **Cost regression**: assert calls-per-decision, so an agentic loop cannot silently multiply spend (`execution-spec.md` Rule 8.3)
- [ ] **Soak test**: one world, 24h unattended, zero writes while agents travel
- [ ] Load: 1,000 agents in one world, 100 worlds on one worker

## Corner cases found in audit

Each is a case the rules do not currently settle, or settle differently from what
the surrounding text intends. Ordered by severity. Unresolved ones are marked ⚠
and need a decision before the phase that meets them.

### Resolved during audit
- [x] **A berth did not require boarding.** Rule 4.10 said a berth was the exemption without saying the agent must be aboard, so as written a berth-holder survived anywhere — while §4.2's commentary describes *which agents board and which are left in the water*. Fixed: Rules 4.10/4.10a now require presence at the Ark.

### ⚠ Unresolved — structural
- [ ] ⚠ **A user with zero connections is permanently stuck at one agent.** Rule 7.1 grants a free first agent; Rule 2.1 needs four kinds; Rule 2.2 gives a world two; Rule 6.2a draws portals from connections, of which there are none. No trade, so never four kinds, so never a second agent — and the Observatory that forges links needs five distinct contributors. There is no escape path in the current rules. **Every new user starts here.**
- [ ] ⚠ **Account deletion conflicts with permanent links.** Rule 6.3a makes teleport links permanent and Rule 7.2 regenerates agents in their home world. Deleting a user destroys a world that other worlds hold permanent links to, and into which foreign-parented agents may be due to regenerate.

### ⚠ Unresolved — undefined values and outcomes
- [ ] ⚠ **Ark capacity has no number.** Rule 4.3 says capacity is finite and shared between agents, constructions and stock. The entire bargaining drama of §4.2 depends on the total being smaller than the claims, and nothing sets it.
- [ ] ⚠ **A user's berth claim is proportional (Rule 3.7); nothing says how a claim becomes a specific agent's berth.** Rule 3.7a assumes an agent already holds one.
- [ ] ⚠ **Carrier death mid-portage.** Rule 3.12 has carriers move as one body; if one of five dies en route, the fate of the construction is undefined.
- [ ] ⚠ **Where a foreign agent emerges after boarding.** Rule 5.6 has the user emerge owning a hull, in the host's world. A boarded agent belonging to another user emerges — where?
- [ ] ⚠ **Which world a strain is created in on teleport** — origin or destination (`pathogen-spec.md` §2).

### Resolved by existing rules, recorded so they are not re-litigated
- [x] Agent mid-journey inside a flooding world is present and dies; passage is instantaneous so there is no third state (`genome-spec.md` Rule 6.1a).
- [x] Both parties broke in a negotiation: neither can counter, so the first offer is take-it-or-leave-it both ways (`execution-spec.md` Rule 5.2b). Coherent.
- [x] Agent whose home world floods while it is abroad: untouched by that flood (Rule 4.11), regenerates into a nascent world if it dies later (Rule 7.2).
- [x] Deposit at the user ceiling is partially accepted and the remainder stays aboard, decaying (`genome-spec.md` Rules 4.19, 4.18).

### Consequent tasks
- [ ] **Berth transfer must be atomic**, on the same two-phase pattern as cargo (`system-spec.md` Rules 5.1, 5.2) — two agents must not both acquire one berth
- [ ] **Boarding is an action with a deadline**: model the race, and the case of a berth bought by an agent that cannot reach the ship in time (Rule 4.10a)
- [ ] Ark manifest allocation across agents, constructions and stock against one limit (Rule 4.3)
- [ ] Late flood: a world whose worker held no lease fires its countdown late — decide whether agents are owed the full two days
- [ ] Portal placement collision with a pile or another portal (Rule 6.2e)
- [ ] Addressability granted by an owner: a user browses freely (Rule 5.4) and may tell an agent of someone it has never met, which makes that agent addressable under Rule 9.1d

## Risk register

| Risk | Rule at stake | Detection |
| :--- | :--- | :--- |
| Unscoped realm query leaks across worlds | `genome-spec.md` 3.5 | Phase 0.3 test must fail-closed |
| Agentic loop silently multiplies cost 5× | `execution-spec.md` 8.3 | Per-decision call count metered from Phase 2 |
| Redis loss strands agents permanently | `system-spec.md` 8.3 | Flush-and-resume test in Phase 1.2 |
| Second texture atlas kills batching | `interface-spec.md` 6.12 | Frame-time budget in CI |
| Agent-facing read reuses a user-facing path | `interface-spec.md` 1.1 | Separate modules, no shared repository |
| Model pool drifts below 1.5× | `execution-spec.md` 10.6 | Screen re-run gated on pool change |
| Stalled world looks identical to a quiet one | `system-spec.md` 8.2 | Phase 13 lease and queue-depth view |
| Client interpolation drifts from server clock | `interface-spec.md` 6.13 | Arrival-event comparison assertion |
| Digest rebuilt from a side log that diverges | Phase 11 | Digest derives from `event`/`decision` only |
| Deleted account leaves contact material behind | `system-spec.md` 9.3 | Phase 12 deletion test |

## Open, and answered only by running

Lifespan calibration (`genome-spec.md` §11.2) · whether colour is learnable
(`genotype-spec.md` Rule 6.9c) · whether reliable evacuation makes accumulation
unbounded (`construction-spec.md` Rule 4.9) · co-evolution, reputation and
signalling, untested because every harness so far used a scripted counterparty
(`validation/RESULTS.md`).
