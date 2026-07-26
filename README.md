# agent.london — Multi-Tenant Agent Civilization at Scale (1B Agents)

**agent.london** is a platform for materializing and governing an agent civilization scaling up to **1 billion agents** with structures, laws, permanent governing agents, and dynamic worker materialization.

---

## 🏛️ System Architecture

```
+-----------------------------------------------------------------------------------+
|                                   FRONTEND UI                                     |
|          (Civilization Visualizer, Agent Registry, Tool Registry, Sessions)        |
+------------------------------------------+----------------------------------------+
                                           | WebSocket / REST
                                           v
+-----------------------------------------------------------------------------------+
|                                   BACKEND (BFF)                                   |
|                FastAPI orchestrator with multi-tenancy context                     |
+---------------+--------------------------+------------------------+---------------+
                |                          |                        |
                v                          v                        v
+---------------+-------+  +---------------+-------+  +-------------+---------------+
|    SERVICES /         |  |    SERVICES /         |  |     REDIS WORK & PUB/SUB      |
|   AGENT-REGISTRY      |  |   TOOL-REGISTRY       |  |  Task Queues, Event Stream,   |
| (Kagent CRD & Version)|  |  (MCP Tools per Org)  |  |   Inter-Agent Communication   |
+---------------+-------+  +---------------+-------+  +-------------+---------------+
                |                          |                        |
                +--------------------+-----+                        |
                                     |                              |
                                     v                              v
+------------------------------------+------------------------------+---------------+
|                               POSTGRESQL DATABASE                                 |
|   post-graph: Multi-tenant Org realms (Users, Projects, Permanent & Worker Agents)|
|   post-graph-rag: Shared Session Memory & Constitutional Guardrail Evaluation     |
+-----------------------------------------------------------------------------------+
```

---

## 🔑 Key Architectural Features

1. **Multi-Tenancy Hierarchy (`post-graph`)**:
   - `{org}` (Organization realm) $\rightarrow$ `{user}` $\rightarrow$ `{project}` $\rightarrow$ `{agent}`.
   - Every project is isolated with its own schema realm and graph relations.

2. **Permanent Civilization Agents**:
   Every `{project}` automatically provisions permanent governing agents:
   - **`CivilizationGovernor`**: Enforces constitutions, rules, and laws.
   - **`AgentCreator`**: Materializes and spawns new dynamic worker agents on demand.
   - **`InspectorAgent`**: Audits agent performance and enforces inviolable guardrails.

3. **Kubernetes Microservices (`services/`)**:
   - **`agent-registry`** (Port 8001): Kubernetes service managing versioned agent representations, system prompts, memory policies, and Kagent CRD manifests (`kagent.dev/v1alpha1`).
   - **`tool-registry`** (Port 8002): Kubernetes service managing Model Context Protocol (MCP) `{tool}`s linked to `{org}` or `{project}`.

4. **Redis Work Queues & Inter-Agent Communication**:
   - Redis task queues (`agent:queue:{agent_id}`) for asynchronous task dispatching.
   - Event pub/sub channels (`agent:events:{org}:{project}`) for inter-agent communication.

5. **Shared Session Memory System (`post-graph-rag`)**:
   - Initiates a shared memory graph per `{session}` for knowledge integration, context vector embeddings, and semantic RAG retrieval.

---

## 📁 Directory Structure

```
agents.london/
├── frontend/                     # User-facing web application (Visualizer, Registry, Sessions)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── backend/                      # Backend for Frontend (BFF) FastAPI Service
│   ├── main.py
│   ├── civilization.py           # Multi-tenancy & Civilization Engine
│   ├── redis_bus.py              # Redis Pub/Sub & Task Queues
│   ├── requirements.txt
│   └── Dockerfile
├── services/                     # Kubernetes Microservices
│   ├── agent-registry/           # Versioned Agent Registry & Kagent Materialization
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── deployment.yaml
│   └── tool-registry/            # MCP Tool Registry Service
│       ├── app.py
│       ├── requirements.txt
│       ├── Dockerfile
│       └── deployment.yaml
├── test_civilization.py          # Standalone verification script
└── docker-compose.yml            # Container orchestrator
```

---

## 🚀 Running the System

### Option 1: Standalone Python Execution
```bash
# Start Agent Registry Microservice (Terminal 1)
cd services/agent-registry && uvicorn app:app --port 8001

# Start Tool Registry Microservice (Terminal 2)
cd services/tool-registry && uvicorn app:app --port 8002

# Start Backend BFF Service (Terminal 3)
cd backend && uvicorn main:app --port 8000
```

### Option 2: Docker Compose Orchestration
```bash
docker-compose up --build
```
