# Model Context Protocol (MCP) Tool Registry Microservice

The **MCP Tool Registry Service** (`services/tool-registry`) is a Kubernetes microservice (Port 8002) that manages versioned Model Context Protocol (MCP) tool registrations across organizations and projects in **agent.london**.

Specification: [`spec/tool-registry-spec.md`](../../spec/tool-registry-spec.md).

---

## 🔑 Key Capabilities

1. **Versioned, content-hashed tools**:
   - `mcp_tools` holds one identity vertex per tool; `mcp_tools_data` holds one append-only, immutable record per version.
   - Each version is hashed over `endpoint_url`, `transport`, both schemas, `auth`, `limits`, `min_reputation_score` and `side_effects` — so an agent that names a tool names a specific contract.
   - Agents store resolved pins (`{tool_id, version, content_hash}`), not bare ids, because a bare id inside an agent's own hash would certify behaviour that can change underneath it.

2. **Tenancy and scope, kept separate**:
   - Tenancy: `realm = org_id` (physical, a PostgreSQL schema), `space = project_id` (logical).
   - Scope: `scope_type: "org"` is visible to every project in the realm; `scope_type: "project"` to one. Inconsistent combinations are rejected, never normalised.
   - `org_id` is **required** on every read. A listing without a realm is not "all tools".

3. **Invocation with real controls**:
   - `POST /tools/{tool_id}/call` validates arguments against the pinned version's `input_schema` before dispatch.
   - `min_reputation_score` is evaluated at invocation against the calling agent's standing, and fails closed.
   - Tools declaring `side_effects` other than `read` require an `idempotency_key`, because at-least-once delivery means the effect happens at least once too.
   - Credentials are never stored: `auth.secret_ref` names a Kubernetes secret.

4. **Discovery**:
   - By vector over name, description, capabilities and input-schema property descriptions (`GET /tools/search`).
   - By id, the only path that may return a non-current version — pins need it.
   - Rendered as prose for `post-graph-rag` indexing (`GET /tools/rag-documents`).

5. **Accounting**: `search_query`, `search_results` and `rag_lookup` usage events per organisation, through the shared bounded-queue meter. Metering never blocks or fails a call.

---

## 📜 Swagger & OpenAPI Specifications

- **Interactive Swagger UI**: [http://localhost:8002/docs](http://localhost:8002/docs)
- **ReDoc Documentation**: [http://localhost:8002/redoc](http://localhost:8002/redoc)
- **OpenAPI Schema JSON**: [http://localhost:8002/openapi.json](http://localhost:8002/openapi.json)

---

## 🔌 API Endpoints Summary

| Endpoint | Purpose |
| :--- | :--- |
| `POST /tools/register` | Register a tool version. Accepts `{identity, version}` or the legacy flat body. |
| `GET /tools?org_id=…` | List tools visible to `(org_id, project_id)`. `org_id` required. |
| `GET /tools/search?q=…&org_id=…` | Vector discovery over tool descriptions. |
| `GET /tools/rag-documents?org_id=…` | Tools rendered as prose for RAG indexing. |
| `GET /tools/{tool_id}?org_id=…&version=…` | One tool, at a version or at `current_version`. |
| `POST /tools/{tool_id}/call` | Invoke a tool version. |
| `POST /tools/{tool_id}/retire` | Deprecate or revoke one version. Revocation requires a replacement. |
| `DELETE /tools/{tool_id}?org_id=…` | Dormancy, persisted. The tool is retained for provenance. |
| `POST /tools/{tool_id}/restore?org_id=…` | Undo dormancy. |
| `POST /tools/google-search` | Builtin: GCP Custom Search. Every failure path errors; it never invents results. |
| `GET /health` | Reports what is actually reachable, not constants. |

---

## 🧱 Layout

| File | Holds |
| :--- | :--- |
| `tool_model.py` | Validation and hashing. No I/O, directly testable. |
| `tool_store.py` | Reads and writes against post-graph. |
| `tool_cache.py` | Realm-partitioned read-through cache. |
| `tool_api.py` | HTTP surface. |
| `app.py` | Host, lifespan, default catalogue, builtin tools. |

`metering.py` and `embedding.py` come from `shared/` and are copied into the image — one canonical copy, not a vendored duplicate.

---

## 🚀 Running Locally

```bash
python3 -m pytest services/tool-registry -q     # from the repository root
PYTHONPATH=.:../../backend uvicorn app:app --port 8002 --reload
```

The image builds from the **repository root**, not this directory:

```bash
docker build -f services/tool-registry/Dockerfile -t tool-registry .
```

## External provider tools

Three providers are catalogued as `kind: "builtin"` tools, implemented in
`external_tools.py`. All of them obey Rule 7.2 — a call that did not obtain a
result raises rather than returning one — and Rule 7.3: a provider with no
credential is **not registered at all**, so discovery never offers an agent a
tool that can only answer 503.

| `tool_id` | Endpoint | Credential |
| :--- | :--- | :--- |
| `mcp-tavily-search` | `POST /tools/tavily-search` | `TAVILY_API_KEY[_n]` |
| `mcp-serper-search` | `POST /tools/serper-search` | `SERPER_API_KEY` |
| `mcp-rapidapi-deezer` | `POST /tools/rapidapi/deezer` | `RAPIDAPI_KEY` |
| `mcp-rapidapi-yahoo-finance` | `POST /tools/rapidapi/yahoo-finance` | `RAPIDAPI_KEY` |

### Tavily key rotation

Supply as many keys as you hold, as `TAVILY_API_KEY` and `TAVILY_API_KEY_1..n`.
`TavilyKeyRing` does two separate things that a plain retry does not:

- **Spreads load.** Each call starts at the next key, so *n* keys carry roughly
  1/*n* of the traffic rather than the first key absorbing all of it.
- **Fails over within a call.** A key that reports an auth or quota problem is
  stepped over and the next tried, up to the number of usable keys.

The two failure classes are treated differently on purpose. A revoked key (401)
fails identically forever, so it is **quarantined** and leaves the rotation —
keeping it would turn one dead key into a fixed fraction of failed searches. An
exhausted key (429/432) recovers on the provider's clock, so it is only
**benched** for `TAVILY_QUOTA_COOLDOWN_SECS` (default 900).

`GET /tools/tavily-search/keys` reports per-key state by *variable name* and
never returns a key's value, so an operator can see which key is quarantined
without access to the secret.

### Adding a RapidAPI service

Append a `RapidApiService` to `RAPIDAPI_SERVICES`. Each becomes its own
`tool_id`, deliberately: a single generic "call RapidAPI" tool taking a host
and path would push the choice of endpoint onto the model, which is the
guessing Rule 3.2 exists to prevent.

Only services this account is subscribed to **and** that still answer are
listed. Three subscribed APIs are deliberately excluded as dead upstreams —
`linkedin-api8` (HTTP 200 with `{"success": false, "message": "This service is
no longer available at this location"}`), `google-translate1`
(`{"message": "API doesn't exists"}`) and `numbersapi` (404 on every path).
Cataloguing them would advertise capabilities that fail at call time. The
linkedin case is the dangerous one — a 200 with a falsy body is the shape most
easily mistaken for a result — so `rapidapi_call` checks for it explicitly.

Note also that RapidAPI returns the **same** HTTP 403 for an invalid key and
for a valid key that is not subscribed, so the error raised here says both are
possible rather than guessing one.

### Creating the secret

```bash
kubectl create secret generic external-tool-keys \
  --from-literal=SERPER_API_KEY=... \
  --from-literal=TAVILY_API_KEY_1=... \
  --from-literal=TAVILY_API_KEY_2=... \
  --from-literal=RAPIDAPI_KEY=...
```
