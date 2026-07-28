# Agent Registry & Ontological Microservice

The **Agent Registry Service** (`services/agent-registry/app.py`) is a Kubernetes microservice (Port 8001) that acts as the ontological authority and versioned registry for every agent in **agent.london**.

---

## 🔑 Key Capabilities

1. **Versioned Ontological Registry**:
   - Registers agents with caste classifications, roles, Telos objectives, token balances, reputation scores, and progeny lineage.
   - Maintains append-only immutable version histories in `post-graph` database table `agent_registry_data`.

2. **Cryptographic Binding & Provenance**:
   - Generates and verifies `ED25519` keypairs (`public_key`), `SHA-256` payload digests (`hash_digest`), and parent signatures (`signature`).

3. **`Kagent` CRD Manifest Generator**:
   - `GET /agents/{agent_id}/kagent-manifest`: Generates valid Kubernetes `kagent.dev/v1alpha1` Custom Resource Definition (CRD) manifests for native Kubernetes pod deployment.

4. **Project Realm Persistence**:
   - All vertices and version records are persisted in `post-graph` PostgreSQL tables (`agent_registry` and `agent_registry_data`) under `realm = project_id`.

---

## 📜 Swagger & OpenAPI Specifications

- **Interactive Swagger UI**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **ReDoc Documentation**: [http://localhost:8001/redoc](http://localhost:8001/redoc)
- **OpenAPI Schema JSON**: [http://localhost:8001/openapi.json](http://localhost:8001/openapi.json)

---

## 🔌 API Endpoints Summary

- **`POST /agents/register`**: Registers a new agent entity or version.
- **`POST /agents/verify`**: Verifies agent cryptographic signature and payload digest.
- **`POST /agents/{agent_id}/audit`**: Records oversight audit notes and updates reputation score.
- **`POST /agents/{agent_id}/allocate-tokens`**: Allocates compute utility tokens.
- **`GET /agents`**: Lists agents filtered by `org_id`, `project_id`, `caste`, or `role`.
- **`GET /agents/{agent_id}`**: Retrieves agent details and version history.
- **`GET /agents/{agent_id}/kagent-manifest`**: Returns `Kagent` Kubernetes CRD YAML manifest.

---

## 🚀 Running Locally

```bash
cd services/agent-registry
pip install -r requirements.txt
uvicorn app:app --port 8001 --reload
```
