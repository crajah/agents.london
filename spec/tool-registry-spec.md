# The MCP tool registry

Specification for the agent.london tool registry (`services/tool-registry`,
port 8002). Substrate is **post-graph** on PostgreSQL, the same store and the
same realm/space tenancy as the agent graph.

Companion to `agent-graph-spec.md`, which owns agents and pipelines. Rule
references of the form "AG Rule 3.4" point there.

Status: implemented in `services/tool-registry`. §12 records implementation
status, the defects the end-to-end suite found, and what is still outstanding.

---

## 1. What is being modelled

A **tool** is a capability an agent can invoke that is not another agent: a web
search, a SQL executor, a vector lookup, a Kubernetes operator. The registry
holds the declaration — identity, endpoint, input contract, access conditions —
and nothing about the tool's implementation.

The agent graph already depends on this. An agent version carries
`tools: ["mcp-google-search", "mcp-pgvector-search"]` (AG §3.2.1), and those
strings are `tool_id`s in this registry. They are also **inside the agent's
`content_hash`** (AG §4.2), which is the constraint the whole of §4 below
follows from: if the thing a `tool_id` refers to can change without the id
changing, then an agent's content hash certifies a behaviour it no longer has.

### 1.1 Why a registry rather than configuration

Three reasons, in order of weight:

1. **Agents discover tools at run time.** An orchestrator asking "what can I
   use to search the web" needs a queryable catalogue, not a YAML file baked
   into an image.
2. **Scope is per-tenant.** A tool available to one organisation must not be
   visible to another, and that is a data property, not a deployment property.
3. **Tools are pinned by agents.** A pin needs something to resolve against.

### 1.2 Non-goals

The registry does not proxy every tool call. It is a catalogue plus a small
number of first-party tool implementations that happen to be hosted here
(§7.2). Whether an agent's runtime calls a tool directly or through a gateway
is a runtime concern.

---

## 2. Tenancy and scope

Two orthogonal mechanisms, routinely confused, so stated separately.

**Tenancy** is inherited from the agent graph unchanged (AG §2):

| Concept | post-graph construct | Isolation |
| :--- | :--- | :--- |
| Organisation (`org_id`) | realm — its own schema | Physical |
| Project (`project_id`) | space — a column | Logical |

**Scope** is a property of the tool within a tenant, recorded as `scope_type`:

| `scope_type` | Visible to | `project_id` |
| :--- | :--- | :--- |
| `org` | every project in the organisation | must be null |
| `project` | one project | required |

**Rule 2.1** — Every read is scoped by `org_id`. A listing without one is not
"all tools", it is a cross-tenant leak. The registry rejects a tool query that
does not name a realm rather than defaulting to one; a default realm is how a
tenant's catalogue ends up in another tenant's discovery response.

**Rule 2.2** — `scope_type: "org"` with a `project_id`, or `scope_type:
"project"` without one, is rejected at registration. Both are rejected rather
than normalised, because either normalisation silently widens or narrows
visibility, and the author cannot tell which happened.

**Rule 2.3** — No tool is visible across realms. A tool needed by two
organisations is registered twice. This mirrors AG Rule 2.2 for the same
reason: a realm is a schema, so a cross-realm reference cannot carry a foreign
key and would have to be maintained by convention.

---

## 3. Storage

### 3.1 `mcp_tools` — the stable identity

One vertex per tool, holding what does not change between versions. Carries the
standard post-graph columns: `realm`, `space`, `id`, `uuid`, `payload` (JSONB),
`embedding` (`vector(1536)`), `created_at`, `updated_at`.

```jsonc
{
  "tool_id": "mcp-google-search",     // stable, immutable, unique per realm
  "name": "Google Search (GCP API)",
  "description": "Performs web search via the GCP Custom Search API.",
  "scope_type": "org" | "project",
  "org_id": "org_london_meta",
  "project_id": null,                 // required iff scope_type = "project"
  "kind": "http" | "grpc" | "ipc" | "builtin",
  "current_version": "1.2.0",         // pointer into mcp_tools_data
  "lifecycle": "active" | "deprecated" | "dormant",
  "owner": "user_id or agent_id",
  "created_at": "2026-08-13T09:00:00Z"
}
```

`embedding` is computed from `name + description + the input schema's property
descriptions`. This is what makes "find me a tool that can query a relational
database" resolve without a keyword index, and it is the same mechanism agents
use (AG §10).

**Rule 3.1** — `tool_id` is stable and never reused. It is a URL-safe slug,
unique per `(realm, space)` for project-scoped tools and per realm for
org-scoped ones. Renaming a tool changes `name`, not `tool_id`, because
`tool_id` is what sits inside published agents' content hashes.

### 3.2 `mcp_tools_data` — the versions

post-graph gives every vertex table an append-only companion. **That is what a
tool version is.** One record per version, written with `add_vertex_data()`,
immutable once published.

```jsonc
{
  "tool_version_id": "tlv_mcp-google-search_1.2.0",
  "tool_id": "mcp-google-search",
  "version": "1.2.0",                 // semver, §4.1
  "content_hash": "sha256:…",         // §4.2
  "endpoint_url": "http://tool-registry-service.default.svc.cluster.local:8002/tools/google-search",
  "transport": "http_post_json",
  "input_schema":  { "type": "object", … },   // JSON Schema, required
  "output_schema": { "type": "object", … },   // JSON Schema, required
  "auth": {
    "mode": "none" | "bearer" | "service_account" | "secret_ref",
    "secret_ref": {"name": "litellm-api-keys", "key": "MASTER_KEY"}
  },
  "limits": {"timeout_secs": 5, "max_calls_per_run": 20, "max_bytes": 1048576},
  "min_reputation_score": 0.0,        // §6
  "side_effects": "read" | "write" | "external",   // §6.2
  "cost_hint": {"kind": "search_query", "bytes_per_call": 2048},
  "status": "draft" | "published" | "deprecated" | "revoked",
  "published_at": "…",
  "changelog": "What changed and why."
}
```

**Rule 3.2** — `input_schema` and `output_schema` are **required**. The input
schema is what an agent's model is shown when the tool is offered to it; a tool
with no declared input is one the model must guess at, and a guessed tool call
fails at the far end where the failure is least diagnosable. The output schema
is what lets a pipeline's `payload_map` be checked at publish time (AG §9,
rejection 7) when a step's output flows from a tool.

**Rule 3.3** — A published tool version is immutable. Changing an endpoint,
schema, timeout or auth mode produces a new version. Enforced by
`content_hash`: the registry recomputes on write and rejects a mismatch.

### 3.3 Why not one table with the endpoint on the identity vertex

Because that is precisely the shape that breaks agent pinning. If
`endpoint_url` and `input_schema` live on the identity vertex, then editing
them in place changes what every published agent that names this `tool_id`
actually does, while every one of those agents' content hashes continues to
certify the old behaviour. The append-only history is not a nicety here; it is
the only thing that makes AG Rule 4.2 mean anything for tool-using agents.

---

## 4. Versioning

### 4.1 Scheme

Semver, with meaning defined against the **contract**, since that is what a
caller can depend on mechanically:

| Bump | Trigger |
| :--- | :--- |
| **MAJOR** | `input_schema` or `output_schema` changes incompatibly; `auth.mode` changes; `side_effects` widens |
| **MINOR** | Optional input field added; output field added; limits raised |
| **PATCH** | `endpoint_url` moved within the cluster; description; timeout lowered; `cost_hint` |

**Rule 4.1** — An endpoint change is at least a PATCH. A tool that answers from
a different address is a different tool as far as an audit is concerned, even
when the answers are identical.

### 4.2 Content hash

```
content_hash = sha256(canonical_json({
    endpoint_url, transport, input_schema, output_schema,
    auth, limits, min_reputation_score, side_effects
}))
```

Canonical JSON: sorted keys, no insignificant whitespace, UTF-8 — identical to
AG §4.2, so one implementation serves both registries.

Excluded: `name`, `description`, `changelog`, `cost_hint`, timestamps. A
description is embedded for discovery and does not determine behaviour.

**Rule 4.2** — Two published versions of one tool with equal `content_hash` are
an error at registration, for the same reason as AG Rule 4.2.

### 4.3 How agents pin tools

An agent version's `tools` list carries pins, not bare ids:

```jsonc
"tools": [
  {"tool_id": "mcp-google-search", "version": "1.2.0", "content_hash": "sha256:…"},
  {"tool_id": "mcp-sql-query",     "version": "2.0.0", "content_hash": "sha256:…"}
]
```

**Rule 4.3** — A bare string in `tools` is accepted at registration and
resolved to `{tool_id, version, content_hash}` against the tool's
`current_version` **before** the agent's `content_hash` is computed. The
resolved form is what is stored and hashed. `@latest` is a convenience for
authors and never a stored value — identical reasoning to AG Rule 4.3: an agent
whose behaviour changes because a tool was republished is not reproducible, and
its run history stops being interpretable.

**Rule 4.4** — Agent registration fails if a named tool does not exist, is not
published, is revoked, or is out of scope for the agent's `(org_id,
project_id)`. Caught here it is a typo; caught at run time it is a model being
offered a tool that 404s mid-conversation, which it will then narrate around.

**Rule 4.5** — Revoking a tool version that published agents pin requires
either a `replacement_version_id` or an explicit cascade that marks those agent
versions revoked too. Silent revocation leaves agents that report success while
one of their capabilities is gone.

---

## 5. Discovery

Three paths, mirroring AG §10 so an orchestrator uses one idiom for both
registries.

- **By vector** — `mcp_tools.embedding` over name, description and schema
  property descriptions, via post-graph `vector_search`, filtered to the
  caller's realm and to `org`-scoped plus own-project tools.
- **By id** — exact `tool_id` lookup. This is the path an agent's runtime takes
  when resolving a pin, and it is the only one that may return a
  non-`current_version` record.
- **By capability** — exact match on a `capabilities` tag list, GIN-indexed on
  the payload.

**Rule 5.1** — Discovery returns only `published`, non-`deprecated`,
`lifecycle: active` versions unless the caller explicitly asks otherwise, and
never returns a tool the caller's `(org_id, project_id)` cannot invoke.
Returning an unreachable tool teaches an agent to plan around a capability it
does not have.

**Rule 5.2** — A discovery response carries the resolved `version` and
`content_hash`, not just the `tool_id`. A caller that wants to pin needs both,
and a second round trip to get them is a race.

### 5.1 The RAG export

`GET /tools/rag-documents` renders each tool as a prose document for indexing
into post-graph-rag, so tool selection can be part of ordinary retrieval rather
than a separate lookup. The rendering is derived, never stored: a second copy
of a tool's description drifts from the first.

---

## 6. Access control

### 6.1 Reputation

`min_reputation_score` gates invocation against the calling agent's
`reputation_score` in the agent registry.

**Rule 6.1** — The check happens at **invocation**, in the tool call path, and
denies with an error naming the tool and the shortfall. A threshold that is
stored and never evaluated is worse than no threshold: it reads, to everyone
looking at the registration, like a control that exists.

**Rule 6.2** — `side_effects` is declared, not inferred. `read` may be invoked
speculatively; `write` and `external` may not be invoked during a pipeline
step's retry (AG Rule 8.2) without an idempotency key, because at-least-once
delivery over a side-effecting tool means the effect happens at least once too.

### 6.2 Secrets

**Rule 6.3** — Credentials are never stored in the registry. `auth.secret_ref`
names a Kubernetes secret; the value is read by whatever executes the call.
A registry row is readable by every service that can read the realm, and a
catalogue is not a secret store.

---

## 7. Invocation

### 7.1 Contract

```
POST /tools/{tool_id}/call
{
  "arguments": { … },          // validated against input_schema
  "org_id": "org_…",
  "project_id": "proj_…",
  "caller": {"agent_id": "agt_…", "run_id": "run_…", "step_id": "step_…"},
  "idempotency_key": "01J…"    // required when side_effects != "read"
}
```

**Rule 7.1** — Arguments are validated against the pinned version's
`input_schema` before dispatch. A tool that receives an argument shape it did
not declare will either fail confusingly or succeed on the wrong thing.

**Rule 7.2** — A failed tool call returns an error. It never returns a
plausible-looking synthetic result. This is not hypothetical: the search
endpoint previously answered `status: success` with three invented results
whose snippets described themselves as empirically retrieved, which an agent
then reasoned over and persisted as fact. An agent cannot distinguish fabricated
evidence from real evidence, so the registry must never produce any.

**Rule 7.3** — An unconfigured tool fails with `503` and a message naming the
missing configuration. It does not fall back to a degraded mode, and it is not
listed as available (Rule 5.1).

### 7.2 First-party tools

A small number of tools are implemented in this service rather than merely
catalogued, because they are infrastructure rather than capability: the GCP
Custom Search binding is the current example. These are registered like any
other tool and carry `kind: "builtin"`. Being builtin changes where the code
lives and nothing about the contract.

### 7.3 The default catalogue

The registry seeds a standard set at startup — search, vector memory, the Redis
event bus, SQL, and the Kubernetes operator.

**Rule 7.4** — Seeding is **idempotent**. Defaults are upserted by `tool_id`,
and a version record is appended only when the content hash differs from the
current one. A seed that appends unconditionally grows the vertex table by the
size of the default set on every pod restart, and the duplicates are invisible
because the read path deduplicates by `tool_id`.

---

## 8. Registration

`POST /tools/register` is the only way a tool enters the graph.

Rejected at registration:

1. Missing `input_schema` or `output_schema` (Rule 3.2)
2. A `tool_id` that is not a valid slug, or is taken by another tool in the
   realm (Rule 3.1)
3. `scope_type` inconsistent with `project_id` (Rule 2.2)
4. A `content_hash` colliding with an existing published version (Rule 4.2)
5. An `auth` block containing a literal credential rather than a reference
   (Rule 6.3)
6. `side_effects` absent — there is no safe default, since guessing `read` for
   a writing tool licenses speculative execution of it
7. An `endpoint_url` outside the cluster for a tool declaring
   `side_effects: "read"` without an explicit `external: true`

**Rule 8.1** — Registration is idempotent on `(realm, tool_id, content_hash)`.
Re-registering identical content returns the existing version rather than
appending a duplicate. Registration is retried by deployment tooling, and a
retry must not be a new version.

**Rule 8.2** — Registration failures raise. They do not log and return the
object. Identical to AG Rule 9.2, and for the identical reason: a registry that
reports success for a write it did not perform is indistinguishable, from the
caller's side, from one that worked.

---

## 9. Lifecycle and deletion

**Rule 9.1** — Deletion is dormancy. A tool that is no longer wanted is marked
`lifecycle: dormant` and drops out of discovery. It is not removed, because
published agent versions pin it and their hashes must remain resolvable — an
agent's history stops being auditable the moment a pinned tool cannot be looked
up.

**Rule 9.2** — `DELETE /tools/{tool_id}` performs that transition **in
post-graph**, not only in a process-local cache. A delete that mutates the
cache alone reports success, survives until the next restart, and then
reappears — and there is no error anywhere in that sequence.

**Rule 9.3** — Deprecating a tool warns at agent-registration time and does not
break existing agents. Revoking follows Rule 4.5.

---

## 10. Caching

The registry keeps a process-local cache in front of post-graph, because tool
resolution is on the hot path of every agent turn.

**Rule 10.1** — The cache is a **read-through cache of post-graph, keyed by
`(realm, tool_id, version)`**, never a parallel store. Every write goes to
post-graph first and updates the cache only on success. A cache that can hold
an entry post-graph does not have is a registry that answers differently
depending on which replica served the request.

**Rule 10.2** — The cache is realm-partitioned, and a read is served from a
realm's partition only. A single flat process dictionary shared across realms
makes Rule 2.1 unenforceable at exactly the layer that serves most reads.

**Rule 10.3** — Startup sync enumerates realms from the database, not from a
hardcoded list. A hardcoded list means a new organisation's tools are invisible
until someone edits and redeploys the service, and nothing reports that.

---

## 11. Accounting

Tool use is metered into `usage_events` (AG §12), per organisation, through the
shared `metering` module. The tool registry is the origin of three of the six
event kinds AG §12.1 defines and which currently nothing emits.

| Event | `kind` | `bytes` | Emitted when |
| :--- | :--- | :--- | :--- |
| Query issued | `search_query` | size of the query text | before dispatch |
| Results returned | `search_results` | size of the returned payload | after a successful call |
| Vector lookup | `rag_lookup` | size of the retrieved chunks | after a successful call |

**Rule 11.1** — Metering never blocks or fails a tool call (AG Rule 12.2).
Events go to the bounded queue and are flushed in batches.

**Rule 11.2** — `search_query` and `search_results` are separate events, not one
event with two byte counts. They have different cost profiles — a cheap query
can return an expensive result — and separating them at write time is the only
way to bill them apart later.

**Rule 11.3** — Every event carries `agent_id`, `run_id` and `step_id` from the
caller block. Without them a ledger line says an organisation spent something
and cannot say on what, which makes a disputed invoice unanswerable.

---

## 12. Implementation status

Implemented in `services/tool-registry`. Every gap the first draft of this
section recorded is closed:

| Was | Now |
| :--- | :--- |
| No versioning; a tool was a single mutable vertex | `mcp_tools_data` holds one immutable, content-hashed record per version, published behind a draft marker (§3.2) |
| `add_vertex` unconditionally, so every restart re-appended the default catalogue | Registration is idempotent on `(realm, tool_id, content_hash)`; seeding five tools twice creates five vertices (Rule 7.4, Rule 8.1) |
| `DELETE` mutated a process dictionary and the tool returned on restart | Dormancy, written to post-graph, reversible via `/restore` (Rule 9.2) |
| `GET /tools` with no `org_id` returned every realm's tools | `org_id` is required, and the cache is partitioned by realm (Rule 2.1, Rule 10.2) |
| `min_reputation_score` stored and never evaluated | Checked at invocation against the calling agent's standing, failing closed (Rule 6.1) |
| No `output_schema`, `side_effects`, `auth` or `limits` | All present; `side_effects` has no default, and `auth` rejects literal credentials (Rules 3.2, 6.2, 6.3) |
| No way to invoke a tool | `POST /tools/{tool_id}/call`, with argument validation, scope and lifecycle checks, and an idempotency key required for side-effecting tools (§7.1) |
| No metering | `search_query`, `search_results` and `rag_lookup` emitted per call (§11) |
| Startup sync over a hardcoded org list | Realms enumerated from the database (Rule 10.3) |
| No embeddings, so vector discovery could not work | Computed at registration; `GET /tools/search` searches them (§5) |

### 12.1 Compatibility

`POST /tools/register` accepts both the versioned body (`{identity, version}`)
and the original flat body, so `apps/civilization/backend/main.py` and any deployment manifest
keep working — and a caller that has not been updated still produces a properly
versioned, hashed, pinnable tool rather than an unversioned vertex.

A legacy registration that declares no `side_effects` is recorded as
`external`, not `read`. There is no safe default (rejection 6), and `external`
is the conservative one: it forbids speculative execution and
retry-without-a-key, which is the behaviour that matters until the caller
declares.

### 12.2 Defects found by the end-to-end suite

Three, all of the same shape — a control that reads as enforced and is not:

1. **The reputation check asked the agent registry without a realm.** Both
   registries keep each organisation in its own schema, so the lookup read
   whichever realm the agent registry defaults to, found nothing, and denied a
   legitimate caller with a 503 that blamed the network. The realm is now
   passed.
2. **`auth.mode` was applied to nothing.** Every version could declare
   `bearer` or `secret_ref` and dispatch sent no credential, so the far end's
   401 came back as a 502 blaming the endpoint. `dispatch` now resolves the
   reference — environment variable, then mounted secret path — and fails with
   a message naming the missing configuration rather than sending nothing.
3. **Seeding failed when the deployment moved.** A changed `SELF_URL` collided
   with Rule 3.3 on version `1.0.0`, so the catalogue went on advertising the
   old address with only a log line to say so. The seed now publishes the next
   patch instead, which is what Rule 4.1 asks for.

### 12.3 What is still outstanding

- **`max_calls_per_run`** is declared in `limits` and not enforced. Enforcing it
  needs a per-run counter the tool registry does not currently see, since the
  run lives in the agent registry.
- **Deprecated tools remain callable**, as specified (§4.4), but nothing warns
  the calling agent at invocation — only the registering author is warned.
