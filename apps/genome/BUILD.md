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

Recorded so they are not drifted into: no audio, 3D, lighting or decorative
particles (`interface-spec.md` Rule 6.10a) — **2D physics, pathfinding and
visible agent movement are core product**, corrected by the user; no tile grid
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

### 0.2 Storage shapes — on post-graph, never raw DDL (`system-spec.md` Rules 3.2a/3.2b)
- [x] ~~SQL migration~~ — written, caught, deleted; post-graph owns all DDL
- [ ] `ensure_world_realm` per world (`world_meta, piles, portals, events, presence`); `ensure_agents_realm` once (`agents, decisions`, edge `opinion_of`) — idempotent, post-graph owns DDL
- [ ] Realms **one-to-one**: world = its own post-graph realm; agents realm = `genome_agents` with **agent-keyed spaces**; movement and decisions as **append-only vertex data**; presence lives in the world's realm (Rule 6.10)
- [ ] **SCHEMA_PER_REALM is not set by genome** — services construct the client without it; the environment decides. Do not copy the registries' `"1"` default
- [ ] Agent knowledge stores on **post-graph-rag**, agent-keyed spaces (`genome-spec.md` §8)
- [ ] Later phases add their vertex/edge tables where the work lands: `objectives, negotiations` (6), `chats` (7), `infections, strains, antigens` (9), `constructions, plans, berths, ark_manifests` (10)
- [ ] Seed fixtures; ensure_schema idempotence test against the in-cluster DB (throwaway pod)

### 0.3 Realm scoping — the highest-risk primitive
- [ ] Store layer where the **world space is a required argument**, never defaulted, never inferred from context
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
- [ ] **Terrain generation**: impassable obstacles, fixed at creation, flood-surviving (`genome-spec.md` Rule 5.3)
- [ ] **Pathfinding at decision time**: waypoint polylines around terrain (`execution-spec.md` Rule 2.1a); position piecewise along them (2.2)
- [ ] **Contact = proximity sweep crossing the contact radius** (Rule 2.2a); no stepped physics server-side
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

### 2.1 ADK runtime on KAgent
- [ ] Per-invocation runner, not a resident process (`execution-spec.md` Rules 1.1, 8.1)
- [ ] **Public kagent.dev** helm-installed (marty `infra/kagent`); custom `kagents.kagent.dev` CRD retired — done 2026-08-30
- [ ] **Two `Agent` CRs, one per caste** — economy and deliberative deciders; never one per simulated agent (Rule 8.6)
- [ ] `ModelConfig` → litellm OpenAI-compatible endpoint (Rule 8.2); telos + guardrails as system prompt; no reliance on kagent session memory (Rule 8.4)
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
- [ ] **Self-knowledge in the prompt**: genotype, faculties, pools and maxima, cargo, objectives, opinions, preference weights (`genotype-spec.md` 6.6a)
- [ ] Current **expression** shown alongside genotype, so infection and attrition are self-evident (6.6b)
- [ ] **Never** how the agent appears to others — no appraised attractiveness (6.6c)
- [ ] **Fidelity, not rank**: Amenability expressed as how faithfully the top objective is served (`genome-spec.md` Rule 10.1d)

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

- [ ] React + Tailwind chrome; **canvas may be a game engine** — renderer + 2D physics for local motion and contact, server authoritative (`interface-spec.md` Rules 6.1–6.3)
- [ ] Terrain drawn; routes visible as agents follow them; contact legible at encounters (Rule 6.10)
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
- [ ] World generation reads its quantities from [`spec/calibration-spec.md`](spec/calibration-spec.md): uniform random kind pair (3.0c); 6–10 piles per kind, min-spaced, capacities 15–50 (3.0d)
- [ ] Founder genotype: uniform about a recorded per-world centre (`genotype-spec.md` 3.2a/3.2b)
- [ ] Founder surnames drawn fresh from the name pool; founders root lineages (calibration 3.0e)
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

### 5.3a Email identity, invites, notifications (user directive 2026-08-30)
- [ ] Platform id = **hash of normalised email** from every route (`genome-spec.md` Rule 6.2i); OAuth extracts the email claim; direct entry accepted unverified (magic-link verification a hardening task)
- [ ] **Invite by email** (Rule 6.2j): creates invitee world eagerly, writes outbox login link, links the two worlds' portals both ways, notifies both sides
- [ ] **Notifications**: per-user feed with source × level config (`interface-spec.md` §7); always-important set per Rule 7.3; emit from genesis, invites, links, births, deaths, combat, transfers
- [ ] **Outbox** (`system-spec.md` §10): durable rows, no-op sender until SMTP configured
- [ ] Web: email-entry login, notification bell, per-source level settings

### 5.4 Onboarding — J1
- [ ] First run: OIDC sign-in → world generated → **first agent free** (`genome-spec.md` Rule 7.1)
- [ ] World gets two kinds, two colours, piles, and its opening 30 portal slots (Rules 4.1, 4.9, 6.2a)
- [ ] Explain the one thing that is not guessable: **you cannot reach four kinds alone** (Rule 2.3)
- [ ] Contact import offered, never required — the world must be usable with zero connections
- [ ] **Commons portal present from creation** (`genome-spec.md` Rule 6.2f); one-way exit enforced (6.2g)
- [ ] Commons **sharded, stable assignment** at world creation, hundreds of worlds per shard (6.2h)
- [ ] Cold-start path provable: agent → commons → trade → four kinds → second agent
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
- [ ] **Combat**: Attack against Attack moderated by Agility, probabilistic (`genome-spec.md` 9.3a)
- [ ] Both parties lose Stamina, loser more; recovery at reStamina (9.3b), **less Immune Vigilance's watch-cost** (`genotype-spec.md` 3.8e)
- [ ] Winner takes cargo to its ceiling, remainder stays (9.3c, 4.19a)
- [ ] Mana spent to press an attack (9.3d); zero Stamina incapacitates without killing (9.3e)
- [ ] **Winner's maximum Stamina permanently reduced by Attrition** (`genotype-spec.md` 3.8c); loser recovers in full
- [ ] Zero maximum Stamina perishes, Rule 7.2 applying as for any death (3.8d)
- [ ] **Selection-differential check**: combat loci against dispositions, per §3.8's warning

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
- [ ] Strain creation rolled **independently at both ends** of a teleport
- [ ] Replication, contagion, **infection distance** (`pathogen-spec.md` Rule 2.4); contact probability (Rule 2.5); creation chance on teleport
- [ ] Expression modifiers changing phenotype, not genotype; defences are three heritable things (Rule 2.2)
- [ ] Antigens with genotype-derived retention (Rule 2.19); signatures 8-16 dimensions (Rule 2.0)
- [ ] **Antigens synthesised during infection**, after Immune Vigilance's detection delay, at Synthesis Speed (Rule 2.18a)
- [ ] Antigen as a **vector in signature space**, unbound to any strain (2.18b)
- [ ] Recovery when **combined coverage** crosses the threshold, or at a Sanatorium (2.18c, 2.18f)
- [ ] Antigen **decay rate fixed at synthesis** from the maker's genotype (2.18d), modulated by the holder (2.19)
- [ ] Antigens **copied, not transferred** — sharing costs the giver nothing (2.18e)
- [ ] **Graded immunity** by coverage rather than binary (2.20)
- [ ] Inoculist bank holds antigens **against decay** (2.20a)
- [ ] Antigens may be false (2.18g); **Apothecary authenticates** (2.18h)
- [ ] **Test the prediction**: Cooperativeness should *not* predict antigen sharing, since sharing is costless (Rule 12.15)
- [ ] **Infection rendered** as a broken disc outline (`interface-spec.md` Rule 6.9i) — it is public (Rule 2.21)

---

## Phase 10 — Constructions, plans, flood

- [ ] 18 constructions, five branches, contributor counts 1/2/3/4/5 (`construction-spec.md` §2)
- [ ] Contributor counted once per **user** (Rule 3.4); claims enforced not promised (3.7)
- [ ] Berths: one per agent (3.7c), exchangeable to anyone (3.7a/3.7d), tradeable during countdown (3.7b), **lost on death** (3.7g)
- [ ] Berths arrive **unassigned**; a user's own agents contest them (3.7e); presence settles the remainder (3.7f)
- [ ] **Boarding required** — a berth held but not reached saves nobody (4.10, 4.10a)
- [ ] Ark lands in the host's world; **foreign survivors emerge there** and must travel home (4.3c)
- [ ] Carrier death sets the construction down in place, reclaimable by the right number of distinct users (3.12a)
- [ ] Portage by that many **distinct users**; never dismantled into resources (3.10–3.13)
- [ ] Ark tree immutable (3.9a); user plans additive (`genome-spec.md` Rule 13.6c)
- [ ] Plans are **trees**, authored conversationally in the world channel, buildable anywhere (13.6a, 13.6b, 13.6d)
- [ ] Plan grammar cannot express an effect (`interface-spec.md` Rule 3.5, `genome-spec.md` Rule 13.7)
- [ ] Flood clock 15–30 days undisclosed; two-day countdown (`construction-spec.md` Rules 4.7, 4.8)
- [ ] **Kills every agent present, native or visitor**; berth is the only exemption; those elsewhere untouched (4.9–4.11)
- [ ] Partial hull persists across floods while building (4.4a); **a successful voyage spends the Ark** (4.4b); an unused Ark is not spent (4.4c)
- [ ] Wreck state: decaying hull is unboardable, uncontributable, unsalvageable

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
- [ ] Delete an account: agents, keys, chats, opinions, corpus and **imported contact material**
- [ ] **Tombstone the world** rather than removing it (`genome-spec.md` Rule 3.6); neighbours' portals stay valid
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

### Consequent tasks (structural)
- [ ] **Economy dry-run before constants freeze**: spreadsheet-level simulation of mining → cargo → trade → materialisation → construction under the chosen calibration, verifying an Ark is reachable inside a cycle
- [ ] **Construction cost table** in `calibration-spec.md` — 18 rows plus the Ark, kinds × units each
- [x] **Production-prompt re-screen done**: 11/14 pass outright, several strengthened (Cooperativeness 0.25→0.50); two harness biases found and encoded (`validation/RESULTS.md`)
- [ ] **Genotype schema versioning**: adding a budgeted locus post-launch changes every agent's expressed values; migrations must state the dilution and re-baseline
- [ ] **Cross-document reference lint**: rule numbers collide across documents (two Rule 6.9a's exist); every cross-doc citation must be doc-qualified

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

### Resolved by decision
- [x] **A user with zero connections is permanently stuck at one agent.** Resolved: every world holds a permanent portal to an ownerless **commons** (`genome-spec.md` Rule 6.2f), whose only exit is the way in (6.2g) so the topology is preserved.
- [x] **Account deletion conflicts with permanent links.** Resolved: the world is **tombstoned** (Rule 3.6) — kinds, colours, piles and portals persist ownerless; everything personal is deleted.

### Found by journey-tracing, resolved
- [x] **The specification contained no quantities at all** — no map size, no speed, no collection rate, no pile count, no founder distribution. 378 rules and not one number governing tempo. Now [`spec/calibration-spec.md`](spec/calibration-spec.md), with crossing time set at ~6h, calibrated against §4.2's own claim about the two-day countdown.
- [x] **Founder genotype was undefined** — the starting condition of the whole evolutionary experiment. Resolved: uniform within a world about a per-world centre, with the centre **recorded** so structure findings can control for it (`genotype-spec.md` Rules 3.2a/3.2b).
- [x] **A berth's fate on death was undefined.** Resolved: lost, returning to unassigned (`construction-spec.md` Rule 3.7g).

### Found by structural analysis (composition, not coverage)
- [x] **Deleterious-direction loci repaired.** Attrition is now intensity (adds to Attack, burns maximum Stamina on wins); Detection Latency became **Immune Vigilance** (fast detection costs Stamina regeneration). Both are trade-offs selection can settle either way (`genotype-spec.md` 3.8c/3.8e).
- [x] **Budget membership stated: all four inside**, with Longevity's membership made deliberate (`genotype-spec.md` Rule 3.23a). Pre-launch dilution is free; post-launch additions need the genotype-versioning task below.
- [ ] ⚠ **Construction resource costs do not exist.** The tree specifies kinds and contributor counts and never unit quantities — there is no cost table for any of the eighteen constructions or the Ark. Every feasibility claim in §4.2 is unfalsifiable until they exist.
- [x] **Partial Ark survives** (Rule 4.4a): hull contributions persist across floods, so the first Ark is a multi-cycle undertaking and the one-cycle impossibility cannot strand the objective hierarchy. Economy dry-run still required to size the cycles.
- [x] **The validated prompts are not the production prompts.** Resolved by the Phase 2 re-screen: expression survives and mostly strengthens under the full Rule 6.6a assembly. Every ρ in `validation/RESULTS.md` came from prompts showing 14 dispositions. Rule 6.6a's self-knowledge adds faculties, pools, maxima, cargo, objectives and opinions — several times the context. Expression may not survive the dilution; **the validation must be re-run with the full production prompt** before Phase 2's done-when is meaningful.
- [x] **Amenability vs 10.1a settled: rank absolute, fidelity is not** (Rule 10.1d). The owner decides what; the genotype decides how, and how much.
- [x] **Fake antigens: fakeable like any claim, verifiable at an Apothecary** (Rules 2.18g/2.18h). Fraud, not assault — no infection is caused, and Rule 6.10a's surprise update makes it work once per victim per liar. Antigens are information (2.18e), shared as claims. Rule 4.2 of pathogen-spec decided disease is never a weapon — but sharing a *corrupt* antigen that covers nothing is deception with epidemiological consequences, discovered only on infection.

### ⚠ Still unresolved
- [x] **Ark capacity has no number.** Resolved: **twelve slots**, an agent costing one, a construction its contributor count, stock one per unit (`construction-spec.md` Rule 4.3b) — oversubscribed by construction.
- [x] **How a berth claim becomes a specific agent's berth.** Resolved: berths arrive **unassigned** and the user's own agents contest them (Rules 3.7e/3.7f). Presence settles what argument did not. Supersedes commentary that had the owner allocate directly.
- [x] **Carrier death mid-portage.** Resolved: the construction is **set down where the party stands** and any group of the required number of distinct users may take it up, strangers included (Rule 3.12a).
- [x] **Where a foreign agent emerges after boarding.** Resolved: **in the world where the Ark came to rest** — its host's — whoever owns the agent (Rule 4.3c). A survivor is a guest with a journey ahead of it.
- [x] **Which world a strain is created in on teleport.** Resolved: **both ends, independently rolled**.
- [ ] ⚠ **Mechanical calibration constants remain unset** (live count in [`spec/calibration-spec.md`](spec/calibration-spec.md) §4 — currently 15). All are rates, thresholds and exchange functions with sensible first values; the two that were experiments (lifespan, mutation step) are now set.
- [x] **Trade breaching the cargo ceiling.** Resolved: **partially accepted** up to 15, remainder stays with the giver — covering trade and spoils alike (Rule 4.19a).
- [x] **Combat was referenced and never specified.** Rule 9.3 allowed encounters to resolve in aggression and never said what that meant, while `Range`, `Agility`, `Courage`, both pools and both regeneration loci sat unused. Resolved: Rules 9.3a–9.3e and the **Maturation** locus (`genotype-spec.md` 3.8a).

### Resolved by existing rules, recorded so they are not re-litigated
- [x] Agent mid-journey inside a flooding world is present and dies; passage is instantaneous so there is no third state (`genome-spec.md` Rule 6.1a).
- [x] Both parties broke in a negotiation: neither can counter, so the first offer is take-it-or-leave-it both ways (`execution-spec.md` Rule 5.2b). Coherent.
- [x] Agent whose home world floods while it is abroad: untouched by that flood (Rule 4.11), regenerates into a nascent world if it dies later (Rule 7.2).
- [x] Deposit at the user ceiling is partially accepted and the remainder stays aboard, decaying (`genome-spec.md` Rules 4.19, 4.18).

### Consequent tasks
- [ ] **Berth transfer must be atomic**, on the same two-phase pattern as cargo (`system-spec.md` Rules 5.1, 5.2) — two agents must not both acquire one berth
- [ ] **Boarding is an action with a deadline**: model the race, and the case of a berth bought by an agent that cannot reach the ship in time (Rule 4.10a)
- [ ] Ark manifest allocation against **twelve slots**, priced by kind (Rule 4.3b)
- [x] **Late flood.** Resolved: the countdown is a promise — the flood fires two full days after the countdown actually became visible (calibration 3.0f). Agents lose to the game, never to an outage.
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
