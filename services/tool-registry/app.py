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

from external_tools import (
    EXTERNAL_TIMEOUT, RAPIDAPI_BY_SLUG, RAPIDAPI_SERVICES, NotConfigured,
    ProviderError, TavilyKeyRing, rapidapi_call, rapidapi_key, serper_key,
    serper_search, tavily_search,
)
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

# External providers. Each is catalogued only when its credential is present
# (Rule 7.3): a tool that is listed but 503s teaches an agent to plan around a
# capability it does not have, which is worse than not offering it.
TAVILY_KEYS = TavilyKeyRing()

# The Kubernetes Secret the catalogue points at. Only the name and the key name
# are recorded in a tool version; the value never enters the registry, because
# a registry row is readable by every service in the realm (Rule 6.3).
EXTERNAL_KEYS_SECRET = os.getenv("EXTERNAL_KEYS_SECRET", "external-tool-keys")


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


def _external_tools():
    """Catalogue entries for the providers whose credentials are configured.

    Rule 7.3 is the whole point of the conditionals. A provider with no key is
    not registered at all, so discovery (Rule 5.1) never offers an agent a tool
    whose only possible answer is 503. Note that `mcp-web-search` above is
    seeded unconditionally even when WEB_SEARCH_MODEL is empty, which is the
    gap this avoids repeating rather than one it fixes.
    """
    entries = []

    # ---- Tavily, over a rotating pool of keys ----------------------------
    if TAVILY_KEYS.configured:
        entries.append((
            ToolIdentity(
                tool_id="mcp-tavily-search", name="Tavily web search",
                description="Searches the web through Tavily and returns ranked "
                            "results with snippets, links and an optional "
                            "synthesised answer. Built for retrieval by agents.",
                scope_type="org", org_id=SEED_REALM, kind="builtin",
                capabilities=["web_search", "internet", "retrieve", "research"]),
            dict(endpoint_url=f"{SELF_URL.rstrip('/')}/tools/tavily-search",
                 side_effects="external",
                 auth={"mode": "secret_ref",
                       "secret_ref": {"name": EXTERNAL_KEYS_SECRET,
                                      "key": "TAVILY_API_KEY_1"}},
                 input_schema=_obj({
                     "query": {"type": "string", "description": "What to search for"},
                     "max_results": {"type": "integer", "description": "How many results, 1 to 20"},
                     "search_depth": {"type": "string", "description": "'basic' (fast) or 'advanced' (deeper)"},
                     "include_answer": {"type": "boolean", "description": "Include a synthesised answer"}},
                     ["query"]),
                 output_schema=_obj({
                     "answer": {"type": "string", "description": "Synthesised answer, when requested"},
                     "results": {"type": "array", "description": "Titles, snippets and links"},
                     "count": {"type": "integer"},
                     "key_used": {"type": "string", "description": "Which key variable served the call"}}, []),
                 limits={"timeout_secs": EXTERNAL_TIMEOUT},
                 cost_hint={"kind": "search_query"}),
        ))

    # ---- Serper ----------------------------------------------------------
    if serper_key():
        entries.append((
            ToolIdentity(
                tool_id="mcp-serper-search", name="Serper Google search",
                description="Searches Google through Serper and returns organic "
                            "results with titles, snippets and links, plus the "
                            "answer box when Google shows one.",
                scope_type="org", org_id=SEED_REALM, kind="builtin",
                capabilities=["web_search", "internet", "retrieve", "google"]),
            dict(endpoint_url=f"{SELF_URL.rstrip('/')}/tools/serper-search",
                 side_effects="external",
                 auth={"mode": "secret_ref",
                       "secret_ref": {"name": EXTERNAL_KEYS_SECRET,
                                      "key": "SERPER_API_KEY"}},
                 input_schema=_obj({
                     "query": {"type": "string", "description": "What to search Google for"},
                     "num_results": {"type": "integer", "description": "How many results, 1 to 20"},
                     "country": {"type": "string", "description": "Two-letter country code, e.g. gb"},
                     "language": {"type": "string", "description": "Two-letter language code, e.g. en"}},
                     ["query"]),
                 output_schema=_obj({
                     "answer": {"type": "string", "description": "Answer box text, when Google returned one"},
                     "results": {"type": "array", "description": "Titles, snippets and links"},
                     "count": {"type": "integer"},
                     "credits_used": {"type": "integer"}}, []),
                 limits={"timeout_secs": EXTERNAL_TIMEOUT},
                 cost_hint={"kind": "search_query"}),
        ))

    # ---- RapidAPI: one tool per service ----------------------------------
    if rapidapi_key():
        for service in RAPIDAPI_SERVICES:
            entries.append((
                ToolIdentity(
                    tool_id=service.tool_id, name=service.name,
                    description=service.description,
                    scope_type="org", org_id=SEED_REALM, kind="builtin",
                    capabilities=list(service.capabilities)),
                dict(endpoint_url=f"{SELF_URL.rstrip('/')}/tools/rapidapi/{service.slug}",
                     side_effects="external",
                     auth={"mode": "secret_ref",
                           "secret_ref": {"name": EXTERNAL_KEYS_SECRET,
                                          "key": "RAPIDAPI_KEY"}},
                     input_schema=_obj(dict(service.schema_properties),
                                       list(service.required)),
                     output_schema=_obj({
                         "service": {"type": "string"},
                         "data": {"type": "object", "description": "The provider's response, unaltered"}}, []),
                     limits={"timeout_secs": EXTERNAL_TIMEOUT},
                     cost_hint={"kind": "api_call"}),
            ))

    return entries


DEFAULT_TOOLS += _external_tools()


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


# -------------------------------------------------- external provider tools

class TavilySearchRequest(BaseModel):
    query: str
    max_results: int = Field(5, ge=1, le=20)
    search_depth: str = "basic"
    include_answer: bool = True
    project_id: Optional[str] = None


class SerperSearchRequest(BaseModel):
    query: str
    num_results: int = Field(5, ge=1, le=20)
    country: str = "us"
    language: str = "en"
    project_id: Optional[str] = None


def _as_http_error(e: ProviderError) -> HTTPException:
    """Map a provider failure onto a response without softening it.

    Rule 7.2: the caller is an agent, and an agent that receives a synthesised
    "no results found" cannot tell it apart from a real empty result set. The
    status and the provider's own message both survive.
    """
    return HTTPException(status_code=e.status_code, detail=str(e))


@app.post("/tools/tavily-search", tags=["Builtin Tools"])
async def execute_tavily_search(req: TavilySearchRequest):
    """Search the web via Tavily, rotating automatically across the key pool.

    Rotation is handled by `TavilyKeyRing`: each call starts at the next key so
    load is spread, and a key that reports an auth or quota failure is stepped
    over and the next one tried within the same call. A revoked key leaves the
    rotation permanently; an over-quota key is benched and returns later.
    """
    try:
        return await tavily_search(
            TAVILY_KEYS, query=req.query, max_results=req.max_results,
            search_depth=req.search_depth, include_answer=req.include_answer)
    except ProviderError as e:
        raise _as_http_error(e) from e


@app.get("/tools/tavily-search/keys", tags=["Builtin Tools"])
async def tavily_key_health():
    """Per-key rotation state, by variable name.

    Deliberately reports names and never values: this endpoint exists so an
    operator can see that, say, TAVILY_API_KEY is quarantined while the four
    prod keys are healthy, and that diagnosis needs no access to the secrets.
    """
    return {"configured": TAVILY_KEYS.configured,
            "key_count": len(TAVILY_KEYS),
            "keys": TAVILY_KEYS.status()}


@app.post("/tools/serper-search", tags=["Builtin Tools"])
async def execute_serper_search(req: SerperSearchRequest):
    """Search Google via Serper."""
    try:
        return await serper_search(
            query=req.query, num_results=req.num_results,
            country=req.country, language=req.language)
    except ProviderError as e:
        raise _as_http_error(e) from e


@app.post("/tools/rapidapi/{slug}", tags=["Builtin Tools"])
async def execute_rapidapi(slug: str, arguments: Dict[str, Any]):
    """Call one catalogued RapidAPI service.

    `slug` is closed over the catalogue rather than free-form: an unknown slug
    is a 404 here, not a request forwarded to an arbitrary host. A tool whose
    input chose the upstream host would let a model reach any API on RapidAPI,
    including ones this account is not subscribed to, and the failure would
    surface as a confusing 403 from somewhere the caller never named.
    """
    service = RAPIDAPI_BY_SLUG.get(slug)
    if service is None:
        raise HTTPException(
            status_code=404,
            detail=(f"No RapidAPI service '{slug}' is catalogued. "
                    f"Available: {', '.join(sorted(RAPIDAPI_BY_SLUG))}."))
    try:
        return await rapidapi_call(service, arguments or {})
    except ProviderError as e:
        raise _as_http_error(e) from e
