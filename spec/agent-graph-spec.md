# Storing agents and pipelines in a graph database

Specification for the agent.london registry. Target substrate is **post-graph**
on PostgreSQL: vertex and edge tables with JSONB payloads, pgvector embeddings,
realm/space tenancy, and append-only `{table}_data` history.

Companion specifications, sharing this document's tenancy, versioning and
accounting models:

- `tool-registry-spec.md` — the MCP tools an agent version's `tools` list names
- `document-registry-spec.md` — the corpus agents retrieve over

Status: implemented in `services/agent-registry`. Section 11 records design
questions and their resolutions; section 13 records implementation status,
including the defects the end-to-end suite found and the items still
outstanding.

---

## 1. What is being modelled, and why a graph

An **agent** is an atomic executable instance: a system prompt, a model binding,
a tool set, and a declared interface. Agents spawn other agents, so the
population is a growing directed graph whose edges record provenance.

A **pipeline** is a composition of agents. It is not a list — it is a graph whose
nodes are pinned agent versions and whose edges are the dependencies between
them. Pipelines may be **cyclic** (a review step sends work back) and
**recursive** (a pipeline invokes itself, or an agent within it spawns the
pipeline again on a sub-problem).

Three properties make a graph database the right store rather than a
convenience:

1. **Provenance is transitive.** "Which agents descend from this one" and "what
   produced this output" are reachability questions. In a relational schema they
   are recursive CTEs written by hand at every call site; here they are one
   traversal.
2. **Composition is the primary relationship.** A pipeline *is* its edge set.
   Storing it as a JSON blob on a row makes the edges invisible to query — you
   cannot ask "which pipelines use this agent version" without scanning.
3. **Cycles are legitimate data, not corruption.** A store that forbids them
   forces the cycle into application code, where it cannot be inspected.

### 1.1 Non-goals

This specification covers **storage, registration, identity and exposure**. It
does not specify the scheduler, the model router, or the prompt engineering. It
defines what a runtime must record, not how a runtime must be built.

---

## 2. Tenancy

Two levels, mapped directly onto post-graph:

| Concept | post-graph construct | Isolation |
| :--- | :--- | :--- |
| Organisation (`org_id`) | **realm** — its own PostgreSQL schema | Physical. No query crosses a realm. |
| Project (`project_id`) | **space** — a column within the realm | Logical. Queries scope by default, may opt out. |

Every vertex and edge carries both. `realm` is a schema name, so it is validated
as an identifier before use; `space` is data.

**Rule 2.1** — A traversal must pass `space` explicitly. post-graph applies space
filtering per step; a walk that starts correctly scoped but omits the parameter
wanders into another project's subgraph after the first hop.

**Rule 2.2** — Cross-org references are forbidden. A pipeline in `org_a` cannot
pin an agent version in `org_b`. Sharing is by publishing a copy, which records
its origin in `derived_from` (§4.4), not by pointing across a realm boundary.

---

## 3. Vertex tables

Four vertex tables — `agents`, `pipelines`, `prompts`, `pipeline_runs` — each
with its append-only `{table}_data` companion (§3.2). All carry `realm`,
`space`, `id`, `uuid`, `payload` (JSONB), `created_at`, `updated_at`.

`agents` and `pipelines` additionally carry `embedding` (`vector(1536)`),
because those are the two things discovery searches over (§10). `prompts` and
`pipeline_runs` do not: a run is reached from its definition or its id, never
by similarity, and a vector column on a table that grows one row per execution
is an index nothing queries.

### 3.1 `agents` — the stable identity

One vertex per agent, for the life of the agent. It holds what does **not**
change between versions.

```jsonc
{
  "agent_id": "agt_researcher_7f3a",     // stable, immutable, globally unique
  "name": "Corpus Researcher",
  "slug": "corpus-researcher",           // unique per (realm, space); URL and MCP safe
  "caste": "genesis" | "archivist" | "economist" | "judicature"
         | "architect" | "task_workforce" | "auditor",
  "role":  "permanent_governor" | "permanent_creator" | "permanent_inspector"
         | "permanent_conductor" | "permanent_react" | "worker",
  "telos": "One sentence: what this agent exists to do.",
  "description": "Prose. Embedded for semantic discovery.",
  "owner": "user_id or agent_id of the spawner",
  "current_version": "3.1.0",            // pointer into agents_data; see §3.2
  "lifecycle": "active" | "deprecated" | "dormant",
  "created_at": "2026-08-13T09:00:00Z"
}
```

`caste` and `role` are two independent axes and are often collapsed by mistake.
**Caste** is what part of the civilisation an agent belongs to — governance,
memory, economics, adjudication, design, work, oversight. **Role** is its
standing within that caste, and the `permanent_` prefix marks an agent the
population does not garbage-collect. Neither says anything about provenance:
whether an agent was spawned by another is recorded by the `spawns` edge (§5),
not by a field, because provenance is transitive and a field cannot be
traversed.

`embedding` is computed from `name + telos + description + capability names`. This
is what makes "find me an agent that can summarise filings" work without a
keyword index.

**Rule 3.1** — `agent_id` is never reused, and never changes. Renaming an agent
changes `name`, not identity.

**Rule 3.2** — Deletion is dormancy. An agent whose last referencing pipeline is
removed is marked `lifecycle: dormant` and excluded from discovery. It is not
deleted, because its `spawns` edges are the provenance record of everything
below it.

### 3.2 Versions live in `agents_data`, not in a separate vertex table

post-graph gives every vertex table an append-only companion, `{table}_data`,
written with `add_vertex_data()` and read with `get_vertex_data()` /
`get_latest_vertex_data()`. **That is what a version is**, so versions are stored
there rather than duplicated as vertices.

This is not merely a saving. A separate `agent_versions` vertex table would need
its own uniqueness constraints, its own `has_version` edges, and its own
ordering column — all of which `{table}_data` already provides and enforces, and
all of which could drift out of step with the identity vertex. Append-only is
also the property Rule 3.3 needs: history cannot be rewritten in place.

- `agents` — one vertex, the stable identity (§3.1)
- `agents_data` — one record per version, append-only, immutable once published
- `pipelines` / `pipelines_data` — the same pairing (§3.4)
- `prompts` / `prompts_data` — system prompts versioned independently (§3.2.1)

**The consequence for edges is the important part.** Edges connect *vertices*,
not data records, so an edge cannot point at a version directly. A pipeline that
pins an agent version therefore carries the pin in the **edge payload**:

```jsonc
// composes_pipeline: pipelines -> agents
{
  "step_id": "step_extract",
  "agent_version": "2.0.1",           // the pin — resolved against agents_data
  "content_hash": "sha256:…",         // what was pinned, verifiable later
  "pipeline_version": "2.0.0"         // which version of the pipeline pinned it
}
```

Resolution is then: follow the edge to the `agents` vertex, read
`agents_data` for that vertex, select the record whose `version` matches the
edge's `agent_version`. One hop plus one indexed history read.

**Rule 3.2a** — An edge that pins a version must record `content_hash` alongside
it. The version string says *which* record; the hash proves the record has not
been altered since it was pinned, which is the guarantee a reproducible run
actually needs.

#### 3.2.1 The version record

One record per version, in `agents_data`. **This is what pipelines pin and what
execution resolves.** An agent vertex with no version record is not executable.

```jsonc
{
  "version_id": "agv_researcher_7f3a_3.1.0",
  "agent_id": "agt_researcher_7f3a",
  "version": "3.1.0",                    // semver, §4
  "content_hash": "sha256:…",            // §4.2
  "system_prompt": "…",
  "model": {
    "name": "DeepSeek-V3.2",
    "api_base": "http://litellm…/v1",
    "params": {"temperature": 0.2, "max_tokens": 2048},
    "fallback_models": ["MiniMax-M2.7"]
  },
  "tools": [                                              // resolved pins; see tool-registry-spec §4.3
    {"tool_id": "mcp-google-search", "version": "1.2.0", "content_hash": "sha256:…"},
    {"tool_id": "mcp-pgvector-search", "version": "0.9.1", "content_hash": "sha256:…"}
  ],
  "input_schema":  { "$schema": "…", "type": "object", … }, // JSON Schema, required
  "output_schema": { "$schema": "…", "type": "object", … }, // JSON Schema, required
  "capabilities": ["summarise", "cite", "retrieve"],
  "resource_limits": {"max_tokens": 100000, "max_wall_secs": 300, "max_spawns": 8},
  "status": "draft" | "published" | "deprecated" | "revoked",
  "published_at": "2026-08-13T09:00:00Z",
  "changelog": "What changed from the previous version and why."
}
```

**Rule 3.3** — A version with `status: published` is **immutable**. Any change
produces a new version. Enforced by `content_hash`: on write, the registry
recomputes it and rejects a mismatch against a published version.

**Rule 3.4** — `input_schema` and `output_schema` are **required**, not optional.
They are what makes MCP exposure (§7) mechanical rather than hand-written, and
what lets a pipeline edge be validated at registration instead of at runtime.

**Rule 3.5** — `tools` holds resolved pins — `tool_id`, `version`,
`content_hash` — not bare ids, and it is inside `content_hash` (§4.2). A bare
id is a reference to whatever that tool currently is, so an agent's hash would
certify a behaviour that changes when someone edits a tool's endpoint or input
schema. The resolution happens at registration, against the tool registry
(`tool-registry-spec.md` §4.3), and fails the registration if a named tool is
missing, unpublished, revoked, or out of scope for this `(realm, space)`.

### 3.3 `pipelines` — the stable identity

Mirrors `agents`.

```jsonc
{
  "pipeline_id": "pln_filing_analysis_2c9d",
  "name": "Filing Analysis",
  "slug": "filing-analysis",
  "telos": "…",
  "description": "…",                    // embedded
  "owner": "…",
  "current_version": "2.0.0",
  "lifecycle": "active" | "deprecated" | "dormant"
}
```

### 3.4 Pipeline versions live in `pipelines_data`

Same pattern as §3.2: one `pipelines` vertex for the stable identity, one
append-only record per version in `pipelines_data`. The record below is the
payload of that record, not of a vertex.

```jsonc
{
  "pipeline_version_id": "plv_filing_analysis_2c9d_2.0.0",
  "pipeline_id": "pln_filing_analysis_2c9d",
  "version": "2.0.0",
  "content_hash": "sha256:…",
  "entry_steps": ["step_ingest"],        // one or more; where a run begins
  "exit_steps": ["step_report"],         // where a run may terminate
  "steps": {                             // step_id -> binding
    "step_ingest":  {"version_id": "agv_ingest_a1b2_1.4.0", "alias": "ingest"},
    "step_extract": {"version_id": "agv_extract_c3d4_2.0.1", "alias": "extract"},
    "step_review":  {"version_id": "agv_review_e5f6_1.0.0", "alias": "review"},
    "step_report":  {"version_id": "agv_report_g7h8_3.2.0", "alias": "report"}
  },
  "execution": {                         // §6
    "max_iterations": 25,
    "max_recursion_depth": 3,
    "on_limit": "fail" | "halt_and_return",
    "concurrency": 4
  },
  "context_policy": { … },               // §8.2
  "input_schema":  { … },                // the pipeline's own external contract
  "output_schema": { … },
  "status": "draft" | "published" | "deprecated" | "revoked",
  "published_at": "…",
  "changelog": "…"
}
```

`steps` is a map, and step identity is the **step_id, not the agent_id**. This is
what allows the same agent version to appear twice in one pipeline as two
distinct nodes — a reviewer that runs both before and after a rewrite is one
agent version and two steps.

### 3.5 `pipeline_runs` — an instance of an execution

Definitions are immutable; runs are where the mutable state lives. Separating
them is what keeps a cyclic definition finite (§6).

```jsonc
{
  "run_id": "run_01J…",
  "pipeline_version_id": "plv_…_2.0.0",
  "parent_run_id": "run_01J…" | null,    // set for recursive invocations
  "depth": 0,                            // recursion depth; parent.depth + 1
  "trigger": {"kind": "mcp" | "a2a" | "schedule" | "agent", "by": "…"},
  "status": "queued" | "running" | "succeeded" | "failed" | "halted",
  "iteration_count": 0,                  // edge traversals; §11.2
  "retry_count": 0,                      // redeliveries; §11.2
  "compute_units": 0,                    // running total for this run; §11.4
  "started_at": "…", "ended_at": "…",
  "input": { … }, "output": { … },
  "error": {"step_id": "…", "type": "…", "message": "…"} | null,
  "halt_reason": "…" | null              // set iff status = halted; §11.5
}
```

`halt_reason` is a field on the run, not something reconstructed at the
protocol edge. A2A reports a halted run as `failed` and needs the reason to
attach (§11.5); MCP reports it as an error and needs the same string. Deriving
it twice from `status` plus `error` is how the two surfaces come to disagree
about why a run stopped.

### 3.6 Shared context lives in `pipeline_runs_data`, not its own table

Context is per-run, append-only, and only ever read in the context of its run —
which is exactly the shape `{table}_data` already provides against the run
vertex. A separate `context_entries` table would need its own run foreign key,
its own revision ordering and its own retention rule, all of which the data
companion enforces already.

Each record is tagged by `kind` so the run's history holds both context writes
and the conflicts detected between them (Rule 8.6):

```jsonc
// kind: "context" — one record per revision, never per key
{"kind": "context", "key": "extracted_entities", "value": { … },
 "written_by": "step_extract", "revision": 3, "written_at": "…"}

// kind: "conflict" — Rule 8.6, recorded rather than inferred
{"kind": "conflict", "key": "extracted_entities",
 "previous_writer": "step_a", "writer": "step_b"}
```

**Rule 3.6** — Every revision is written, not just the final value of each key.
Collapsing to a snapshot makes a cyclic run's second iteration
indistinguishable from its first, which removes the only evidence available
when a cycle produces a different answer than it did on the previous pass.

---

## 4. Versioning

### 4.1 Scheme

Semver `MAJOR.MINOR.PATCH`, with meaning defined against the **schemas**, since
that is the only part a caller can depend on mechanically:

| Bump | Trigger |
| :--- | :--- |
| **MAJOR** | `input_schema` or `output_schema` changes incompatibly; a capability is removed |
| **MINOR** | Capability added; optional schema field added; model changed; tools added |
| **PATCH** | Prompt wording, parameters, fallback list, description |

**Rule 4.1** — A prompt change is at least a PATCH. There is no such thing as an
unversioned edit to a published agent: the prompt *is* the behaviour.

### 4.2 Content hash

```
content_hash = sha256(canonical_json({
    system_prompt, model, tools, input_schema, output_schema,
    capabilities, resource_limits, invokes_pipeline
}))
```

`invokes_pipeline` is in the hash because an agent that calls a pipeline
behaves differently from one that does not (§6.3), and the hash is the record
of what an agent version *does*.

Canonical JSON: keys sorted, no insignificant whitespace, UTF-8. The hash covers
what determines behaviour and excludes what does not (`description`,
`changelog`, timestamps).

**Rule 4.2** — Two published versions of the same agent with equal
`content_hash` are an error at registration. The caller either meant to bump
nothing (reuse the existing version) or changed something excluded from the
hash — both are worth an error rather than a duplicate.

### 4.3 Resolution

Pipelines pin **exact versions**, never ranges.

**Rule 4.3** — `steps[*].version_id` must resolve to a `published` version at
pipeline publish time. Pinning a `draft` is rejected.

The registry resolves a human reference (`corpus-researcher@3.1.0`, or
`corpus-researcher@latest`) to a `version_id` **at publish time** and stores the
resolved identifier. `@latest` is a convenience for authors, never a stored
value: a pipeline whose behaviour changes because a dependency was republished
is not reproducible, and its run history becomes uninterpretable.

### 4.4 Deprecation and revocation

- `deprecated` — still resolvable, still runnable, excluded from discovery, and
  warned on at publish time. Existing pipelines keep working.
- `revoked` — not runnable. A run that resolves a revoked version fails at
  resolution with a message naming the revoked version and its replacement.

**Rule 4.4** — Revoking a version that published pipelines pin requires either
`--cascade` (which marks those pipeline versions revoked too, transitively) or
an explicit `replacement_version_id`. Silent revocation would break pipelines
that report success.

---

## 5. Edge tables

All edges carry `realm`, `space`, `from_id`, `to_id`, `relation_type`, `payload`.
Endpoints are typed, and foreign keys are composite `(realm, from_id) → (realm,
id)` with `ON DELETE CASCADE`.

| Edge table | From → To | `relation_type` | Meaning |
| :--- | :--- | :--- | :--- |
| `spawns` | `agents` → `agents` | `spawned` | Provenance. Who created whom. |
| `composes_pipeline` | `pipelines` → `agents` | `contains_step` | Membership. Payload pins the version (§3.2). |
| `pipeline_step_dependency` | `agents` → `agents` | *the relationship* | The pipeline's edges. See below. |
| `invokes_pipeline` | `agents` → `pipelines` | `invokes` | Recursion and nesting (§6.3) |
| `derived_from` | `agents` → `agents` | `derived_from` | Fork/copy lineage, incl. cross-org publishing |
| `run_of` | `pipeline_runs` → `pipelines` | `run_of` | A run to its definition |
| `run_step` | `pipeline_runs` → `agents` | `executed_step` | What actually ran, with timings |

There is no `has_version` edge: `{table}_data` *is* the identity-to-versions
relationship, and duplicating it as edges would create two records of the same
fact that can disagree. Every edge above whose meaning depends on a particular
version carries `{"agent_version": …, "content_hash": …}` in its payload.

### 5.1 `pipeline_step_dependency` is scoped to a pipeline version

The same two agent versions may be connected in several pipelines, differently.
The edge therefore carries the owning pipeline version, and **every query over
pipeline structure must filter on it**:

```jsonc
{
  "pipeline_version_id": "plv_…_2.0.0",   // REQUIRED. The scope of this edge.
  "from_step": "step_extract",            // step_ids, not agent_ids — see §3.4
  "to_step":   "step_review",
  "relationship": "depends_on" | "on_success" | "on_failure" | "on_condition",
  "condition": "…",                       // when relationship = on_condition
  "payload_map": {"…": "…"},              // output field -> input field
  "is_back_edge": false                   // §6.1
}
```

**Rule 5.1** — `relation_type` is the relationship, and is **required**. This is
not a formality: `add_edge` takes `relation_type` as a required parameter, and
omitting it raises `TypeError`. Where that has been caught and discarded, edges
silently fail to be written and the pipeline appears to register successfully
with no dependencies at all.

**Rule 5.2** — `from_step` and `to_step` must both exist in the owning
`pipeline_version.steps`. Validated at publish, not at run.

---

## 6. Cyclic and recursive pipelines

### 6.1 Cycles

Cycles are permitted and are first-class. post-graph's `add_edge` accepts
`check_cycle`; pipeline dependency edges are written with `check_cycle=False`
deliberately.

An edge that closes a cycle is marked `is_back_edge: true`. This is computed at
publish time by a depth-first search from `entry_steps`: an edge to a step
already on the current DFS stack is a back edge. It is stored rather than
recomputed because it is a property of the definition, and every run needs it.

**Rule 6.1** — A pipeline containing at least one back edge **must** declare
`execution.max_iterations`. Publishing a cyclic pipeline without a bound is
rejected. An unbounded cycle is not a pipeline; it is a way to exhaust a budget
silently.

**Rule 6.2** — Every cycle must be able to terminate, which means either an edge
leaving the cycle to a step outside it, or a conditional edge
(`on_condition` / `on_success` / `on_failure`) inside it that may not fire. A
cycle built only from unconditional edges with no exit runs to the iteration cap
on every execution, and is statically detectable at publish time.

Iteration is counted **per run, across the whole graph**, in
`pipeline_runs.iteration_count`. On reaching `max_iterations`, behaviour follows
`execution.on_limit`:

- `fail` — run ends `failed`, error names the limit and the step that hit it.
- `halt_and_return` — run ends `halted`, returning the context so far. Distinct
  from `succeeded`, so a caller cannot mistake exhaustion for completion.

**Rule 6.3** — `halted` is never reported as success at any layer, including MCP
and A2A responses.

### 6.2 Traversal safety

Reading a cyclic pipeline back out is itself a cycle risk. post-graph's
`traverse()` bounds depth via `max_depth`; the registry always passes it.

**Rule 6.4** — Any traversal over `pipeline_step_dependency` passes both
`max_depth` and a `relation_types` filter. Reading the full structure of a
cyclic pipeline uses the stored step and edge sets — a bounded query over the
owning `pipeline_version_id` — rather than a walk.

### 6.3 Recursion

A pipeline invokes itself when a step's agent version has an `invokes_pipeline`
edge to a pipeline version — including its own.

Recursion is bounded by `execution.max_recursion_depth`, enforced on
`pipeline_runs.depth`, which is `parent.depth + 1`. The chain of `parent_run_id`
gives the stack.

**Rule 6.5** — Depth is enforced at **run creation**, before the child run does
any work. Enforcing it on completion means the work is already spent.

**Rule 6.6** — A recursive invocation inherits `run_id` as `parent_run_id` and
starts a *new* context scope (§8.2), unless the pipeline declares
`context_policy.inherit: true`. Sharing a mutable context bag between a parent
and its own recursive children is how a recursion corrupts its own inputs.

---

## 7. Exposure: MCP and A2A

Every **published** agent version and pipeline version is exposed over both
protocols. Neither is a wrapper around the other; they answer different
questions. MCP asks *what can I call*; A2A asks *who can I delegate to*.

### 7.1 MCP

Each published version becomes one MCP tool.

| MCP field | Source |
| :--- | :--- |
| `name` | `agent:{slug}@{version}` / `pipeline:{slug}@{version}` |
| `description` | `telos` + `description` + capability list |
| `inputSchema` | `input_schema`, verbatim |

**Rule 7.1** — The MCP tool name embeds the exact version. A caller that pinned
`agent:corpus-researcher@3.1.0` keeps calling 3.1.0 after 3.2.0 publishes. An
unversioned alias `agent:{slug}` resolving to `current_version` is also exposed,
and is explicitly documented as unstable.

**Rule 7.2** — `inputSchema` is the stored schema unmodified. A hand-maintained
second copy drifts, and the drift shows up as a validation failure the caller
cannot diagnose.

Registry endpoints:

```
GET  /mcp/tools                     # tools/list, all published versions
POST /mcp/tools/{name}/call         # tools/call -> creates a run
```

### 7.2 A2A

Each published version gets an agent card.

```
GET /.well-known/agent.json                    # this registry's own card
GET /a2a/agents/{slug}/{version}/card
GET /a2a/pipelines/{slug}/{version}/card
```

```jsonc
{
  "name": "Corpus Researcher",
  "description": "…",
  "url": "https://…/a2a/agents/corpus-researcher/3.1.0",
  "version": "3.1.0",
  "capabilities": {"streaming": true, "pushNotifications": false},
  "skills": [{"id": "summarise", "name": "…", "description": "…",
              "inputModes": ["text"], "outputModes": ["text"]}],
  "provenance": {                                // beyond the A2A baseline
    "agent_id": "agt_…", "content_hash": "sha256:…",
    "spawned_by": "agt_…", "pipeline_versions_using": 3
  }
}
```

A2A task lifecycle maps onto `pipeline_runs`: `submitted → working →
completed | failed | canceled` mirrors `queued → running → succeeded | failed |
halted`, with `halted` surfacing as `failed` plus a `halt_reason` (Rule 6.3).

**Rule 7.3** — A pipeline is exposed as **one** A2A agent, not as its members.
Its internal steps are an implementation detail; a caller delegates to the
pipeline and receives one result.

**Rule 7.4** — Exposure is derived from the registry, never hand-registered. A
version that is published is callable; one that is not, is not. Two lists that
can disagree will.

---

## 8. Redis transport and shared context

### 8.1 Channels

```
agent:run:{run_id}:step:{step_id}        # work handed to a step
agent:run:{run_id}:events                # ordered run event log (fan-out)
agent:run:{run_id}:control               # cancel, pause
agent:pipeline:{pipeline_version_id}     # definition-level broadcast
```

Envelope:

```jsonc
{
  "msg_id": "01J…",             // ULID; monotonic, dedup key
  "run_id": "run_01J…",
  "from_step": "step_extract",
  "to_step": "step_review",
  "attempt": 1,
  "sent_at": "…",
  "payload": { … },             // validated against to_step's input_schema
  "context_ref": "ctx_…"        // §8.2, a reference — never the context itself
}
```

**Rule 8.1** — Redis carries *messages*, not state. A message references context
by id. Redis is not the system of record; post-graph is. A Redis flush must cost
in-flight work, never committed history.

**Rule 8.2** — Delivery is at-least-once, so every step must be idempotent on
`msg_id`. Processed ids are recorded per run.

**Rule 8.3** — A step that cannot deliver to a **configured** Redis fails the
run. It does not fall back to publishing nothing and carrying on: that produces
a run whose event log is missing steps that did happen, which is worse than a
failure, because anything reading the log treats absence as "did not run".

Redis being configured at all is a deployment choice. With no `REDIS_URL` the
transport is a declared no-op, runs execute, and no event stream is published —
a cache outage cannot stop the registry serving. The distinction matters and is
easy to lose: **no transport** is a mode the operator chose, **a broken
transport** is a failure, and the second must not be silently rendered as the
first. A registry that starts with Redis configured and later cannot reach it
fails runs; it does not quietly degrade into the no-transport mode.

### 8.2 Shared context

Context is a per-run key/value store, written through post-graph as append-only
records against the run vertex (§3.6) so it is durable and auditable, and cached
in Redis for latency.

```jsonc
{
  "kind": "context",
  "scope": "run" | "branch" | "step",
  "key": "extracted_entities",
  "value": { … },
  "written_by": "step_extract",
  "written_at": "…",
  "revision": 3
}
```

The record carries no `run_id` or `context_id` of its own: it is a data record
*of* the run vertex, so the association is the foreign key rather than a field
that could disagree with it.

Access is declared per step in the pipeline version:

```jsonc
"context_policy": {
  "inherit": false,                    // §6.6
  "default": "read",
  "steps": {
    "step_extract": {"read": ["source_docs"], "write": ["extracted_entities"]},
    "step_review":  {"read": ["extracted_entities"], "write": ["review_notes"]}
  }
}
```

**Rule 8.4** — A step may read only declared keys and write only declared keys.
An undeclared write is an error, not a silent no-op. Without this, a cyclic
pipeline's second iteration reads values its first iteration wrote by accident,
and the coupling is invisible in the definition.

**Rule 8.5** — Writes are append-only with an incrementing `revision`. A step in
a cycle overwriting a key does not destroy the prior value; the run's audit
trail keeps every revision. This is what makes a cyclic run debuggable.

**Rule 8.6** — Concurrent writes to the same key from concurrent steps are
resolved last-writer-wins **and logged as a conflict**. Silent interleaving in a
concurrent pipeline is not reproducible.

---

## 9. Registration

`POST /agents` and `POST /pipelines` are the only ways structure enters the
graph.

Rejected at registration — each of these is cheaper to catch here than to debug
in a run:

1. Missing `input_schema` or `output_schema` (Rule 3.4)
2. A `content_hash` colliding with an existing published version (Rule 4.2)
3. A step pinning an unpublished, revoked or non-existent version (Rule 4.3)
4. A dependency edge naming a `from_step`/`to_step` not in `steps` (Rule 5.2)
5. A cyclic pipeline with no `max_iterations` (Rule 6.1)
6. A cycle with no conditional exit (Rule 6.2)
7. A `payload_map` whose source field is absent from the upstream
   `output_schema`, or whose target is absent from the downstream `input_schema`
8. A cross-realm `version_id` (Rule 2.2)
9. A slug that is not unique within `(realm, space)`
10. A `tools` entry naming a tool that is missing, unpublished, revoked, or out
    of scope for this `(realm, space)` (Rule 3.5)

**Rule 9.1** — A partially-written pipeline must never be **resolvable**. A
pipeline missing some of its edges is one that runs and produces a plausible
wrong answer, which is the failure this rule exists to prevent.

One transaction would give this, but post-graph opens a transaction per public
call, so `add_vertex` plus N x `add_edge` cannot be wrapped in one without
re-implementing both against a raw connection. The guarantee is therefore met
by **ordering** instead:

1. upsert the identity vertex
2. append the version record with `status: "draft"`
3. write every edge
4. append the same record again with `status: "published"`

Version records are append-only and the newest wins, so a failure anywhere
between 2 and 4 leaves the newest record saying `draft` — and a draft cannot be
pinned (Rule 4.3), is not discoverable (Rule 10.1) and is not exposed over MCP
or A2A (Rule 7.4). The half-written pipeline is inert rather than silently
live, and its orphaned edges are unreachable for the same reason.

This is a weaker guarantee than atomicity in one specific way, and it is worth
naming: a failed registration leaves rows behind. They are unreferenceable, but
they are there, and a garbage collector for draft records older than some
threshold is the missing piece rather than an optimisation.

**Rule 9.2** — Registration failures raise. They do not log and return the
object. A registry that reports success for a write it did not perform is
indistinguishable, to every caller, from one that worked.

---

## 10. Discovery

- **By vector** — `agents.embedding` and `pipelines.embedding` over telos and
  description. This is the path used when an orchestrator asks for "an agent
  that can reconcile invoices".
- **By capability** — exact match on `capabilities`, a GIN index on the payload.
- **By structure** — "pipelines using this agent version" is one hop backwards
  along `composes_pipeline`; "everything descended from this agent" is a bounded
  `traverse()` over `spawns`.

**Rule 10.1** — Discovery returns only `published`, non-`deprecated`,
`lifecycle: active` entries unless the caller explicitly asks otherwise.

---

## 11. Resolved design questions

Each of these was open in the first draft. They are recorded with their
resolution because the reasoning is the useful part.

### 11.1 Cross-org publishing

**Resolved: publish by copy, with lineage.** §2.2 forbids cross-realm edges, and
a realm is a PostgreSQL schema, so a reference across one is not merely
discouraged — it cannot carry a foreign key. Sharing an agent between
organisations therefore copies the version record into the target realm and
writes a `derived_from` edge **within** that realm, pointing at a local stub
that records the origin realm, agent id, version and `content_hash`.

The hash is what makes the copy honest: it proves the two are the same
extraction without requiring a live link the schema cannot express. A copy that
diverges is a new version with its own hash, which is exactly the signal a
consumer needs.

### 11.2 Retries versus cycles

**Resolved: separate counters.** A retried step and a one-node cycle looked
identical in `iteration_count`, which made an iteration budget uninterpretable —
a pipeline could exhaust its cycle allowance on transport retries. `pipeline_runs`
therefore carries `retry_count` alongside `iteration_count`, and only edge
traversals increment the latter. A step re-executed for the same `msg_id`
(Rule 8.2) is a retry; a step reached again along an edge is an iteration.

### 11.3 Context value schemas

**Resolved: optional per-key schemas, validated on write.** `context_policy`
gains an optional `schemas` map from key to JSON Schema. Where a key has one, a
write that fails validation raises rather than storing — consistent with Rule
8.4, which already makes an undeclared write an error. Where a key has none,
values are unvalidated, because requiring a schema for every scratch value
would push authors toward one untyped bag key to avoid the ceremony.

### 11.4 Run-level cost accounting

**Resolved: §12 plus a per-run budget.** `resource_limits` remains per agent
version. `execution` gains an optional `max_compute_units` covering the whole
run *including* recursive children, enforced against the ledger's running total
for the run tree before dispatching a step — the same before-the-work rule as
iteration and depth (Rule 6.5). Exceeding it ends the run `halted`, never
`succeeded` (Rule 6.3).

### 11.5 A2A partial results for a halted run

**Resolved: `failed` with a halt reason.** A2A has no state meaning "stopped
early but produced something", and inventing one would not be understood by
standard clients. A halted run therefore surfaces as `failed` with
`halt_reason` and the partial context attached as an artifact. Mapping it to
`completed` was rejected outright: a client that reads a partial result as a
complete one is the precise failure Rule 6.3 exists to prevent, and it would be
undetectable from the caller's side.

---

## 12. Accounting and metering

Usage is accounted **per organisation**, which is already the realm boundary
(§2), so accounting inherits the isolation the graph enforces rather than
re-deriving it.

### 12.1 What is measured

| Metric | Unit | Where it is captured |
| :--- | :--- | :--- |
| **Bytes processed** | bytes | document ingestion, RAG lookup, room use, search query, search results |
| **Tokens** | count | `input`, `output`, and `total` per LLM call |
| **Compute units** | derived | `total_tokens x 4` |

Bytes are counted per *operation kind*, so ingestion and retrieval are separable
in the ledger — they have very different cost profiles and are worth billing
apart.

Each kind has exactly one owning service, and the ledger is only complete when
all three emit:

| `kind` | Emitted by | Specified in |
| :--- | :--- | :--- |
| `llm_call` | agent registry — every model call in a step or an agent invocation | §12.3 |
| `document_ingest` | document registry — after successful extraction | document-registry-spec §9 |
| `rag_lookup` | document registry — after a successful query | document-registry-spec §9 |
| `search_query` | tool registry — before dispatching a search | tool-registry-spec §11 |
| `search_results` | tool registry — after a successful search | tool-registry-spec §11 |
| `room_use` | backend — shared-memory room occupancy | not yet specified |

**Rule 12.0** — A kind has one emitter. Two services emitting the same kind for
the same operation double-bills, and the duplicate is undetectable in the
ledger because both rows are individually correct.

**Rule 12.1** — Compute units are `total_tokens * 4`, stored as a derived
column at write time rather than computed at read. The multiplier will change;
recomputing history under a new multiplier would silently restate past
invoices.

### 12.2 Where it is stored, and why not Prometheus

The telemetry stack at `marty/infra/telemetry` runs Prometheus with
Kubernetes pod service discovery, Loki and Grafana. Two properties of that
deployment decide the design:

```yaml
--storage.tsdb.retention.time=7d      # 01-prometheus.yaml
volumes: [{ emptyDir: {} }]           # storage is a pod-local scratch dir
```

**Seven days of retention, on `emptyDir`.** The data is deleted when the pod
restarts. That is entirely appropriate for dashboards and alerts, and
disqualifying for an accounting ledger — a month-end invoice cannot be derived
from a store that forgets on reschedule. Prometheus is also lossy by design:
scrape intervals sample, counters reset on restart, and `rate()` interpolates.
Those are the right trade-offs for observability and the wrong ones for money.

Cardinality is the second objection. `org_id` as a Prometheus label is fine for
tens of organisations and becomes a cardinality problem at thousands — and the
number of organisations is exactly the dimension expected to grow.

So the split is:

| | System of record | Observability |
| :--- | :--- | :--- |
| **Store** | post-graph (`usage_events`) | Prometheus, via existing scrape |
| **Guarantee** | exact, durable, append-only | sampled, ephemeral, 7 days |
| **Answers** | "what does org X owe for March" | "what is the token rate right now" |
| **Cost to add** | one table | one annotation, zero infrastructure |

post-graph is a defensible time-series store *for this shape of data*: the
volume is one row per operation rather than per scrape, it is append-only by
construction, `realm` gives per-tenant physical isolation, and the same
database already holds the graph the usage refers to — so "which agent version
burned these tokens" is a join, not a correlation across two systems.

**Option (z), OpenTelemetry, is not adopted.** There is no collector in the
stack, so it would mean deploying and operating a new component. Prometheus
already scrapes any pod carrying `prometheus.io/scrape`, which is the same
outcome with nothing new to run. OTel becomes worth revisiting when traces are
wanted alongside metrics; it buys nothing for counters.

### 12.3 `usage_events`

```jsonc
{
  "event_id": "01J…",          // ULID, idempotency key
  "org_id": "org_…",           // realm — the accounting boundary
  "project_id": "proj_…",      // space
  "occurred_at": "…",          // event time, not write time
  "kind": "document_ingest" | "rag_lookup" | "room_use" | "search_query"
        | "search_results" | "llm_call",
  "bytes": 20481,
  "tokens_input": 1200, "tokens_output": 380, "tokens_total": 1580,
  "compute_units": 6320,       // tokens_total * 4, stored (Rule 12.1)
  "agent_id": "agt_…", "agent_version": "3.1.0",
  "pipeline_id": "pln_…", "run_id": "run_…",
  "model": "DeepSeek-V3.2"
}
```

**Rule 12.2** — Metering never blocks the operation it measures. Events go to an
in-process queue and are flushed in batches by a background task. A metering
failure degrades accounting, and must never degrade throughput or fail a user's
request.

**Rule 12.3** — The queue is **bounded**, and overflow is counted and logged,
never silently dropped. An unbounded queue turns a slow database into an
out-of-memory kill; a silent drop turns it into an undetectable revenue leak.

**Rule 12.4** — Events carry `occurred_at` from the moment of the operation, not
the moment of the flush. Batching otherwise smears usage across period
boundaries, and month-end is a period boundary.

---

## 13. Implementation status

This document is a specification, and `services/agent-registry` now implements
it. What follows records what changed, because several of these were places
where reading the spec gave a confident and wrong answer about what the system
did.

### 13.1 Mechanisms that were specified with no implementation

All now implemented:

| Was missing | Now |
| :--- | :--- |
| Recursion (§6.3) | `invokes_pipeline` edges are written at publish, carried onto the step binding, and followed by the executor mid-run. Depth is enforced at run creation (Rule 6.5), and a nested run's compute units count against the parent's budget (§11.4). |
| `derived_from`, `run_of`, `run_step` (§5) | Created and written. A cross-org copy points at a local origin stub carrying the origin realm, agent id, version and hash (§11.1). |
| Discovery (§10) | `GET /discover` by vector or by capability, `GET /agents/{id}/descendants` as a bounded `traverse()` over `spawns`, `GET /agents/{id}/dependents` as one hop back along `composes_pipeline`. Embeddings are computed at registration. |
| `prompts` / `prompts_data` (§3.2) | Written. One vertex per agent, one record per *distinct* prompt — an unchanged prompt appends nothing. |
| Revocation and deprecation (§4.4) | `POST /agents/{id}/retire` and the pipeline equivalent. Revoking a pinned version requires a replacement or an explicit cascade (Rule 4.4). |
| `@latest` (§4.3) | Resolved at publish time; the *resolved* id is stored, never `@latest`. |
| `GET /.well-known/agent.json` (§7.2) | Served. |
| `resource_limits` (§3.2.1) | `max_wall_secs` is carried onto the step binding and enforced per step. |
| `trigger` and `input` (§3.5) | Populated on every run, from the protocol edge that started it. |
| `execution.concurrency` (§3.4) | Honoured. Independent steps dispatch in batches, bounded by the iteration limit so a wide batch cannot overshoot. |
| `context_policy.schemas` (§11.3) | Validated on write. A key with no schema stays unvalidated, by design. |

### 13.2 Rules the code contradicted

All now hold, and each has a regression test:

1. **Rule 6.6** — `inherit` built an identical fresh context in both arms of its
   branch, so declaring it changed nothing. A child now shares the parent's
   context only when the pipeline opts in, and gets a fresh scope otherwise.
2. **Rule 8.2** — `msg_id` was generated per envelope and never checked.
   Processed ids are recorded per run, a redelivery is a no-op, and a retry
   reuses the id of the message it is retrying so the dedup set can recognise
   it. `retry_count` is incremented and counted separately from
   `iteration_count` (§11.2).
3. **Agents can be drafts.** The status is no longer overwritten
   unconditionally, so the state Rule 4.3 depends on is reachable: a version can
   be staged, reviewed, and only then published.
4. **§9 rejections 8 and 9** — slug uniqueness within `(realm, space)` and
   cross-realm version ids are both enforced.
5. **§9 rejection 10** — an agent's `tools` are resolved against the tool
   registry to `{tool_id, version, content_hash}` *before* the content hash is
   computed (Rule 3.5). A missing, unpublished, revoked or out-of-scope tool
   fails the registration.

Two further defects were found while implementing and are fixed:

- **Semver was compared lexically**, so `@latest` and unpinned resolution would
  have started returning `1.9.0` over `1.10.0` once a minor number reached
  double digits — silently, and only for projects that had been going long
  enough.
- **A nested run that failed left the parent reporting `succeeded`.** A step
  whose invoked pipeline fails now fails the run, unless the pipeline declares
  an `on_failure` edge from that step — in which case the author has said how to
  handle it and control routes there.

### 13.3 One agent model

The two surfaces are reconciled. `services/agent-registry/legacy_shim.py`
translates the older registration shape onto the graph: `POST /agents/register`
keeps its exact request and response, and the frontend and `backend/main.py`
need no change, but the data lands in `agents` and `agents_data` like everything
else. The economic and attestation fields — `token_balance`,
`reputation_score`, `hash_digest`, `public_key`, `uaid`, `x509_certificate` —
live on the identity vertex, where §3.1 says they belong.

Two consequences worth stating:

- **Progeny is derived.** The old surface kept a `progeny_agent_ids` list and
  appended to it in a fire-and-forget task. A list and the `spawns` edges are
  two records of one fact; the edges are the provenance record (Rule 3.2), so
  the list is computed from them on read and cannot drift.
- **Auditing does not version.** Moving a reputation score or a token balance
  patches the identity vertex. It does not produce a new version or change a
  content hash, because it does not change what the agent does (§4.2).

### 13.4 Defects found by the end-to-end suite

Running the real services against a live database and a real model router
found ten defects that every unit test passed. Four were in this registry, and
each is a class of bug a test double cannot reach:

1. **`descendants` returned nothing.** `traverse()` was called with
   `start_vertex_table`/`start_vertex_id` — the real parameters are
   `start_table`/`start_id` — and its result was read as vertices when it
   returns `{id, table_name, depth, path, …}` dicts. The endpoint now hydrates
   ids into identities and passes `relation_types` and `space` as well as
   `max_depth` (Rule 6.4).
2. **`run_of` and `run_step` were never written.** `link_run` existed and was
   imported and never called, so §5's claim was false. `RunStore` now takes a
   linker, injected rather than imported so the shared runtime does not depend
   on the registry's schema constants.
3. **Recursion was still unreachable.** `invokes_pipeline` had a writer at
   publish time and no field on `AgentVersionSpec` to trigger it. The field now
   exists and is part of the content hash (§4.2).
4. **Metering lost whole batches.** The flush ran `CREATE TABLE` every time;
   two services flushing to one realm raced on the system catalogue and
   PostgreSQL rolled the batch back with `tuple concurrently updated`. The
   ledger table is now created once per realm, and the loser of a create race
   carries on.

`tests/README.md` lists all ten, including the six in the companion services.

### 13.5 What is still outstanding

- **Draft garbage collection** (Rule 9.1). A failed registration leaves
  unreferenceable draft rows behind. They are inert, and nothing collects them.
- **`room_use` metering** (§12.1). The kind is defined and the backend does not
  yet emit it; the other five kinds are emitted by their owning services.
- **Prometheus counters** are exported by the meter but nothing scrapes the
  registries in a local checkout — the annotation exists for the cluster only.
