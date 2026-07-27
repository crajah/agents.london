# Model Context Protocol (MCP) Tool Registry Microservice

The **MCP Tool Registry Service** (`services/tool-registry/app.py`) is a Kubernetes microservice (Port 8002) that manages Model Context Protocol (MCP) tool registrations across organizations and projects in **agent.london**.

---

## 🔑 Key Capabilities

1. **MCP Tool Scoping & Linking**:
   - Registers external and internal MCP tools (HTTP, gRPC, IPC) linked to an `{org_id}` or `{project_id}` realm.
   - Enforces minimum reputation score requirements (`min_reputation_score`) for agent access.

2. **Project Realm Persistence**:
   - Persists all tool vertices in `post-graph` PostgreSQL table `mcp_tools` under `realm = project_id`.
   - Automatically syncs registered tools from PostgreSQL on service startup (`lifespan`).

---

## 🔌 API Endpoints Summary

- **`POST /tools/register`**: Registers a new MCP tool with input schema and endpoint URL.
- **`GET /tools`**: Lists tools filtered by `org_id`, `project_id`, or `scope_type`.
- **`GET /tools/{tool_id}`**: Retrieves MCP tool definition and input schema.
- **`DELETE /tools/{tool_id}`**: Removes an MCP tool from the registry.

---

## 🚀 Running locally

```bash
cd services/tool-registry
pip install -r requirements.txt
uvicorn app:app --port 8002 --reload
```
