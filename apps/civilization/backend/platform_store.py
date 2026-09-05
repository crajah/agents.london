"""Platform storage and LLM helpers that outlived the native engine.

These are not an execution *strategy* -- they are the BFF's storage
(project keys, custom model configs, versions, sessions), its telemetry
record, and its two direct LLM calls. They lived inside the 2208-line
native engine module, which meant importing the whole native engine to
read a project key. Extracted 2026-09-04 when the native engine was
removed (user decision: ADK only)."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import secrets
import string
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from post_graph import AsyncPostGraph
from post_graph_rag import DocumentMetadata, GraphRAG, RAGConfig

try:
    from backend.env_config import DEFAULT_LLM_MODEL, RAG_MODEL, require_env
except ImportError:
    from env_config import DEFAULT_LLM_MODEL, RAG_MODEL, require_env
try:
    from backend.redis_bus import redis_bus
except (ImportError, ModuleNotFoundError):
    from redis_bus import redis_bus

logger = logging.getLogger(__name__)

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
DEFAULT_DB_URI = (f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
                  f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
SCHEMA_PER_REALM = os.getenv("SCHEMA_PER_REALM", "1").lower() in ("1", "true", "yes")
POSTGRES_POOL_KWARGS = {"min_size": 1,
                        "max_size": int(os.getenv("POSTGRES_POOL_MAX", "3"))}
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)
LITELLM_URL = os.getenv("OPENAI_API_BASE",
                        os.getenv("LITELLM_URL",
                                  "http://litellm-service.default.svc.cluster.local:80/v1"))
API_KEY = require_env("OPENAI_API_KEY")


# ------------------------------------------------------------- telemetry
EXECUTION_METRICS: Dict[str, Any] = {
    "global": {"executions": 0, "unique_users": set(), "bytes_in": 0,
               "bytes_out": 0, "tokens_in": 0, "tokens_out": 0},
    "projects": {},
    "agents": {},
}


def _bump(bucket: Dict[str, Any], user_id: str, bi: int, bo: int,
          ti: int, to: int) -> None:
    bucket["executions"] += 1
    bucket["unique_users"].add(user_id)
    bucket["bytes_in"] += bi
    bucket["bytes_out"] += bo
    bucket["tokens_in"] += ti
    bucket["tokens_out"] += to


def _bucket(kind: str, key: str) -> Dict[str, Any]:
    return EXECUTION_METRICS[kind].setdefault(
        key, {"executions": 0, "unique_users": set(), "bytes_in": 0,
              "bytes_out": 0, "tokens_in": 0, "tokens_out": 0})


def _record_in_memory(project_id: str, user_id: str, agent_id: str,
                      bi: int, bo: int, ti: int, to: int) -> None:
    _bump(EXECUTION_METRICS["global"], user_id, bi, bo, ti, to)
    _bump(_bucket("projects", project_id), user_id, bi, bo, ti, to)
    _bump(_bucket("agents", agent_id), user_id, bi, bo, ti, to)


async def record_execution_telemetry_to_pg(
        org_id: str, project_id: str, user_id: str, agent_id: str,
        input_text: str, output_text: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None) -> None:
    """The durable record AND the in-memory cache, always both -- the old
    version updated memory only on the happy path's task and get_real_
    telemetry answered zeros forever."""
    bi = len(input_text.encode("utf-8")) if input_text else 0
    bo = len(output_text.encode("utf-8")) if output_text else 0
    ti = prompt_tokens if prompt_tokens is not None else max(1, len(input_text) // 4)
    to = completion_tokens if completion_tokens is not None else max(1, len(output_text) // 4)
    _record_in_memory(project_id, user_id, agent_id, bi, bo, ti, to)
    try:
        pg = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM,
                            **POSTGRES_POOL_KWARGS)
        await pg.connect()
        await pg.create_vertex_table("executions", realm=org_id)
        payload = {"org_id": org_id, "project_id": project_id,
                   "user_id": user_id, "agent_id": agent_id,
                   "bytes_in": bi, "bytes_out": bo,
                   "tokens_in": ti, "tokens_out": to,
                   "timestamp": datetime.utcnow().isoformat()}
        v = await pg.add_vertex("executions", realm=org_id,
                                space=project_id, payload=payload)
        await pg.add_vertex_data("executions", realm=org_id,
                                 vertex_id=int(v.id), payload=payload)
        await pg.close()
    except Exception as e:
        logger.debug(f"telemetry persistence fallback: {e}")


def record_execution_telemetry(
        org_id: str, project_id: str, user_id: str, agent_id: str,
        input_text: str, output_text: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None) -> None:
    """Synchronous wrapper: memory NOW (so reads see it immediately), the
    durable write in the background when a loop is running."""
    bi = len(input_text.encode("utf-8")) if input_text else 0
    bo = len(output_text.encode("utf-8")) if output_text else 0
    ti = prompt_tokens if prompt_tokens is not None else max(1, len(input_text) // 4)
    to = completion_tokens if completion_tokens is not None else max(1, len(output_text) // 4)
    _record_in_memory(project_id, user_id, agent_id, bi, bo, ti, to)
    try:
        loop = asyncio.get_event_loop()
        coro = record_execution_telemetry_to_pg(
            org_id, project_id, user_id, agent_id, input_text, output_text,
            prompt_tokens, completion_tokens)
        if loop.is_running():
            asyncio.create_task(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        logger.debug(f"telemetry dispatch note: {e}")


def get_real_telemetry(org_id: Optional[str] = None,
                       project_id: Optional[str] = None,
                       agent_id: Optional[str] = None) -> Dict[str, Any]:
    def view(b: Dict[str, Any]) -> Dict[str, Any]:
        return {"executions": b["executions"],
                "unique_user_engagements": len(b["unique_users"]),
                "bytes_in": b["bytes_in"], "bytes_out": b["bytes_out"],
                "tokens_in": b["tokens_in"], "tokens_out": b["tokens_out"]}
    if agent_id:
        return {"agent_id": agent_id, **view(_bucket("agents", agent_id))}
    if project_id:
        return {"project_id": project_id,
                **view(_bucket("projects", project_id))}
    g = EXECUTION_METRICS["global"]
    return {"global": True, "total_executions": g["executions"], **view(g)}


# ----------------------------------------------------------- project keys
def generate_project_api_key() -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


async def get_project_api_key_from_pg(project_id: str,
                                      org_id: str = "org_london_meta") -> str:
    try:
        pg = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM,
                            **POSTGRES_POOL_KWARGS)
        await pg.connect()
        await pg.create_vertex_table("projects", realm=org_id)
        v = await pg.get_vertex("projects", realm=org_id, vertex_id=project_id)
        if v and isinstance(getattr(v, "payload", None), dict) \
                and v.payload.get("api_key"):
            await pg.close()
            return v.payload["api_key"]
        new_key = generate_project_api_key()
        await pg.add_vertex("projects", realm=org_id, space=project_id,
                            payload={"project_id": project_id,
                                     "org_id": org_id, "api_key": new_key,
                                     "created_at": datetime.utcnow().isoformat()})
        await pg.close()
        return new_key
    except Exception as e:
        logger.debug(f"project key read fallback: {e}")
        return generate_project_api_key()


async def save_project_api_key_to_pg(project_id: str, new_api_key: str,
                                     org_id: str = "org_london_meta") -> str:
    try:
        pg = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM,
                            **POSTGRES_POOL_KWARGS)
        await pg.connect()
        await pg.create_vertex_table("projects", realm=org_id)
        await pg.add_vertex("projects", realm=org_id, space=project_id,
                            payload={"project_id": project_id,
                                     "org_id": org_id,
                                     "api_key": new_api_key,
                                     "updated_at": datetime.utcnow().isoformat()})
        await pg.close()
    except Exception as e:
        logger.warning(f"project key save failed: {e}")
    return new_api_key


# ------------------------------------------------------------- LLM calls
async def generate_dynamic_task_document(
        prompt: str, project_id: str = "proj_alpha_civilization",
        org_id: str = "org_london_meta",
        model: str | None = None) -> str:
    """One prompt, one answer, through the router. The arithmetic fast-path
    survives from the native engine (input restricted to digits and
    operators before eval). `model` is honoured when given -- the playground
    used to claim the user's selected model ran while this always called
    RAG_MODEL (F.14: report only what happened)."""
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return "Please provide a valid query or goal directive."
    math_match = re.search(r"(?:what\s+is\s+)?([\d\s\+\-\*\/\(\)\.]+)\??$",
                           clean_prompt.lower())
    if math_match:
        expr = math_match.group(1).strip()
        if expr and re.match(r"^[\d\s\+\-\*\/\(\)\.]+$", expr):
            try:
                val = eval(expr)  # noqa: S307 -- charset-restricted arithmetic
                if isinstance(val, (int, float)):
                    if isinstance(val, float) and val.is_integer():
                        val = int(val)
                    return f"Calculated Result: **{val}**"
            except Exception:
                pass
    candidates = list(dict.fromkeys([LITELLM_URL, "http://localhost:4000/v1"]))
    for api_url in candidates:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{api_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json={"model": model or RAG_MODEL,
                          "messages": [
                              {"role": "system", "content": (
                                  "You are an expert AI assistant and lead "
                                  "strategist in agent.london. Directly answer "
                                  "the user's prompt in clean, well-structured "
                                  "Markdown. Do NOT wrap response in meta "
                                  "descriptions like 'Here is a report'. "
                                  "Provide clear headers, actionable insights, "
                                  "tables, and bullet points.")},
                              {"role": "user", "content": clean_prompt}],
                          "max_tokens": 4096})
                if res.status_code == 200:
                    doc = res.json()["choices"][0]["message"]["content"].strip()
                    if doc and len(doc) > 20:
                        return doc
        except Exception as e:
            logger.debug(f"LLM call to {api_url} note: {e}")
    return (f"**LLM service unavailable.** Could not reach any model router "
            f"to process: *\"{clean_prompt[:100]}\"*. "
            f"Please ensure LiteLLM is running.")


# ----------------------------------------------------- storage mixin
class PlatformStoreMixin:
    """The nine methods main.py needs that were native-only -- storage and
    direct LLM operations, no execution strategy in any of them. The ADK
    engine mixes this in; the endpoints they serve stop 500ing."""

    db_uri: str  # provided by the engine's __init__

    async def _get_pg_client(self, org_id: str) -> AsyncPostGraph:
        try:
            client = AsyncPostGraph(dsn=self.db_uri,
                                    schema_per_realm=SCHEMA_PER_REALM,
                                    **POSTGRES_POOL_KWARGS)
            await client.connect()
        except Exception as e:
            raise RuntimeError(
                f"Could not connect to PostgreSQL at the configured DSN: "
                f"{e}. Check POSTGRES_URI.") from e
        for t in ("users", "projects", "agents", "sessions", "guardrails",
                  "custom_model_configs"):
            await client.create_vertex_table(t, realm=org_id)
        await client.create_edge_table("spawns", from_vertex_table="agents",
                                       to_vertex_table="agents", realm=org_id)
        await client.create_edge_table("inspects", from_vertex_table="agents",
                                       to_vertex_table="agents", realm=org_id)
        await client.create_edge_table("belongs_to",
                                       from_vertex_table="projects",
                                       to_vertex_table="users", realm=org_id)
        return client

    async def save_custom_model_config(self, org_id: str, user_id: str,
                                       project_id: Optional[str],
                                       scope_level: str, provider_name: str,
                                       custom_model_id: str,
                                       api_endpoint: str,
                                       api_key: str) -> Dict[str, Any]:
        """The RAW key is NOT stored (it used to be, in plaintext, beside
        its own mask). Routing metadata only; real credentials belong in
        the authority's vault."""
        target_realm = project_id if project_id else org_id
        client = await self._get_pg_client(target_realm)
        masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
        v = await client.add_vertex(
            table_name="custom_model_configs", realm=target_realm,
            payload={"org_id": org_id, "user_id": user_id,
                     "project_id": project_id, "scope_level": scope_level,
                     "provider_name": provider_name,
                     "custom_model_id": custom_model_id,
                     "api_endpoint": api_endpoint,
                     "masked_api_key": masked,
                     "created_at": datetime.utcnow().isoformat()})
        await client.close()
        return {"config_id": v.id, "org_id": org_id,
                "project_id": project_id, "scope_level": scope_level,
                "custom_model_id": custom_model_id,
                "api_endpoint": api_endpoint, "masked_key": masked}

    async def get_custom_model_configs(self, org_id: str, user_id: str,
                                       project_id: Optional[str] = None
                                       ) -> List[Dict[str, Any]]:
        target_realm = project_id if project_id else org_id
        client = await self._get_pg_client(target_realm)
        try:
            vertices = await client.get_vertices(
                table_name="custom_model_configs", realm=target_realm)
            return [getattr(v, "payload", v) for v in vertices]
        except Exception as e:
            logger.warning(f"custom_model_configs fetch failed: {e}")
            return []
        finally:
            await client.close()

    async def get_agent_version_history(self, project_id: str, agent_id: str,
                                        org_id: str = "org_default"
                                        ) -> List[Dict[str, Any]]:
        client = await self._get_pg_client(project_id)
        try:
            records = await client.get_vertex_data("agents", realm=org_id,
                                                   vertex_id=agent_id)
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"agent version history failed: {e}")
            return []
        finally:
            await client.close()

    async def get_latest_agent_version(self, project_id: str, agent_id: str,
                                       org_id: str = "org_default"
                                       ) -> Optional[Dict[str, Any]]:
        client = await self._get_pg_client(project_id)
        try:
            record = await client.get_latest_vertex_data(
                "agents", realm=org_id, vertex_id=agent_id)
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"latest agent version failed: {e}")
            return None
        finally:
            await client.close()

    async def get_agent_version_by_id(self, project_id: str, data_id: str,
                                      org_id: str = "org_default"
                                      ) -> Optional[Dict[str, Any]]:
        client = await self._get_pg_client(project_id)
        try:
            record = await client.get_vertex_data_by_id(
                "agents", realm=org_id, data_id=data_id)
            return record.to_dict() if record else None
        except Exception as e:
            logger.error(f"agent version by id failed: {e}")
            return None
        finally:
            await client.close()

    async def initiate_session(self, org_id: str, project_id: str,
                               user_id: str, session_name: str
                               ) -> Dict[str, Any]:
        session_realm = f"{org_id}_{project_id}"
        config = RAGConfig(api_base=LITELLM_URL, api_key=API_KEY,
                           model=DEFAULT_LLM_MODEL, db_uri=self.db_uri,
                           realm=session_realm)
        rag = GraphRAG(config)
        await rag.initialize()
        doc_res = await rag.index_document(
            f"Session '{session_name}' initiated in Project '{project_id}' "
            f"by User '{user_id}'. Shared memory context active.",
            metadata=DocumentMetadata(source="session_init",
                                      category="session_memory",
                                      collection=project_id,
                                      document=session_name))
        doc_id = doc_res.get("document_id", "unknown") \
            if isinstance(doc_res, dict) else "unknown"
        await rag.close()
        session_id = f"sess-{doc_id}"
        redis_bus.publish_event(org_id, project_id, {
            "event": "session_initiated", "session_id": session_id,
            "session_name": session_name, "user_id": user_id})
        return {"session_id": session_id, "session_name": session_name,
                "realm": session_realm, "shared_memory_status": "active"}

    async def infer_multimodal(self, file_bytes: bytes, filename: str,
                               user_prompt: str = "") -> str:
        ext = os.path.splitext(filename)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".webp": "image/webp", ".mp4": "video/mp4",
                ".mov": "video/quicktime"}.get(ext, "image/png")
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        messages = [{"role": "user", "content": [
            {"type": "text", "text": user_prompt or
             "Describe this image or video in detail. What do you see? "
             "Extract all relevant information."},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]
        for api_url in [LITELLM_URL, "http://localhost:4000/v1"]:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    res = await client.post(
                        f"{api_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        json={"model": "gemma-4-31B-it",
                              "messages": messages, "max_tokens": 2048})
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.debug(f"vision call to {api_url} note: {e}")
        return (f"[Vision inference unavailable for {filename}. Please "
                f"ensure gemma-4-31B-it is accessible via LiteLLM.]")

    async def get_user_projects(self, org_id: str, user_id: str
                                ) -> List[Dict[str, Any]]:
        """Real projects from the projects table -- this method existed on
        NEITHER engine; main.py silently fabricated a project every call."""
        client = await self._get_pg_client(org_id)
        try:
            vertices = await client.get_vertices("projects", realm=org_id)
            out = []
            for v in vertices:
                pl = getattr(v, "payload", None) or {}
                if isinstance(pl, dict) and pl.get("project_id"):
                    out.append(pl)
            return out
        except Exception as e:
            logger.warning(f"get_user_projects failed: {e}")
            return []
        finally:
            await client.close()
