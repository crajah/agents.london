# Storing agents and pipelines in a graph database

Specification for the agent.london registry. Target substrate is **post-graph**
on PostgreSQL: vertex and edge tables with JSONB payloads, pgvector embeddings,
realm/space tenancy, and append-only `{table}_data` history.

Status: draft for implementation. Section 11 lists what is deliberately left open.

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

Four vertex tables, each with its append-only `{table}_data` companion
(§3.2). All carry `realm`, `space`, `id`, `uuid`, `payload` (JSONB),
`embedding` (`vector(1536)`), `created_at`, `updated_at`.

### 3.1 `agents` — the stable identity

One vertex per agent, for the life of the agent. It holds what does **not**
change between versions.

```jsonc
{
  "agent_id": "agt_researcher_7f3a",     // stable, immutable, globally unique
  "name": "Corpus Researcher",
  "slug": "corpus-researcher",           // unique per (realm, space); URL and MCP safe
  "caste": "permanent" | "progeny" | "pipeline",
  "telos": "One sentence: what this agent exists to do.",
  "description": "Prose. Embedded for semantic discovery.",
  "owner": "user_id or agent_id of the spawner",
  "current_version": "3.1.0",            // pointer into agents_data; see §3.2
  "lifecycle": "active" | "deprecated" | "dormant",
  "created_at": "2026-08-13T09:00:00Z"
}
```

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
  "tools": ["mcp-google-search", "mcp-pgvector-search"],   // tool_ids in the tool registry
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
  "iteration_count": 0,
  "started_at": "…", "ended_at": "…",
  "input": { … }, "output": { … },
  "error": {"step_id": "…", "type": "…", "message": "…"} | null
}
```

### 3.6 `context_entries` — shared context, §8

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
    capabilities, resource_limits
}))
```

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

**Rule 8.3** — A step that cannot deliver to Redis fails the run. It does not
fall back to in-process execution: that produces a run whose event log is
missing steps that did happen, which is worse than a failure.

### 8.2 Shared context

Context is a per-run key/value store in `context_entries`, written through
post-graph so it is durable and auditable, and cached in Redis for latency.

```jsonc
{
  "context_id": "ctx_run_01J…",
  "run_id": "run_01J…",
  "scope": "run" | "branch" | "step",
  "key": "extracted_entities",
  "value": { … },
  "written_by": "step_extract",
  "written_at": "…",
  "revision": 3
}
```

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

**Rule 9.1** — Registration is atomic. A pipeline version, its `composes_pipeline`
edges and its `pipeline_step_dependency` edges are written in **one
transaction**. A partially-written pipeline is a pipeline that runs and produces
a plausible wrong answer.

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

## 11. Open questions

1. **Cross-org publishing.** §2.2 forbids cross-realm edges and §4.4 gestures at
   `derived_from`, but the copy mechanism is unspecified.
2. **Step-level retries versus cycles.** A retried step and a one-node cycle are
   currently indistinguishable in `iteration_count`.
3. **Schema evolution of context.** `context_entries.value` is unvalidated. It
   probably wants a per-key schema in `context_policy`.
4. **Cost accounting.** `resource_limits` is per agent version; a run-level
   budget across a recursive tree is not modelled.
5. **A2A streaming** maps cleanly to the events channel, but partial-result
   semantics for a halted cyclic run are undefined.
