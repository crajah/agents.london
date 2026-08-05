# agent.london — Multi-Tenant Agent Civilization at Scale (1B Agents)

**agent.london** is an enterprise-grade platform for materializing, orchestrating, and governing an agent civilization scaling up to **1 billion synthetic agents**. Built on **Google Agent Development Kit (ADK)**, **PostgreSQL graph database tables (`post-graph`)**, **`{space}` sub-grouping**, **shared session memory (`post-graph-rag`)**, **Redis work queues**, **in-cluster LiteLLM service integration**, **Google Custom Search GCP MCP tools**, **Federated Enterprise Identity (UAID & X.509 Attestation)**, and **Kubernetes microservices (`Kagent` CRDs)**.

---

## 🏛️ System Architecture

```
+-----------------------------------------------------------------------------------+
|                                  REACT FRONTEND UI                                |
|  (Playground Detector-Renderer, Universes Scoping, Prime Visualizer, BYOM)      |
+------------------------------------------+----------------------------------------+
                                           | WebSocket / REST
                                           v
+-----------------------------------------------------------------------------------+
|                            BACKEND BFF & INTENT ROUTER                            |
|  FastAPI service with Google ADK Engine Factory (GOOGLE_ADK / NATIVE Strategies)  |
|  Tri-Tier Context Fusion: Short-Term Session + Chat RAG + Document Registry RAG   |
+---------------+--------------------------+------------------------+---------------+
                |                          |                        |
                v                          v                        v
+---------------+-------+  +---------------+-------+  +-------------+---------------+
|    SERVICES /         |  |    SERVICES /         |  |    SERVICES /             |
|   AGENT-REGISTRY      |  |   TOOL-REGISTRY       |  |   DOCUMENT-REGISTRY       |
| (UAID, X.509 & Kagent)|  | (GCP Search & MCP)    |  | (Docling & post-graph-rag) |
+---------------+-------+  +---------------+-------+  +-------------+---------------+
                |                          |                        |
                +--------------------+-----+------------------------+
                                     |
                                     v
+------------------------------------+----------------------------------------------+
|                         POSTGRESQL POSTGRAPH DATABASE                             |
|   post-graph: Isolated Project {realm} & {space} Sub-grouping (Agents & Progeny) |
|   post-graph-rag: Shared Session Memory, Embeddings & Guardrail Evaluation        |
+-----------------------------------------------------------------------------------+
```

---

## 🔑 Key Architectural Pillars

### 1. 🤖 Google Agent Development Kit (ADK) Engine & Dual Strategy Architecture
- **Primary Engine Strategy (`GOOGLE_ADK`)**: Leverages Google GenAI SDK & Agent Development Kit (ADK) agent specs (`ADKAgentNode`), multi-agent delegation, and structured tool calling.
- **Native Python Strategy (`NATIVE`)**: High-performance Python engine with zero framework dependencies.
- **Dynamic Factory Switcher (`backend/civilization_factory.py`)**: Seamless hot-swapping controlled by `CIVILIZATION_ENGINE_TYPE` (`"GOOGLE_ADK"` or `"NATIVE"`).

---

### 2. 🧠 Tri-Tier Context Fusion Architecture
- **Tier 1 (Short-Term Session Memory)**: Reads recent conversation turns for `session_id` from `post-graph` table `sessions`.
- **Tier 2 (Long-Term Chat History RAG)**: Embeds and retrieves past chat turns via `post-graph-rag` under realm `{org_id}_{project_id}_chat_memory`.
- **Tier 3 (Document Registry Knowledge RAG)**: Embeds and retrieves uploaded PDFs, DOCX, Markdown, and spreadsheets parsed by Docling/PyPDF across project document spaces.

---

### 3. 🎯 In-Cluster LiteLLM Service Target Priority
- **Primary In-Cluster Target**: Connects to in-cluster LiteLLM / Model Router Kubernetes service (`http://litellm-service.default.svc.cluster.local:80/v1` via ConfigMap `00-litellm-configmap.yaml`).
- **Persisted User Custom Model Exception**: Automatically checks `custom_model_configs` table in `post-graph`. If a user/project has saved a custom model and API key, requests route to the custom model endpoint.

---

### 4. 💬 ChatGPT-style Interactive Playground & Detector-Renderer
- **Detector-Renderer Architecture**: Automatically detects model output formats (HTML, SVG, Markdown, Code, Data Tables) and renders them cleanly in iframe sandboxes or rich UI widgets.
- **Project Universes Scoping**: Filters visible projects and spaces dynamically based on the authenticated user's organization permissions (`{org_id}` $\to$ `{user}` $\to$ `{project}`).

---

### 5. 📚 Interactive Swagger / OpenAPI 3.0 Specifications
Every backend component provides interactive Swagger & ReDoc API documentation:
- **Backend BFF API (`:8000`)**: [/docs](http://localhost:8000/docs) | [/redoc](http://localhost:8000/redoc) | `/openapi.json`
- **Agent Registry (`:8001`)**: [/docs](http://localhost:8001/docs) | [/redoc](http://localhost:8001/redoc) | `/openapi.json`
- **Tool Registry (`:8002`)**: [/docs](http://localhost:8002/docs) | [/redoc](http://localhost:8002/redoc) | `/openapi.json`
- **Document Registry (`:8003`)**: [/docs](http://localhost:8003/docs) | [/redoc](http://localhost:8003/redoc) | `/openapi.json`

---

## 📁 Directory Structure

```
agents.london/
├── frontend/                     # Modern React + Vite Frontend UI
│   ├── src/components/           # Playground, Detector-Renderer, Document Registry, Visualizer
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── backend/                      # Backend for Frontend (BFF) FastAPI Service
│   ├── main.py                   # FastAPI app, OpenAPI tags, WebSocket broadcast, LLM Router
│   ├── civilization_interface.py # AbstractCivilizationEngine Interface contract
│   ├── civilization_adk.py       # Google ADK Engine Implementation & Prime Nodes
│   ├── civilization_factory.py   # Dynamic Engine Factory Router (GOOGLE_ADK / NATIVE)
│   ├── civilization.py           # Native Python Engine & PostGraph persistence
│   ├── prompts.py                # 6-Section Production System Prompts
│   ├── redis_bus.py              # Redis Pub/Sub & Task Queues per project
│   ├── requirements.txt
│   └── Dockerfile
├── services/                     # Kubernetes Microservices
│   ├── agent-registry/           # UAID, X.509 Attestation & Kagent Materialization Service
│   ├── tool-registry/            # MCP Tool Registry Microservice (GCP Search, SQL, pgvector)
│   └── document-registry/        # Multi-document upload, Docling parsing, post-graph-rag indexing
├── deploy/k8s/                   # Kubernetes deployment manifests & ConfigMaps
│   ├── 00-litellm-configmap.yaml # Central LiteLLM service & CIVILIZATION_ENGINE_TYPE config
│   ├── 00-secrets.yaml
│   ├── 01-agent-registry.yaml
│   ├── 02-tool-registry.yaml
│   ├── 03-backend.yaml
│   ├── 04-frontend.yaml
│   ├── 05-ingress.yaml
│   └── 06-document-registry.yaml
├── scripts/                      # Automated deployment & test runner scripts
├── test_civilization.py          # Standalone verification test suite
└── docker-compose.yml            # Local Redis + Postgres + Backend compose manifest
```

---

## 🚀 Quick Start & Local Execution

### Option 1: Automated Local Backend Launcher
```bash
chmod +x scripts/run_local_backend.sh
./scripts/run_local_backend.sh
```

### Option 2: Docker Compose Orchestration
```bash
docker-compose up --build
```

### Option 3: Manual Microservices Startup
```bash
# Terminal 1: Agent Registry Microservice
cd services/agent-registry && uvicorn app:app --port 8001

# Terminal 2: Tool Registry Microservice
cd services/tool-registry && uvicorn app:app --port 8002

# Terminal 3: Document Registry Microservice
cd services/document-registry && uvicorn app:app --port 8003

# Terminal 4: Backend BFF Service (Google ADK default)
cd backend && export CIVILIZATION_ENGINE_TYPE="GOOGLE_ADK" && uvicorn main:app --port 8000

# Terminal 5: React Frontend UI
cd frontend && npm install && npm run dev
```

---

## 🧪 Verification & Testing

Run the full end-to-end test suite:

```bash
python test_civilization.py
```

Validates user creation, project provisioning, Google ADK Prime Node scaffolding, progeny materialization, UAID X.509 attestation, GraphRAG vector indexing, Document Registry RAG, Google Search MCP tool execution, and Playground chat workflows.
