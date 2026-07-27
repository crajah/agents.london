# agent.london — Backend BFF Service & Civilization Engine

The **Backend for Frontend (BFF)** is a high-performance Python FastAPI service (`backend/main.py` and `backend/civilization.py`) that powers the **agent.london 1B Agent Civilization Engine**.

---

## 🏗️ Core Modules

1. **`backend/civilization.py`**:
   - **`AgentCivilizationEngine`**: Main engine orchestrating multi-tenant users, projects, 28 Prime Caste permanent agents, progeny workers, token economics, and audit scores.
   - **`process_user_prompt_with_llm()`**: Autonomous LLM Intent Router categorizing queries into `SIMPLE_CHAT`, `RAG_QUERY`, `MULTI_AGENT_ORCHESTRATION`, `REACT_TOOL_LOOP`, or `MULTI_TURN_CONVERSATION`.
   - **PostGraph Database Persistence**: Persists all entities into PostgreSQL graph tables (`users`, `projects`, `agents`, `agents_data`, `custom_model_configs`, `executions_data`).
   - **Dynamic Project API Keys**: Generates and persists unique 16-character keys (`XXXX-XXXX-XXXX-XXXX`) per `{project_id}` realm.

2. **`backend/redis_bus.py`**:
   - **`RedisBus`**: Work queue and pub/sub engine scoped strictly per `{project_id}` realm.
   - **Task Queues**: `agent:queue:{project_id}:{agent_id}`.
   - **Event Channels**: `agent:events:{org_id}:{project_id}`.
   - **Fallback**: In-memory queue fallback if Redis is unreachable locally.

3. **`backend/main.py`**:
   - **REST & WebSocket Gateway**: Exposes API endpoints for Playground chat, Conductor multi-agent DAG execution, ReAct loops, MCP tool calls, BYOM model configs, and real-time execution telemetry.

---

## 🔌 API Endpoints Summary

- **`POST /api/agent/interact`**: Unified entrypoint using LLM Intent Router.
- **`GET /api/projects/{project_id}/key`**: Retrieves dynamic project API key from `post-graph`.
- **`POST /api/projects/{project_id}/key/regenerate`**: Regenerates a brand-new project API key.
- **`POST /api/tasks/enqueue`**: Enqueues an async task into project Redis work queue.
- **`POST /api/tasks/dequeue/{agent_id}`**: Dequeues next pending task for an agent.
- **`GET /api/metrics/telemetry`**: Retrieves execution telemetry (bytes in/out, tokens in/out).
- **`GET /api/models`**: Lists available models from LiteLLM router or custom BYOM endpoints.

---

## 🚀 Running the Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
