# Document Registry Microservice (`document-registry`)

The **Document Registry Microservice** (`services/document-registry/app.py`) is a Kubernetes microservice (Port 8003) managing document spaces, multi-document uploading, Docling structured text extraction, and `post-graph-rag` knowledge graph indexing for **agent.london**.

---

## 🔑 Key Features

1. **Document Space Sub-grouping (`post-graph` space)**:
   - Projects can create multiple document spaces (e.g. `engineering_docs`, `financial_reports`, `legal_contracts`).
   - Space metadata is stored as vertices in PostgreSQL `post-graph`.

2. **Docling Content Extraction**:
   - Uses `docling` (or `pypdf`, `PyPDF2`, `docx`, `openpyxl`) to extract structured Markdown, headings, paragraphs, and tables from uploaded documents (PDF, DOCX, XLSX, Markdown, TXT).

3. **`post-graph-rag` Knowledge Graph Indexing**:
   - Indexes extracted text into vector memory chunks with `metadata=DocumentMetadata(collection=space_name, space=space_name, document=filename)`.

4. **Space-Agnostic & Space-Scoped RAG Querying**:
   - Agents can execute RAG queries scoped to a target `space` or space-agnostically (`space=None`) across all project spaces.

---

## 📜 Swagger & OpenAPI Specifications

- **Interactive Swagger UI**: [http://localhost:8003/docs](http://localhost:8003/docs)
- **ReDoc Documentation**: [http://localhost:8003/redoc](http://localhost:8003/redoc)
- **OpenAPI Schema JSON**: [http://localhost:8003/openapi.json](http://localhost:8003/openapi.json)

---

## 🔌 API Endpoints Summary

- `GET /health` — Microservice health status and Docling availability.
- `POST /spaces` — Create a document space for a project.
- `GET /projects/{project_id}/spaces` — List all document spaces for a project.
- `POST /spaces/{space_name}/documents/upload-file` — Upload file, parse with Docling, index into RAG space.
- `POST /spaces/{space_name}/documents/upload-text` — Index raw text content into RAG space.
- `POST /query` — Execute GraphRAG query across a specific space or space-agnostically across project domain knowledge.

---

## 🚀 Running Locally

```bash
cd services/document-registry
pip install -r requirements.txt
uvicorn app:app --port 8003 --reload
```
