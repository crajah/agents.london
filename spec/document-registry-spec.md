# The document registry

Specification for the agent.london document registry
(`services/document-registry`, port 8003). Substrate is **post-graph** for the
catalogue and **post-graph-rag** for the knowledge graph and vector index, with
Docling doing structured extraction ahead of both.

Companion to `agent-graph-spec.md`, which owns agents and pipelines. Rule
references of the form "AG Rule 12.2" point there.

Status: implemented in `services/document-registry`. §11 records implementation
status, the defects the end-to-end suite found, and what is still outstanding.

---

## 1. What is being modelled

The registry holds the corpus an organisation's agents reason over. Three
distinct things, routinely conflated, kept separate here:

| | What it is | Where it lives |
| :--- | :--- | :--- |
| **Document space** | A named grouping of documents within a project | `document_spaces` vertex |
| **Document** | One ingested artefact and its extraction provenance | `documents_catalog` vertex |
| **Index** | Chunks, entities and relationships derived from a document | post-graph-rag tables |

The catalogue and the index are deliberately separate stores. The catalogue
answers "what was ingested, from what file, by which parser, when" — a
bookkeeping question with an exact answer. The index answers "what is relevant
to this question" — a retrieval question with an approximate one. Collapsing
them means the only record that a document exists is the fact that a search
happened to return it, and a document that indexed badly then becomes
indistinguishable from one that was never uploaded.

### 1.1 Non-goals

Not specified here: the chunking strategy, the entity extraction prompts, or
the embedding model's behaviour. Those belong to post-graph-rag. This document
specifies what the registry must record, expose and guarantee.

---

## 2. The three-tier namespace

This is the part of the design most likely to be misread, because the word
"space" means two different things one level apart.

```
org_id          →  post-graph realm  →  a PostgreSQL schema      (physical)
project_id      →  post-graph space  →  a column in that schema  (logical)
document_space  →  a grouping        →  metadata on the document (a filter)
```

The first two are the tenancy model inherited unchanged from AG §2. The third —
the **document space**, e.g. `engineering_docs`, `financial_reports`,
`legal_contracts` — is one level below, and is *not* a post-graph space. It is
stored as `collection` in the RAG metadata and as `document_space` on the
catalogue vertex, and it is filtered on at query time.

The field is named `document_space` and not `space_name` deliberately. "Space"
one level away from post-graph's `space` is the single most reliable source of
confusion in this service, and a name that says which space it means costs
nothing.

**Rule 2.0** — `space_name` remains an accepted alias on every request and is
still emitted in every response, because the frontend and `backend/main.py`
read it. One canonical field with one alias beats two fields that can disagree,
and beats a coordinated rename across three services.

**Rule 2.1** — post-graph calls are made with `realm=org_id, space=project_id`.
Never `space=document_space`. Passing the document space where post-graph
expects the project puts a project's documents in a partition its own queries do
not read, and the symptom is an empty result set from a corpus that was uploaded
successfully.

**Rule 2.2** — A document space is a filter, not an isolation boundary. Two
document spaces in one project share a knowledge graph: entities extracted from
`legal_contracts` may link to entities from `financial_reports`, and that is
the point of a graph RAG. A caller needing genuine isolation between two bodies
of documents uses two projects.

**Rule 2.3** — A query names the project. `document_space` is optional and, when
omitted, the query runs project-wide. Project-wide is the useful default: an
agent asking a question rarely knows which folder the answer is filed under.

---

## 3. Storage

### 3.1 `document_spaces`

One vertex per document space. Carries the standard post-graph columns.

```jsonc
{
  "space_key": "proj_alpha:engineering_docs",   // unique per (realm, space)
  "org_id": "org_default",
  "project_id": "proj_alpha",
  "document_space": "engineering_docs",
  "space_name": "engineering_docs",   // alias, Rule 2.0
  "description": "Design notes, RFCs and post-mortems.",
  "document_count": 0,                 // derived, §3.3
  "created_at": "2026-08-13T09:00:00Z" // ISO 8601 UTC, §3.4
}
```

**Rule 3.1** — `document_space` is unique per `(org_id, project_id)` and is a slug:
lowercase, alphanumeric plus hyphen and underscore. It appears in URL paths and
in RAG metadata filters, and a name that needs escaping in one of those places
will eventually not be escaped in the other.

**Rule 3.2** — Creating a space that already exists returns the existing space.
It does not append a second vertex. Space creation is called from UI flows that
retry, and a duplicate space is one that silently splits a corpus in half.

### 3.2 `documents_catalog`

One vertex per ingested document.

```jsonc
{
  "document_id": "doc_proj_alpha_engineering_docs_rfc-42.pdf",
  "org_id": "org_default",
  "project_id": "proj_alpha",
  "document_space": "engineering_docs",
  "space_name": "engineering_docs",   // alias, Rule 2.0
  "filename": "rfc-42.pdf",
  "content_type": "application/pdf",
  "content_hash": "sha256:…",          // of the uploaded bytes, §5.3
  "bytes": 204812,
  "extraction": {
    "method": "docling" | "pypdf" | "PyPDF2" | "python-docx" | "python-pptx"
            | "openpyxl" | "utf8_text_reader",
    "characters": 48210,
    "extracted_at": "…"
  },
  "index": {                            // §6
    "status": "indexed" | "pending" | "failed",
    "chunks": 37,
    "entities": 112,
    "relationships": 208,
    "engine": "post-graph-rag",
    "error": null,
    "indexed_at": "…"
  },
  "revision": 1,                        // §7
  "lifecycle": "active" | "superseded" | "withdrawn",
  "uploaded_by": "user_id or agent_id",
  "uploaded_at": "…"
}
```

**Rule 3.3** — `document_count` on a space is **derived at read time** by
counting catalogue vertices, never maintained as a stored counter. A counter
incremented on upload and not decremented on withdrawal drifts, and the drift
is visible to users as a space that claims documents it cannot list.

**Rule 3.4** — Timestamps are ISO 8601 UTC strings taken from the wall clock.
Not `asyncio.get_event_loop().time()`, which returns a monotonic float whose
origin is the process start — a number that sorts correctly within one process
run and means nothing across a restart or between replicas.

### 3.3 `documents_catalog_data`

The append-only companion holds one record per revision (§7), so re-ingesting a
document does not destroy the record of what was previously indexed under that
name. Same construct, same reasoning as AG §3.2.

---

## 4. The ingestion contract

Ingestion is: accept bytes → extract text → index → catalogue → report. Each
arrow can fail, and the difference between the failure modes is what §5 and §6
are about.

**Rule 4.1** — A document is catalogued only after extraction succeeds. A
catalogue entry is a claim that a document is in the corpus; writing one for a
document whose text could not be read makes the catalogue an unreliable
inventory, which is its only job.

**Rule 4.2** — Ingestion reports the extraction method and the index outcome in
its response. A caller that uploaded a scanned PDF which yielded forty
characters of header text needs to see that, and the only moment they are
looking is the moment they upload.

---

## 5. Extraction

### 5.1 The ladder

Tried in order, first success wins:

| Order | Parser | Handles |
| :--- | :--- | :--- |
| 1 | Docling | PDF, DOCX, PPTX, XLSX, HTML, MD — structured Markdown with headings and tables |
| 2 | pypdf, then PyPDF2 | PDF, when Docling declines |
| 3 | python-docx | DOCX |
| 4 | python-pptx | PPTX, slide by slide |
| 5 | openpyxl | XLSX, sheet by sheet |
| 6 | strict UTF-8 decode | TXT, MD, JSON, CSV, HTML |

Docling is first because it produces *structured* Markdown — headings, lists,
tables — and structure survives chunking. A table flattened by a naive PDF text
extractor becomes a run of numbers with no column headers, which embeds as
noise and retrieves as nonsense.

**Rule 5.1** — Success requires more than a non-empty string. A parser that
returns whitespace or a handful of characters has not succeeded; the ladder
continues. The current threshold is 10 non-whitespace characters.

**Rule 5.2** — The final decode is **strict**. Not `errors="ignore"`: ignoring
decode errors turns any binary file into mojibake that passes an
`if text.strip()` check, so a PDF whose parsers had all failed was indexed as
garbage rather than rejected.

### 5.2 Failure

**Rule 5.3** — When no parser succeeds, ingestion fails with `415` naming the
file and the fact that no parser succeeded. It does not substitute a
placeholder.

This rule has two known violations in its own history, which is why it is
stated this emphatically. The first returned `str(file_bytes)` — the Python
repr of the raw bytes — as the document's text, which was then embedded and
indexed into the knowledge graph as if it were prose. The second substituted
the sentence `"Document content from file {filename}"`. Both produce a corpus
entry that retrieves, cites and reads as a real document, and neither leaves any
signal that extraction failed.

**Rule 5.4** — The rule applies identically to single-file and multi-file
upload. A batch endpoint that is more permissive than the single endpoint it
loops over is a way to bypass the check by uploading two files instead of one.

**Rule 5.5** — In a multi-file upload, one file's failure does not fail the
batch. Each file gets a per-file outcome in the response, and the response
reports counts for succeeded and failed separately. A batch that returns
`status: success` and a count of processed files, where the count silently
excludes the failures, is a report the caller will read as complete.

### 5.3 Content hash

`content_hash` is `sha256` of the **uploaded bytes**, before extraction.

**Rule 5.6** — Re-uploading identical bytes to the same document space is a
no-op that returns the existing catalogue entry. Re-extracting and re-indexing
an identical file costs an embedding run and produces duplicate chunks that
compete with each other in retrieval, which degrades every subsequent answer
from that corpus.

---

## 6. Indexing

Extracted text is indexed into post-graph-rag with `realm=org_id`,
`space=project_id`, and `DocumentMetadata(collection=document_space,
document=filename, doc_key=document_id, content_hash=…, source=…, category=…)`.

`doc_key` is the registry's own `document_id`. It is what makes Rule 7.2
possible: superseding a document finds and removes exactly its chunks rather
than guessing from the filename.

```jsonc
{
  "api_base": "…/v1",                       // the LiteLLM model router
  "model": "DeepSeek-V3.2",                 // entity and relationship extraction
  "embedding_model": "text-embedding-3-small",
  "embedding_dim": 1536,                    // must match the agent graph, §6.1
  "realm": "org_default",
  "space": "proj_alpha"
}
```

**Rule 6.1** — `embedding_dim` is 1536 and matches the agent and tool
registries' vector columns. One dimension across the system means a single
embedding service, and a mismatch is not caught by a type — it surfaces as a
pgvector dimension error at query time, in a code path far from the config.

**Rule 6.2** — An indexing failure is **recorded on the catalogue entry** as
`index.status: "failed"` with the error, and returned to the caller. The
document is catalogued (it was extracted successfully, Rule 4.1) but it is not
retrievable, and those are different states that must not both be reported as
success. A document that uploads cleanly and is silently absent from every
subsequent search is the hardest failure in this service to diagnose from the
outside.

**Rule 6.3** — Re-indexing is available as an operation
(`POST /documents/{document_id}/reindex`) precisely because Rule 6.2 leaves
documents in a recoverable failed state. Without it the only remedy for a
transient embedding outage is deleting and re-uploading every affected file.

**Rule 6.4** — The RAG engine is opened per request and closed on every path,
including error paths. Failure to close leaks a pooled connection per upload,
and a bulk ingest exhausts the pool.

---

## 7. Document identity, revision and removal

**Rule 7.1** — Document identity is `(org_id, project_id, document_space,
filename)`. Uploading a new file under an existing name is a **new revision**,
not a second document: `revision` increments, the previous catalogue record
stays in `documents_catalog_data`, and the previous version's chunks are
removed from the index.

**Rule 7.2** — Superseded chunks are removed from the index. Leaving them means
a query can retrieve and cite the old revision alongside the new one, and the
citation names the same filename in both cases, so the caller has no way to see
that two mutually contradictory passages came from two versions of one file.

**Rule 7.3** — Removal is withdrawal: `lifecycle: "withdrawn"`, chunks removed
from the index, catalogue record retained. The record is what explains why a
run from last month cited a document that is no longer in the corpus.

---

## 8. Retrieval

```
POST /query
{
  "org_id": "org_default",
  "project_id": "proj_alpha",
  "query": "What did the Q3 filing say about deferred revenue?",
  "document_space": "financial_reports",  // optional; omit for project-wide
  "top_k": 5,
  "mode": "mix" | "local" | "global" | "naive"
}
```

`mode` is post-graph-rag's retrieval mode: `local` walks the entity
neighbourhood, `global` uses community summaries, `naive` is plain vector
similarity, and `mix` combines them. `mix` is the default because a question
that names an entity and a question that asks for a theme want different
retrievals, and the caller usually does not know which they asked.

### 8.1 The response

```jsonc
{
  "status": "success",
  "engine": "post-graph-rag",
  "org_id": "org_default",
  "project_id": "proj_alpha",
  "document_space": "financial_reports",
  "space_name": "financial_reports",     // alias, Rule 2.0
  "data": {
    "entities": [ … ], "relationships": [ … ], "chunks": [ … ],
    "references": [{"reference_id": "[1]", "document": "q3-filing.pdf"}]
  },
  "metadata": { … }
}
```

**Rule 8.1** — Every response names the `engine` that produced it. An agent
citing retrieved text is making a claim about provenance, and the strength of
that claim depends on whether the text came from a graph traversal, a vector
scan or a filename listing.

### 8.2 Degradation

The service has a fallback chain: post-graph-rag → a direct post-graph read of
the chunk table → the in-process catalogue.

**Rule 8.2** — A degraded retrieval is reported as degraded, not as
`status: "success"` with a different `engine` string buried in the body. The
last tier in particular returns document *names* where chunks should be — it is
a listing wearing the shape of a retrieval, and an agent handed it will cite
filenames as though they were evidence. It answers `status: "degraded"` with an
explicit `"warning"` field, or it does not answer.

**Rule 8.3** — The in-memory catalogue tier is available only when the
database is unreachable, never when a RAG query merely returned nothing. An
empty corpus and a broken index are different answers, and quietly turning the
first into a filename listing hides the second.

---

## 9. Accounting

The document registry is the origin of the byte-denominated events in AG §12.1
— ingestion and retrieval are the two operations that AG §12.1 names first and
that currently nothing emits.

| Event | `kind` | `bytes` | Emitted when |
| :--- | :--- | :--- | :--- |
| Upload | `document_ingest` | size of the uploaded file | after successful extraction |
| Retrieval | `rag_lookup` | size of the returned chunks | after a successful query |
| Extraction LLM calls | `llm_call` | — | per entity-extraction call made by post-graph-rag |

**Rule 9.1** — Ingestion and retrieval are metered separately (AG §12.1). They
have very different cost profiles — ingestion pays for extraction and embedding
once, retrieval pays a small amount per query forever — and a single combined
counter cannot be billed apart afterwards.

**Rule 9.2** — Metering never blocks or fails an upload or a query
(AG Rule 12.2). Events go to the bounded queue and are flushed in batches.

**Rule 9.3** — `occurred_at` is the moment of the operation, not the moment of
the flush (AG Rule 12.4).

**Rule 9.4** — Entity-extraction LLM calls made inside post-graph-rag are
metered. Indexing one large PDF can cost more model tokens than a day of agent
conversation, and unmetered ingestion is the single largest hole an accounting
ledger can have.

---

## 10. Configuration and startup

**Rule 10.1** — The database DSN comes from configuration and is used as given.
Earlier behaviour tried the configured DSN and then three hardcoded localhost
guesses with embedded credentials, returning a client from whichever answered —
so a typo in `POSTGRES_URI` did not fail; it silently wrote a tenant's
documents to whatever local database happened to accept a guess.

**Rule 10.2** — A missing `OPENAI_API_KEY` fails at **import**, not at first
query. A document service that starts without a key accepts uploads and fails
only once embedding begins, after the caller has been told the upload
succeeded.

**Rule 10.3** — `/health` reports what is actually reachable: the database, the
model router, and whether Docling imported. A health check that returns
constants is a monitor for whether the process is running, which Kubernetes
already knows.

---

## 11. Implementation status

Implemented in `services/document-registry`. Every gap the first draft of this
section recorded is closed:

| Was | Now |
| :--- | :--- |
| The multi-file path substituted `"Document content from file {name}"` on extraction failure | One extraction ladder, one rule. `doc_extract.extract` raises, and the batch endpoint records a per-file failure rather than indexing a placeholder (Rules 5.3, 5.4) |
| Indexing failures logged and swallowed; upload returned `success` | Recorded on the catalogue entry as `index.status: "failed"` with the error, and the upload returns `status: "partial"` (Rule 6.2) |
| The catalogue-memory fallback returned `status: "success"` with filenames as chunks | Removed. A degraded chunk read reports `status: "degraded"` with a warning; if that fails too, the request 503s rather than returning a filename listing (Rules 8.2, 8.3) |
| No metering | `document_ingest` after extraction, `rag_lookup` after retrieval (§9) |
| `created_at` was `asyncio.get_event_loop().time()` | ISO 8601 UTC (Rule 3.4) |
| `document_count` was a stored counter | Derived from the catalogue on every read (Rule 3.3) |
| No document identity, revision, reindex or removal | `document_id` is `(project, document_space, filename)`; re-upload is a revision that removes the superseded chunks; `/reindex` and `DELETE` exist (§7, Rule 6.3) |
| No content hash on uploaded bytes | `sha256` of the bytes, and identical bytes in one document space are a no-op (Rules 5.3, 5.6) |
| Space creation was neither idempotent nor validated | Both (Rules 3.1, 3.2) |
| `documents_catalog_data` never written | One record per revision, per lifecycle change and per reindex (§3.3) |
| `/health` returned literals | Probes the database, Docling, and reports the model router and embedding dimension (Rule 10.3) |
| `if client:` guards that could never be false | Removed |

### 11.1 The namespace, made explicit

`document_space` is now a first-class field name throughout — payloads, request
bodies, query parameters and responses — rather than `space_name` doing double
duty one level away from post-graph's `space`. `space_name` is retained
everywhere as an accepted alias and is still emitted in responses, because the
frontend and `backend/main.py` read it. One canonical field with one alias beats
two fields that can disagree.

The rule that made this worth doing is Rule 2.1: every post-graph call uses
`realm=org_id, space=project_id`, and `test_doc_store.py` asserts that the
document space never appears in the post-graph space slot.

### 11.2 A hard version requirement

`post-graph-rag >= 1.5.2` is now required and checked at import.
`DocumentMetadata.doc_key` and `RAGGraphStore.delete_document_chunks` are
load-bearing: without them a superseded revision's chunks cannot be found and
removed, and a query would cite two contradictory revisions under one filename.

Feature-detecting and degrading was considered and rejected for exactly that
reason — the degraded mode is silently wrong in the way Rule 7.2 exists to
prevent, so the service refuses to start instead.

### 11.3 Defects found by the end-to-end suite

Three, and the first is the most instructive bug in this whole exercise:

1. **`_payload` returned `{}` for every real database row.** It guarded with
   `isinstance(row, dict)`, and `asyncpg.Record` is not a `dict` — it is
   indexable by column and nothing else. Every unit test passed because the
   test double returned dicts. The consequence was silent and severe:
   `get_space` never found an existing space, so **`create_space` appended a
   duplicate on every call** and Rule 3.2 held only in the fake. A `Record`-
   shaped double is now part of the unit suite.
2. **Reads assumed the tables existed.** A realm that had never been written to
   raised `UndefinedTableError` where the honest answer is "empty". Reads now
   treat a missing table as an empty result rather than putting DDL — and its
   concurrency hazard — behind every listing.
3. **`IndexOutcome.succeeded` misread the engine's reply.** post-graph-rag
   returns `entities` as a list of names and the count under
   `entities_extracted`; reading the wrong one raised `TypeError` *inside the
   success path*, turning a successful index into a recorded failure — the
   worst direction for that error to go.

### 11.4 What is still outstanding

- **Reindex needs the file.** The extracted text is not retained on the
  catalogue entry — it lives in the index — so `POST …/reindex` can only re-run
  against a document whose text is still recoverable. Where it is not, the
  endpoint returns `409` telling the caller to re-upload, which will be recorded
  as a new revision. Retaining extracted text on the catalogue would fix this
  and would roughly double the catalogue's size; that trade is not yet made.
- **Entity-extraction LLM calls inside post-graph-rag are not metered**
  (Rule 9.4). The calls happen below this service's API surface, and metering
  them needs a hook post-graph-rag does not expose.
