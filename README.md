# agent.london — Multi-Tenant Agent Civilization at Scale (1B Agents)

**agent.london** is an enterprise-grade platform for materializing, orchestrating, and governing an agent civilization scaling up to **1 billion synthetic agents**. Built on **PostgreSQL graph database tables (`post-graph`)**, **shared session memory (`post-graph-rag`)**, **Redis work queues**, **LiteLLM router integration**, and **Kubernetes microservices (`Kagent` CRDs)**.

---

## 🏛️ System Architecture

```
+-----------------------------------------------------------------------------------+
|                                  REACT FRONTEND UI                                |
|        (Playground, 28 Prime Castes Visualizer, Agent & Tool Registries, BYOM)    |
+------------------------------------------+----------------------------------------+
                                           | WebSocket / REST
                                           v
+-----------------------------------------------------------------------------------+
|                            BACKEND BFF & INTENT ROUTER                            |
|    FastAPI service with LLM Intent Classifier (SIMPLE, RAG, ORCHESTRATE, REACT, CHAT)|
+---------------+--------------------------+------------------------+---------------+
                |                          |                        |
                v                          v                        v
+---------------+-------+  +---------------+-------+  +-------------+---------------+
|    SERVICES /         |  |    SERVICES /         |  |     REDIS WORK & PUB/SUB      |
|   AGENT-REGISTRY      |  |   TOOL-REGISTRY       |  |  Task Queues per {project},   |
| (Kagent CRD & Version)|  |  (MCP Tools per Scope)|  |   Event Stream & Pub/Sub      |
+---------------+-------+  +---------------+-------+  +-------------+---------------+
                |                          |                        |
                +--------------------+-----+                        |
                                     |                              |
                                     v                              v
+------------------------------------+------------------------------+---------------+
|                         POSTGRESQL POSTGRAPH DATABASE                             |
|   post-graph: Isolated Project realms (Users, Projects, 28 Prime Agents & Progeny)|
|   post-graph-rag: Shared Session Memory, Embeddings & Guardrail Evaluation        |
+-----------------------------------------------------------------------------------+
```

---

## 🔑 Key Architectural Pillars

### 1. 🤖 2.0 Autonomous LLM Intent Router
Every incoming prompt is dynamically evaluated by LLM intelligence into one of 5 execution pathways:
- **`SIMPLE_CHAT`**: Evaluates direct factual questions, greetings, or mathematical expressions (e.g. `what is 2 + 2` $\rightarrow$ `4`) instantly.
- **`RAG_QUERY`**: Queries `post-graph-rag` vector embeddings and session memory for document retrieval.
- **`MULTI_AGENT_ORCHESTRATION`**: Decomposes complex goals into multi-stage execution DAGs across the 28 Prime Agents and materializes progeny worker agents (`Kagent`).
- **`REACT_TOOL_LOOP`**: Executes multi-turn reasoning loops with MCP tools (pgvector search, SQL, Redis queues).
- **`MULTI_turn_CONVERSATION`**: Maintains conversation history in `post-graph` session memory across turns.

---

### 2. 🏰 28 Prime Agent Castes & Progeny Lineage
Every `{project}` automatically provisions 28 permanent Prime Agents spanning 4 core castes:
- **Genesis Caste**: `Evolution Driver`, `Telos Architect`, `Caste Arbiter`, `Lineage Governor`.
- **Archivist Caste**: `Chronicle Keeper`, `Knowledge Grapher`, `Memory Vectorizer`, `Signal Router`.
- **Architect Caste**: `Master Strategist`, `Prime Executor`, `Inference Chain`, `Action Sequencer`, `Polymath Node`, `Swarm Commander`, `Decision Router`, `Tool Master`.
- **Auditor Caste**: `Grand Critic`, `Nexus Coordinator`, `Feedback Loop`, `Protocol Translator`, `Self Corrector`, `Synchronicity Engine`.

Dynamic **Progeny Worker Agents** are materialized on demand with cryptographically signed provenance (`ED25519` keypair & `SHA-256` payload digest).

---

### 3. 🔒 100% PostGraph Database Persistence & Project Isolation
- **100% Persistent**: All users, project universes, dynamic project API keys (`XXXX-XXXX-XXXX-XXXX`), agent vertices, append-only immutable version histories (`agents_data`), tool registries (`mcp_tools`), execution telemetry (`executions_data`), and custom BYOM/BYOK configs are stored in PostgreSQL graph tables.
- **Strict `{project}` Isolation**: Every database table query, Redis work queue (`agent:queue:{project_id}:{agent_id}`), and pub/sub event channel (`agent:events:{org_id}:{project_id}`) uses `realm = project_id` to guarantee zero cross-project leakage.

---

### 4. 📊 Observability & Telemetry Stack
- **Prometheus & Loki**: Pod metrics and log aggregation.
- **GKE Autopilot Compliant Promtail**: Strictly uses `/var/log/pods` to comply with GKE Warden constraints.
- **Public Read-Only Grafana**: Accessible externally at **`https://agents.london/telemetry`** with anonymous viewer privileges (read logs/dashboards without edit rights).

---

## 📁 Directory Structure

```
agents.london/
├── frontend/                     # Modern React + Vite Frontend UI (Visualizer, Playground, BYOM)
│   ├── src/components/           # ReAct Thinking, 28 Prime Castes, Tool & Agent Registries
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── backend/                      # Backend for Frontend (BFF) FastAPI Service
│   ├── main.py                   # REST endpoints, WebSocket broadcast, LLM Router
│   ├── civilization.py           # Multi-tenant 1B Civilization Engine & PostGraph persistence
│   ├── redis_bus.py              # Redis Pub/Sub & Task Queues per project
│   ├── requirements.txt
│   └── Dockerfile
├── services/                     # Kubernetes Microservices
│   ├── agent-registry/           # Versioned Agent Registry & Kagent Materialization Service
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── README.md
│   └── tool-registry/            # MCP Tool Registry Microservice
│       ├── app.py
│       ├── requirements.txt
│       ├── Dockerfile
│       └── README.md
├── scripts/                      # Local development & Kubernetes deployment scripts
│   ├── run_local_backend.sh      # Local dev launcher with Redis & Postgres container auto-detection
│   └── 03_deploy_k8s.sh
├── test_civilization.py          # Standalone verification test suite
└── docker-compose.yml            # Local Redis + Postgres + Backend compose manifest
```

---

## 🚀 Quick Start & Local Execution

### Option 1: Automated Local Backend Launcher
Runs local Redis & Postgres containers if needed and starts the backend service:

```bash
chmod +x scripts/run_local_backend.sh
./scripts/run_local_backend.sh
```

### Option 2: Docker Compose Orchestration
```bash
docker-compose up --build
```

### Option 3: Manual Python Startup
```bash
# Terminal 1: Agent Registry Microservice
cd services/agent-registry && uvicorn app:app --port 8001

# Terminal 2: Tool Registry Microservice
cd services/tool-registry && uvicorn app:app --port 8002

# Terminal 3: Backend BFF Service
cd backend && uvicorn main:app --port 8000

# Terminal 4: React Frontend UI
cd frontend && npm install && npm run dev
```

---

## 🧪 Verification & Testing

Run the full end-to-end engine test suite:

```bash
python test_civilization.py
```

Validates user creation, project provisioning, 28 Prime Caste scaffolding, progeny materialization, cryptographic verification, token allocation, GraphRAG indexing, Conductor multi-agent composition, and ReAct reasoning loops.
