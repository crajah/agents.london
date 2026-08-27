"""The toolbelt a new realm starts with.

A founding agent that pins `mcp-pgvector-search` cannot be registered unless
that tool is a published, in-scope tool version in the same realm — the agent
registry refuses the registration by Rule 3.5, on the grounds that an agent
must not pin something it cannot call. Nothing published these tools, so in a
newly created organisation *every* agent registration failed with a 400, the
failure was logged at debug level inside a loop that tried four hosts, and the
civilisation came up with twenty-eight agents in post-graph and none in the
registry: no versions, no content hashes, no MCP names, nothing invocable.

These are the tools that seed a realm. Each one points at an endpoint that
exists and answers; there is no placeholder here, because a registered tool
that 502s on first use is worse than an absent one — the agent has already
committed to a plan that includes it.

The set is deliberately small. It is what an agent civilisation needs to
function at all: find knowledge, find an agent, find a tool, file a document,
call another agent. Everything else is registered by the Toolwright as the
civilisation acquires it.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

TOOL_REGISTRY_URL = os.getenv("TOOL_REGISTRY_URL", "http://localhost:8002")
AGENT_REGISTRY_URL = os.getenv("AGENT_REGISTRY_URL", "http://localhost:8001")
DOCUMENT_REGISTRY_URL = os.getenv("DOCUMENT_REGISTRY_URL", "http://localhost:8003")


def web_search_configured() -> bool:
    """Whether this deployment can actually reach the web.

    Search runs through the model router's grounding rather than the Google
    Custom Search API — Google withdrew "search the entire web" for new
    Programmable Search engines on 20 January 2026 and ends it for existing
    ones on 1 January 2027, so that route could not be set up and would not
    have lasted.

    The router is already a hard requirement of this system, so the only thing
    left to decide is whether a grounding-capable model is named. Setting
    WEB_SEARCH_MODEL empty turns web search off, and then no realm is seeded
    with it and no agent is told it has it.
    """
    return bool(os.getenv("WEB_SEARCH_MODEL", "gemini-3.5-flash-lite").strip())


def _object(properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": True}


def platform_tools(org_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The seed toolbelt, as registration bodies.

    Scoped to the organisation rather than a project: these are platform
    capabilities, and a second project in the same organisation should not have
    to re-register them (tool-registry Rule 2.2).
    """
    doc = DOCUMENT_REGISTRY_URL.rstrip("/")
    agent = AGENT_REGISTRY_URL.rstrip("/")
    tool = TOOL_REGISTRY_URL.rstrip("/")

    def body(tool_id: str, name: str, description: str, endpoint: str,
             side_effects: str, input_schema: Dict[str, Any],
             output_schema: Dict[str, Any], capabilities: List[str],
             timeout_secs: int = 120) -> Dict[str, Any]:
        return {
            "identity": {
                "tool_id": tool_id, "name": name, "description": description,
                "scope_type": "org", "org_id": org_id, "project_id": None,
                "kind": "http", "capabilities": capabilities,
                "owner": "platform",
            },
            "version": {
                "tool_id": tool_id, "version": "1.0.0", "endpoint_url": endpoint,
                "transport": "http_post_json",
                "input_schema": input_schema, "output_schema": output_schema,
                "side_effects": side_effects,
                "auth": {"mode": "none"},
                "limits": {"timeout_secs": timeout_secs},
                "changelog": "Seeded with the realm.",
            },
        }

    tools = []

    # Web search is seeded only when it is configured. Publishing a tool that
    # cannot work is worse than publishing none: an agent plans around it and
    # fails at the moment it calls, which is the most expensive moment to find
    # out.
    if web_search_configured():
        tools.append(body(
            "mcp-web-search", "Web search",
            "Search the public web and return a summary with the sources that "
            "support it. Use it for anything outside this project's own "
            "documents — current events, external facts, other organisations.",
            f"{tool}/tools/web-search", "external",
            _object({
                "query": {"type": "string", "description": "What to search for"},
                "num_results": {"type": "integer",
                                "description": "How many results, 1 to 10"},
            }, ["query"]),
            _object({"summary": {"type": "string",
                                 "description": "What the sources say"},
                     "results": {"type": "array",
                                 "description": "Titles, snippets and links"},
                     "count": {"type": "integer"}}),
            ["web_search", "internet", "current_events", "external_research"],
        ))

    return tools + [
        body(
            "mcp-pgvector-search", "Document retrieval",
            "Retrieve passages from this project's document spaces by meaning. "
            "Returns the chunks and names the engine that produced them, so a "
            "citation can state where it came from.",
            f"{doc}/query", "read",
            _object({
                "org_id": {"type": "string", "description": "the realm"},
                "project_id": {"type": "string", "description": "the project"},
                "query": {"type": "string", "description": "what to look for"},
                "document_space": {"type": "string",
                                   "description": "one space, or omit for the whole project"},
                "top_k": {"type": "integer", "description": "how many chunks"},
                "mode": {"type": "string", "description": "mix, local or global"},
            }, ["org_id", "project_id", "query"]),
            _object({"status": {"type": "string"}, "engine": {"type": "string"},
                     "data": {"type": "object"}}),
            ["retrieval", "rag", "documents", "search", "knowledge"],
        ),
        body(
            "mcp-document-ingest", "Document ingestion",
            "File a text document into a document space so it becomes "
            "retrievable. Reports indexed and catalogued-but-not-indexed "
            "separately; a document that is catalogued only cannot be cited.",
            f"{doc}/spaces/default/documents/upload-text", "write",
            _object({
                "org_id": {"type": "string"},
                "project_id": {"type": "string"},
                "document_name": {"type": "string", "description": "the file name"},
                "content": {"type": "string", "description": "the text itself"},
                "document_space": {"type": "string",
                                   "description": "which space to file it in"},
                "category": {"type": "string"},
            }, ["org_id", "project_id", "document_name", "content"]),
            _object({"status": {"type": "string"}, "document": {"type": "object"}}),
            ["ingest", "documents", "corpus", "index"],
            timeout_secs=600,
        ),
        body(
            "mcp-agent-discovery", "Agent discovery",
            "Find registered agents or pipelines by describing what is needed. "
            "Only published, active entries are returned, each with the version "
            "and content hash that pins it.",
            f"{agent}/discover", "read",
            _object({
                "q": {"type": "string", "description": "what capability is needed"},
                "capability": {"type": "string", "description": "an exact capability tag"},
                "kind": {"type": "string", "description": "agent or pipeline"},
                "org_id": {"type": "string"},
                "project_id": {"type": "string"},
                "top_k": {"type": "integer"},
            }, ["org_id"]),
            _object({"results": {"type": "array"}, "count": {"type": "integer"},
                     "method": {"type": "string"}}),
            ["discovery", "agents", "registry", "capability"],
        ),
        body(
            "mcp-tool-discovery", "Tool discovery",
            "Find a registered tool by describing what it must do. Returns the "
            "tool id, version and declared side effects, which is what a caller "
            "needs before deciding whether it may retry.",
            f"{tool}/tools/search", "read",
            _object({
                "q": {"type": "string", "description": "what the tool must do"},
                "org_id": {"type": "string"},
                "project_id": {"type": "string"},
                "top_k": {"type": "integer"},
            }, ["q", "org_id"]),
            _object({"tools": {"type": "array"}, "count": {"type": "integer"}}),
            ["discovery", "tools", "registry", "capability"],
        ),
        body(
            "mcp-agent-invoke", "Agent invocation",
            "Call a registered agent or pipeline by its MCP name, "
            "`agent:{slug}@{version}` or `pipeline:{slug}@{version}`. The "
            "version is part of the name, so a call names exactly what runs.",
            f"{agent}/mcp/call", "write",
            _object({
                "tool_name": {"type": "string",
                              "description": "agent:slug@version or pipeline:slug@version"},
                "arguments": {"type": "object", "description": "the callee's input"},
                "org_id": {"type": "string"},
                "project_id": {"type": "string"},
            }, ["tool_name", "org_id", "project_id"]),
            _object({"status": {"type": "string"}, "content": {"type": "array"},
                     "isError": {"type": "boolean"}}),
            ["invoke", "agents", "pipelines", "delegation"],
            timeout_secs=600,
        ),
    ]


async def ensure_platform_tools(org_id: str,
                                project_id: Optional[str] = None) -> Dict[str, Any]:
    """Publish the seed toolbelt into a realm. Safe to call repeatedly.

    Re-registering an identical version is a no-op in the tool registry
    (Rule 8.1), so this runs on every project creation rather than needing a
    separate provisioning step that someone has to remember.

    Failures are reported, never swallowed: a realm whose toolbelt did not
    publish will refuse every agent registration afterwards, and the reason
    should be visible at the moment it happens rather than inferred from the
    absence of agents an hour later.
    """
    registered, failed = [], []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for spec in platform_tools(org_id, project_id):
            tool_id = spec["identity"]["tool_id"]
            try:
                res = await client.post(
                    f"{TOOL_REGISTRY_URL.rstrip('/')}/tools/register", json=spec)
            except Exception as e:
                logger.error("could not reach the tool registry to seed %s: %s",
                             tool_id, e)
                failed.append({"tool_id": tool_id, "error": str(e)})
                continue
            if res.status_code == 200:
                registered.append(res.json().get("pin", {"tool_id": tool_id}))
            else:
                logger.error("tool registry rejected the seed tool %s: %s %s",
                             tool_id, res.status_code, res.text[:300])
                failed.append({"tool_id": tool_id, "status": res.status_code,
                               "detail": res.text[:300]})

    return {"org_id": org_id, "registered": registered, "failed": failed,
            "count": len(registered)}


# The tools a founding agent may pin. Derived from the definitions above rather
# than written out again: a second list would eventually name a tool that is no
# longer seeded, and a founder would be born pinning it.
def platform_tool_ids() -> tuple:
    """Every tool this deployment seeds, including the optional ones."""
    return tuple(spec["identity"]["tool_id"] for spec in platform_tools("_ids"))


# The tools that are always present, whatever the deployment is configured with.
PLATFORM_TOOL_IDS = ("mcp-pgvector-search", "mcp-document-ingest",
                     "mcp-agent-discovery", "mcp-tool-discovery",
                     "mcp-agent-invoke")

# Tools that exist only when the deployment can support them. A founder may
# name one, and its prompt will only mention it where it is actually published.
OPTIONAL_TOOL_IDS = ("mcp-web-search",)

ALL_TOOL_IDS = PLATFORM_TOOL_IDS + OPTIONAL_TOOL_IDS
