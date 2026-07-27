# agent.london — Multi-Tenant Agent Civilization at Scale (1B Agents)

**agent.london** is an enterprise-grade platform for materializing, orchestrating, and governing an agent civilization scaling up to **1 billion synthetic agents**. Built on **PostgreSQL graph database tables (`post-graph`)**, **`{space}` sub-grouping**, **shared session memory (`post-graph-rag`)**, **Redis work queues**, **LiteLLM router integration**, **Google Custom Search GCP MCP tools**, **Federated Enterprise Identity (UAID & X.509 Attestation)**, and **Kubernetes microservices (`Kagent` CRDs)**.

---

## 🏛️ System Architecture

```
+-----------------------------------------------------------------------------------+
|                                  REACT FRONTEND UI                                |
|   (ChatGPT Playground, Solitary/Workflow Modes, 28 Prime Visualizer, BYOM)         |
+------------------------------------------+----------------------------------------+
                                           | WebSocket / REST
                                           v
+-----------------------------------------------------------------------------------+
|                            BACKEND BFF & INTENT ROUTER                            |
| FastApi service with LLM Intent Classifier (SOLITARY, WORKFLOW, RAG, REACT, CHAT) |
+---------------+--------------------------+------------------------+---------------+
                |                          |                        |
                v                          v                        v
+---------------+-------+  +---------------+-------+  +-------------+---------------+
|    SERVICES /         |  |    SERVICES /         |  |     REDIS WORK & PUB/SUB      |
|   AGENT-REGISTRY      |  |   TOOL-REGISTRY       |  |  Task Queues per {project},   |
| (UAID, X.509 & Kagent)|  | (GCP Search & MCP)    |  |   Event Stream & Pub/Sub      |
+---------------+-------+  +---------------+-------+  +-------------+---------------+
                |                          |                        |
                +--------------------+-----+                        |
                                     |                              |
                                     v                              v
+------------------------------------+------------------------------+---------------+
|                         POSTGRESQL POSTGRAPH DATABASE                             |
|   post-graph: Isolated Project {realm} & {space} Sub-grouping (Agents & Progeny) |
|   post-graph-rag: Shared Session Memory, Embeddings & Guardrail Evaluation        |
+-----------------------------------------------------------------------------------+
```

---

## 🔑 Key Architectural Pillars

### 1. 💬 ChatGPT-style Interactive Playground & Execution Modes
The Playground interface ([PlaygroundView.jsx](file:///Users/crajah/Dropbox/_CREATIVE_/_GITHUB_ME/agents.london/frontend/src/components/PlaygroundView.jsx)) provides a ChatGPT-like interaction model:
- **Solitary Agent Mode**: Direct 1-on-1 interaction with a specific target agent (one of the 28 Primes or custom progeny worker) using its specific Telos system prompt and assigned LLM model.
- **Multi-Agent Workflow Mode**: Conductor DAG guild orchestration decomposing user prompts into parallel sub-tasks across governing agents with multi-page consensus reports.
- **Model Router Selector**: Select models on the fly (`DeepSeek-V3.2`, `Meta-Llama-3.3-70B`, `GPT-OSS 120B`, `Gemma 4 31B`, `MiniMax M2.7`).
- **Full Document Output**: Synthesizes structured 5-section Markdown reports (Executive Summary, Guild Allocation, Quantitative Data Tables, Strategic Synthesis, and Cryptographic Signoff).

---

### 2. 🏛️ Federated Enterprise Identity (UAID, Entra & X.509 Attestation)
- **Unique Agent Identifier (UAID)**: Digital Passport issued by Federated Root CA:
  `uaid:london:auth:{project_id}:{agent_id}:v{version}`
- **Entra Agent 365 Principal**: Security principal mapping for IAM access control within Cortex:
  `spn:agent365:{agent_id}@{project_id}.entra.agent.london`
- **X.509 Certificate Codebase Attestation**: Cryptographically binds the agent's identity to the SHA-256 hash digest of its system prompt, codebase, and configuration (`codebase_hash_attestation: sha256:{hash}`).

---

### 3. 📜 Comprehensive 6-Section Production System Prompts
Every agent operates under an exhaustive 6-section system prompt:
1. **Identity & Cognitive Mandate** (Caste, Topology, Telos, Cryptographic Provenance).
2. **Constitutional Bindings & 4 Inviolable Directives** (Preservation, Purpose, Compliance, Efficiency).
3. **Standard Operating Protocol & Execution Workflow** (Ingestion, RAG Search, Decomposed Execution, Self-Correction, Signoff).
4. **Tool Execution & MCP Integration Guidelines** (Defensive error handling & schema compliance).
5. **Response Formatting & Presentation Standards** (GitHub-Flavored Markdown, LaTeX math, comparative tables).
6. **Provenance Signature Header** (`[ED25519 VERIFIED: sig_...]`).

---

### 4. 🔒 Dual Isolation: `{realm}` & `{space}` Sub-grouping (`post-graph`)
- **Macro-Isolation (`realm = project_id`)**: Strict project-level data separation across all PostgreSQL tables and Redis queues.
- **Micro-Isolation (`space`)**: Application-level sub-grouping (`space VARCHAR(255) DEFAULT 'default'`) allowing teams to segregate datasets (e.g. `production`, `sandbox`, `staging`) within a project.

---

### 5. 🔍 GCP Google Custom Search MCP Microservice (`mcp-google-search`)
- Integrated into `services/tool-registry/app.py` (`POST /tools/google-search`).
- Leverages GCP Custom Search API with secret key management (`GOOGLE_SEARCH_API_KEY`) and fallback Search Engine ID (`GOOGLE_SEARCH_CX`).
- Accessible to authorized agents when configured in their tool registry access policy.

---

### 6. 🏰 28 Prime Agent Castes & Persistent Progeny Recovery
- Every project provisions 28 permanent Prime Agents spanning 4 core castes (Genesis, Archivist, Architect, Auditor).
- **Agent Recovery (`GET /api/projects/{project_id}/agents`)**: Persists and recovers all Primes and custom progeny agents from `post-graph` tables (`agents`, `agents_data`).

---

## 📁 Directory Structure

```
agents.london/
├── frontend/                     # Modern React + Vite Frontend UI
│   ├── src/components/           # Playground, Visualizer, Agent & Tool Registries
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── backend/                      # Backend for Frontend (BFF) FastAPI Service
│   ├── main.py                   # Playground endpoints, REST, WebSocket broadcast, LLM Router
│   ├── civilization.py           # 1B Civilization Engine & PostGraph persistence
│   ├── prompts.py                # Comprehensive 6-Section System Prompt Generator
│   ├── redis_bus.py              # Redis Pub/Sub & Task Queues per project
│   ├── requirements.txt
│   └── Dockerfile
├── services/                     # Kubernetes Microservices
│   ├── agent-registry/           # UAID, X.509 Attestation & Kagent Materialization Service
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── README.md
│   └── tool-registry/            # MCP Tool Registry Microservice (GCP Search, SQL, pgvector)
│       ├── app.py
│       ├── requirements.txt
│       ├── Dockerfile
│       └── README.md
├── deploy/k8s/                   # Kubernetes deployment manifests & secret templates
├── scripts/                      # Deployment & test runner scripts
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

### Option 3: Manual Startup
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

Run the full end-to-end test suite:

```bash
python test_civilization.py
```

Validates user creation, project provisioning, 28 Prime Caste scaffolding, progeny materialization, UAID X.509 attestation, GraphRAG vector indexing, Google Search MCP tool execution, and Playground chat workflows.
