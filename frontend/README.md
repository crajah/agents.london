# agent.london — Web Application Frontend

The **agent.london Frontend** is a React application built with Vite and Vanilla CSS. It provides a dashboard for visualizing and managing the 1 billion agent civilization.

---

## 🎨 Core Visual Components

1. **`PlaygroundView.jsx` & Detector-Renderer**:
   - Interactive ChatGPT-style prompt playground with **automatic output format detection and rendering**:
     - **HTML Output**: Rendered in an isolated iframe sandbox.
     - **SVG Graphics**: Rendered as dynamic inline vector graphics.
     - **Markdown & Code**: Rendered with syntax highlighting.
     - **Quantitative Tables**: Rendered as interactive data grids.

2. **`DocumentRegistryView.jsx`**:
   - Multi-document space management interface with drag-and-drop file uploading (PDFs, DOCX, Markdown), Docling text extraction preview, and `post-graph-rag` knowledge graph indexing.

3. **`ProjectTabsBar.jsx` & Organization Universes Scoping**:
   - Filters visible project tabs and workspaces based on the authenticated user's organization permissions (`{org_id}` $\to$ `{user}` $\to$ `{project}`).

4. **`CivilizationVisualizer.jsx`**:
   - Interactive 28 Prime Caste network topology visualizer displaying Genesis, Archivist, Architect, and Auditor nodes, progeny hierarchy trees, and cryptographic signature badges.

5. **`AgentRegistryView.jsx` & `ToolRegistryView.jsx`**:
   - Ontological agent registry and MCP tool management interface with `Kagent` CRD YAML export capabilities.

6. **`ModelConfigModal.jsx` (BYOM / BYOK)**:
   - Configuration modal for custom LLM providers (LiteLLM, OpenAI, Ollama, DeepSeek) and custom API endpoints.

---

## 🚀 Running the Frontend

```bash
cd frontend
npm install
npm run dev
```

The application will be available locally at `http://localhost:5173`.

### Production Build
```bash
npm run build
```
Outputs minified assets in `dist/`.
