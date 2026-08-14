# Agent Registry & Ontological Microservice

The **Agent Registry Service** (`services/agent-registry`) is a Kubernetes microservice (Port 8001) that acts as the ontological authority and versioned registry for every agent and pipeline in **agent.london**.

Specification: [`spec/agent-graph-spec.md`](../../spec/agent-graph-spec.md).

---

## 🔑 Key Capabilities

1. **One versioned graph**:
   - `agents` / `agents_data` and `pipelines` / `pipelines_data` — one identity vertex, one append-only immutable record per version.
   - Every version is content-hashed over what determines behaviour. A published version is immutable; any change is a new version.
   - Pipelines pin **exact** agent versions. `@latest` is resolved at publish time and never stored, because a pipeline whose behaviour changes when a dependency is republished is not reproducible.
   - Composition is edges, not a JSON blob: "which pipelines pin this agent version" is one hop, not a scan.

2. **Cyclic and recursive pipelines**:
   - Back edges are computed at publish by DFS and stored. A cyclic pipeline must declare `max_iterations` and must have a way out.
   - `invokes_pipeline` edges are written and **followed by the executor**. Recursion depth is enforced at run creation, before the child does any work, and a nested run's compute units count against the parent's budget.
   - Exhaustion is never success: a halted run surfaces as `isError` over MCP and as `failed` with a `halt_reason` over A2A.

3. **Tools are pinned, not named**:
   - An agent's `tools` list is resolved against the tool registry to `{tool_id, version, content_hash}` *before* the agent's content hash is computed. A missing, unpublished, revoked or out-of-scope tool fails registration.

4. **Exposure is derived**:
   - Every published version is one MCP tool and one A2A card. Nothing else is. Two lists that can disagree eventually will.

5. **Discovery**: by vector over telos and description, by exact capability, and by structure (`descendants` over `spawns`, `dependents` back along `composes_pipeline`).

6. **Accounting**: `llm_call` usage events per organisation into `usage_events`, through a bounded queue that never blocks the work it measures.

---

## 📜 Swagger & OpenAPI Specifications

- **Interactive Swagger UI**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **ReDoc Documentation**: [http://localhost:8001/redoc](http://localhost:8001/redoc)
- **OpenAPI Schema JSON**: [http://localhost:8001/openapi.json](http://localhost:8001/openapi.json)

---

## 🔌 API Endpoints Summary

### The graph surface

| Endpoint | Purpose |
| :--- | :--- |
| `POST /agents` | Register an agent version. `publish: false` stages a draft. |
| `POST /pipelines` | Register a pipeline composition. Validated in full before the first write. |
| `POST /agents/{id}/retire` | Deprecate or revoke a version. Revoking a pinned one needs a replacement or a cascade. |
| `POST /agents/{id}/lifecycle` | Dormancy. Agents are never deleted — their `spawns` edges are the provenance record. |
| `GET /discover` | By vector (`q=`) or by exact capability (`capability=`). |
| `GET /agents/{id}/descendants` | Bounded traversal over `spawns`. |
| `GET /agents/{id}/dependents` | Which published pipelines pin a version. |
| `GET /mcp/tools`, `POST /mcp/tools/{name}/call` | MCP listing and invocation. |
| `GET /.well-known/agent.json` | This registry's own A2A card. |
| `GET /a2a/{plural}/{slug}/{version}/card`, `POST …/tasks` | A2A cards and task submission. |

### The original surface, unchanged

`POST /agents/register`, `/agents/verify`, `/agents/{id}/audit`, `/agents/{id}/allocate-tokens`, `GET /agents`, `/agents/{id}`, `/agents/{id}/progeny`, `/agents/{id}/kagent-manifest`, `/agents/rag-documents`, `/pipelines/{id}/graph`.

Same requests, same responses — `backend/main.py` and the frontend need no change. Underneath, `legacy_shim.py` translates them onto the graph, so there is one store rather than two that can disagree. Progeny is derived from the `spawns` edges rather than kept as a list; auditing patches the identity vertex and does not produce a new version, because it does not change what the agent does.

---

## 🧱 Layout

| File | Holds |
| :--- | :--- |
| `registry_model.py` | Validation, hashing, cycle analysis. No I/O, directly testable. |
| `registry_store.py` | Reads and writes against post-graph. |
| `registry_api.py` | Registration, discovery, MCP, A2A. |
| `execution.py` | Resolving and calling one agent version. |
| `tool_client.py` | Reading the tool registry to resolve tool pins. |
| `legacy_shim.py` | The original surface, translated onto the graph. |
| `app.py` | Host, lifespan, the original endpoints. |

`metering.py`, `pipeline_runtime.py` and `embedding.py` come from `backend/` and are copied into the image — one canonical copy, not vendored duplicates.

---

## 🚀 Running Locally

```bash
python3 -m pytest services/agent-registry -q     # from the repository root
PYTHONPATH=.:../../backend uvicorn app:app --port 8001 --reload
```

The image builds from the **repository root**, not this directory:

```bash
docker build -f services/agent-registry/Dockerfile -t agent-registry .
```
