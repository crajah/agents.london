# Document Registry Microservice (`document-registry`)

The **Document Registry Microservice** manages document spaces, document uploads, Docling content parsing, and GraphRAG knowledge graph indexing for **agent.london**.

---

## 🌟 Key Features

1. **Document Space Sub-grouping (`post-graph` space)**:
   - Projects can create multiple document spaces (e.g. `engineering_docs`, `financial_reports`, `legal_contracts`).
   - Space metadata is stored as vertices in `post-graph`.
2. **Docling Content Extraction**:
   - Uses `docling` to extract structured Markdown, headings, paragraphs, and tables from uploaded documents (PDF, DOCX, Markdown, TXT).
3. **`post-graph-rag` Knowledge Graph Indexing**:
   - Indexes extracted content with `metadata=DocumentMetadata(collection=space_name, space=space_name, document=filename)`.
4. **Space-Agnostic & Space-Scoped RAG Querying**:
   - Agents can execute RAG queries scoped to a target `space` or space-agnostically (`space=None`) across all project spaces.

---

## 🔌 API Endpoints

- `GET /health` — Microservice health status and Docling availability.
- `POST /spaces` — Create a document space for a project.
- `GET /projects/{project_id}/spaces` — List all document spaces for a project.
- `POST /spaces/{space_name}/documents/upload-file` — Upload file, parse with Docling, index into RAG space.
- `POST /spaces/{space_name}/documents/upload-text` — Index raw text content into RAG space.
- `POST /query` — Execute GraphRAG query across a specific space or space-agnostically.
