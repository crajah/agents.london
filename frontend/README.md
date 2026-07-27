# agent.london — Web Application Frontend

The **agent.london Frontend** is a modern React application built with Vite and Vanilla CSS. It provides an intuitive, high-density dashboard for visualizing and managing the 1 billion agent civilization.

---

## 🎨 Core Visual Components

1. **`PlaygroundView.jsx`**:
   - Interactive prompt playground with **LLM Intent Router accordion** rendering ReAct thinking steps, mode classification (`SIMPLE_CHAT`, `RAG_QUERY`, `MULTI_AGENT_ORCHESTRATION`, `REACT_TOOL_LOOP`, `MULTI_TURN_CONVERSATION`), and mathematical evaluation.

2. **`CivilizationVisualizer.jsx`**:
   - Interactive 28 Prime Caste network topology visualizer displaying Genesis, Archivist, Architect, and Auditor nodes, progeny hierarchy trees, and cryptographic signature badges.

3. **`AgentRegistryView.jsx` & `ToolRegistryView.jsx`**:
   - Ontological agent registry and MCP tool management interface with `Kagent` CRD YAML export capabilities.

4. **`ModelConfigModal.jsx` (BYOM / BYOK)**:
   - Configuration modal for custom LLM providers (LiteLLM, OpenAI, Ollama, DeepSeek) and custom API endpoints.

5. **`ProjectTabsBar.jsx`**:
   - Multi-tenant project switcher enforcing strict `{project}` context boundaries across the entire UI.

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
