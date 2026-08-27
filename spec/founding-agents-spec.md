# The Founding Agents

**Status:** implemented · `apps/civilization/backend/founders.py`, `apps/civilization/backend/platform_tools.py`, `apps/civilization/backend/autonomy.py`
**Depends on:** agent-graph-spec (registration, versions, lineage), tool-registry-spec (publication, side effects), document-registry-spec (spaces, retrieval)

---

## 1. What a founding roster is for

Every project is created with a set of agents nobody asked for. They exist so
that the project can do something before a human has configured anything: take
in a request, find what it needs, decide what to do, and — the part that was
missing — acquire capabilities it was not born with.

A roster is not a cast list. Each founder exists because some decision has to
have exactly one owner, and the roster is the set of those owners.

---

## 2. What was wrong before

Three findings, all confirmed against a running stack.

**2.1 — There were three rosters, and the one that ran had four members.** The
engine selected by default (`CIVILIZATION_ENGINE_TYPE=GOOGLE_ADK`) provisioned
four scaffold agents whose entire system prompt was *"You are the Genesis Prime
Agent in Google ADK civilization."* A second engine provisioned twenty-eight
richer ones. A third list in `main.py` backed discovery. A user could search for
"The Grand Ledger", see it offered as an archetype, and never find it in their
project — because the running engine had never created it.

**2.2 — No founder could reproduce.** The roster governed, remembered, reasoned
and evaluated. Nothing in it published a tool, an agent version or a pipeline. A
civilisation whose members cannot add a capability executes a fixed repertoire
until someone edits Python.

**2.3 — The founders pinned tools that did not exist.** They named
`mcp-pgvector-search` and `mcp-redis-queue`; nothing had ever registered either.
The agent registry refused every registration under Rule 3.5 — an agent must not
pin what it cannot call — and the refusal was logged at debug level inside a
loop that tried four hosts. A new organisation therefore came up with agents in
post-graph, none in the registry: no versions, no content hashes, no MCP names,
nothing invocable. This was invisible for as long as it existed.

---

## 3. One roster

**Rule 3.1** — `apps/civilization/backend/founders.py` is the only definition of the founding
roster. Both engines and the discovery archetype list derive from it. A second
list is a second civilisation.

**Rule 3.2** — A founder is `{id, name, caste, cog_func, topo, telos, mandate,
inputs, tools, procedure, emits, writes, escalates_to, stops_when, never,
keywords, tokens, duty?}`. The prompt is composed from these; it is not stored
separately, because a prompt and a description of a prompt drift.

**Rule 3.3** — Agent ids in a project are `{founder_id}-{project_id}`. Prompt
lookup accepts either form.

**Rule 3.4** — Castes remain the four the architecture declares: `genesis`,
`archivist`, `architect`, `auditor`.

---

## 4. What every founding prompt states

**Rule 4.1** — Every prompt states nine things, in this order: mandate,
constitutional bindings, what it is given, what it may call, how it decides,
what it emits, what it writes, when it stops or escalates, and what it must
never do. Duty-bearing founders state a tenth: their duty cycle.

**Rule 4.2** — Tools are named by their exact registry id. A prompt that
describes a capability without naming the tool produces an agent that guesses
tool names.

**Rule 4.3** — The output contract is rendered as JSON in the prompt, and the
rendered JSON is the founder's declared `emits` — enforced by test, so the
contract and the prompt cannot diverge.

**Rule 4.4** — Every prompt carries the no-fabrication prohibition verbatim:

> Never invent a result, a citation, a tool output, a signature, a latency or a
> status. If a call failed, say it failed and say what you tried. Another agent
> downstream cannot tell your fabricated evidence from real evidence, and it
> will act on it.

**Rule 4.5** — Every prompt carries the four core directives, rendered from one
constant, so a constitutional change reaches every founder rather than the ones
someone remembered to edit.

**Rule 4.6** — Every prompt states a stopping rule. An agent with no stopping
rule stops when its context does.

Prompts now run 3.1k–5.8k characters. The previous generation averaged 1.0k, of
which none was a tool name, an output schema or a stopping rule.

---

## 5. Intake — one founder receives the prompt first

**Rule 5.1** — Every request entering a project goes to **The Intake Praetor**
before anything else. It chooses one of five routes: `SIMPLE_CHAT`,
`DIRECT_AGENT`, `PIPELINE`, `COMMISSION`, `REFUSE`.

**Rule 5.2** — Routing is a judgement, not a keyword match. The previous ADK
router matched substrings on the raw prompt: a request containing "audit" went
to the ReAct loop and one containing "plan" to the conductor, so *"How do I stop
the auditor?"* was routed by punctuation.

**Rule 5.3** — The Praetor may retrieve before deciding, and reports whether it
did. Routing on a guess about the corpus is the commonest way a request reaches
the wrong agent.

**Rule 5.4** — `REFUSE` is an outcome, and it names the rule that refuses. It
does not answer anyway.

**Rule 5.5** — When the Praetor cannot be reached, the fallback is
`SIMPLE_CHAT`, explicitly labelled as a fallback with `confidence: low`. A
router that cannot be reached must not invent a route silently — everything
downstream inherits it.

---

## 6. The organs of reproduction

**Rule 6.1** — Exactly one founder publishes each kind of thing:

| Publishes | Founder | Refuses to |
| :--- | :--- | :--- |
| A tool version | **The Toolwright** | register an endpoint it has not called successfully |
| An agent version | **The Progenitor** | publish an agent it has not invoked once |
| A pipeline version | **The Conductor** | publish a pipeline with an unpinned stage |
| A document | **The Corpus Librarian** | report a catalogued-only document as filed |

**Rule 6.2** — Each verifies before publishing, and reports what the
verification actually returned. A registered tool that 502s on first use is
worse than an absent one: an agent has already committed to a plan that
includes it.

**Rule 6.3** — Published versions are never edited. A behavioural change is a
version bump, because a published version's content hash is what a pipeline
pins.

**Rule 6.4** — An agent materialised without a named parent descends from the
Progenitor, so lineage always points at a registered agent.

---

## 7. The autonomous founders

**Rule 7.1** — Four founders carry a duty cycle and run without being asked:

| Founder | Interval | Watches | May change |
| :--- | ---: | :--- | :--- |
| **The Anomaly Detector** | 600s | runs against each agent's own baseline | anomaly records; escalations |
| **The Quarantine Warden** | 900s | failure rates, halt reasons, reputation | an agent's lifecycle in the registry |
| **The Proving Ground** | 1800s | published agents against what they promised | reputation; version proposals |
| **The Adversary** | 3600s | conclusions and newly published agents | findings; escalations |

**Rule 7.2** — A duty cycle does four real things: gathers evidence from the
records, asks the founder to judge that evidence with its own registered
prompt, applies the decision through the same registry APIs a person would use,
and records what happened. A prompt describing a loop that nothing schedules is
a description of a system that does not exist.

**Rule 7.3** — Cycles are bounded by the founder's declared
`budget_per_cycle`. A duty that tried to be exhaustive in one pass would starve
the others.

**Rule 7.4** — A quiet cycle is a successful cycle, and is recorded as one. The
failure mode of an autonomous evaluator is manufacturing findings to justify
having run — and unlike a missed finding, a manufactured one gets acted on.

**Rule 7.5** — A cycle with zero subjects makes no model call. An empty project
must not cost tokens every fifteen minutes.

**Rule 7.6** — Founding agents are not subjects. An evaluator that can
quarantine the Arbiter can quarantine the thing that would overrule it.

**Rule 7.7** — Quarantine is dormancy, never deletion: the agent leaves
discovery, and every record and lineage edge below it stays. An agent with
published dependents is escalated to the High Arbiter rather than quarantined
unilaterally.

**Rule 7.8** — The Proving Ground proposes version changes; it does not publish
them. Publication is the Progenitor's and adoption is the Evolution Driver's.
An evaluator that could rewrite published agents on its own judgement has no
check on it.

**Rule 7.9** — Autonomy is configurable: `AUTONOMY_ENABLED` (default true),
`AUTONOMY_TICK_SECONDS` (default 60). A project enters the watchlist when it is
created or explicitly watched. `GET /api/autonomy/status`, `GET
/api/autonomy/cycles` and `POST /api/autonomy/run` expose it.

---

## 8. The seed toolbelt

**Rule 8.1** — A realm is seeded with five tools at project creation, before
any agent is registered: `mcp-pgvector-search`, `mcp-document-ingest`,
`mcp-agent-discovery`, `mcp-tool-discovery`, `mcp-agent-invoke`.

**Rule 8.2** — A founder may only pin a seeded tool. Everything else is
registered by the Toolwright as the civilisation acquires it. Held shut by test.

**Rule 8.3** — Seeded tools are org-scoped, carry real input and output
schemas, declare their side effects honestly (`read` for the three discovery
and retrieval tools, `write` for ingestion and invocation), and store no
credential literal.

**Rule 8.4** — Seeding is idempotent — re-registering an identical version is a
no-op (tool-registry Rule 8.1) — so it runs on every project creation rather
than being a step someone has to remember.

**Rule 8.5** — There is no fallback catalogue. Both engines previously returned
a hardcoded list of five tools when the registry was unreachable, including a
Kubernetes operator and a SQL executor that were registered nowhere. An
unreachable registry now yields no tools and says so.

---

## 9. Is thirty-six enough?

The question worth asking is not how many, but whether the roster closes. It
does when four things are true, and each is now owned:

1. **Something receives.** Intake Praetor.
2. **Something acquires.** Toolwright, Progenitor, Conductor, Corpus Librarian.
3. **Something judges.** Proving Ground, Adversary, Grand Critic, Feedback Loop.
4. **Something removes.** Quarantine Warden, under the High Arbiter's appeal.

Before this work, (2) and (4) had no owner and (1) was a substring match. The
count went from 4 provisioned to 36; the count is not the point — a roster of
four that could publish would have grown, and a roster of a hundred that could
not would not.

What the roster still cannot do, stated plainly rather than left to be
discovered:

- **It cannot acquire a capability requiring a new *kind* of endpoint.** The
  Toolwright registers HTTP POST JSON tools. Anything else needs platform work.
- **It has no economic pressure.** The Resource Sovereign allocates and the
  ledger records, but nothing prices a capability or retires one for being
  unaffordable.
- **It cannot negotiate outside itself.** There is no founder for federation
  with another organisation's civilisation; the A2A surface exists and nobody
  owns using it.
- **Adoption is still centralised.** The Evolution Driver decides alone. A real
  population would have this contested.

---

## 10. Implementation status

Holds today, verified 14 August 2026 against a live stack:

- One roster of 36, both engines, derived archetypes (`apps/civilization/backend/test_founders.py`, 23 assertions).
- Prompts 3.1k–5.8k chars, all nine sections, no-fabrication and the four directives in every one.
- A fresh realm seeds 5 tools and registers 36 founders — previously 0 and 0.
- Intake routes real prompts: arithmetic to `SIMPLE_CHAT`, a four-stage request to `PIPELINE`, with its reasoning recorded.
- Duty cycles run, apply real registry effects, record quiet cycles, and skip empty projects without a model call (`tests/test_e2e_autonomy.py`, 6 assertions).
- Guardrails travel from materialisation through registration to the listing, and the interface shows the real ones.

Not yet built: a frontend view of duty cycles (the API is there); the four gaps
in §9.
