"""Tool Registry Microservice (Kubernetes Service) for agent.london

Registers every Model Context Protocol (MCP) tool available to agents, as
versioned, content-hashed records an agent version can pin (see
spec/tool-registry-spec.md). Tools are scoped to an {org} or a {project}, and
persisted in post-graph under realm = org_id, space = project_id.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from post_graph import AsyncPostGraph

from tool_api import discovery_embedding, router as tool_router
from tool_cache import ToolCache
from tool_model import DORMANT, ToolIdentity, ToolVersionSpec
from tool_store import (
    ensure_schema, list_realms, list_tools, register_or_bump, set_lifecycle,
)

logger = logging.getLogger(__name__)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)

# Realm means schema (spec §2): physical isolation per organisation. Matched to
# the agent registry's default so the two services address the same tables.
SCHEMA_PER_REALM = os.getenv("SCHEMA_PER_REALM", "1").lower() in ("1", "true", "yes")

# The realm the first-party catalogue is seeded into.
SEED_REALM = os.getenv("TOOL_SEED_REALM", "org_london_meta")

# Web search, through the router this cluster already runs. Google withdrew
# "search the entire web" from Programmable Search Engine for new engines on
# 20 January 2026 and ends it for existing ones on 1 January 2027, so the
# Custom Search route is closed; grounding is the supported replacement and
# needs no second vendor.
#
# Set WEB_SEARCH_MODEL empty to switch web search off: the backend then seeds
# no search tool, and no agent is told it has one.
MODEL_ROUTER_URL = os.getenv("OPENAI_API_BASE",
                             os.getenv("LITELLM_URL", "http://localhost:4000/v1"))
MODEL_ROUTER_KEY = os.getenv("OPENAI_API_KEY", "")
WEB_SEARCH_MODEL = os.getenv("WEB_SEARCH_MODEL", "gemini-3.5-flash-lite").strip()
SEARCH_TIMEOUT = float(os.getenv("WEB_SEARCH_TIMEOUT", "120"))

# Grounding returns opaque `vertexaisearch…/grounding-api-redirect/…` links.
# Following them costs one HEAD per citation and yields the URL the claim
# actually came from, which is what a citation is for.
RESOLVE_CITATIONS = os.getenv("WEB_SEARCH_RESOLVE_CITATIONS", "1").lower() in (
    "1", "true", "yes")

BACKEND_MCP = os.getenv(
    "BACKEND_MCP_URL",
    "http://agent-london-backend-service.default.svc.cluster.local:8000/api/mcp/v1/tools/call")
SELF_URL = os.getenv(
    "TOOL_REGISTRY_URL",
    "http://tool-registry-service.default.svc.cluster.local:8002")


@asynccontextmanager
async def pg_client(org_id: str = "org_default"):
    """A short-lived post-graph client for one realm, closed on the way out.

    Used by the metering flush, which writes per realm in batches. Request
    handling uses the long-lived client on app.state instead.
    """
    client = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM)
    await client.connect()
    try:
        yield client
    finally:
        try:
            await client.close()
        except Exception:
            logger.exception("Failed to close post-graph client for realm '%s'", org_id)


# ---------------------------------------------------------- default catalogue

def _obj(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


DEFAULT_TOOLS = [
    (
        ToolIdentity(
            tool_id="mcp-web-search", name="Web search",
            description="Searches the public web through the model router's "
                        "search grounding, and returns a summary with the "
                        "sources that support it.",
            scope_type="org", org_id=SEED_REALM, kind="builtin",
            capabilities=["web_search", "internet", "retrieve"]),
        dict(endpoint_url=f"{SELF_URL.rstrip('/')}/tools/web-search",
             side_effects="external",
             input_schema=_obj({"query": {"type": "string", "description": "What to search for"},
                                "num_results": {"type": "integer", "description": "How many findings, 1 to 10"}},
                               ["query"]),
             output_schema=_obj({"summary": {"type": "string", "description": "What the sources say"},
                                 "results": {"type": "array", "description": "Titles, snippets and links"},
                                 "count": {"type": "integer"}}, []),
             cost_hint={"kind": "search_query"}),
    ),
    (
        ToolIdentity(
            tool_id="mcp-pgvector-search", name="PostGraph Vector Memory Search",
            description="Queries post-graph-rag shared vector memory for semantic "
                        "document chunks and knowledge graphs.",
            scope_type="org", org_id=SEED_REALM,
            capabilities=["retrieve", "semantic_search"]),
        dict(endpoint_url=BACKEND_MCP, side_effects="read",
             input_schema=_obj({"query": {"type": "string", "description": "Vector similarity query text"},
                                "top_k": {"type": "integer", "description": "How many chunks to return"}},
                               ["query"]),
             output_schema=_obj({"chunks": {"type": "array"}, "references": {"type": "array"}}, []),
             cost_hint={"kind": "rag_lookup"}),
    ),
    (
        ToolIdentity(
            tool_id="mcp-redis-queue", name="Redis Cluster Event Bus & Task Queue",
            description="Publishes event streams or queues background sub-tasks on "
                        "Redis pub-sub channels.",
            scope_type="org", org_id=SEED_REALM, capabilities=["publish", "enqueue"]),
        dict(endpoint_url=BACKEND_MCP, side_effects="write",
             input_schema=_obj({"channel": {"type": "string", "description": "Target Redis channel or queue name"},
                                "payload": {"type": "object", "description": "Event message JSON payload"}},
                               ["channel", "payload"]),
             output_schema=_obj({"published": {"type": "boolean"}}, [])),
    ),
    (
        ToolIdentity(
            tool_id="mcp-sql-query", name="PostgreSQL Relational DB Executor",
            description="Executes parameterized SQL queries against post-graph "
                        "database tables.",
            scope_type="org", org_id=SEED_REALM, capabilities=["query", "sql"]),
        dict(endpoint_url=BACKEND_MCP, side_effects="write",
             input_schema=_obj({"sql_query": {"type": "string", "description": "SQL statement to execute"}},
                               ["sql_query"]),
             output_schema=_obj({"rows": {"type": "array"}}, [])),
    ),
    (
        ToolIdentity(
            tool_id="kagent-operator", name="Kubernetes Agent Cluster Operator",
            description="Interacts with the Kubernetes API server to inspect pods, "
                        "deployments, and cluster rollouts.",
            scope_type="org", org_id=SEED_REALM, capabilities=["operate", "inspect"]),
        dict(endpoint_url=BACKEND_MCP, side_effects="write",
             input_schema=_obj({"command": {"type": "string", "description": "Cluster operator command (e.g. get pods, status)"}},
                               ["command"]),
             output_schema=_obj({"output": {"type": "string"}}, [])),
    ),
]


async def seed_default_tools(client, cache: ToolCache) -> int:
    """Register the first-party catalogue. Idempotent (Rule 7.4).

    `register_or_bump` returns the existing record when the content hash is
    unchanged, so a restart appends nothing. The previous implementation called
    `add_vertex` unconditionally and grew the table by the size of this list on
    every pod restart — invisibly, because the read path deduplicated by
    `tool_id`.

    When the content *has* changed — most often because the deployment moved
    and `SELF_URL` with it — the seed publishes the next patch rather than
    failing on immutability (Rule 4.1). Failing would leave the catalogue
    advertising the old address with only a log line to say so.
    """
    seeded = 0
    await ensure_schema(client, SEED_REALM)
    for identity, version_fields in DEFAULT_TOOLS:
        spec = ToolVersionSpec(tool_id=identity.tool_id, version="1.0.0",
                               **version_fields)
        try:
            # With the discovery vector, or the tool is registered and then
            # cannot be found by the search every agent uses to look for it.
            record = await register_or_bump(
                client, identity, spec,
                embedding=await discovery_embedding(identity, spec))
        except Exception:
            logger.exception("failed to seed tool %s", identity.tool_id)
            continue
        cache.put(SEED_REALM, identity.tool_id, record.get("version"),
                  identity.model_dump(mode="json"), record)
        seeded += 1

    await retire_withdrawn_defaults(client)
    return seeded


async def retire_withdrawn_defaults(client) -> int:
    """Withdraw first-party tools that are no longer in the catalogue.

    A renamed or removed default leaves its old identity published, pointing at
    an endpoint this service no longer serves — `mcp-google-search` outlived the
    endpoint it named by exactly one rename. Listed, discoverable, and a 404 the
    moment an agent believes it and calls.

    Dormancy, not deletion: a published agent version may pin it, and its hash
    certifies that pin (Rule 9.3).
    """
    current = {identity.tool_id for identity, _ in DEFAULT_TOOLS}
    retired = 0
    try:
        entries = await list_tools(client, SEED_REALM, None, include_inactive=False)
    except Exception:
        logger.exception("could not review the first-party catalogue")
        return 0

    for entry in entries:
        identity = entry["identity"]
        if identity.kind != "builtin" or identity.tool_id in current:
            continue
        try:
            await set_lifecycle(client, SEED_REALM, identity.tool_id, DORMANT)
            logger.warning("retired %s: no longer in the first-party catalogue, "
                           "and its endpoint is no longer served",
                           identity.tool_id)
            retired += 1
        except Exception:
            logger.exception("could not retire %s", identity.tool_id)
    return retired


async def warm_cache(client, cache: ToolCache) -> int:
    """Populate the cache from every realm that has tools (Rule 10.3).

    Realms are enumerated from the database. A hardcoded list — which is what
    this was — means a new organisation's tools stay invisible until someone
    edits and redeploys this service, and nothing reports that.
    """
    total = 0
    try:
        realms = await list_realms(client)
    except Exception:
        logger.exception("could not enumerate realms; starting with a cold cache")
        return 0
    for realm in realms:
        try:
            for entry in await list_tools(client, realm):
                cache.put(realm, entry["identity"].tool_id, entry["version"],
                          entry["identity"].model_dump(mode="json"), entry["record"])
                total += 1
        except Exception:
            logger.exception("could not read tools in realm %r", realm)
    return total


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connection failures are raised. This registry has no meaningful degraded
    # mode: without the database it can neither read the tools it is asked for
    # nor persist the ones it is given, and answering "no tools" is worse than
    # refusing, because the caller cannot tell the two apart.
    client = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM)
    await client.connect()
    app.state.pg_client = client
    app.state.pg_client_factory = pg_client
    app.state.cache = ToolCache()

    # Metering is optional infrastructure: accounting must never be the reason
    # the registry will not start (AG Rule 12.2).
    app.state.meter = None
    try:
        from metering import configure
        app.state.meter = configure(pg_client)
        await app.state.meter.start()
    except Exception:
        logger.exception("metering unavailable; the tool registry runs unmetered")

    seeded = await seed_default_tools(client, app.state.cache)
    warmed = await warm_cache(client, app.state.cache)
    logger.info("tool registry ready: %d default tools, %d cached", seeded, warmed)

    try:
        yield
    finally:
        if app.state.meter:
            await app.state.meter.stop()
        await client.close()


tags_metadata = [
    {"name": "Tool Registry", "description": "Register, version, discover, and invoke Model Context Protocol (MCP) tools."},
    {"name": "Builtin Tools", "description": "First-party tools implemented by this service."},
    {"name": "System", "description": "Health check and microservice status endpoints."},
]

app = FastAPI(
    title="MCP Tool Registry Microservice",
    description="""
    # 🧰 agent.london MCP Tool Registry OpenAPI Specs

    Manages versioned registration, capability discovery, and execution binding for
    Model Context Protocol (MCP) tools (Search, Code Execution, SQL Queries, Kubernetes
    Operators) backed by `post-graph`.

    Every tool version is content-hashed and pinnable, so an agent that names a tool
    names a specific, immutable contract.

    - **Interactive Swagger Documentation:** [/docs](/docs)
    - **ReDoc API Documentation:** [/redoc](/redoc)
    - **OpenAPI Schema JSON:** [/openapi.json](/openapi.json)
    """,
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

app.include_router(tool_router)


@app.get("/", tags=["System"])
@app.get("/health", tags=["System"])
async def health_check():
    """Reports what is actually reachable, not constants."""
    database = "unreachable"
    try:
        await app.state.pg_client._fetch("SELECT 1")
        database = "ok"
    except Exception as e:
        logger.warning("health: database unreachable: %s", e)

    cache: ToolCache = app.state.cache
    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": "tool-registry",
        "database": database,
        "persistence": "post-graph",
        "cached_tools": cache.count(),
        "cache_hits": cache.hits,
        "cache_misses": cache.misses,
        "metering": "on" if app.state.meter else "off",
    }


# ------------------------------------------------------------- builtin tools

class WebSearchRequest(BaseModel):
    query: str
    num_results: int = Field(5, ge=1, le=10)
    project_id: Optional[str] = None


async def _resolve_citation(http: httpx.AsyncClient, url: str) -> str:
    """Follow a grounding redirect to the page it actually points at.

    Grounding hands back `vertexaisearch.cloud.google.com/grounding-api-redirect/…`
    rather than the source URL. That is an opaque token: it resolves in a
    browser, but an agent storing it has recorded where Google sent it, not
    where the claim came from — and this system's whole argument about
    citations is that they say where a passage came from.

    Best effort. A redirect that will not resolve is returned unchanged rather
    than dropped, because the opaque link is still better than no link.
    """
    try:
        res = await http.head(url, follow_redirects=True, timeout=6.0)
        return str(res.url) or url
    except httpx.HTTPError:
        return url


@app.post("/tools/web-search", tags=["Builtin Tools"])
async def execute_web_search(req: WebSearchRequest):
    """Search the public web, through the model router's search grounding.

    This used to call the Google Custom Search JSON API against a Programmable
    Search Engine. Google withdrew "search the entire web" for new engines on
    20 January 2026 and stops it for existing ones on 1 January 2027, so that
    route cannot be set up any more and would not have lasted. Grounding is
    Google's own replacement path and needs no second vendor: the router this
    cluster already runs serves the model, and the model does the searching.

    Every failure path raises. An earlier version of this endpoint answered
    `status: success` with three invented results whose snippets described
    themselves as "empirically retrieved" — handing an agent fabricated
    evidence it had no way to tell from a real search, which it would then
    reason over and persist as fact.
    """
    if not WEB_SEARCH_MODEL:
        raise HTTPException(
            status_code=503,
            detail="Web search is disabled: WEB_SEARCH_MODEL is empty.")

    body = {
        "model": WEB_SEARCH_MODEL,
        "messages": [
            {"role": "system", "content":
                "You are a search tool, not an assistant. Search the web and "
                "report what you find. State only what the sources say. If the "
                "search returns nothing relevant, say so plainly rather than "
                "answering from memory — the caller needs to know the web was "
                "consulted and came back empty."},
            {"role": "user", "content":
                f"Search the web for: {req.query}\n\n"
                f"Summarise the {req.num_results} most relevant findings."},
        ],
        # The grounding tool. Without it the model answers from training data,
        # which is the one thing a search tool must never silently do.
        "tools": [{"googleSearch": {}}],
        "max_tokens": 1200,
    }

    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as http:
            res = await http.post(
                f"{MODEL_ROUTER_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {MODEL_ROUTER_KEY}"},
                json=body)
    except httpx.HTTPError as e:
        logger.warning("search grounding request failed: %s", e)
        raise HTTPException(status_code=502,
                            detail=f"Search upstream unreachable: {e}") from e

    if res.status_code != 200:
        logger.warning("search grounding returned %s: %s",
                       res.status_code, res.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"Search upstream returned {res.status_code}: {res.text[:200]}")

    message = res.json()["choices"][0]["message"]
    summary = message.get("content") or ""
    citations = [a.get("url_citation") or {} for a in (message.get("annotations") or [])
                 if a.get("type") == "url_citation"]

    # No citations means the model answered without consulting anything. That
    # is not a search result, and returning it as one would put unsourced text
    # into an agent's evidence with a search tool's authority behind it.
    if not citations:
        raise HTTPException(
            status_code=502,
            detail=("The search returned no sources. The model answered without "
                    "grounding, so there is nothing to cite and this is not a "
                    "search result."))

    async with httpx.AsyncClient() as http:
        links = list(await asyncio.gather(*[
            _resolve_citation(http, c.get("url", "")) for c in citations
        ])) if RESOLVE_CITATIONS else [c.get("url", "") for c in citations]

    results = []
    for citation, link in zip(citations, links):
        start_at, end_at = citation.get("start_index"), citation.get("end_index")
        # The span of the summary this source actually supports, where the
        # provider marked one. A snippet lifted from somewhere else in the
        # answer would attribute a claim to a source that did not make it.
        snippet = (summary[start_at:end_at]
                   if isinstance(start_at, int) and isinstance(end_at, int)
                   else "")
        results.append({
            "title": citation.get("title") or link,
            "snippet": snippet.strip(),
            "link": link,
            "redirect": citation.get("url"),
        })

    return {
        "status": "success",
        # Named, so a caller can tell how the passage was obtained (Rule 8.1).
        "source": "gemini_search_grounding",
        "model": WEB_SEARCH_MODEL,
        "query": req.query,
        "summary": summary,
        "count": len(results),
        "results": results,
        "citations_resolved": RESOLVE_CITATIONS,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
