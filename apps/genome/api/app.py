"""genome api — user-facing reads and the owner channel.

interface-spec.md Rule 1.1: this service is the USER-FACING path. It may read
any world (genome-spec.md Rule 13.2) and must NOT import GenomeStore, whose
fail-closed scoping exists for the simulation path. The two paths have opposite
rules and therefore separate modules.

Phase 0 skeleton: health, client lifecycle, agents-realm bootstrap. Surfaces
grow with their phases (BUILD.md).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from post_graph import AsyncPostGraph

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "core"))
from genome_core import store  # ensure_agents_realm only; NOT GenomeStore
import contacts
import snapshot
import auth as auth_mod
import genesis
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1] / 'core'))
from genome_core import notify

logger = logging.getLogger(__name__)

POSTGRES_USER = os.getenv("POSTGRES_USER", "")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres-service")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")
DB_URI = os.getenv(
    "POSTGRES_URI",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")


def make_client() -> AsyncPostGraph:
    """SCHEMA_PER_REALM is deliberately NOT passed (user decision, recorded in
    genome_core/store.py): the environment and post-graph's default decide."""
    return AsyncPostGraph(dsn=DB_URI)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = make_client()
    await client.connect()
    app.state.pg = client
    await store.ensure_agents_realm(client)
    logger.info("agents realm ensured")
    try:
        yield
    finally:
        await client.close()


app = FastAPI(title="genome api", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("GENOME_WEB_BASE", "http://localhost:5173")],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "genome-api"}


@app.get("/worlds/{realm}/snapshot", tags=["World"])
async def get_snapshot(realm: str):
    """Any world, read-only (genome-spec Rule 13.2). Observation confers
    nothing on agents (Rule 13.3) — this path serves humans only."""
    return await snapshot.world_snapshot(app.state.pg, realm)


@app.get("/auth/{provider}/login", tags=["Auth"])
async def auth_login(provider: str):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(auth_mod.login_url(provider, state="genome"))


@app.get("/auth/{provider}/callback", tags=["Auth"])
async def auth_callback(provider: str, code: str):
    from fastapi.responses import RedirectResponse
    info = auth_mod.exchange_code(provider, code)
    uid = auth_mod.user_id_from(provider, info)
    result = await genesis.ensure_user_world(app.state.pg, uid,
                                             email=info.get("email"))
    await genesis.mark_verified(app.state.pg, uid)   # the provider attests
    web = os.getenv("GENOME_WEB_BASE", "http://localhost:5173")
    resp = RedirectResponse(f"{web}/?world={result['world_realm']}")
    resp.set_cookie("genome_session", auth_mod.session_cookie(uid),
                    httponly=True, samesite="lax")
    return resp


@app.post("/auth/email/login", tags=["Auth"])
async def email_login(payload: dict):
    """Direct entry (Rule 6.2i): the session opens at once so the demo stays
    frictionless, but it opens UNVERIFIED; a magic link goes to the outbox
    and only following it proves the address is really held."""
    from fastapi.responses import JSONResponse
    email = (payload.get("email") or "").strip()
    if "@" not in email:
        return JSONResponse({"error": "email required"}, status_code=400)
    uid = auth_mod.user_id_from_email(email)
    result = await genesis.ensure_user_world(app.state.pg, uid, email=email)
    link = (f"{auth_mod.REDIRECT_BASE}/auth/email/verify"
            f"?token={auth_mod.magic_token(uid)}")
    await notify.outbox(app.state.pg, email, "Verify your genome sign-in",
                        f"Follow this link to verify your address: {link}\n"
                        f"It works for one day.")
    verified = await genesis.is_verified(app.state.pg, uid)
    resp = JSONResponse({"ok": True, "world_realm": result["world_realm"],
                         "verified": verified})
    resp.set_cookie("genome_session", auth_mod.session_cookie(uid),
                    httponly=True, samesite="lax")
    return resp


@app.get("/auth/email/verify", tags=["Auth"])
async def email_verify(token: str):
    from fastapi.responses import RedirectResponse, JSONResponse
    uid = auth_mod.verify_magic(token)
    if not uid:
        return JSONResponse({"error": "link invalid or expired"},
                            status_code=400)
    await genesis.mark_verified(app.state.pg, uid)
    web = os.getenv("GENOME_WEB_BASE", "http://localhost:5173")
    resp = RedirectResponse(f"{web}/?verified=1")
    resp.set_cookie("genome_session", auth_mod.session_cookie(uid),
                    httponly=True, samesite="lax")
    return resp


def _uid(request) -> str | None:
    return auth_mod.verify_cookie(request.cookies.get("genome_session", ""))


@app.post("/invites", tags=["Social"])
async def invite(payload: dict, request: __import__("fastapi").Request):
    """Rule 6.2j: world created eagerly, login link mailed, portals linked,
    both sides notified."""
    from fastapi.responses import JSONResponse
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    email = (payload.get("email") or "").strip()
    if "@" not in email:
        return JSONResponse({"error": "email required"}, status_code=400)
    result = await genesis.invite_user(app.state.pg, uid, email)
    return result


@app.get("/notifications", tags=["Social"])
async def notifications(request: __import__("fastapi").Request):
    uid = _uid(request)
    if not uid:
        return []
    return await notify.feed(app.state.pg, uid)


@app.post("/notifications/read", tags=["Social"])
async def notifications_read(payload: dict,
                             request: __import__("fastapi").Request):
    uid = _uid(request)
    if not uid:
        return {"read": 0}
    return {"read": await notify.mark_read(app.state.pg, uid,
                                           payload.get("keys", []))}


@app.get("/me/prefs", tags=["Social"])
async def get_prefs(request: __import__("fastapi").Request):
    from genome_core.notify import DEFAULT_PREFS
    uid = _uid(request)
    if not uid:
        return {"prefs": DEFAULT_PREFS}
    rows = await app.state.pg.find_vertices(
        "agents", realm="genome_agents",
        filters={"key": f"user:{uid}"}, limit=1)
    prefs = (rows[0].payload.get("notification_prefs")
             if rows else None) or DEFAULT_PREFS
    return {"prefs": {**DEFAULT_PREFS, **prefs}}


@app.put("/me/prefs", tags=["Social"])
async def set_prefs(payload: dict, request: __import__("fastapi").Request):
    uid = _uid(request)
    if not uid:
        return {"ok": False}
    rows = await app.state.pg.find_vertices(
        "agents", realm="genome_agents",
        filters={"key": f"user:{uid}"}, limit=1)
    if rows:
        await app.state.pg.upsert_vertex(
            "agents", realm="genome_agents", vertex_id=int(rows[0].id),
            payload={**rows[0].payload,
                     "notification_prefs": payload.get("prefs", {})})
    return {"ok": True}


@app.get("/contacts/import/{provider}/start", tags=["Social"])
async def contacts_start(provider: str, request: __import__("fastapi").Request):
    uid = _uid(request)
    if not uid or provider not in contacts.CONTACT_SCOPES:
        return {"error": "login first"}
    state = auth_mod.session_cookie(uid)       # HMAC-signed; verified on return
    return __import__("fastapi").responses.RedirectResponse(
        contacts.import_url(provider, state))


@app.get("/contacts/import/{provider}/callback", tags=["Social"])
async def contacts_callback(provider: str, code: str, state: str):
    uid = auth_mod.verify_cookie(state)
    if not uid:
        return {"error": "bad state"}
    result = await contacts.run_import(app.state.pg, uid, provider, code)
    dest = os.getenv("GENOME_WEB_BASE", "http://localhost:5173")
    return __import__("fastapi").responses.RedirectResponse(
        f"{dest}/?imported={result['proposed']}&matched={result['matched']}")


@app.get("/proposals", tags=["Social"])
async def proposals(request: __import__("fastapi").Request):
    uid = _uid(request)
    if not uid:
        return {"incoming": [], "outgoing": []}
    return await contacts.list_proposals(app.state.pg, uid)


@app.post("/proposals/respond", tags=["Social"])
async def proposals_respond(payload: dict,
                            request: __import__("fastapi").Request):
    uid = _uid(request)
    if not uid:
        return {"error": "login first"}
    return await contacts.respond(app.state.pg, uid,
                                  payload.get("key", ""),
                                  bool(payload.get("accept")))


@app.post("/worlds/{realm}/sites", tags=["World"])
async def found_site(realm: str, payload: dict,
                     request: __import__("fastapi").Request):
    """Break ground (construction-spec §3): the world's OWNER founds a site;
    everyone may contribute to it."""
    from fastapi.responses import JSONResponse
    from genome_core import construction, drain
    from genome_core.store import GenomeStore
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    meta = await drain._world_payload(GenomeStore(app.state.pg), realm)
    if meta.get("is_commons"):
        return JSONResponse({"error": "the commons builds nothing from the "
                             "tree; agents may raise caches there"},
                            status_code=403)
    if meta.get("owner_user_id") != uid:
        return JSONResponse({"error": "only the owner breaks ground"},
                            status_code=403)
    name = (payload.get("name") or "").lower()
    x = float(payload.get("x", 0.5)); y = float(payload.get("y", 0.5))
    return await construction.found_site(app.state.pg, realm, uid, name,
                                         x, y, meta.get("kinds", []))


@app.get("/me", tags=["Auth"])
async def me(request: __import__("fastapi").Request):
    uid = auth_mod.verify_cookie(
        request.cookies.get("genome_session", ""))
    if not uid:
        return {"authenticated": False}
    realm = await genesis.user_world_realm(app.state.pg, uid)
    return {"authenticated": True, "user": uid, "world_realm": realm,
            "verified": await genesis.is_verified(app.state.pg, uid)}


@app.get("/agents/{agent_uuid}", tags=["Agent"])
async def get_agent(agent_uuid: str):
    """Any agent, anywhere (genome-spec Rule 13.1): genotype AND expression."""
    return await snapshot.agent_inspect(app.state.pg, agent_uuid)


@app.get("/agents/{agent_uuid}/decisions", tags=["Agent"])
async def get_agent_decisions(agent_uuid: str, limit: int = 20):
    return await snapshot.agent_decisions(app.state.pg, agent_uuid, limit)


@app.get("/worlds/{realm}/events", tags=["World"])
async def get_events(realm: str, since: str = ""):
    return await snapshot.world_events(app.state.pg, realm, since)
