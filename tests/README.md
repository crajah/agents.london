# End-to-end tests

Nothing in this suite is stubbed.

| | What runs |
| :--- | :--- |
| **Database** | A live PostgreSQL with pgvector. One schema per test realm, dropped afterwards. |
| **Graph client** | The real `post-graph`, at the version `requirements.txt` pins — loaded from the sibling checkout, not from a possibly-stale `site-packages`. |
| **Model router** | The real LiteLLM. Real `gemini-embedding-001` vectors, real `gemini-3.5-flash-lite` completions, real token accounting. |
| **Services** | The three real FastAPI applications, under real uvicorn, on real ports, through their real lifespans. |
| **Transport** | Real HTTP, including every cross-service call. |

The services listen on real ports rather than being mounted through an ASGI
transport, because a registered tool's `endpoint_url` has to be genuinely
reachable for `POST /tools/{id}/call` to dispatch to it. Mounting in-process
would have forced a fake at exactly the seam the tool tests exist to prove.

```bash
python3 -m pytest tests -q              # the end-to-end suite (108)
python3 -m pytest services backend -q   # the unit suite (235)
# test_civilization.py targeted the removed native engine (deleted 2026-09-04)
```

The civilization script needs the agent registry listening on `:8001`; without
it, two of its fourteen checks report the registry offline.

The suite **skips with a reason** when the database or the router is
unreachable, rather than failing.

---

## What each file proves

### `test_smoke.py` — the harness itself

The router is the real one and serves the models the services default to; real
embeddings are 1536-dimensional, matching the `vector(1536)` the schema
declares; real embeddings discriminate between unrelated work (the premise
every discovery test rests on); a realm really is a PostgreSQL schema.

### `test_e2e_tool_discovery.py` — tool lookup by RAG, and invocation

Five tools with genuinely distinct purposes are registered and embedded. Five
different natural-language intents each retrieve their own tool, first-ranked,
from one index. The queries deliberately share little vocabulary with the tool
descriptions, so the match comes from the embedding rather than keywords.

Then: search returns a pin so the caller can bind it; out-of-scope tools never
appear and cannot be reached by probing; dormancy removes a tool from the index
and survives in the database; arguments are validated before dispatch;
side-effecting tools require an idempotency key; a failing endpoint is reported
rather than invented; reputation is enforced against the live agent registry;
and both services meter their own kinds into one ledger.

The tools point at genuinely real endpoints — the document registry's `/query`,
the model router's `/v1/chat/completions` — so invocation is a real
cross-service call.

### `test_e2e_agent_composition.py` — **one prompt to a running pipeline**

The headline. One sentence of English:

> *"Read this quarterly regulatory filing, pull out the financial risk
> disclosures, have them checked for accuracy, and write me a short executive
> briefing."*

goes in, and the suite proves each stage of what comes out:

1. the real model **decomposes** the goal into ordered capability needs;
2. each need is matched to a registered agent by **RAG over the agent graph**
   (`GET /discover`, the spec's §10 vector path);
3. the matches are **composed** into a pipeline, with `payload_map` edges so one
   step's declared output feeds the next step's declared input;
4. the registry **validates and publishes** it — pins resolved, cycles checked,
   schemas cross-checked;
5. it **runs**, and the run lands in the graph with `executed_steps` matching
   the agents that were chosen.

A real observed run:

```
extract_text      -> risk-extractor      (agt_risk_extractor)
identify_risks    -> risk-extractor      (agt_risk_extractor)
verify_content    -> risk-extractor      (agt_risk_extractor)
synthesize_brief  -> executive-briefer   (agt_briefer)

RUN: succeeded
OUTPUT: "BRIEFING: The company faces a material uncertainty regarding its
         revolving credit facility... a contingent tax liability of GBP 4.2m."
```

That one agent version legitimately serves three steps is the spec's §3.4 point
made concrete: step identity is the **step**, not the agent.

Also proved here: a different goal composes a different pipeline; the chain
really passes data (the last step's instructed prefix reaches the output, and
the run records every step in order); a composition that could not pass data is
rejected at publish; a composition pinning a draft is rejected; the result is
exposed over MCP and A2A; and running it bills the organisation from
provider-reported usage.

`composer.py` holds the orchestration. It uses nothing but the registries'
public HTTP surface — which is the point: if it needed a private hook, the
surface would be wrong.

### `test_e2e_documents.py` — ingestion and GraphRAG retrieval

Real `.docx` and `.xlsx` files are built and pushed through the real Docling
ladder into a real post-graph-rag index, with the real model doing entity
extraction. Unreadable binary is rejected with `415` and **not** catalogued. A
batch reports each file separately rather than hiding failures behind a count.
Re-uploading a name is a revision; identical bytes are a no-op; withdrawal keeps
the record and drops the chunks; counts are derived. Retrieval finds an ingested
fact, can be scoped to one document space, and always names the engine that
answered. Two realms and two projects cannot see each other's documents.

### `test_e2e_backend.py` — the backend that fronts them

The backend had no test at all, and three of its endpoints answered without
calling anything: `GET /api/mcp/v1/tools` returned a hardcoded list of six
tools that existed nowhere else; `POST /api/mcp/v1/tools/call` answered
`status: success` for any name it did not recognise, with a fabricated
`ed25519:` signature and a made-up latency, and invented a search result with a
google.com link when the search tool was unreachable; `POST /api/a2a/v1/dispatch`
reported `delivered` without contacting the target.

These tests hold that shut, and prove the replacements: the catalogue is the
two registries and reports any it could not read; a call routes to the registry
that owns the name and propagates every failure; A2A resolves the target's
published card and returns what the target really answered; discovery prefers
registered agents and hands back a name that can be invoked directly.

### `test_e2e_guarantees.py` — the specification's promises

Immutability and duplicate-hash rejection; slug uniqueness; realm isolation
including discovery; provenance through `spawns`, `progeny` and a bounded
`descendants` traversal; fork and cross-org lineage with a local origin stub;
independent prompt versioning; cyclic pipelines rejected without a bound and
rejected when inescapable; a bounded cycle that **halts** and is never reported
as success at either protocol edge; recursion through `invokes_pipeline`;
`run_of` and `run_step` edges; revocation requiring a replacement or a cascade;
dormancy that keeps provenance; `@latest` resolved by semver at publish;
exposure limited to published versions; and the original registration surface
round-tripping through the graph.

---

## Bugs this suite found

Every one of these passed the unit tests. They are recorded because each is a
class of defect a test double cannot reach.

| # | Defect | Why the unit tests missed it |
| :--- | :--- | :--- |
| 1 | `traverse()` called with `start_vertex_table`/`start_vertex_id`, and its result read as vertices | The real signature is `start_table`/`start_id`, and it returns `{id, table_name, depth, …}` dicts. `descendants` returned nothing, silently. |
| 2 | `link_run` imported and never called | `run_of` and `run_step` edges were never written, though the spec claimed they were. |
| 3 | Metering ran `CREATE TABLE` on every flush | Two services flushing to one realm raced on the system catalogue; PostgreSQL raised `tuple concurrently updated` and **whole batches of usage events were lost**. |
| 4 | The reputation check asked the agent registry without a realm | It read whichever schema the registry defaults to, found nothing, and denied legitimate callers with a 503 blaming the network. |
| 5 | Seeding the first-party catalogue failed on `Rule 3.3` when the deployment URL changed | A moved endpoint is a PATCH (Rule 4.1), not an immutability violation. |
| 6 | `auth.mode` was stored on every tool version and applied to nothing | Same class as the unevaluated reputation score: it reads like a control and does nothing. Tools needing a bearer token got a 401 reported as a broken endpoint. |
| 7 | Document reads assumed the tables existed | A realm that had never been written to raised `UndefinedTableError` instead of answering "empty". |
| 8 | `_payload` guarded with `isinstance(row, dict)` | `asyncpg.Record` is **not** a `dict`. It returned `{}` for every real row, so `get_space` never found anything and **`create_space` appended a duplicate space on every call** — Rule 3.2 held only in the fake. |
| 9 | `invokes_pipeline` had no field on `AgentVersionSpec` | The edge had a writer nothing could trigger, so recursion was unreachable through the public API. |
| 10 | `IndexOutcome.succeeded` misread post-graph-rag's reply | It reads `entities` as a count; the engine returns a *list* of names and the count under `entities_extracted`. The `TypeError` turned a successful index into a failed one. |

| 11 | The civilization engine ran without `schema_per_realm` while all three registries ran with it | Two `agents` tables — `public.agents` (335 rows) and `org_x.agents`. An agent the engine materialised was invisible to the registry, which answered 404 for it, and vice versa. Tenants were separated by a column and called physically isolated. |
| 12 | `add_vertex_data` and `add_edge` given business keys instead of vertex ids, in five places | `add_vertex` returns an integer pk that was discarded. One raised `invalid literal for int()` and failed project creation; three sat inside debug-level handlers, so version history and telemetry were silently never written; one guarded with `isinstance(v_res, dict)` — always false for a `Vertex` — so the branch never ran. |
| 13 | Each `_get_pg_client()` opened a fresh ten-connection pool | Twenty-eight agent registrations exhausted a hundred server connections: "sorry, too many clients already", after which every later write failed. |
| 14 | The engine tried four DSNs and used whichever answered | Two carried hardcoded credentials. A typo in `POSTGRES_URI` did not fail — it silently wrote a tenant's agents to whatever local database accepted a guess. |

Bugs 11 to 14 were found by running the since-removed `test_civilization.py`, which had never
passed more than 12 of its 14 checks. It now passes 14.

Fixes 8 and 10 have unit regressions added alongside them
(`test_doc_store.py`, `test_doc_model.py`) using a `Record`-shaped double, so
the class of bug is caught at unit speed from now on.

---

## Notes on running against a real model

**Model selection is automatic.** The router fronts several providers and any of
them can be out of credits on a given day — `DeepSeek-V3.2` and the
SambaNova-backed models returned `402 out of credits` mid-suite during
development. `conftest.py` probes candidates in order and uses the first that
answers twice in a row, so a provider outage skips to the next model instead of
producing a wall of failures that look like application bugs. Override with
`TEST_CHAT_MODEL`.

**Assertions do not depend on wording.** The chat model is non-deterministic, so
the assertions are about which agent version ran, what reached it, what the
provider charged, and what landed in the graph. Where a specific value is
needed, the agent's system prompt constrains the answer and the check is
case-insensitive.

**Timing.** The full E2E suite takes roughly four minutes; the document tests
dominate it, because indexing one document through GraphRAG costs several model
calls.

## Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `TEST_POSTGRES_URI` | `postgresql://crajah:…@localhost:5432/postgres` | The database. `.env` names the container-internal host, which does not resolve from a checkout. |
| `TEST_OPENAI_API_BASE` | `http://localhost:4000/v1` | The router, likewise. |
| `TEST_CHAT_MODEL` | probed | Force one chat model. |
| `TEST_EMBEDDING_MODEL` | `gemini-embedding-001` | Must be 1536-dimensional; the width is requested explicitly. |
| `TEST_MODEL_PROBES` | `2` | Consecutive successful probes required. |
