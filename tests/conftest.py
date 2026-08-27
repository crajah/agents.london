"""End-to-end fixtures. Nothing is stubbed.

Everything in this suite is the real thing:

| | What runs |
| :--- | :--- |
| Database | A live PostgreSQL with pgvector, one schema per test realm |
| Graph client | The real `post-graph` at the version `requirements.txt` pins |
| Model router | The real LiteLLM at `OPENAI_API_BASE`, the configured embedding model, and the first chat model that answers a probe |
| Services | The three real FastAPI applications, under real uvicorn, on real ports |
| Transport | Real HTTP, including every cross-service call |

The services are started as **listening servers** rather than mounted through
an ASGI transport, because a registered tool's `endpoint_url` has to be
genuinely reachable for `POST /tools/{id}/call` to dispatch to it. In-process
mounting would have forced a fake at exactly the seam the tool tests exist to
prove.

**Writing assertions against a real model.** The chat model is
non-deterministic, so nothing here asserts on exact wording. The assertions are
about structure and flow — which agent version ran, what reached it, what the
provider charged, what landed in the graph. Where a test needs a specific
value, the agent's system prompt constrains the answer and the assertion is
case-insensitive and substring-based.

Skips cleanly, with a reason, when the database or the model router is not
reachable.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import socket
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
SIBLINGS = ROOT.parent

load_dotenv(ROOT / ".env")

# The pinned libraries, ahead of whatever is installed. requirements.txt asks
# for post-graph>=0.6.2 and post-graph-rag>=1.5.2; a stale site-packages copy
# would silently test a different library than the services ship against.
for name in ("post-graph", "post-graph-rag"):
    local = SIBLINGS / name
    if (local / name.replace("-", "_")).is_dir():
        sys.path.insert(0, str(local))

# The civilization app's BFF. shared/ goes on the path too: metering,
# embedding and pipeline_runtime moved out of the app so the registry services
# could import them without reaching into an application directory.
BACKEND = ROOT / "apps" / "civilization" / "backend"
SHARED = ROOT / "shared"
SERVICES = {
    "agent": ROOT / "services" / "agent-registry",
    "tool": ROOT / "services" / "tool-registry",
    "document": ROOT / "services" / "document-registry",
}
for path in (BACKEND, BACKEND.parent, SHARED, *SERVICES.values()):
    sys.path.insert(0, str(path))

# `.env` names both the database and the router as the *containers* see them —
# `postgres:5432` and `host.docker.internal:4000`. Neither resolves from a
# checkout, so the test defaults are the host-visible addresses and both stay
# overridable. Reusing the container values here would skip the whole suite on
# a developer machine and look like the stack was down.
DSN = os.getenv(
    "TEST_POSTGRES_URI",
    "postgresql://crajah:postgrespassword@localhost:5432/postgres")
ROUTER = os.getenv("TEST_OPENAI_API_BASE", "http://localhost:4000/v1")
ROUTER_KEY = os.getenv("OPENAI_API_KEY", "")

# Candidate chat models, most preferred first. The router fronts several
# providers and any of them can be out of credits or down on a given day; a
# hardcoded model turns that into a wall of failures that look like code bugs.
# The first one that actually answers is used, and which one is reported.
# Ordered by observed stability against this router, not by capability. The
# suite needs a model that answers every time for several minutes, and the
# SambaNova-backed entries intermittently return 402 "out of credits" — which
# fails a run mid-suite and reads exactly like an application bug.
CHAT_CANDIDATES = [
    m for m in [
        os.getenv("TEST_CHAT_MODEL"),
        "gemini-3.5-flash-lite",
        "google/gemma-4-26b-a4b-it-maas",
        "Meta-Llama-3.3-70B-Instruct",
        "gemma-4-31B-it",
        "DeepSeek-V3.2",
    ] if m
]

# A model can pass one probe and fail the next when its provider's credits run
# out between calls, so the probe is repeated.
PROBES = int(os.getenv("TEST_MODEL_PROBES", "2"))
# The deployment default, so the suite exercises the same geometry the
# services write in. Overridable, but never silently different: vectors
# written by one embedding model are not comparable with another's.
EMBEDDING_MODEL = os.getenv("TEST_EMBEDDING_MODEL", "gemini-embedding-001")

# Resolved by `_check_router()` at collection time.
CHAT_MODEL = CHAT_CANDIDATES[0]


# --------------------------------------------------------------- environment

def _service_env() -> Dict[str, str]:
    return {
        "POSTGRES_URI": DSN,
        "SCHEMA_PER_REALM": "1",
        "OPENAI_API_KEY": ROUTER_KEY,
        "OPENAI_API_BASE": ROUTER,
        "LITELLM_URL": ROUTER,
        "RAG_EMBEDDING_DIM": "1536",
        "RAG_EMBEDDING_MODEL": EMBEDDING_MODEL,
        "DEFAULT_LLM_MODEL": CHAT_MODEL,
        "RAG_MODEL": CHAT_MODEL,
        # No Redis configured: the transport is a declared no-op and runs still
        # execute (Rule 8.3). A unit test proves a *broken* transport fails a run.
        "REDIS_URL": "",
        "TOOL_RESOLUTION_STRICT": "1",
        "DEFAULT_ORG_ID": "org_test",
        "AGENT_CALL_TIMEOUT": "120",
        "EMBED_TIMEOUT": "60",
    }


# ------------------------------------------------------------ preconditions

def _check_database() -> Optional[str]:
    try:
        import asyncpg
    except ImportError:
        return "asyncpg is not installed"

    async def check():
        conn = await asyncpg.connect(DSN, timeout=5)
        try:
            row = await conn.fetchrow(
                "SELECT installed_version FROM pg_available_extensions "
                "WHERE name = 'vector'")
            if not row or not row["installed_version"]:
                return "pgvector is not installed; the discovery tests need it"
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            return None
        finally:
            await conn.close()

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(check())
        finally:
            loop.close()
    except Exception as e:  # noqa: BLE001 — the reason is the useful part
        return f"no database at {DSN.split('@')[-1]}: {type(e).__name__}: {e}"


def _check_router() -> Optional[str]:
    """Confirm the router serves an embedding model and a chat model that works.

    "Serves" is checked by actually calling it. A model can be listed and still
    return 402 because its provider is out of credits — which is exactly what
    happened to DeepSeek mid-suite, and which reads as a wall of application
    failures unless the harness looks.
    """
    global CHAT_MODEL
    try:
        import httpx
        headers = {"Authorization": f"Bearer {ROUTER_KEY}"}
        res = httpx.get(f"{ROUTER.rstrip('/')}/models", timeout=10, headers=headers)
        if res.status_code != 200:
            return f"model router at {ROUTER} returned {res.status_code}"
        available = {m["id"] for m in res.json().get("data", [])}
        if EMBEDDING_MODEL not in available:
            return f"model router does not serve {EMBEDDING_MODEL}"

        tried = []
        for candidate in CHAT_CANDIDATES:
            if candidate not in available:
                continue
            failure = None
            for _ in range(PROBES):
                try:
                    probe = httpx.post(
                        f"{ROUTER.rstrip('/')}/chat/completions", headers=headers,
                        timeout=45,
                        json={"model": candidate, "max_tokens": 8, "temperature": 0,
                              "messages": [
                                  {"role": "system",
                                   "content": "Reply with exactly the word PONG."},
                                  {"role": "user", "content": "ping"}]})
                except Exception as e:  # noqa: BLE001
                    failure = type(e).__name__
                    break
                if probe.status_code != 200:
                    failure = f"HTTP {probe.status_code}"
                    break
            if failure is None:
                CHAT_MODEL = candidate
                return None
            tried.append(f"{candidate}: {failure}")
        return ("no chat model on the router answered "
                f"{PROBES} consecutive probes — tried " + "; ".join(tried))
    except Exception as e:  # noqa: BLE001
        return f"no model router at {ROUTER}: {type(e).__name__}: {e}"


DB_SKIP = _check_database()
# Resolves CHAT_MODEL to one that actually answers, so the environment below
# configures the services with a model that is up.
ROUTER_SKIP = _check_router()

os.environ.update(_service_env())

requires_db = pytest.mark.skipif(DB_SKIP is not None, reason=DB_SKIP or "")
requires_router = pytest.mark.skipif(ROUTER_SKIP is not None, reason=ROUTER_SKIP or "")
requires_stack = pytest.mark.skipif(
    (DB_SKIP or ROUTER_SKIP) is not None,
    reason=DB_SKIP or ROUTER_SKIP or "")


# --------------------------------------------------------------- the services

def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _load(module_name: str, path: pathlib.Path):
    """Import a service's app.py under a unique module name.

    All three services name their entrypoint `app.py`, so a plain import would
    have the second shadow the first. Loading each under its own name keeps
    three real applications alive in one process.
    """
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path / "app.py")
    assert spec and spec.loader, f"cannot load {path}/app.py"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class RunningService:
    """One real service, under uvicorn, on a real port.

    The port is claimed in `__init__` but the module is imported in `load()`,
    which is a separate step on purpose: every service reads its peers' URLs
    from the environment *at import time*, so all three ports must be known and
    exported before any module is imported. Importing on construction made the
    tool registry read a stale `AGENT_REGISTRY_URL` and fail every reputation
    check with a 503 (Rule 6.1) — the control was correct and unreachable.
    """

    def __init__(self, name: str, module_name: str, path: pathlib.Path):
        self.name = name
        self.module_name = module_name
        self.path = path
        self.module = None
        self.port = _free_port()
        self._server = None
        self._thread: Optional[threading.Thread] = None

    def load(self) -> "RunningService":
        self.module = _load(self.module_name, self.path)
        return self

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "RunningService":
        import uvicorn
        if self.module is None:
            self.load()
        config = uvicorn.Config(self.module.app, host="127.0.0.1", port=self.port,
                                log_level="warning", lifespan="on")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        import httpx
        deadline = time.time() + 60
        while time.time() < deadline:
            if self._server.started:
                try:
                    httpx.get(f"{self.url}/health", timeout=5)
                    return self
                except Exception:
                    pass
            time.sleep(0.05)
        raise RuntimeError(f"{self.name} did not start on {self.url}")

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=20)


@pytest.fixture(scope="session")
def stack():
    """All three services, running, wired to each other by real URL.

    Started in dependency order and torn down in reverse. The tool registry
    comes up first because the agent registry resolves tool pins against it on
    every registration that names a tool (Rule 3.5).
    """
    if DB_SKIP or ROUTER_SKIP:
        pytest.skip(DB_SKIP or ROUTER_SKIP)

    tool = RunningService("tool-registry", "svc_tool_app", SERVICES["tool"])
    document = RunningService("document-registry", "svc_document_app",
                              SERVICES["document"])
    agent = RunningService("agent-registry", "svc_agent_app", SERVICES["agent"])

    # Every URL is exported before any module is imported, because each service
    # reads its peers' addresses at import time. The tool registry calls the
    # agent registry for reputation; the agent registry calls the tool registry
    # to resolve pins. Neither can be told about the other afterwards.
    os.environ["TOOL_REGISTRY_URL"] = tool.url
    os.environ["DOCUMENT_REGISTRY_URL"] = document.url
    os.environ["AGENT_REGISTRY_URL"] = agent.url

    for service in (tool, document, agent):
        service.load()
    for service in (tool, document, agent):
        service.start()

    services = {"tool": tool, "document": document, "agent": agent}
    try:
        yield services
    finally:
        for service in (agent, document, tool):
            service.stop()


@pytest_asyncio.fixture
async def tools(stack):
    import httpx
    async with httpx.AsyncClient(base_url=stack["tool"].url, timeout=120.0) as c:
        c.service = stack["tool"]          # type: ignore[attr-defined]
        yield c


@pytest_asyncio.fixture
async def agents(stack):
    import httpx
    async with httpx.AsyncClient(base_url=stack["agent"].url, timeout=180.0) as c:
        c.service = stack["agent"]         # type: ignore[attr-defined]
        yield c


@pytest_asyncio.fixture
async def documents(stack):
    import httpx
    async with httpx.AsyncClient(base_url=stack["document"].url, timeout=300.0) as c:
        c.service = stack["document"]      # type: ignore[attr-defined]
        yield c


@pytest.fixture
def router_url() -> str:
    """The real model router, for tools that need a genuine HTTP endpoint."""
    return ROUTER


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def realm() -> str:
    """A unique realm — under SCHEMA_PER_REALM, its own PostgreSQL schema."""
    return "t_" + uuid.uuid4().hex[:12]


@pytest.fixture
def project() -> str:
    return "proj_" + uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def db():
    """A raw asyncpg connection, for asserting on what actually landed."""
    import asyncpg
    conn = await asyncpg.connect(DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _drop_realms_at_end():
    """Drop every schema this suite created, however the session ended."""
    yield
    if DB_SKIP:
        return
    import asyncpg

    async def clean():
        conn = await asyncpg.connect(DSN)
        try:
            rows = await conn.fetch(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 't\\_%'")
            for row in rows:
                await conn.execute(
                    f'DROP SCHEMA IF EXISTS "{row["nspname"]}" CASCADE')
        finally:
            await conn.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(clean())
    finally:
        loop.close()


# --------------------------------------------------------------- conveniences

def object_schema(properties: Dict[str, Any],
                  required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


TEXT_IN = object_schema(
    {"prompt": {"type": "string", "description": "The task for this agent"}},
    ["prompt"])
TEXT_OUT = object_schema(
    {"result": {"type": "string", "description": "The agent's answer"}})


def agent_body(*, org: str, project: str, agent_id: str, name: str, slug: str,
               telos: str, description: str, prompt: str,
               capabilities: Optional[List[str]] = None,
               tools: Optional[List[Any]] = None,
               version: str = "1.0.0",
               resource_limits: Optional[Dict[str, Any]] = None,
               publish: bool = True,
               spawned_by: Optional[str] = None) -> Dict[str, Any]:
    """A registration body for `POST /agents`, with the boilerplate filled in."""
    return {
        "org_id": org, "project_id": project,
        "identity": {"agent_id": agent_id, "name": name, "slug": slug,
                     "telos": telos, "description": description},
        "version": {
            "agent_id": agent_id, "version": version, "system_prompt": prompt,
            "model": {"name": CHAT_MODEL, "params": {"temperature": 0.0,
                                                     "max_tokens": 200}},
            "input_schema": TEXT_IN, "output_schema": TEXT_OUT,
            "capabilities": capabilities or [],
            "tools": tools or [],
            "resource_limits": resource_limits or {},
        },
        "publish": publish,
        "spawned_by": spawned_by,
    }


def tool_body(*, org: str, tool_id: str, name: str, description: str,
              endpoint: str, side_effects: str = "read",
              scope_type: str = "org", project: Optional[str] = None,
              capabilities: Optional[List[str]] = None,
              input_schema: Optional[Dict[str, Any]] = None,
              output_schema: Optional[Dict[str, Any]] = None,
              min_reputation_score: float = 0.0,
              version: str = "1.0.0",
              limits: Optional[Dict[str, Any]] = None,
              auth: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "identity": {"tool_id": tool_id, "name": name, "description": description,
                     "scope_type": scope_type, "org_id": org,
                     "project_id": project, "capabilities": capabilities or []},
        "version": {
            "tool_id": tool_id, "version": version, "endpoint_url": endpoint,
            "side_effects": side_effects,
            "input_schema": input_schema or object_schema(
                {"query": {"type": "string", "description": "the query text"}},
                ["query"]),
            "output_schema": output_schema or object_schema(
                {"results": {"type": "array", "description": "what came back"}}),
            "min_reputation_score": min_reputation_score,
            "limits": limits or {"timeout_secs": 60},
            "auth": auth or {"mode": "none"},
        },
    }


# The real model router requires a bearer token. A tool pointed at it declares
# `auth.mode: bearer` and names the secret; the registry resolves the reference
# at dispatch and never stores the value (Rule 6.3).
ROUTER_AUTH = {"mode": "bearer",
               "secret_ref": {"name": "litellm", "key": "OPENAI_API_KEY"}}
