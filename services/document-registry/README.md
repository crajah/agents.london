# Document Registry Microservice (`document-registry`)

The **Document Registry Microservice** (`services/document-registry`) is a Kubernetes microservice (Port 8003) managing document spaces, multi-document uploading, Docling structured text extraction, and `post-graph-rag` knowledge graph indexing for **agent.london**.

Specification: [`spec/document-registry-spec.md`](../../spec/document-registry-spec.md).

---

## 🗂 The three-tier namespace

The word "space" means two different things one level apart, so they are named apart:

| Tier | Field | post-graph construct | Isolation |
| :--- | :--- | :--- | :--- |
| Organisation | `org_id` | **realm** — a PostgreSQL schema | Physical |
| Project | `project_id` | **space** — a column in that schema | Logical |
| Document space | `document_space` | *none* — payload metadata | A filter |

Every post-graph call is made with **`realm=org_id, space=project_id`**. The document space (`engineering_docs`, `financial_reports`, `legal_contracts`) is the third tier: it travels as `collection` in the RAG metadata and as `document_space` on the catalogue vertex, and it is filtered on at query time.

`space_name` is accepted everywhere as an alias for `document_space`, because that is the field the backend and frontend send. One canonical field with one alias beats two fields that can disagree.

Two document spaces in one project **share a knowledge graph** — entities from `legal_contracts` may link to entities from `financial_reports`, which is the point of a graph RAG. A caller needing genuine isolation uses two projects.

---

## 🔑 Key Features

1. **The catalogue and the index are separate stores.** The catalogue answers "what was ingested, from what file, by which parser, when" — exactly. The index answers "what is relevant" — approximately. Collapsing them makes a document that indexed badly indistinguishable from one never uploaded.

2. **Extraction fails loudly.** Docling → pypdf → PyPDF2 → python-docx → python-pptx → openpyxl → strict UTF-8. When nothing succeeds, ingestion returns `415` and stores nothing. It never substitutes a placeholder — twice in this service's history it did, and both times the placeholder was embedded and indexed as if it were prose. The batch endpoint applies the identical rule.

3. **Indexing failures are recorded, not swallowed.** A document that extracted but failed to index is catalogued with `index.status: "failed"` and the error, and the upload reports `status: "partial"`. `POST …/reindex` exists precisely because that state is recoverable.

4. **Documents have identity and revisions.** Identity is `(org_id, project_id, document_space, filename)`. Re-uploading that name is a revision: the superseded chunks are removed from the index, and every revision is kept in `documents_catalog_data`. Identical bytes are a no-op.

5. **Degraded retrieval says so.** Responses always name the `engine`. A fall back to a direct chunk read returns `status: "degraded"` with an explicit warning; there is no filename-listing tier, because a listing presented as retrieval is evidence an agent will cite.

6. **Accounting.** `document_ingest` and `rag_lookup` usage events per organisation, through the shared bounded-queue meter. Metering never blocks or fails an upload or a query.

---

## 📜 Swagger & OpenAPI Specifications

- **Interactive Swagger UI**: [http://localhost:8003/docs](http://localhost:8003/docs)
- **ReDoc Documentation**: [http://localhost:8003/redoc](http://localhost:8003/redoc)
- **OpenAPI Schema JSON**: [http://localhost:8003/openapi.json](http://localhost:8003/openapi.json)

---

## 🔌 API Endpoints Summary

| Endpoint | Purpose |
| :--- | :--- |
| `GET /health` | Real probes: database, Docling, model router, embedding dim. |
| `POST /spaces` | Create a document space. Idempotent. |
| `GET /projects/{project_id}/spaces` | Spaces with **derived** document counts. |
| `GET /projects/{project_id}/documents` | Documents, optionally filtered by document space. |
| `POST /spaces/{space}/documents/upload-text` | Index raw text. |
| `POST /spaces/{space}/documents/upload-file` | Upload one file. `415` if nothing extracts. |
| `POST /spaces/{space}/documents/upload-multiple-files` | Batch upload with per-file outcomes and separate succeeded/failed counts. |
| `POST /projects/{p}/documents/{doc_id}/reindex` | Retry a failed index. |
| `DELETE /projects/{p}/documents/{doc_id}` | Withdraw: chunks removed, record retained. |
| `GET /projects/{p}/documents/{doc_id}/revisions` | Revision history. |
| `POST /query` | GraphRAG retrieval, project-wide or scoped to a document space. |

---

## 🧱 Layout

| File | Holds |
| :--- | :--- |
| `doc_model.py` | Namespace, identity, hashing, request shapes. No I/O. |
| `doc_extract.py` | The extraction ladder and Rule 5.3. |
| `doc_store.py` | The catalogue in post-graph. |
| `doc_rag.py` | post-graph-rag indexing, chunk removal, retrieval. |
| `app.py` | Host and HTTP surface. |

`metering.py` comes from `backend/` and is copied into the image.

---

## ⚠️ Version requirement

`post-graph-rag >= 1.5.2` is required and checked at import. Two capabilities are load-bearing: `DocumentMetadata.doc_key` (finding a document's chunks again) and `RAGGraphStore.delete_document_chunks` (removing a superseded revision's). Feature-detecting and degrading would leave superseded chunks in the index, where a query cites two contradictory revisions under one filename.

---

## 🚀 Running Locally

```bash
python3 -m pytest services/document-registry -q     # from the repository root
PYTHONPATH=.:../../backend uvicorn app:app --port 8003 --reload
```

The image builds from the **repository root**:

```bash
docker build -f services/document-registry/Dockerfile -t document-registry .
```
