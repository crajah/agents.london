"""Backend for Frontend (BFF) FastAPI Service for agent.london

Connects user interfaces to agent.london's multi-tenant 1B-agent civilization engine,
post-graph database, post-graph-rag shared session memory, Redis work bus, and Kubernetes services.
Includes Playground API, Conductor Orchestration, ReAct Loops, and Progeny Hierarchy.
"""
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
import httpx
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
try:
    from backend.env_config import (
        DEFAULT_LLM_MODEL, EMBEDDING_DIM, EMBEDDING_MODEL,
        JUDGE_MODELS as CONFIGURED_JUDGE_MODELS,
        RAG_MODEL, require_env,
    )
except ImportError:  # started with backend/ as the working directory
    from env_config import (
        DEFAULT_LLM_MODEL, EMBEDDING_DIM, EMBEDDING_MODEL,
        JUDGE_MODELS as CONFIGURED_JUDGE_MODELS,
        RAG_MODEL, require_env,
    )
try:
    from backend.civilization import civilization_engine, get_real_telemetry, record_execution_telemetry, generate_dynamic_task_document
    from backend.redis_bus import redis_bus
except (ImportError, ModuleNotFoundError):
    try:
        from civilization import civilization_engine, get_real_telemetry, record_execution_telemetry, generate_dynamic_task_document
        from redis_bus import redis_bus
    except (ImportError, ModuleNotFoundError):
        from .civilization import civilization_engine, get_real_telemetry, record_execution_telemetry, generate_dynamic_task_document
        from .redis_bus import redis_bus

try:
    from post_graph_rag import GraphRAG, RAGConfig, DocumentMetadata, QueryParam
    HAS_POST_GRAPH_RAG = True
except ImportError:
    HAS_POST_GRAPH_RAG = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

tags_metadata = [
    {"name": "Civilization Engine", "description": "Core multi-agent Conductor orchestration, ReAct loops, and dynamic task synthesis."},
    {"name": "Playground", "description": "Interactive prompt testing, detector-renderers, and live LLM streaming."},
    {"name": "Document Registry", "description": "Multi-document space uploading, Docling parsing, and GraphRAG indexing."},
    {"name": "Agent Management", "description": "Materialize progeny worker nodes and inspect Prime Node hierarchies."},
    {"name": "System & Telemetry", "description": "Health checks, live cluster metrics, and Redis bus events."}
]

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the duty cycles with the app, and stop them with it.

    The founders that run without being asked need somewhere to look: the
    scheduler works from a watchlist that project creation adds to. A backend
    that has just started and has seen no projects runs no cycles, which is
    correct — there is nothing yet to evaluate.
    """
    try:
        from backend.autonomy import scheduler as _sched
    except ImportError:                   # running from inside backend/
        from autonomy import scheduler as _sched
    _sched._client_factory = _autonomy_client
    await _sched.start()
    try:
        yield
    finally:
        await _sched.stop()


app = FastAPI(
    title="agent.london Backend API",
    description="""
    # 🏛️ agent.london OpenAPI / Swagger Specifications
    
    Multi-tenant Agent Civilization API scaling to 1 Billion Autonomous Agents with Google ADK, post-graph, post-graph-rag, and Model Context Protocol (MCP).
    
    - **Interactive Swagger Documentation:** [/docs](/docs)
    - **ReDoc API Documentation:** [/redoc](/redoc)
    - **OpenAPI Schema JSON:** [/openapi.json](/openapi.json)
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ACTIVE_CONNECTIONS: List[WebSocket] = []


class CreateUserRequest(BaseModel):
    org_id: str
    username: str
    email: str

class CreateProjectRequest(BaseModel):
    org_id: str
    user_id: str
    project_name: str
    constitution_rules: Optional[List[str]] = None

class MaterializeAgentRequest(BaseModel):
    org_id: str
    project_id: str
    user_id: str
    agent_name: str
    system_prompt: str
    parent_agent_id: Optional[str] = None
    tools: Optional[List[str]] = None
    custom_guardrails: Optional[List[str]] = None

class InitiateSessionRequest(BaseModel):
    org_id: str
    project_id: str
    user_id: str
    session_name: str

class EnqueueTaskRequest(BaseModel):
    org_id: str
    project_id: str
    agent_id: str
    task_description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

class PlaygroundChatRequest(BaseModel):
    org_id: str
    project_id: str
    user_id: str
    mode: str = "conductor" # "conductor", "react", "direct"
    prompt: str
    agent_id: Optional[str] = None

GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.ca",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
    "zoho.com", "gmx.com", "gmx.net", "yandex.com", "mail.com", "fastmail.com",
    "comcast.net", "sbcglobal.net", "verizon.net", "att.net"
}

# The realm every unscoped registry read falls back to. One constant rather than
# nine literals: the registry keeps each organisation in its own PostgreSQL
# schema, so disagreeing about the default means reading an empty schema and
# reporting "not found" for an agent that exists.
DEFAULT_ORG_ID = os.getenv("DEFAULT_ORG_ID", "org_london_meta")

try:
    from backend.founders import (roster as founder_roster, AUTONOMOUS,
                                  founder, founder_prompt)
except ImportError:                       # running from inside backend/
    from founders import (roster as founder_roster, AUTONOMOUS,
                          founder, founder_prompt)


# The registries this backend fronts. One constant each, read from the
# environment, so a deployment moves a service by setting a variable rather
# than by finding every hardcoded cluster URL.
TOOL_REGISTRY_URL = os.getenv(
    "TOOL_REGISTRY_URL",
    "http://tool-registry-service.default.svc.cluster.local:8002")
AGENT_REGISTRY_URL = os.getenv(
    "AGENT_REGISTRY_URL",
    "http://agent-registry-service.default.svc.cluster.local:8001")


def resolve_tenancy_from_email(email: str) -> dict:
    clean_email = email.strip().lower()
    if "@" not in clean_email:
        return {"org_id": "org_london_meta", "user_id": "user_chandan", "is_generic": False}
    
    parts = clean_email.split("@")
    user_part = re.sub(r'[^a-z0-9]', '_', parts[0])
    domain_part = parts[1]
    sanitized_domain = re.sub(r'[^a-z0-9]', '_', domain_part)
    
    is_generic = domain_part in GENERIC_EMAIL_DOMAINS
    if is_generic:
        org_id = f"org_user_{user_part}_{sanitized_domain}"
    else:
        org_id = f"org_{sanitized_domain}"
        
    return {
        "org_id": org_id,
        "user_id": f"user_{user_part}",
        "domain": domain_part,
        "is_generic": is_generic,
        "email": clean_email
    }

class VerifyGoogleTokenRequest(BaseModel):
    id_token: Optional[str] = None
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None

class EmailSessionRequest(BaseModel):
    email: str


@app.post("/api/auth/email/session")
async def create_email_session(req: EmailSessionRequest):
    """Resolve an email address to a tenancy, and say plainly that nothing was verified.

    **This does not authenticate anyone.** No password, no mail round trip, no
    proof the address belongs to whoever typed it. It exists for two reasons:

    1. The organisation is derived **here**, by the same function the Google and
       Microsoft routes use, so all three doors put a person in the same realm.
       The rule used to be written twice more in the browser, and two copies of
       a tenancy rule that can disagree is a way to land in a different
       organisation depending on which door you came through (F.5).
    2. The response states `verified: false` and names the method, so the
       client is not left to assume it — an interface can only label what it is
       told (F.7).

    Replacing this with real verification means issuing a one-time link or code
    to the address and returning a session only after it comes back. The shape
    of this response does not change when that happens; `verified` becomes true.
    """
    email = (req.email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400,
                            detail="That does not look like an email address.")

    tenancy = resolve_tenancy_from_email(email)
    return {
        "status": "unverified",
        "verified": False,
        "method": "email",
        "email": email,
        "org_id": tenancy["org_id"],
        "user_id": tenancy["user_id"],
        "is_generic": tenancy["is_generic"],
        "notice": ("This address was not verified. Anyone can enter any "
                   "address and reach this organisation."),
    }


MS_JWKS_URL = os.getenv(
    "MS_JWKS_URL", "https://login.microsoftonline.com/common/discovery/v2.0/keys")

# Cached across calls: fetching the key set on every sign-in is a request to
# Microsoft on the critical path, and the keys rotate on the order of weeks.
_ms_jwks_client = None


def _verify_microsoft_id_token(id_token: str, accepted: List[str]) -> Dict[str, Any]:
    """Check a Microsoft ID token, signature and all.

    This used to base64-decode the middle segment of the JWT and read the email
    out of it. No signature check, no issuer, no expiry, no audience — so a
    string anyone could type by hand was accepted as proof of identity:

        header = {"alg": "RS256"}                      (ignored)
        payload = {"email": "anyone@anywhere.com"}     (believed)
        signature = "not-a-signature"                  (never looked at)

    and the endpoint answered `verified: true` for whatever address the payload
    named — which then decided the organisation the session landed in. The
    signature is the only thing that makes a JWT evidence of anything.
    """
    global _ms_jwks_client
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as e:                       # pragma: no cover
        # Refusing is the only safe answer: the alternative is the behaviour
        # this replaced.
        raise HTTPException(
            status_code=500,
            detail="PyJWT is not installed, so Microsoft tokens cannot be "
                   "verified. Sign-in is refused rather than assumed.") from e

    if _ms_jwks_client is None:
        _ms_jwks_client = PyJWKClient(MS_JWKS_URL, cache_keys=True)

    try:
        key = _ms_jwks_client.get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token, key, algorithms=["RS256"], audience=accepted,
            options={"require": ["exp", "iss", "aud"]})
    except Exception as e:
        logger.warning("Microsoft token rejected: %s", e)
        raise HTTPException(status_code=401,
                            detail=f"Invalid Microsoft ID Token: {e}") from e

    # The `common` endpoint issues per-tenant, so the tenant is not fixed — but
    # the issuer must still be Microsoft rather than anyone who can serve a JWKS.
    issuer = str(claims.get("iss", ""))
    if not (issuer.startswith("https://login.microsoftonline.com/")
            and issuer.endswith("/v2.0")):
        raise HTTPException(status_code=401,
                            detail=f"Unexpected token issuer {issuer!r}.")
    return claims


# ------------------------------------------------------------------- sign-in

def _accepted_client_ids(primary: str, extra_var: str) -> List[str]:
    """Every OAuth client whose tokens this deployment will accept.

    A list rather than one value because the browser bundle and the backend are
    configured in different places — a GitHub Actions build argument and a
    Kubernetes secret — and they can hold different clients. During a migration
    both are legitimate; the point is that the set is stated, not that anything
    signed by the provider is waved through.
    """
    accepted = [c.strip() for c in
                ([primary] + os.getenv(extra_var, "").split(",")) if c.strip()]
    if not accepted:
        raise HTTPException(
            status_code=500,
            detail="No OAuth client is configured, so no token can be checked "
                   "against one.")
    return accepted


def _require_audience(token_info: Dict[str, Any], accepted: List[str],
                      provider: str) -> None:
    """The check that decides whether this token was minted for us.

    Without it, any token the provider signed is accepted — including one
    issued to somebody else's application entirely. An attacker registers their
    own OAuth client, signs a user in to it, and presents the resulting token
    here; it is genuinely signed, genuinely unexpired, and grants a session for
    whatever address it names. Google's own documentation calls this out.
    """
    audience = token_info.get("aud")
    if audience not in accepted:
        logger.warning("%s token rejected: audience %r is not one of this "
                       "deployment's clients", provider, audience)
        raise HTTPException(
            status_code=401,
            detail=(f"This {provider} token was issued to a different "
                    f"application, so it does not prove anything about who is "
                    f"calling here."))


@app.post("/api/auth/google/verify")
async def verify_google_oauth_token(req: VerifyGoogleTokenRequest):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars.")

    async with httpx.AsyncClient() as client:
        if req.code:
            token_url = "https://oauth2.googleapis.com/token"
            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": req.code,
                "grant_type": "authorization_code",
                "redirect_uri": req.redirect_uri or "http://localhost:3000"
            }
            if req.code_verifier:
                payload["code_verifier"] = req.code_verifier
            resp = await client.post(token_url, data=payload)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Google OAuth token exchange failed: {resp.text}")
            token_data = resp.json()
            id_token = token_data.get("id_token")
        else:
            id_token = req.id_token

        if not id_token:
            raise HTTPException(status_code=400, detail="Missing id_token or code")

        # tokeninfo validates the signature and the expiry at Google. What it
        # does not do is say the token was meant for us — that is the caller's
        # job, and it was not being done.
        info_resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token})
        if info_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Google ID Token")

        token_info = info_resp.json()
        _require_audience(token_info,
                          _accepted_client_ids(client_id, "GOOGLE_ADDITIONAL_CLIENT_IDS"),
                          "Google")

        if token_info.get("iss") not in ("accounts.google.com",
                                         "https://accounts.google.com"):
            raise HTTPException(status_code=401,
                                detail="This token was not issued by Google.")

        email = token_info.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="No email associated with Google account")

        # Google returns this as the string "true". An unverified address is an
        # address the holder has not shown they control, and tenancy is derived
        # from the domain.
        if str(token_info.get("email_verified", "")).lower() not in ("true", "1"):
            raise HTTPException(
                status_code=401,
                detail=f"Google has not verified {email}, so it cannot be used "
                       f"to identify an organisation.")

        tenancy = resolve_tenancy_from_email(email)
        return {
            "status": "verified",
            "verified": True,
            "method": "google",
            "email": email,
            "org_id": tenancy["org_id"],
            "user_id": tenancy["user_id"],
            "token_info": token_info
        }

class VerifyMicrosoftTokenRequest(BaseModel):
    id_token: Optional[str] = None
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None

@app.post("/api/auth/ms/verify")
async def verify_microsoft_oauth_token(req: VerifyMicrosoftTokenRequest):
    client_id = os.getenv("MS_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(status_code=500, detail="Microsoft OAuth not configured. Set MS_CLIENT_ID env var.")

    async with httpx.AsyncClient() as client:
        if req.code:
            token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            payload = {
                "client_id": client_id,
                "code": req.code,
                "grant_type": "authorization_code",
                "redirect_uri": req.redirect_uri or "http://localhost:3000",
                "scope": "openid email profile"
            }
            # The code is redeemed SERVER-side (no browser Origin header),
            # so the redirect URI must be registered under the WEB platform
            # and this app must authenticate as a confidential client --
            # AADSTS90023 rejects SPA-platform codes redeemed off-origin.
            # PKCE's code_verifier still rides along; the two compose.
            ms_secret = os.getenv("MS_CLIENT_SECRET", "")
            if ms_secret:
                payload["client_secret"] = ms_secret
            if req.code_verifier:
                payload["code_verifier"] = req.code_verifier
            resp = await client.post(token_url, data=payload)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Microsoft OAuth token exchange failed: {resp.text}")
            token_data = resp.json()
            id_token = token_data.get("id_token")
        else:
            id_token = req.id_token

        if not id_token:
            raise HTTPException(status_code=400, detail="Missing id_token or code")

        token_info = _verify_microsoft_id_token(
            id_token, _accepted_client_ids(client_id, "MS_ADDITIONAL_CLIENT_IDS"))

        email = (token_info.get("email") or token_info.get("preferred_username")
                 or token_info.get("upn"))
        if not email:
            raise HTTPException(status_code=400, detail="No email found in Microsoft ID Token")

        tenancy = resolve_tenancy_from_email(email)
        return {
            "status": "verified",
            "verified": True,
            # This said "google". A session that misreports which provider
            # authenticated it cannot be audited afterwards.
            "method": "microsoft",
            "email": email,
            "org_id": tenancy["org_id"],
            "user_id": tenancy["user_id"],
            "token_info": token_info
        }

OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "http://localhost:4000/v1")
OPENAI_API_KEY = require_env("OPENAI_API_KEY")
POSTGRES_URI = os.getenv("POSTGRES_URI", "postgresql://crajah@localhost:5432/postgres")

# ─── RAG Discovery Helpers ──────────────────────────────────────────────────

_AGENT_RAG_INDEXED: set = set()  # tracks "{org_id}:{project_id}" indexed this process lifetime


def _build_agent_rag_config(org_id: str, project_id: str) -> "RAGConfig":
    return RAGConfig(
        api_base=OPENAI_API_BASE,
        api_key=OPENAI_API_KEY,
        db_uri=POSTGRES_URI,
        realm=f"{org_id}_{project_id}_agent_registry_rag",
    )


async def _ensure_agents_indexed_in_rag(org_id: str, project_id: str, agents_list: list):
    """Lazy-index agents into post-graph-rag on first discovery call per org/project."""
    cache_key = f"{org_id}:{project_id}"
    if cache_key in _AGENT_RAG_INDEXED:
        return
    config = _build_agent_rag_config(org_id, project_id)
    rag = GraphRAG(config)
    try:
        await rag.initialize()
        # Check if already indexed by probing for any existing chunk
        probe = await rag.query_data("agent", param=QueryParam(mode="naive", top_k=1))
        if probe.get("data", {}).get("chunks"):
            _AGENT_RAG_INDEXED.add(cache_key)
            await rag.close()
            return
        # Index each agent as a document
        for agent in agents_list:
            doc_text = (
                f"Agent ID: {agent['id_prefix']}-{project_id}\n"
                f"Name: {agent['name']}\n"
                f"Caste: {agent['caste']}\n"
                f"Cognitive Function: {agent['cog_func']}\n"
                f"Topology: {agent['topo']}\n"
                f"Telos: {agent['telos']}\n"
                f"Keywords: {', '.join(agent.get('keywords', []))}\n"
                f"Assigned Model: {agent.get('assignedModel', DEFAULT_LLM_MODEL)}\n"
            )
            meta = DocumentMetadata(
                source="prime_agent_registry",
                category="agent_specification",
                collection=project_id,
                document=agent["id_prefix"],
            )
            await rag.index_document(doc_text, metadata=meta)
        _AGENT_RAG_INDEXED.add(cache_key)
        await rag.close()
    except Exception as e:
        logger.warning(f"RAG agent indexing unavailable: {e}")
        try:
            await rag.close()
        except Exception as _e:
            logger.warning("%s: recoverable Exception in _ensure_agents_indexed_in_rag, continuing", type(_e).__name__, exc_info=_e)


async def _rag_discover_agents(org_id: str, project_id: str, query: str, agents_list: list, top_k: int = 4):
    """Query post-graph-rag for vector-similar agents. Returns list or None if RAG unavailable."""
    if not HAS_POST_GRAPH_RAG:
        return None
    try:
        await _ensure_agents_indexed_in_rag(org_id, project_id, agents_list)
    except Exception:
        return None

    config = _build_agent_rag_config(org_id, project_id)
    rag = GraphRAG(config)
    try:
        await rag.initialize()
        result = await rag.query_data(query, param=QueryParam(mode="mix", top_k=top_k * 2))
        await rag.close()

        chunks = [c for c in result.get("data", {}).get("chunks", []) if c.get("content")]
        if not chunks:
            return None

        # Build id_prefix lookup
        agents_by_prefix = {a["id_prefix"]: a for a in agents_list}

        discovered = []
        seen = set()
        for rank, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            for prefix, agent in agents_by_prefix.items():
                if prefix in content or agent["name"] in content:
                    if prefix not in seen:
                        seen.add(prefix)
                        # Similarity decreases with rank position
                        sim = round(max(0.70, 0.97 - rank * 0.03), 2)
                        discovered.append({
                            "agent_id": f"{prefix}-{project_id}",
                            "name": agent["name"],
                            "caste": agent["caste"],
                            "cog_func": agent["cog_func"],
                            "topo": agent["topo"],
                            "telos": agent["telos"],
                            "similarity": sim,
                            "reason": f"RAG vector similarity match via post-graph-rag for '{query[:45]}...'",
                            "pubkey": agent["pubkey"],
                            "tokens": agent["tokens"],
                            "rep": agent["rep"],
                            "assignedModel": agent["assignedModel"],
                            "systemPrompt": f"You are {agent['name']} ({agent['caste']}). Your telos: {agent['telos']}"
                        })
                        if len(discovered) >= top_k:
                            break
            if len(discovered) >= top_k:
                break
        return discovered if discovered else None
    except Exception as e:
        logger.warning(f"RAG agent discovery query failed: {e}")
        try:
            await rag.close()
        except Exception as _e:
            logger.warning("%s: recoverable Exception in _rag_discover_agents, continuing", type(_e).__name__, exc_info=_e)
        return None


def _keyword_discover_agents(query: str, project_id: str, agents_list: list, top_k: int = 4):
    """Keyword fallback for agent discovery when RAG is unavailable."""
    query_terms = [t for t in re.findall(r'\w+', query.lower()) if len(t) > 2]
    scored = []
    for agent in agents_list:
        score = 0
        matches = []
        for term in query_terms:
            for kw in agent.get("keywords", []):
                if term in kw or kw in term:
                    score += 2
                    matches.append(kw)
            if term in agent["telos"].lower() or term in agent["name"].lower():
                score += 1
        sim = min(0.98, max(0.75, 0.82 + (score * 0.04)))
        scored.append({
            "agent_id": f"{agent['id_prefix']}-{project_id}",
            "name": agent["name"],
            "caste": agent["caste"],
            "cog_func": agent["cog_func"],
            "topo": agent["topo"],
            "telos": agent["telos"],
            "similarity": round(sim, 2),
            "reason": f"Keyword match for '{query[:45]}...' (Keywords: {', '.join(list(set(matches))[:3]) or agent['cog_func']}).",
            "pubkey": agent["pubkey"],
            "tokens": agent["tokens"],
            "rep": agent["rep"],
            "assignedModel": agent["assignedModel"],
            "systemPrompt": f"You are {agent['name']} ({agent['caste']}). Your telos: {agent['telos']}"
        })
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


@app.get("/")
@app.get("/health")
@app.get("/api")
@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "agent.london-backend", "active_websockets": len(ACTIVE_CONNECTIONS)}

@app.get("/api/models")
async def list_available_models():
    """Queries LiteLLM Model Router at {OPENAI_API_BASE}/models and returns available LLMs."""
    models_url = f"{OPENAI_API_BASE.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"} if OPENAI_API_KEY else {}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(models_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("data", [])
                parsed_models = []
                for item in raw_models:
                    m_id = item.get("id", "unknown")
                    parsed_models.append({
                        "id": m_id,
                        "name": m_id.replace("-", " ").title(),
                        "provider": "LiteLLM Router",
                        "context_window": item.get("max_tokens", 128000),
                        "status": "active",
                        "source": "litellm_router"
                    })
                if parsed_models:
                    # The configured defaults travel with the list so the UI
                    # preselects what this deployment actually runs, instead of
                    # each view hardcoding a favourite that drifts from it.
                    return {"models": parsed_models, "source": "litellm_router",
                            "router_url": models_url,
                            "default_model": DEFAULT_LLM_MODEL,
                            "embedding_model": EMBEDDING_MODEL,
                            "embedding_dim": EMBEDDING_DIM}
    except Exception as e:
        logger.warning(f"Could not reach LiteLLM Model Router at {models_url}: {e}")

    # The router is unreachable. What comes back is the configured pair and
    # nothing else — deliberately not a remembered catalogue.
    #
    # A hardcoded list of "the models we usually have" goes stale silently: it
    # offered DeepSeek V3.1 and V3.2 long after that provider stopped answering,
    # so the UI presented models a user could select and no agent could call.
    # The two names below are the two this deployment is actually configured
    # for, and `status: unverified` says the router was not reached.
    return {
        "source": "configured_defaults",
        "router_url": models_url,
        "default_model": DEFAULT_LLM_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "warning": (f"The model router at {models_url} could not be reached. "
                    f"These are this deployment's configured defaults, not a "
                    f"live list of what the router serves."),
        "models": [
            {"id": DEFAULT_LLM_MODEL, "name": DEFAULT_LLM_MODEL,
             "provider": "configured default", "context_window": 128000,
             "status": "unverified", "role": "chat"},
            {"id": EMBEDDING_MODEL, "name": EMBEDDING_MODEL,
             "provider": "configured default", "context_window": 2048,
             "status": "unverified", "role": "embedding",
             "dimensions": EMBEDDING_DIM},
        ],
    }

class CustomModelRequest(BaseModel):
    org_id: str
    user_id: str
    project_id: Optional[str] = None
    scope_level: str  # "org", "project", "user"
    provider_name: str
    custom_model_id: str
    api_endpoint: str
    api_key: str

@app.post("/api/models/custom")
async def save_custom_model(req: CustomModelRequest):
    """Saves custom BYOM & BYOK model settings scoped to org, project, or user in post-graph DB."""
    res = await civilization_engine.save_custom_model_config(
        org_id=req.org_id,
        user_id=req.user_id,
        project_id=req.project_id,
        scope_level=req.scope_level,
        provider_name=req.provider_name,
        custom_model_id=req.custom_model_id,
        api_endpoint=req.api_endpoint,
        api_key=req.api_key
    )
    return res

@app.get("/api/models/custom")
async def get_custom_models(org_id: str, user_id: str, project_id: Optional[str] = None):
    """Fetches custom BYOM & BYOK model settings from post-graph database."""
    res = await civilization_engine.get_custom_model_configs(org_id=org_id, user_id=user_id, project_id=project_id)
    return {"configs": res}

class RecordIOTraceRequest(BaseModel):
    org_id: str
    agent_id: str
    input_prompt: str
    tool_calls: List[str] = []
    output_response: str

class SynthesizeDescriptionRequest(BaseModel):
    org_id: str
    agent_id: str
    agent_name: str
    caste: str

@app.post("/api/agents/record-trace")
async def record_agent_io_trace(req: RecordIOTraceRequest):
    """Records an input/output execution trace for an agent in post-graph database."""
    try:
        record_execution_telemetry(
            org_id=req.org_id,
            project_id="proj_alpha_civilization",
            user_id="system",
            agent_id=req.agent_id,
            input_text=req.input_prompt,
            output_text=req.output_response,
        )
    except Exception as e:
        logger.debug(f"Trace persistence note: {e}")
    return {"status": "recorded", "agent_id": req.agent_id, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/api/agents/synthesize-description")
async def synthesize_agent_description(req: SynthesizeDescriptionRequest):
    """Uses LLM to synthesize an updated descriptive metadata summary from sampled empirical I/O traces."""
    synth_prompt = (
        f"You are a metadata synthesizer for the agent.london civilization platform. "
        f"Write a concise 2-3 sentence professional description for the following agent:\n\n"
        f"Agent Name: {req.agent_name}\n"
        f"Agent ID: {req.agent_id}\n"
        f"Caste: {req.caste}\n"
        f"Organization Realm: {req.org_id}\n\n"
        f"Describe what this agent specializes in, its operational role within the civilization, "
        f"and its key capabilities. Be specific and technical."
    )
    description = await generate_dynamic_task_document(synth_prompt, "proj_alpha_civilization", req.org_id)
    return {
        "agent_id": req.agent_id,
        "agent_name": req.agent_name,
        "llm_description": description,
        "synthesized_at": datetime.now(timezone.utc).isoformat()
    }

class GeneratePromptRequest(BaseModel):
    user_prompt: str
    target_role: Optional[str] = "Worker Agent"

@app.post("/api/generate-system-prompt")
async def generate_system_prompt(req: GeneratePromptRequest):
    try:
        from backend.prompts import generate_comprehensive_system_prompt
    except ImportError:
        try:
            from prompts import generate_comprehensive_system_prompt
        except ImportError:
            from .prompts import generate_comprehensive_system_prompt

    generated = generate_comprehensive_system_prompt(
        agent_name=req.target_role or "Progeny Worker Agent",
        caste_role=req.target_role or "Specialized Task Workforce",
        telos=req.user_prompt
    )
    return {"system_prompt": generated}

@app.post("/api/users")
async def create_user(req: CreateUserRequest):
    tenancy = resolve_tenancy_from_email(req.email)
    effective_org_id = req.org_id if req.org_id and req.org_id != "auto" else tenancy["org_id"]
    res = await civilization_engine.create_user(effective_org_id, req.username, req.email)
    res["resolved_tenancy"] = tenancy
    return res

@app.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    res = await civilization_engine.create_project(
        org_id=req.org_id,
        user_id=req.user_id,
        project_name=req.project_name,
        constitution_rules=req.constitution_rules
    )
    # A new project is watched from the moment it exists: its founders' duty
    # cycles are part of it, not something a human has to switch on.
    if res.get("project_id"):
        autonomy_scheduler.watch(req.org_id, res["project_id"])
    await broadcast_ws_event({
        "type": "project_created",
        "data": res
    })
    return res

@app.post("/api/agents/materialize")
async def materialize_agent(req: MaterializeAgentRequest):
    res = await civilization_engine.materialize_worker_agent(
        org_id=req.org_id,
        project_id=req.project_id,
        user_id=req.user_id,
        agent_name=req.agent_name,
        system_prompt=req.system_prompt,
        parent_agent_id=req.parent_agent_id,
        tools=req.tools,
        custom_guardrails=req.custom_guardrails
    )
    await broadcast_ws_event({
        "type": "agent_materialized",
        "data": res
    })
    return res

@app.get("/api/runs")
async def list_pipeline_runs(project_id: Optional[str] = Query(None),
                             org_id: str = Query(DEFAULT_ORG_ID),
                             limit: int = Query(25, ge=1, le=200)):
    """Recent pipeline runs, from the registry that recorded them."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.get(f"{AGENT_REGISTRY_URL.rstrip('/')}/runs",
                                   params={"org_id": org_id, "project_id": project_id,
                                           "limit": limit})
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Agent registry unreachable: {e}") from e
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()


@app.get("/api/runs/{run_pk}/context")
async def get_run_context(run_pk: int, org_id: str = Query(DEFAULT_ORG_ID)):
    """Every context revision a run wrote, in order (AG §3.6).

    Revisions rather than a final snapshot: the registry keeps each one so a
    cyclic run can be read back afterwards, and collapsing them discards the
    reason they are kept (F.33).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.get(
                f"{AGENT_REGISTRY_URL.rstrip('/')}/runs/{run_pk}/context",
                params={"org_id": org_id})
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Agent registry unreachable: {e}") from e
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()


@app.get("/api/projects/{project_id}/agents")
async def get_project_agents(project_id: str, org_id: str = Query(DEFAULT_ORG_ID)):
    """Returns all Prime Agents + all persisted custom/progeny agents recovered for a given project."""
    persisted_custom = await civilization_engine.get_all_project_agents(org_id, project_id)
    
    all_agents = []
    seen_ids = set()
    
    for agent in PRIME_AGENTS:
        aid = f"{agent['id_prefix']}-{project_id}"
        seen_ids.add(aid)
        all_agents.append({
            "agent_id": aid,
            "id": aid,
            "name": agent["name"],
            "caste": agent["caste"],
            "cog_func": agent["cog_func"],
            "topo": agent["topo"],
            "telos": agent["telos"],
            "pubkey": agent["pubkey"],
            "assignedModel": agent.get("assignedModel", DEFAULT_LLM_MODEL),
            "is_prime": True
        })

    for ca in persisted_custom:
        aid = ca.get("agent_id") or ca.get("id")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            ca["id"] = aid
            ca["is_prime"] = False
            all_agents.append(ca)

    # The registry's own view of these agents, merged in: version, content hash
    # and slug. They are what make an agent reproducible (AG §4.2) and what a
    # pipeline pins, and the difference between "the summariser" and "the
    # summariser as it was when this run cited it" (F.21).
    registered = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{AGENT_REGISTRY_URL.rstrip('/')}/agents",
                                   params={"org_id": org_id, "project_id": project_id})
            if res.status_code == 200:
                for row in res.json().get("agents", []):
                    if row.get("agent_id"):
                        registered[row["agent_id"]] = row
    except Exception as e:
        # The list still renders; it simply cannot show pins for agents whose
        # registry entry could not be read.
        logger.warning("could not merge registry detail into the agent list: %s", e)

    for agent in all_agents:
        detail = registered.get(agent["agent_id"])
        if not detail:
            continue
        agent.update({
            "version": detail.get("version"),
            "content_hash": detail.get("content_hash"),
            "version_status": detail.get("version_status"),
            "slug": detail.get("slug"),
            "lifecycle": detail.get("lifecycle", "active"),
            "reputation_score": detail.get("reputation_score", agent.get("rep")),
            "token_balance": detail.get("token_balance", agent.get("tokens")),
            # What a caller invokes it by, if it is published (F.17).
            "mcp_tool": (f"agent:{detail['slug']}@{detail['version']}"
                         if detail.get("slug") and detail.get("version") else None),
        })

    return {"project_id": project_id, "org_id": org_id,
            "count": len(all_agents), "agents": all_agents,
            "registered_count": len(registered)}




@app.get("/api/projects/{project_id}/guardrails")
async def get_project_guardrails(project_id: str, org_id: str = Query(DEFAULT_ORG_ID)):
    """The guardrails actually attached to this project's agents.

    Guardrails are not a separate registry: they are recorded on the agents
    that carry them, with a level and a source (constitution, or discovered
    from the prompt that materialised the agent). This aggregates them and
    names the agents bound by each, so the panel shows the project's real
    constraints rather than a fixed list written in the browser.

    There is no "action on violation" field in the record. Rather than assert
    one, `action` is returned as null and the interface says it is not
    recorded — a guardrail whose consequence is unknown is a different promise
    from one that blocks and audits (F.34).
    """
    agents = await civilization_engine.get_all_project_agents(org_id, project_id)

    by_rule: Dict[str, Dict[str, Any]] = {}
    for agent in agents:
        for guardrail in agent.get("guardrails") or []:
            rule = (guardrail.get("rule") or "").strip()
            if not rule:
                continue
            entry = by_rule.setdefault(rule, {
                "rule": rule,
                "level": guardrail.get("level"),
                "source": guardrail.get("source"),
                "guardrail_id": guardrail.get("guardrail_id"),
                "action": guardrail.get("action"),   # not recorded today
                "bound_agents": [],
            })
            name = agent.get("name") or agent.get("agent_id")
            if name and name not in entry["bound_agents"]:
                entry["bound_agents"].append(name)

    guardrails = sorted(by_rule.values(), key=lambda g: (g.get("level") or "", g["rule"]))
    return {"project_id": project_id, "org_id": org_id,
            "count": len(guardrails), "guardrails": guardrails,
            "agents_scanned": len(agents)}


async def _registry_call(method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                         json_body: Optional[Dict[str, Any]] = None,
                         timeout: float = 15.0) -> httpx.Response:
    """One call to the one configured agent registry.

    Every one of these proxies used to try four URLs in turn — the configured
    one, two Kubernetes service names and localhost — and take whichever
    answered. That is not a fallback, it is a different deployment: a backend
    pointed at a staging registry would quietly serve production agents from
    localhost when staging was slow, and nothing in the response said which one
    replied. Configuration is the only authority; if it is unreachable that is
    a 502, not a silent substitution.
    """
    url = f"{AGENT_REGISTRY_URL.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            return await client.request(method, url, params=params, json=json_body)
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Agent registry unreachable at {url}: {e}") from e


# --------------------------------------------------------------- autonomy

try:
    from backend.autonomy import scheduler as autonomy_scheduler
except ImportError:                       # running from inside backend/
    from autonomy import scheduler as autonomy_scheduler


async def _autonomy_client(org_id: str):
    """A post-graph client for the scheduler to write its cycle records with."""
    return await civilization_engine._get_pg_client(org_id)


@app.get("/api/autonomy/status", tags=["Autonomy"])
async def autonomy_status():
    """What runs without being asked, how often, and what it may change."""
    return autonomy_scheduler.status()


@app.get("/api/autonomy/cycles", tags=["Autonomy"])
async def autonomy_cycles(limit: int = Query(50, ge=1, le=200)):
    """Recent duty cycles, newest first — including the quiet ones.

    Quiet cycles are shown rather than filtered: "the Adversary ran four times
    and found nothing" and "the Adversary has not run" are different states of
    the world, and only one of them is reassuring.
    """
    cycles = autonomy_scheduler.cycles[:limit]
    return {"cycles": cycles, "count": len(cycles),
            "quiet": sum(1 for c in cycles if c.get("quiet"))}


class AutonomyRunRequest(BaseModel):
    org_id: str = Field(default=DEFAULT_ORG_ID)
    project_id: str
    founder_id: str = Field(description="quarantine-warden | anomaly-detector | "
                                        "proving-ground | adversary")


@app.post("/api/autonomy/run", tags=["Autonomy"])
async def autonomy_run_now(req: AutonomyRunRequest):
    """Run one duty cycle immediately, and return what it actually did."""
    autonomy_scheduler.watch(req.org_id, req.project_id)
    result = await autonomy_scheduler.run_once(req.org_id, req.project_id,
                                               req.founder_id)
    if result.get("error") and "not a duty-bearing founder" in result["error"]:
        raise HTTPException(status_code=400, detail=result["error"])
    await broadcast_ws_event({"type": "autonomy_cycle", "data": result})
    return result


@app.post("/api/autonomy/watch", tags=["Autonomy"])
async def autonomy_watch(org_id: str = Query(DEFAULT_ORG_ID),
                         project_id: str = Query(...)):
    """Put a project under continuous watch."""
    autonomy_scheduler.watch(org_id, project_id)
    return autonomy_scheduler.status()


@app.get("/api/agents")
async def list_registered_agents(
    org_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    caste: Optional[str] = Query(None),
    role: Optional[str] = Query(None)
):
    """The registry's list of versioned, registered agents."""
    params = {"org_id": org_id or DEFAULT_ORG_ID}
    if project_id: params["project_id"] = project_id
    if caste: params["caste"] = caste
    if role: params["role"] = role

    res = await _registry_call("GET", "/agents", params=params)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.get("/api/agents/{agent_id}")
async def get_registered_agent_detail(agent_id: str, org_id: Optional[str] = Query(None)):
    """Proxies Agent Registry microservice to fetch full agent details and immutable version history.

    The realm is named explicitly. The registry stores each organisation in its
    own PostgreSQL schema, so a lookup that does not say which one is a lookup
    in whichever realm the service happens to default to — and it silently 404s
    for agents that exist somewhere else.
    """
    res = await _registry_call("GET", f"/agents/{agent_id}",
                               params={"org_id": org_id or DEFAULT_ORG_ID})
    if res.status_code == 404:
        raise HTTPException(status_code=404,
                            detail=f"Agent '{agent_id}' not found in realm "
                                   f"'{org_id or DEFAULT_ORG_ID}'.")
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.get("/api/agents/{agent_id}/progeny")
async def get_agent_progeny_tree(agent_id: str):
    """The lineage tree this agent spawned.

    An unreachable registry is not an agent with no descendants — the empty
    tree this used to return is a claim about lineage that was never checked.
    """
    res = await _registry_call("GET", f"/agents/{agent_id}/progeny")
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.get("/api/agents/{agent_id}/kagent-manifest")
async def get_kagent_crd_manifest(agent_id: str):
    """The Kubernetes KAgent CRD manifest the registry generates for this agent."""
    res = await _registry_call("GET", f"/agents/{agent_id}/kagent-manifest")
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.post("/api/agents/verify")
async def verify_agent_signature(payload: Dict[str, Any]):
    """ED25519 signature verification, by the registry that holds the key.

    The previous fallback answered `verified: true` when the registry could not
    be reached, describing it as "offline verification". Nothing was verified.
    A signature check that cannot run must fail loudly — an unchecked signature
    reported as valid is the one failure mode this whole mechanism exists to
    prevent.
    """
    res = await _registry_call("POST", "/agents/verify", json_body=payload)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.post("/api/agents/{agent_id}/audit")
async def audit_agent(agent_id: str, payload: Dict[str, Any]):
    """Record an oversight audit and let it move the reputation score."""
    res = await _registry_call("POST", f"/agents/{agent_id}/audit", json_body=payload)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.post("/api/agents/{agent_id}/allocate-tokens")
async def allocate_agent_tokens(agent_id: str, payload: Dict[str, Any]):
    """Allocate compute tokens. An allocation that did not happen is an error."""
    res = await _registry_call("POST", f"/agents/{agent_id}/allocate-tokens",
                               json_body=payload)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

class EnhancedPlaygroundChatRequest(BaseModel):
    org_id: str = Field(default="org_london_meta")
    project_id: str = Field(default="proj_alpha_civilization")
    prompt: str
    mode: Optional[str] = Field("workflow", description="'solitary' or 'workflow' / 'conductor'")
    agent_id: Optional[str] = None
    model_name: Optional[str] = DEFAULT_LLM_MODEL
    session_id: Optional[str] = None

@app.post("/api/playground/chat")
async def playground_chat(req: EnhancedPlaygroundChatRequest):
    """Playground execution, returning a trace of what actually ran.

    `steps` describes work that happened, and only that. The client used to
    invent its own — a `KAGENT_EXECUTION` at "64ms" and a `VERIFICATION_AUDIT`
    at "28ms", both marked success, appended after every turn including failed
    ones (F.13). Anything the interface shows has to come from here, so here is
    where it has to be true.

    Every step carries a real `started_at` and `ended_at`; nothing carries a
    latency this endpoint did not measure (F.14).
    """
    started = datetime.now(timezone.utc)

    def step(name: str, detail: str, status: str, begin, agent=None, tool=None):
        finished = datetime.now(timezone.utc)
        return {
            "name": name, "detail": detail, "status": status,
            "agent": agent, "tool": tool,
            "started_at": begin.isoformat(), "ended_at": finished.isoformat(),
            "duration_ms": int((finished - begin).total_seconds() * 1000),
        }

    if req.mode == "solitary" and req.agent_id:
        target_agent_id = req.agent_id
        solitary_prompt = (
            f"You are the solitary agent '{target_agent_id}' in project '{req.project_id}' of the agent.london civilization.\n"
            f"User Prompt: {req.prompt}\n\n"
            f"Execute this request strictly as '{target_agent_id}'. Provide a complete, thorough, authoritative response in Markdown."
        )
        try:
            answer = await generate_dynamic_task_document(solitary_prompt, req.project_id, req.org_id)
            steps = [step("AGENT_DISPATCH",
                          f"Called '{target_agent_id}' with model '{req.model_name}'.",
                          "succeeded", started, agent=target_agent_id)]
        except Exception as e:
            logger.exception("solitary playground turn failed")
            steps = [step("AGENT_DISPATCH",
                          f"Call to '{target_agent_id}' failed: {e}",
                          "failed", started, agent=target_agent_id)]
            raise HTTPException(status_code=502,
                                detail=f"Agent execution failed: {e}") from e

        res = {
            "mode": "solitary",
            "agent_id": target_agent_id,
            "model": req.model_name,
            "prompt": req.prompt,
            "answer": answer,
            "final_answer": answer,
            "status": "succeeded",
            "steps": steps,
            "execution_summary": f"Executed solitary agent interaction with '{target_agent_id}' using model '{req.model_name}'.",
        }
        await broadcast_ws_event({"type": "solitary_chat_completed", "data": res})
        return res

    # Multi-agent workflow. The conductor builds and registers a real pipeline;
    # its nodes are the steps, so they are reported rather than re-imagined.
    try:
        res = await civilization_engine.run_conductor_orchestration(
            req.org_id, req.project_id, req.prompt)
    except Exception as e:
        logger.exception("conductor orchestration failed")
        raise HTTPException(status_code=502,
                            detail=f"Orchestration failed: {e}") from e

    res["mode"] = "workflow"
    res.setdefault("status", "succeeded")
    if not res.get("steps"):
        finished = datetime.now(timezone.utc)
        res["steps"] = [{
            "name": "CONDUCTOR_ORCHESTRATION",
            "detail": (f"source={res.get('execution_source')} "
                       f"pipeline={res.get('registered_pipeline_id') or res.get('reused_pipeline_id')}"),
            "status": res.get("status", "succeeded"),
            "agent": res.get("conductor_id"),
            "tool": None,
            "started_at": started.isoformat(),
            "ended_at": finished.isoformat(),
            "duration_ms": int((finished - started).total_seconds() * 1000),
        }]
        for task in (res.get("sub_tasks_orchestrated") or []):
            if isinstance(task, dict):
                res["steps"].append({
                    "name": task.get("name") or task.get("id") or "SUB_TASK",
                    "detail": task.get("assigned_task", ""),
                    "status": task.get("status", "succeeded"),
                    "agent": task.get("agent_id"),
                    "tool": None,
                    "started_at": None, "ended_at": None, "duration_ms": None,
                })
    await broadcast_ws_event({"type": "workflow_completed", "data": res})
    return res


class AgentInteractRequest(BaseModel):
    org_id: str = Field(default="org_london_meta")
    project_id: str = Field(default="proj_alpha_civilization")
    prompt: str
    session_id: Optional[str] = None
    isolation_mode: str = Field(default="isolated", description="'isolated' scopes to this project, 'shared' spans all projects in the org")

@app.post("/api/agent/interact")
async def agent_interact(req: AgentInteractRequest):
    """Uses LLM Intent Router to evaluate user prompt and dynamically dispatch execution:
    SIMPLE_CHAT, RAG_QUERY, MULTI_AGENT_ORCHESTRATION, REACT_TOOL_LOOP, or MULTI_TURN_CONVERSATION.
    """
    res = await civilization_engine.process_user_prompt_with_llm(
        org_id=req.org_id,
        project_id=req.project_id,
        user_prompt=req.prompt,
        session_id=req.session_id,
        isolation_mode=req.isolation_mode
    )
    res["isolation_mode"] = req.isolation_mode
    return res

@app.post("/api/agent/interact-multimodal")
async def agent_interact_multimodal(
    file: UploadFile = File(...),
    org_id: str = Query("org_london_meta"),
    project_id: str = Query("proj_alpha_civilization"),
    prompt: str = Query(""),
    session_id: Optional[str] = Query(None),
    isolation_mode: str = Query("isolated", description="'isolated' or 'shared'")
):
    """Accepts an image or video file, uses gemma-4-31B-it vision model to infer content,
    then feeds the inference into the automated pipeline orchestration flow."""
    file_bytes = await file.read()
    filename = file.filename or "uploaded_media"

    # Step 1: Vision inference via gemma-4-31B-it
    vision_description = await civilization_engine.infer_multimodal(file_bytes, filename, prompt)

    # Step 2: Combine vision inference with user prompt and route through pipeline
    combined_prompt = f"{prompt}\n\n[Vision Analysis of {filename}]:\n{vision_description}" if prompt else vision_description
    res = await civilization_engine.process_user_prompt_with_llm(
        org_id=org_id,
        project_id=project_id,
        user_prompt=combined_prompt,
        session_id=session_id,
        isolation_mode=isolation_mode
    )
    res["vision_inference"] = vision_description
    res["source_file"] = filename
    return res

class ConductorRequest(BaseModel):
    org_id: str = Field(default="org_london_meta")
    project_id: str = Field(default="proj_alpha_civilization")
    prompt: str

class ReactRequest(BaseModel):
    org_id: str = Field(default="org_london_meta")
    project_id: str = Field(default="proj_alpha_civilization")
    prompt: str

@app.post("/api/conductor/orchestrate")
async def conductor_orchestrate(req: ConductorRequest):
    res = await civilization_engine.run_conductor_orchestration(req.org_id, req.project_id, req.prompt)
    return res

@app.post("/api/react/execute")
async def react_execute(req: ReactRequest):
    res = await civilization_engine.run_react_loop(req.org_id, req.project_id, req.prompt)
    return res

class DiscoveryRequest(BaseModel):
    org_id: str = Field(default="org_london_meta")
    project_id: str = Field(default="proj_alpha_civilization")
    query: str

# The archetypes discovery searches when the registry has nothing to offer.
# This was a fourth hand-written copy of the roster, with its own model
# assignments and its own drift: it advertised agents the running engine never
# created, and models the router stopped serving. It is derived now, so an
# archetype cannot describe an agent that no project would contain.
PRIME_AGENTS = [
    {
        "id_prefix": member["founder_id"],
        "name": member["name"],
        "caste": member["caste"],
        "cog_func": member["cog_func"],
        "topo": member["topo"],
        "telos": member["telos"],
        "pubkey": f"ed25519:{member['founder_id'].replace('-', '_')}",
        "tokens": int(member["token_balance"]),
        "rep": member["reputation_score"],
        "assignedModel": DEFAULT_LLM_MODEL,
        "keywords": member["keywords"],
        "autonomous": member["autonomous"],
    }
    for member in founder_roster("archetype")
]

async def _registry_discover_agents(org_id: str, project_id: str, query: str,
                                    top_k: int = 6) -> List[Dict[str, Any]]:
    """Vector discovery over the agents that are actually registered (AG §10).

    The tiers below this one search `PRIME_AGENTS` — a seed list of archetypes
    that exists in this process. That answers "which archetype fits" and cannot
    answer "which registered agent can I call", because an archetype has no
    published version to pin or invoke. The registry can, so it is asked first.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{AGENT_REGISTRY_URL.rstrip('/')}/discover",
                params={"q": query, "kind": "agent", "org_id": org_id,
                        "project_id": project_id, "top_k": top_k})
    except Exception as e:
        logger.warning("agent registry discovery unavailable (%s); "
                       "falling back to the archetype index", e)
        return []
    if res.status_code != 200:
        logger.warning("agent registry discovery returned %s", res.status_code)
        return []

    found = []
    for row in res.json().get("results", []):
        found.append({
            "agent_id": row.get("id"),
            "id": row.get("id"),
            "name": row.get("name"),
            "slug": row.get("slug"),
            "telos": row.get("telos"),
            "description": row.get("description"),
            "capabilities": row.get("capabilities", []),
            # What a caller needs to pin and invoke it (AG §4.3).
            "version": row.get("version"),
            "content_hash": row.get("content_hash"),
            "mcp_tool": f"agent:{row.get('slug')}@{row.get('version')}",
            "match_distance": row.get("distance"),
            "registered": True,
        })
    return found


@app.post("/api/agents/discover")
async def discover_rag_agents(req: DiscoveryRequest):
    """Finds agents for a natural-language need, most authoritative source first.

    1. the agent registry's vector index over **registered, published** agents;
    2. post-graph-rag over the archetype seed list;
    3. keyword matching.

    Each tier names itself in `source`, because what a caller can do with the
    answer differs: only the first returns agents with a version and a hash
    that can be pinned into a pipeline.
    """
    project_id = req.project_id

    registered = await _registry_discover_agents(req.org_id, project_id, req.query)
    if registered:
        return {
            "project_id": project_id,
            "query": req.query,
            "source": "agent-registry",
            "discovered_agents": registered,
        }

    # Try RAG vector search first
    rag_results = await _rag_discover_agents(req.org_id, project_id, req.query, PRIME_AGENTS)
    if rag_results:
        return {
            "project_id": project_id,
            "query": req.query,
            "source": "post-graph-rag",
            "discovered_agents": rag_results
        }

    # Fallback to keyword matching
    keyword_results = _keyword_discover_agents(req.query, project_id, PRIME_AGENTS)
    return {
        "project_id": project_id,
        "query": req.query,
        "source": "keyword_fallback",
        "discovered_agents": keyword_results
    }
@app.post("/api/conductor/compose")
async def compose_dag_pipeline(req: DiscoveryRequest):
    """Turn one natural-language goal into a published, runnable pipeline.

    This is the path the end-to-end suite proves and the interface could not
    reach (F.50): the model decomposes the goal, RAG finds a registered agent
    for each stage, the stages are composed into a pipeline and **published**
    by the agent registry — validated, cycle-checked, and pinned to exact
    versions (F.51).

    It replaces a handler that returned four hardcoded DAG nodes with invented
    latencies and `status: success`, composing and running nothing at all.

    The work itself lives in `_compose_pipeline`, because the playground stream
    needs the same composition with progress reported as it happens. Two copies
    of a composition would eventually compose two different pipelines.
    """
    return await _compose_pipeline(req.org_id, req.project_id, req.query)


async def _compose_pipeline(org_id: str, project_id: str, goal: str,
                            emit=None) -> Dict[str, Any]:
    """Decompose a goal, resolve each stage to a published agent, publish it.

    `emit(event, payload)` is an optional async callback, called as each part
    actually completes. It is how the playground shows the composition being
    made rather than presenting it finished — the events are emitted at the
    moment the thing they describe happens, not replayed afterwards.
    """
    async def report(event: str, payload: Dict[str, Any]) -> None:
        if emit:
            await emit(event, payload)

    stages = await _decompose_goal(goal)
    if len(stages) < 2:
        raise HTTPException(
            status_code=422,
            detail=("The goal could not be broken into stages. Try describing "
                    "the work as a sequence."))
    await report("decomposed", {"stages": stages, "count": len(stages)})

    # RAG over the agent graph, one need at a time (AG §10).
    resolved, unmatched = [], []
    seen_steps = set()
    for stage in stages:
        await report("matching", {"step": stage["step"], "need": stage["need"]})
        found = await _registry_discover_agents(org_id, project_id,
                                                stage["need"], top_k=1)
        if not found:
            unmatched.append(stage)
            await report("unmatched", {"step": stage["step"], "need": stage["need"]})
            continue
        step = stage["step"]
        # Step identity is the step, not the agent (AG §3.4) — the same agent
        # may legitimately serve two stages, but two steps cannot share a name.
        while step in seen_steps:
            step = f"{step}_2"
        seen_steps.add(step)
        agent = found[0]
        resolved.append({"step": step, "need": stage["need"], "agent": agent})
        await report("matched", {
            "step": step, "need": stage["need"],
            "agent_id": agent["agent_id"], "agent_name": agent.get("name"),
            "agent_slug": agent.get("slug"), "version": agent.get("version"),
            "content_hash": agent.get("content_hash"),
            "match_distance": agent.get("match_distance"),
        })

    if len(resolved) < 2:
        raise HTTPException(
            status_code=409,
            detail=(f"Only {len(resolved)} of {len(stages)} stages matched a "
                    f"registered agent, which is not enough to compose a "
                    f"pipeline. Register agents for: "
                    f"{'; '.join(s['need'] for s in unmatched)}"))

    text_in = {"type": "object",
               "properties": {"prompt": {"type": "string",
                                         "description": "The task for this agent"}},
               "required": ["prompt"]}
    text_out = {"type": "object",
                "properties": {"result": {"type": "string",
                                          "description": "The agent's answer"}}}

    suffix = uuid.uuid4().hex[:8]
    pipeline_id = f"pln_composed_{suffix}"
    slug = f"composed-{suffix}"
    body = {
        "org_id": org_id, "project_id": project_id,
        "identity": {"pipeline_id": pipeline_id, "name": f"Composed {suffix}",
                     "slug": slug, "telos": goal, "description": goal},
        "version": {
            "pipeline_id": pipeline_id, "version": "1.0.0",
            "steps": {s["step"]: {
                "version_id": f"agv_{s['agent']['agent_id']}_{s['agent']['version']}",
                "alias": s["agent"].get("slug")} for s in resolved},
            # Each edge maps one step's declared output to the next step's
            # declared input. The registry checks that against both schemas at
            # publish time, so a chain that could not pass data is rejected
            # before it can run and produce a plausible wrong answer.
            "dependencies": [
                {"from_step": resolved[i]["step"], "to_step": resolved[i + 1]["step"],
                 "relationship": "depends_on",
                 "payload_map": {"result": "prompt"}}
                for i in range(len(resolved) - 1)],
            "entry_steps": [resolved[0]["step"]],
            "exit_steps": [resolved[-1]["step"]],
            "input_schema": text_in, "output_schema": text_out,
            "execution": {"max_iterations": 20, "concurrency": 1,
                          "on_limit": "halt_and_return"},
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            res = await client.post(f"{AGENT_REGISTRY_URL.rstrip('/')}/pipelines",
                                    json=body)
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Agent registry unreachable: {e}") from e
    if res.status_code != 200:
        # A rejected composition is reported as rejected, with the registry's
        # own reason — it names the rule that refused it.
        raise HTTPException(status_code=res.status_code,
                            detail=f"The registry refused this pipeline: {res.text[:400]}")
    registration = res.json()

    composed = {
        "org_id": org_id,
        "project_id": project_id,
        "goal": goal,
        "pipeline_id": pipeline_id,
        "slug": slug,
        "version": registration.get("version", "1.0.0"),
        "mcp_tool": f"pipeline:{slug}@{registration.get('version', '1.0.0')}",
        "is_cyclic": registration.get("is_cyclic", False),
        # The stages, so the interface can show what was decided and why (F.50).
        "stages": [{
            "step": s["step"],
            "need": s["need"],
            "agent_id": s["agent"]["agent_id"],
            "agent_name": s["agent"].get("name"),
            "agent_slug": s["agent"].get("slug"),
            # The resolved pin — what will actually run (F.51).
            "version": s["agent"].get("version"),
            "content_hash": s["agent"].get("content_hash"),
            "match_distance": s["agent"].get("match_distance"),
        } for s in resolved],
        "unmatched_stages": unmatched,
        "resolved_steps": registration.get("resolved_steps", {}),
        "status": "published",
    }
    await report("published", composed)
    return composed


# --------------------------------------------------------- playground stream

class PlaygroundStreamRequest(BaseModel):
    org_id: str = Field(default=DEFAULT_ORG_ID)
    project_id: str
    prompt: str
    # A single published agent, invoked directly, instead of a composition.
    agent: Optional[str] = Field(
        default=None, description="agent:{slug}@{version} to run alone")


async def _published_tool_ids(org_id: str,
                              project_id: Optional[str] = None) -> Optional[List[str]]:
    """Which tools this realm actually has, or None if the registry is unreachable.

    None means "do not filter": a founder told about no tools at all would
    refuse everything, which is a worse failure than a prompt that overstates
    the toolbelt by one entry.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{TOOL_REGISTRY_URL.rstrip('/')}/tools",
                                   params={"org_id": org_id,
                                           "project_id": project_id})
        if res.status_code != 200:
            return None
        return [tool["tool_id"] for tool in res.json().get("tools", [])
                if tool.get("tool_id")]
    except Exception as e:
        logger.warning("could not read the toolbelt for %s/%s: %s",
                       org_id, project_id, e)
        return None


async def _intake_decision(org_id: str, project_id: str, prompt: str) -> Dict[str, Any]:
    """What the Intake Praetor decides to do with this prompt.

    The founder's own registered system prompt, so the decision the playground
    shows is the decision the platform makes — not a second router written for
    the demo that could disagree with the real one.

    The realm's actual toolbelt is passed in, so the Praetor is told what this
    deployment can do rather than what a founder would like to hold. Without
    it, a request to search the web was refused as "not granted to this realm"
    in deployments that had search — the Praetor was reasoning about a fixed
    tool list rather than a real one.
    """
    system = founder_prompt("intake-praetor", await _published_tool_ids(org_id,
                                                                        project_id)) or ""
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            res = await client.post(
                f"{OPENAI_API_BASE.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={"model": DEFAULT_LLM_MODEL, "temperature": 0.0,
                      "max_tokens": 900,
                      "response_format": {"type": "json_object"},
                      "messages": [
                          {"role": "system", "content": system},
                          {"role": "user", "content":
                              f"Project: {project_id} | Organisation: {org_id}\n\n"
                              f"Request: {prompt}\n\n"
                              "Respond with your JSON object only."}]})
        if res.status_code != 200:
            raise RuntimeError(f"model router returned {res.status_code}")
        decision = json.loads(res.json()["choices"][0]["message"]["content"])
    except Exception as e:
        logger.warning("intake could not be reached for the playground: %s", e)
        # Labelled, not silently defaulted: everything downstream inherits this.
        return {"route": "PIPELINE", "confidence": "low",
                "reasoning": f"The Intake Praetor could not be reached ({e}); "
                             f"this was composed as a pipeline without its "
                             f"judgement."}
    return decision


async def _invoke_agent(org_id: str, project_id: str, mcp_tool: str,
                        prompt: str) -> Dict[str, Any]:
    """Run one published agent version by its MCP name, and return what it said."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        res = await client.post(
            f"{AGENT_REGISTRY_URL.rstrip('/')}/mcp/call",
            json={"tool_name": mcp_tool, "arguments": {"prompt": prompt},
                  "org_id": org_id, "project_id": project_id})
    if res.status_code != 200:
        raise RuntimeError(f"{mcp_tool} returned {res.status_code}: {res.text[:300]}")
    body = res.json()
    text = ""
    for part in body.get("content") or []:
        if part.get("type") == "text":
            text += part.get("text") or ""
    return {"text": text, "isError": bool(body.get("isError")),
            "usage": body.get("usage") or {}}


@app.post("/api/playground/stream", tags=["Playground"])
async def playground_stream(req: PlaygroundStreamRequest):
    """The whole journey from a prompt to an answer, streamed as it happens.

    Server-sent events, one per thing that actually occurred:

      accepted    the request was received
      intake      the Intake Praetor's route, reasoning and confidence
      decomposed  the stages the planner produced
      matching    a stage being looked up in the registry
      matched     the agent it resolved to, with its version and content hash
      unmatched   a stage with no registered agent — named, never dropped
      published   the pipeline, pinned and validated by the registry
      step_start  an agent about to run, with the input it was handed
      step_end    what that agent actually returned, and how long it took
      step_error  a stage that failed, with the real reason
      complete    the final answer and the total elapsed time
      error       the run could not continue, and why

    The stages are executed one at a time rather than by calling the published
    pipeline in a single shot. Both run the same pinned versions in the same
    order with the same payload map; the difference is that this way each
    agent's real output is available the moment it arrives, which is the point
    of watching a pipeline work. Nothing here is simulated: there is no typing
    animation, no invented reasoning trace, and no step that reports a result
    it did not receive.
    """
    queue: asyncio.Queue = asyncio.Queue()
    started = datetime.now(timezone.utc)

    async def emit(event: str, payload: Dict[str, Any]) -> None:
        await queue.put((event, payload))

    async def work() -> None:
        try:
            await emit("accepted", {"prompt": req.prompt, "project_id": req.project_id,
                                    "org_id": req.org_id,
                                    "at": started.isoformat()})

            # One published agent, run directly. Still a real invocation of a
            # real pinned version — just without a composition around it.
            if req.agent:
                await emit("step_start", {"step": "single", "index": 0, "total": 1,
                                          "agent": req.agent, "input": req.prompt})
                begin = datetime.now(timezone.utc)
                out = await _invoke_agent(req.org_id, req.project_id, req.agent,
                                          req.prompt)
                ms = int((datetime.now(timezone.utc) - begin).total_seconds() * 1000)
                await emit("step_end", {"step": "single", "index": 0,
                                        "agent": req.agent, "output": out["text"],
                                        "duration_ms": ms, "usage": out["usage"],
                                        "failed": out["isError"]})
                await emit("complete", {
                    "answer": out["text"], "failed": out["isError"],
                    "duration_ms": int((datetime.now(timezone.utc) - started)
                                       .total_seconds() * 1000)})
                return

            decision = await _intake_decision(req.org_id, req.project_id, req.prompt)
            await emit("intake", decision)

            route = str(decision.get("route", "PIPELINE")).upper()
            if route == "REFUSE":
                await emit("complete", {
                    "answer": decision.get("refusal_reason")
                              or "This request was refused at intake.",
                    "refused": True, "failed": False,
                    "duration_ms": int((datetime.now(timezone.utc) - started)
                                       .total_seconds() * 1000)})
                return
            if route == "SIMPLE_CHAT" and decision.get("answer"):
                # The Praetor already answered it. Composing a pipeline for a
                # greeting would be theatre, and would cost real tokens.
                await emit("complete", {
                    "answer": decision["answer"], "failed": False,
                    "direct": True,
                    "duration_ms": int((datetime.now(timezone.utc) - started)
                                       .total_seconds() * 1000)})
                return

            composed = await _compose_pipeline(req.org_id, req.project_id,
                                               req.prompt, emit=emit)

            # Execute the published stages in dependency order, feeding each
            # one the previous stage's output — the payload map the pipeline
            # declares and the registry validated.
            stages = composed["stages"]
            carried = req.prompt
            outputs = []
            for index, stage in enumerate(stages):
                mcp_tool = f"agent:{stage['agent_slug']}@{stage['version']}"
                await emit("step_start", {
                    "step": stage["step"], "index": index, "total": len(stages),
                    "need": stage["need"], "agent": mcp_tool,
                    "agent_name": stage["agent_name"],
                    "version": stage["version"],
                    "content_hash": stage["content_hash"],
                    "input": carried})
                begin = datetime.now(timezone.utc)
                try:
                    out = await _invoke_agent(req.org_id, req.project_id,
                                              mcp_tool, carried)
                except Exception as e:
                    ms = int((datetime.now(timezone.utc) - begin).total_seconds() * 1000)
                    await emit("step_error", {
                        "step": stage["step"], "index": index, "agent": mcp_tool,
                        "error": str(e), "duration_ms": ms})
                    # A halted pipeline is not a pipeline that produced a
                    # shorter answer. It stops, and says where.
                    await emit("complete", {
                        "answer": None, "failed": True,
                        "halted_at": stage["step"], "reason": str(e),
                        "duration_ms": int((datetime.now(timezone.utc) - started)
                                           .total_seconds() * 1000)})
                    return
                ms = int((datetime.now(timezone.utc) - begin).total_seconds() * 1000)
                outputs.append(out["text"])
                await emit("step_end", {
                    "step": stage["step"], "index": index, "agent": mcp_tool,
                    "agent_name": stage["agent_name"],
                    "output": out["text"], "duration_ms": ms,
                    "usage": out["usage"], "failed": out["isError"]})
                if out["isError"]:
                    await emit("complete", {
                        "answer": None, "failed": True,
                        "halted_at": stage["step"],
                        "reason": out["text"][:500],
                        "duration_ms": int((datetime.now(timezone.utc) - started)
                                           .total_seconds() * 1000)})
                    return
                carried = out["text"]

            await emit("complete", {
                "answer": outputs[-1] if outputs else None,
                "failed": False,
                "pipeline_id": composed["pipeline_id"],
                "mcp_tool": composed["mcp_tool"],
                "stages_run": len(outputs),
                "duration_ms": int((datetime.now(timezone.utc) - started)
                                   .total_seconds() * 1000)})

        except HTTPException as e:
            await emit("error", {"status": e.status_code, "detail": e.detail})
        except Exception as e:
            logger.exception("playground stream failed")
            await emit("error", {"status": 500, "detail": str(e)})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(work())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    # A comment line keeps the connection open through proxies
                    # while a slow agent is still thinking.
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                event, payload = item
                yield f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 # nginx and friends buffer streamed responses by default,
                 # which turns a live trace into one delivery at the end.
                 "X-Accel-Buffering": "no"})


DECOMPOSE_SYSTEM = """\
You break a goal into an ordered list of independent processing stages.

Reply with ONLY a JSON array of objects, no prose and no code fences. Each
object has:
  "step": a short snake_case identifier
  "need": one sentence describing the CAPABILITY required, written as a
          description of what a worker does — not as an instruction

Produce between 2 and 4 stages. Order them so each stage consumes the previous
stage's output.
"""


async def _decompose_goal(goal: str) -> List[Dict[str, str]]:
    """Ask the model to break one goal into ordered capability needs.

    Models wrap JSON in fences and prose even when told not to, so the first
    well-formed array wins rather than the whole reply being required to parse.
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        res = await client.post(
            f"{OPENAI_API_BASE.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": DEFAULT_LLM_MODEL, "temperature": 0.0, "max_tokens": 400,
                  "messages": [{"role": "system", "content": DECOMPOSE_SYSTEM},
                               {"role": "user", "content": goal}]})
    if res.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"The planner model returned {res.status_code}.")

    text = res.json()["choices"][0]["message"]["content"].strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise HTTPException(status_code=502,
                            detail="The planner did not return a usable plan.")
    try:
        raw = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502,
                            detail=f"The planner's plan did not parse: {e}") from e

    stages = []
    for index, stage in enumerate(raw):
        if not isinstance(stage, dict):
            continue
        step = re.sub(r"[^a-z0-9_]+", "_",
                      str(stage.get("step") or f"stage_{index}").lower()).strip("_")
        need = str(stage.get("need") or "").strip()
        if need:
            stages.append({"step": step or f"stage_{index}", "need": need})
    return stages


class VerifySignaturePayload(BaseModel):
    agent_id: str
    public_key: str
    signature: str
    payload_text: str

@app.post("/api/civilization/verify")
async def verify_civilization_agent(req: VerifySignaturePayload):
    """Signature verification, by the registry that holds the key.

    This used to answer `verified: true` with a `computed_digest` of
    "verified_digest" whenever the registry could not be reached — a hardcoded
    string standing in for a check that never ran. An unverifiable signature
    reported as valid is the single failure this mechanism exists to prevent.
    """
    res = await _registry_call("POST", "/agents/verify",
                               json_body=req.model_dump())
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:400])
    return res.json()

@app.post("/api/sessions")
async def initiate_session(req: InitiateSessionRequest):
    res = await civilization_engine.initiate_session(
        org_id=req.org_id,
        project_id=req.project_id,
        user_id=req.user_id,
        session_name=req.session_name
    )
    await broadcast_ws_event({
        "type": "session_initiated",
        "data": res
    })
    return res

@app.post("/api/tasks/enqueue")
def enqueue_task(req: EnqueueTaskRequest):
    task_id = redis_bus.enqueue_task(req.agent_id, {
        "org_id": req.org_id,
        "project_id": req.project_id,
        "agent_id": req.agent_id,
        "task_description": req.task_description,
        "parameters": req.parameters
    }, project_id=req.project_id)

    redis_bus.publish_event(req.org_id, req.project_id, {
        "event": "task_enqueued",
        "agent_id": req.agent_id,
        "task_id": task_id,
        "description": req.task_description
    })

    return {"status": "enqueued", "task_id": task_id, "agent_id": req.agent_id, "project_id": req.project_id}

@app.post("/api/tasks/dequeue/{agent_id}")
def dequeue_task(agent_id: str, project_id: Optional[str] = Query(None)):
    proj = project_id or "proj_alpha_civilization"
    task = redis_bus.dequeue_task(agent_id, project_id=proj)
    if not task:
        return {"status": "empty", "task": None}
    return {"status": "dequeued", "task": task}

@app.get("/api/events/{org_id}/{project_id}")
def get_civilization_events(org_id: str, project_id: str, limit: int = Query(50)):
    events = redis_bus.get_recent_events(org_id, project_id, limit=limit)
    return {"events": events, "count": len(events)}

# =========================================================================
# AGENT IMMUTABLE VERSION CONTROL & DATA TABLE RETRIEVAL ENDPOINTS
# =========================================================================
@app.get("/api/projects/{project_id}/agents/{agent_id}/versions")
async def get_agent_version_history(project_id: str, agent_id: str):
    """Retrieves all immutable append-only version records for an agent in post-graph."""
    records = await civilization_engine.get_agent_version_history(project_id, agent_id)
    return {"project_id": project_id, "agent_id": agent_id, "versions_count": len(records), "versions": records}

@app.get("/api/projects/{project_id}/agents/{agent_id}/versions/latest")
async def get_latest_agent_version(project_id: str, agent_id: str):
    """Retrieves the latest immutable data record (version) for an agent."""
    record = await civilization_engine.get_latest_agent_version(project_id, agent_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No version records found for agent '{agent_id}' in project '{project_id}'")
    return {"project_id": project_id, "agent_id": agent_id, "latest_version": record}

@app.get("/api/projects/{project_id}/agents/{agent_id}/versions/{version_id}")
async def get_agent_version_by_id(project_id: str, agent_id: str, version_id: str):
    """Queries a specific data entry by its sequential data_id (version number)."""
    record = await civilization_engine.get_agent_version_by_id(project_id, version_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Version data_id '{version_id}' not found in project '{project_id}'")
    return {"project_id": project_id, "agent_id": agent_id, "version_id": version_id, "version": record}

# =========================================================================
# REAL GLOBAL & PROJECT EXECUTION TELEMETRY (NO FAKE / PLACEHOLDER DATA)
# =========================================================================
@app.get("/api/metrics/global")
async def get_global_real_metrics():
    """Returns real global execution telemetry metrics across all orgs, users, and projects."""
    telemetry = get_real_telemetry()
    return {
        "global": True,
        "total_agent_instances": len(PRIME_AGENTS),
        "total_agent_executions": telemetry["total_executions"],
        "unique_user_engagements": telemetry["unique_user_engagements"],
        "bytes_in": telemetry["bytes_in"],
        "bytes_out": telemetry["bytes_out"],
        "tokens_in": telemetry["tokens_in"],
        "tokens_out": telemetry["tokens_out"]
    }

@app.get("/api/metrics/project/{project_id}")
async def get_project_real_metrics(project_id: str):
    """Returns real project-specific civilization metrics and telemetry."""
    telemetry = get_real_telemetry(project_id=project_id)
    return {
        "project_id": project_id,
        "active_agents": len(PRIME_AGENTS),
        "total_agent_executions": telemetry["executions"],
        "unique_user_engagements": telemetry["unique_user_engagements"],
        "bytes_in": telemetry["bytes_in"],
        "bytes_out": telemetry["bytes_out"],
        "tokens_in": telemetry["tokens_in"],
        "tokens_out": telemetry["tokens_out"]
    }

@app.get("/api/metrics/agent/{agent_id}")
async def get_agent_real_metrics(agent_id: str):
    """Returns real agent-specific execution telemetry (bytes in/out, tokens in/out)."""
    return get_real_telemetry(agent_id=agent_id)

# =========================================================================
# MCP & A2A PROJECT API KEY ACCESS PROTOCOL (XXXX-XXXX-XXXX-XXXX)
# =========================================================================

@app.get("/api/projects/{project_id}/key")
async def get_project_api_key(project_id: str):
    """Retrieves the randomly generated 16-character project API key for MCP and A2A access directly from post-graph database."""
    try:
        from backend.civilization import get_project_api_key_from_pg
    except Exception:
        from civilization import get_project_api_key_from_pg

    key = await get_project_api_key_from_pg(project_id)

    return {
        "project_id": project_id,
        "api_key": key,
        "format": "XXXX-XXXX-XXXX-XXXX",
        "persistence": "post-graph"
    }

@app.post("/api/projects/{project_id}/key/regenerate")
async def regenerate_project_api_key(project_id: str):
    """Regenerates a brand new random 16-character project API key for MCP and A2A access and persists in post-graph database."""
    try:
        from backend.civilization import generate_project_api_key, save_project_api_key_to_pg
    except Exception:
        from civilization import generate_project_api_key, save_project_api_key_to_pg

    new_key = generate_project_api_key()
    await save_project_api_key_to_pg(project_id, new_key)

    return {
        "project_id": project_id,
        "api_key": new_key,
        "format": "XXXX-XXXX-XXXX-XXXX",
        "status": "regenerated",
        "persistence": "post-graph"
    }

class MCPCallRequest(BaseModel):
    project_id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    org_id: str = DEFAULT_ORG_ID
    # Recorded on the usage event the tool registry writes (tool-registry-spec
    # Rule 11.3): without it the ledger says an organisation spent something and
    # cannot say on what.
    caller: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None

def _require_project_key(api_key, authorization):
    """The project API key, or a 401/400 naming what is wrong with it."""
    provided = api_key or (authorization.replace("Bearer ", "").strip()
                           if authorization else None)
    if not provided:
        raise HTTPException(
            status_code=401,
            detail="Missing Project API Key header. Set 'Authorization: Bearer "
                   "XXXX-XXXX-XXXX-XXXX' or 'X-Project-API-Key'")
    if not re.match(r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', provided):
        raise HTTPException(
            status_code=400,
            detail="Invalid API Key format. Must be 16 uppercase alphanumeric "
                   "digits with hyphens (e.g. XXXX-XXXX-XXXX-XXXX)")
    return provided


@app.get("/api/mcp/v1/tools")
async def list_mcp_agent_tools(
    project_id: str = Query("proj_alpha_civilization"),
    org_id: str = Query(DEFAULT_ORG_ID),
    api_key: Optional[str] = Header(None, alias="X-Project-API-Key"),
):
    """Every MCP tool this project can actually call.

    Aggregated from the two registries that own them: published agent and
    pipeline versions from the agent registry (AG Rule 7.4), and MCP tools from
    the tool registry. Nothing is listed that is not callable.

    This endpoint previously returned a hardcoded list of six tools that
    existed nowhere else in the system — four invented agents, a search tool
    and a RAG tool — so a client could discover a tool, call it, and receive a
    fabricated answer from the handler below.

    A registry that cannot be reached is **reported**, not silently omitted: a
    short list that looks complete is worse than a list that says what is
    missing.
    """
    tools: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, str]] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(f"{AGENT_REGISTRY_URL.rstrip('/')}/mcp/tools",
                                   params={"org_id": org_id, "project_id": project_id})
            if res.status_code == 200:
                for tool in res.json().get("tools", []):
                    tools.append({**tool, "registry": "agent-registry"})
            else:
                unavailable.append({"registry": "agent-registry",
                                    "reason": f"HTTP {res.status_code}"})
        except Exception as e:
            unavailable.append({"registry": "agent-registry",
                                "reason": f"{type(e).__name__}: {e}"})

        try:
            res = await client.get(f"{TOOL_REGISTRY_URL.rstrip('/')}/tools",
                                   params={"org_id": org_id, "project_id": project_id})
            if res.status_code == 200:
                for tool in res.json().get("tools", []):
                    tools.append({
                        "name": tool["tool_id"],
                        "description": tool.get("description", ""),
                        "inputSchema": tool.get("input_schema",
                                                {"type": "object", "properties": {}}),
                        "registry": "tool-registry",
                        "side_effects": tool.get("side_effects"),
                        "pin": tool.get("pin"),
                    })
            else:
                unavailable.append({"registry": "tool-registry",
                                    "reason": f"HTTP {res.status_code}"})
        except Exception as e:
            unavailable.append({"registry": "tool-registry",
                                "reason": f"{type(e).__name__}: {e}"})

    body = {"mcp_version": "1.0", "org_id": org_id, "project_id": project_id,
            "tools": tools, "count": len(tools)}
    if unavailable:
        body["unavailable"] = unavailable
        body["warning"] = ("Part of the catalogue could not be read; this list "
                           "is incomplete.")
    return body


@app.post("/api/mcp/v1/tools/call")
async def call_mcp_agent_tool(
    req: MCPCallRequest,
    api_key: Optional[str] = Header(None, alias="X-Project-API-Key"),
    authorization: Optional[str] = Header(None),
):
    """Invoke a tool, an agent version or a pipeline version. Restricted by API key.

    Routed by name to the registry that owns it — `agent:` and `pipeline:`
    names to the agent registry, anything else to the tool registry as a
    `tool_id`.

    **Every failure is reported.** This handler used to answer `status:
    success` for any name it did not recognise, with an invented
    `agent_response`, a fabricated `ed25519:` signature and a made-up `28ms`
    latency; and when the search tool was unreachable it returned an invented
    search result with a `google.com/search` link presented as a retrieved
    finding. An agent cannot tell fabricated evidence from real evidence, so
    this layer must never produce any.
    """
    _require_project_key(api_key, authorization)

    name = req.tool_name
    async with httpx.AsyncClient(timeout=180.0) as client:
        if name.startswith("agent:") or name.startswith("pipeline:"):
            try:
                res = await client.post(
                    f"{AGENT_REGISTRY_URL.rstrip('/')}/mcp/tools/{name}/call",
                    json={"arguments": req.arguments, "org_id": req.org_id,
                          "project_id": req.project_id})
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Agent registry unreachable: {e}") from e
            if res.status_code != 200:
                raise HTTPException(status_code=res.status_code, detail=res.text[:500])
            return {"mcp_version": "1.0", "project_id": req.project_id,
                    "tool": name, **res.json()}

        # Anything else is a tool_id in the tool registry. Legacy underscored
        # aliases are accepted so existing callers keep working.
        tool_id = {"mcp_google_search": "mcp-google-search",
                   "agent_google_search": "mcp-google-search",
                   "mcp_document_rag_query": "mcp-pgvector-search",
                   "mcp_pgvector_search": "mcp-pgvector-search",
                   "mcp_sql_query": "mcp-sql-query",
                   "mcp_redis_queue": "mcp-redis-queue"}.get(name, name)

        payload = {"arguments": req.arguments, "org_id": req.org_id,
                   "project_id": req.project_id, "caller": req.caller}
        if req.idempotency_key:
            payload["idempotency_key"] = req.idempotency_key
        try:
            res = await client.post(
                f"{TOOL_REGISTRY_URL.rstrip('/')}/tools/{tool_id}/call", json=payload)
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Tool registry unreachable: {e}") from e
        if res.status_code != 200:
            raise HTTPException(status_code=res.status_code, detail=res.text[:500])
        return {"mcp_version": "1.0", "project_id": req.project_id,
                "tool": tool_id, **res.json()}


class A2ADispatchRequest(BaseModel):
    project_id: str
    sender_agent_id: str
    target_agent_id: str
    payload: Dict[str, Any]
    signature: Optional[str] = None
    # The realm the target lives in. A registry keeps each organisation in its
    # own schema, so a delivery that does not name one looks in the wrong
    # place and reports the target as unregistered.
    org_id: str = DEFAULT_ORG_ID

@app.post("/api/a2a/v1/dispatch")
async def dispatch_a2a_agent_message(
    req: A2ADispatchRequest,
    api_key: Optional[str] = Header(None, alias="X-Project-API-Key"),
    authorization: Optional[str] = Header(None),
):
    """Deliver an A2A message to the target agent, and return what it answered.

    The message is really delivered: the target agent id is resolved to its
    published slug and version in the agent registry, and the payload is
    submitted as an A2A task.

    This endpoint used to publish a Redis event and then return `status:
    delivered` with a fabricated `ed25519:` acknowledgement and a sentence
    saying the goal had been "processed successfully" — without ever contacting
    the target. A sender had no way to tell that from a real delivery.
    """
    _require_project_key(api_key, authorization)
    org_id = getattr(req, "org_id", None) or DEFAULT_ORG_ID

    async with httpx.AsyncClient(timeout=180.0) as client:
        # Resolve the target to the slug and version its A2A card is published
        # under. An agent that is not published has no card and cannot receive
        # a task (AG Rule 7.4).
        try:
            found = await client.get(
                f"{AGENT_REGISTRY_URL.rstrip('/')}/agents/{req.target_agent_id}",
                params={"org_id": org_id, "project_id": req.project_id})
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"Agent registry unreachable: {e}") from e
        if found.status_code != 200:
            raise HTTPException(
                status_code=404,
                detail=f"Target agent '{req.target_agent_id}' is not registered "
                       f"in org '{org_id}'.")

        agent = found.json().get("agent", {})
        slug, version = agent.get("slug"), agent.get("version")
        if not slug or not version:
            raise HTTPException(
                status_code=409,
                detail=f"Target agent '{req.target_agent_id}' has no published "
                       f"version, so it has no A2A card to deliver to.")

        try:
            res = await client.post(
                f"{AGENT_REGISTRY_URL.rstrip('/')}/a2a/agents/{slug}/{version}/tasks",
                json={"arguments": req.payload, "org_id": org_id,
                      "project_id": req.project_id})
        except Exception as e:
            raise HTTPException(status_code=502,
                                detail=f"A2A delivery failed: {e}") from e
        if res.status_code != 200:
            raise HTTPException(status_code=res.status_code, detail=res.text[:500])
        task = res.json()

    # The event stream is a record of what happened, published after the fact
    # rather than in place of it.
    redis_bus.publish_event("org_global", req.project_id, {
        "event": "a2a_message_dispatched",
        "sender": req.sender_agent_id,
        "target": req.target_agent_id,
        "state": task.get("state"),
        "payload": req.payload,
    })

    return {
        "protocol": "A2A_DIRECT_v1",
        "project_id": req.project_id,
        "sender": req.sender_agent_id,
        "target": req.target_agent_id,
        "target_card": f"/a2a/agents/{slug}/{version}/card",
        # The target's real state. A halted run surfaces as `failed` with a
        # halt_reason and is never reported as completion (AG §11.5).
        "state": task.get("state"),
        "status": "delivered" if task.get("state") == "completed" else task.get("state"),
        "halt_reason": task.get("halt_reason"),
        "response": task,
    }


# =========================================================================
# DOCUMENT REGISTRY & POST-GRAPH-RAG SPACE ENDPOINTS
# =========================================================================

# User & Org Scoped Project Registry (in-memory cache, synced with post-graph on create)
PROJECTS_REGISTRY: Dict[str, List[Dict[str, Any]]] = {}

@app.get("/api/orgs/{org_id}/users/{user_id}/projects")
async def list_user_org_projects(org_id: str, user_id: str):
    """Returns project universes for the specified org_id and user_id, querying post-graph with in-memory fallback."""
    # Try post-graph via civilization engine
    try:
        pg_projects = await civilization_engine.get_user_projects(org_id, user_id)
        if pg_projects:
            return {"org_id": org_id, "user_id": user_id, "projects": pg_projects}
    except Exception as _e:
        logger.warning("%s: recoverable Exception in list_user_org_projects, continuing", type(_e).__name__, exc_info=_e)

    # In-memory cache fallback
    key = f"{org_id}:{user_id}"
    user_projects = PROJECTS_REGISTRY.get(key, [])

    if not user_projects:
        default_proj = {
            "id": f"proj_{org_id.replace('org_', '')}_default",
            "name": f"{org_id.replace('org_', '').replace('_', ' ').title()} Primary Universe",
            "org_id": org_id,
            "owner_user_id": user_id,
            "agentsCount": len(PRIME_AGENTS),
            "status": "ACTIVE"
        }
        user_projects = [default_proj]
        PROJECTS_REGISTRY[key] = user_projects

    return {
        "org_id": org_id,
        "user_id": user_id,
        "projects": user_projects
    }

@app.post("/api/orgs/{org_id}/users/{user_id}/projects")
async def create_user_org_project(org_id: str, user_id: str, name: str = Query(...)):
    """Creates a new project universe, persisting to post-graph via civilization engine."""
    clean_id = f"proj_{name.lower().replace(' ', '_').replace('-', '_')}"
    # Persist via civilization engine (writes to post-graph)
    try:
        result = await civilization_engine.create_project(
            org_id=org_id, user_id=user_id,
            project_name=name.strip(),
            constitution_rules=["No unauthorized data mutations", "All outputs must be verifiable"]
        )
        new_proj = {
            "id": result.get("project_id", clean_id),
            "name": name.strip(),
            "org_id": org_id,
            "owner_user_id": user_id,
            "agentsCount": result.get("prime_agents_count", len(PRIME_AGENTS)),
            "status": "ACTIVE"
        }
    except Exception:
        new_proj = {
            "id": clean_id,
            "name": name.strip(),
            "org_id": org_id,
            "owner_user_id": user_id,
            "agentsCount": 1,
            "status": "ACTIVE"
        }

    key = f"{org_id}:{user_id}"
    if key not in PROJECTS_REGISTRY:
        PROJECTS_REGISTRY[key] = []
    PROJECTS_REGISTRY[key].append(new_proj)
    return {"status": "success", "project": new_proj}

DOCUMENT_REGISTRY_URL = os.getenv("DOCUMENT_REGISTRY_URL", "http://document-registry-service.default.svc.cluster.local:8003")

@app.post("/api/projects/{project_id}/spaces")
async def create_document_space(project_id: str, space_name: str = Query(...),
                                description: Optional[str] = None,
                                org_id: str = Query(DEFAULT_ORG_ID)):
    """Creates a new document space for a project using post-graph space sub-grouping."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(
                f"{DOCUMENT_REGISTRY_URL}/spaces",
                json={"org_id": org_id, "project_id": project_id,
                      "document_space": space_name, "space_name": space_name,
                      "description": description}
            )
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        logger.warning(f"Error calling document-registry service: {e}")

    return {
        "key": f"{project_id}:{space_name}",
        "project_id": project_id,
        "space_name": space_name,
        "description": description or "Document space",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "document_count": 0
    }

@app.get("/api/projects/{project_id}/spaces")
async def list_document_spaces(project_id: str, org_id: str = Query(DEFAULT_ORG_ID)):
    """Lists all document spaces belonging to a project."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{DOCUMENT_REGISTRY_URL}/projects/{project_id}/spaces",
                                   params={"org_id": org_id})
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        logger.warning(f"Error calling document-registry service: {e}")

    return {
        "project_id": project_id,
        "spaces": [
            {
                "key": f"{project_id}:default",
                "project_id": project_id,
                "space_name": "default",
                "description": "Default workspace document repository",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "document_count": 0
            }
        ]
    }

@app.get("/api/projects/{project_id}/documents")
async def list_project_documents(project_id: str, space_name: Optional[str] = None,
                                 org_id: str = Query(DEFAULT_ORG_ID)):
    """Lists all uploaded documents stored persistently in post-graph documents_catalog."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{DOCUMENT_REGISTRY_URL}/projects/{project_id}/documents"
            params = {"org_id": org_id}
            if space_name:
                params["document_space"] = space_name
            res = await client.get(url, params=params)
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        logger.warning(f"Error calling document-registry documents list: {e}")

    return {"project_id": project_id, "space_name": space_name, "documents": [], "count": 0}

@app.post("/api/projects/{project_id}/spaces/{space_name}/documents/upload-text")
async def upload_document_text(project_id: str, space_name: str,
                               document_name: str = Query(...),
                               content: str = Query(...),
                               org_id: str = Query(DEFAULT_ORG_ID)):
    """Index text into a document space, and report what really happened.

    The registry distinguishes indexed from catalogued-but-not-indexed
    (document-registry-spec Rule 6.2), and its answer is passed through
    unchanged. This proxy used to answer `status: success` whenever the
    registry was unreachable, claiming an ingest that never occurred.
    """
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{DOCUMENT_REGISTRY_URL}/spaces/{space_name}/documents/upload-text",
                json={
                    "org_id": org_id,
                    "project_id": project_id,
                    "document_space": space_name,
                    "space_name": space_name,
                    "document_name": document_name,
                    "content": content
                }
            )
    except Exception as e:
        logger.warning(f"Error calling document-registry: {e}")
        raise HTTPException(
            status_code=502,
            detail=(f"The document registry at {DOCUMENT_REGISTRY_URL} could not "
                    f"be reached, so nothing was indexed. Reporting success here "
                    f"would claim a corpus change that did not happen.")) from e
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:500])
    return res.json()

@app.post("/api/projects/{project_id}/spaces/{space_name}/documents/upload-file")
async def upload_document_file(project_id: str, space_name: str,
                               file: UploadFile = File(...),
                               org_id: str = Query(DEFAULT_ORG_ID)):
    """Uploads a PDF, DOCX, or text file, extracts content via Docling/PyPDF, and indexes into target space."""
    file_bytes = await file.read()
    filename = file.filename or "uploaded_document"
    files = {"file": (filename, file_bytes, file.content_type or "application/octet-stream")}
    data = {"project_id": project_id, "org_id": org_id,
            "document_space": space_name}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            res = await client.post(
                f"{DOCUMENT_REGISTRY_URL}/spaces/{space_name}/documents/upload-file",
                data=data,
                files=files
            )
    except Exception as e:
        logger.warning(f"Error calling document-registry file upload: {e}")
        raise HTTPException(
            status_code=502,
            detail=(f"The document registry at {DOCUMENT_REGISTRY_URL} could not "
                    f"be reached, so nothing was uploaded. Reporting success here "
                    f"would claim a corpus change that did not happen.")) from e
    # 415 means no parser could read the file, and the registry stored nothing
    # (Rule 5.3). That is the caller's answer, not something to smooth over.
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:500])
    return res.json()

@app.post("/api/projects/{project_id}/spaces/{space_name}/documents/upload-multiple-files")
async def upload_multiple_document_files(project_id: str, space_name: str,
                                        files: List[UploadFile] = File(...),
                                        org_id: str = Query(DEFAULT_ORG_ID)):
    """Uploads multiple files (PDF, DOCX, PPTX, XLSX, TXT), extracts content via Docling/PyPDF, and indexes all into target space."""
    file_list = []
    for f in files:
        f_bytes = await f.read()
        f_name = f.filename or "uploaded_doc"
        file_list.append(("files", (f_name, f_bytes, f.content_type or "application/octet-stream")))
    data = {"project_id": project_id, "org_id": org_id,
            "document_space": space_name}
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            res = await client.post(
                f"{DOCUMENT_REGISTRY_URL}/spaces/{space_name}/documents/upload-multiple-files",
                data=data,
                files=file_list
            )
    except Exception as e:
        logger.warning(f"Error calling document-registry batch upload: {e}")
        raise HTTPException(
            status_code=502,
            detail=(f"The document registry at {DOCUMENT_REGISTRY_URL} could not "
                    f"be reached, so nothing was uploaded. Reporting success here "
                    f"would claim a corpus change that did not happen.")) from e
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:500])
    # The registry reports per-file outcomes and separate counts (Rule 5.5);
    # collapsing them to one number is how a partial batch reads as complete.
    return res.json()

@app.get("/api/projects/{project_id}/rag/graph")
async def get_rag_graph(project_id: str, query: str = Query(...),
                        space_name: Optional[str] = None,
                        depth: int = Query(1),
                        org_id: str = Query(DEFAULT_ORG_ID)):
    """Returns a focused subgraph from post-graph-rag centered on a search query.
    Use depth=1 for immediate connections, increase to expand the neighborhood."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                f"{DOCUMENT_REGISTRY_URL}/query",
                json={"org_id": org_id, "project_id": project_id, "query": query,
                      "document_space": space_name, "space_name": space_name,
                      "top_k": depth * 5, "mode": "local"}
            )
            if res.status_code == 200:
                data = res.json().get("data", {})
                return {
                    "project_id": project_id,
                    "query": query,
                    "nodes": [
                        {"id": e.get("entity_name", f"entity_{i}"), "type": e.get("entity_type", "unknown"), "description": e.get("description", "")}
                        for i, e in enumerate(data.get("entities", []))
                    ],
                    "edges": [
                        {"source": r.get("src_id", ""), "target": r.get("tgt_id", ""), "type": r.get("relation_type", ""), "description": r.get("description", ""), "weight": r.get("weight", 1)}
                        for r in data.get("relationships", [])
                    ],
                    "chunks": [
                        {"id": c.get("chunk_id", f"chunk_{i}"), "content": c.get("content", "")[:300], "metadata": c.get("metadata", {})}
                        for i, c in enumerate(data.get("chunks", []))
                    ]
                }
    except Exception as e:
        logger.warning(f"Error fetching RAG graph: {e}")
    return {"project_id": project_id, "query": query, "nodes": [], "edges": [], "chunks": []}

@app.post("/api/projects/{project_id}/rag/query")
async def query_document_rag(project_id: str, query: str = Query(...),
                             space_name: Optional[str] = None,
                             org_id: str = Query(DEFAULT_ORG_ID)):
    """GraphRAG retrieval, scoped to a document space or project-wide.

    The registry's own answer is returned, including whether it had to degrade
    (Rule 8.2). An empty result used to be manufactured here with
    `status: success` whenever the registry was unreachable — which an agent
    reads as "the corpus has nothing to say", not "nobody asked it".
    """
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{DOCUMENT_REGISTRY_URL}/query",
                json={"org_id": org_id, "project_id": project_id, "query": query,
                      "document_space": space_name, "space_name": space_name}
            )
    except Exception as e:
        logger.warning(f"Error calling document-registry query: {e}")
        raise HTTPException(
            status_code=502,
            detail=(f"The document registry at {DOCUMENT_REGISTRY_URL} could not "
                    f"be reached. An empty result would read as an empty corpus.")
        ) from e
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=res.text[:500])
    return res.json()

@app.websocket("/ws/civilization")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ACTIVE_CONNECTIONS.append(websocket)
    logger.info("WebSocket client connected to civilization stream.")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"type": "ack", "message": "connected", "received": data}))
    except WebSocketDisconnect:
        ACTIVE_CONNECTIONS.remove(websocket)
        logger.info("WebSocket client disconnected.")

async def broadcast_ws_event(event_dict: Dict[str, Any]):
    message = json.dumps(event_dict)
    for conn in ACTIVE_CONNECTIONS:
        try:
            await conn.send_text(message)
        except Exception as _e:
            logger.warning("%s: recoverable Exception in broadcast_ws_event, continuing", type(_e).__name__, exc_info=_e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
