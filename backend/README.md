# agent.london — Backend BFF Service & Civilization Engine

The **Backend for Frontend (BFF)** is a FastAPI service (`backend/main.py`) powering the **agent.london 1B Agent Civilization Engine** with a **Dual-Engine Strategy Architecture** (Google ADK & Native Python).

---

## 🏗️ Core Architecture & Engine Modules

1. **`backend/civilization_interface.py`**:
   - **`AbstractCivilizationEngine`**: Abstract base class defining unified engine methods (`process_user_prompt_with_llm`, `run_conductor_orchestration`, `run_react_loop`, `provision_civilization_for_project`).

2. **`backend/civilization_adk.py`**:
   - **`GoogleADKCivilizationEngine`**: Google Agent Development Kit (ADK) implementation with 28 Prime Node specs (`ADKAgentNode`), multi-agent delegation, and RAG memory search.

3. **`backend/civilization_factory.py`**:
   - **`get_civilization_engine()`**: Factory router inspecting `CIVILIZATION_ENGINE_TYPE` (`"GOOGLE_ADK"` default vs `"NATIVE"`).

4. **`backend/civilization.py`**:
   - **`AgentCivilizationEngine`**: High-performance Native Python engine with zero framework dependencies.

5. **`backend/redis_bus.py`**:
   - **`RedisBus`**: Work queue and pub/sub engine scoped strictly per `{project_id}` realm.

---

## 🧠 Tri-Tier Context Fusion

All LLM queries automatically assemble a 3-tier context header before calling Google ADK Prime Agents:
- **Tier 1 (Short-Term Session Memory)**: Reads recent turns from PostgreSQL `sessions` table.
- **Tier 2 (Long-Term Chat RAG Memory)**: Retrieves past conversation turns from `post-graph-rag` realm `{org_id}_{project_id}_chat_memory`.
- **Tier 3 (Document Registry RAG Knowledge)**: Retrieves matching chunks from uploaded PDFs, DOCX, Markdown files from space realm `{project_id}`.

---

## 🎯 Model Target Resolution Order

1. **Primary Target**: In-cluster LiteLLM service (`http://litellm-service.default.svc.cluster.local:80/v1` via ConfigMap `00-litellm-configmap.yaml`).
2. **User Custom Model Exception**: Checks `custom_model_configs` table in `post-graph`. If active for `{project_id}`, routes to user custom model & API key.

---

## 📜 Swagger & OpenAPI Specifications

- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI Schema JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 🚀 Running the Backend

```bash
cd backend
pip install -r requirements.txt

# Option A: Run with Google ADK Engine (Default)
export CIVILIZATION_ENGINE_TYPE="GOOGLE_ADK"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Option B: Run with Native Engine
export CIVILIZATION_ENGINE_TYPE="NATIVE"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
