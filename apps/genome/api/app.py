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
    return AsyncPostGraph(dsn=DB_URI, pool_min_size=1, pool_max_size=5,
                          statement_cache_size=0)  # pgbouncer transaction mode


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = make_client()
    await client.connect()
    app.state.pg = client
    try:
        await store.ensure_agents_realm(client)
        logger.info("agents realm ensured")
    except Exception:
        # concurrent CREATE TABLE with a worker races the pg catalog
        # ("tuple concurrently updated"); the tables exist -- carry on
        logger.exception("ensure raced; continuing")
    try:
        yield
    finally:
        await client.close()


app = FastAPI(title="genome api", lifespan=lifespan)

# Behind the GCE ingress the API lives at /genome-api/* and GCE never
# rewrites paths; strip the prefix here so routes stay clean everywhere.
_PREFIX = os.getenv("GENOME_PATH_PREFIX", "").rstrip("/")
if _PREFIX:
    class _StripPrefix:
        def __init__(self, app_):
            self.app = app_

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and                     scope["path"].startswith(_PREFIX):
                scope = dict(scope)
                scope["path"] = scope["path"][len(_PREFIX):] or "/"
                scope["root_path"] = _PREFIX
            await self.app(scope, receive, send)

    app.add_middleware(_StripPrefix)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[__import__("urllib.parse", fromlist=["urlparse"])
                   .urlparse(os.getenv("GENOME_WEB_BASE",
                                       "http://localhost:5173"))
                   ._replace(path="", query="", fragment="").geturl()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "genome-api"}


# Telemetry (user directive): everything measurable lands in Prometheus and
# is scraped by the cluster's telemetry stack (marty infra/telemetry).
from genome_core import metrics as _metrics


@app.middleware("http")
async def _count_requests(request, call_next):
    response = await call_next(request)
    if not request.url.path.endswith(("/metrics", "/health")):
        _metrics.HTTP.labels(request.method, str(response.status_code)).inc()
    return response


@app.get("/metrics", tags=["System"], include_in_schema=False)
async def metrics_endpoint():
    from fastapi.responses import Response
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except Exception:
        return Response("", media_type="text/plain")


# ---------------------------------------------------------------------------
# Live streams (interface-spec 2.2: events on the wire, not frames). One
# refresher task per realm serves EVERY viewer -- N tabs cost one snapshot
# assembly. The task starts with the first subscriber and dies with the
# last; the poll endpoint below remains as the client's fallback.
# ---------------------------------------------------------------------------
import asyncio as _aio
import json as _json

_streams: dict = {}


def _stream_state(realm: str):
    st = _streams.get(realm)
    if st is None:
        st = _streams[realm] = {"subs": 0, "data": None,
                                "cond": _aio.Condition(), "task": None}
    return st


async def _refresher(realm: str):
    st = _stream_state(realm)
    try:
        while st["subs"] > 0:
            try:
                snap = await snapshot.world_snapshot(app.state.pg, realm)
                st["data"] = _json.dumps(snap)
                st["at"] = __import__("time").time()
            except Exception:
                logger.exception("stream refresh failed for %s", realm)
            async with st["cond"]:
                st["cond"].notify_all()
            await _aio.sleep(2.0)
    finally:
        st["task"] = None


@app.get("/worlds/{realm}/stream", tags=["World"])
async def world_stream(realm: str):
    from fastapi.responses import StreamingResponse
    st = _stream_state(realm)

    async def gen():
        st["subs"] += 1
        _metrics.SSE_VIEWERS.inc()
        if st["task"] is None:
            st["task"] = _aio.create_task(_refresher(realm))
        try:
            last = None
            if st["data"]:
                last = st["data"]
                yield f"data: {last}\n\n"   # instant first paint
            while True:
                try:
                    async with st["cond"]:
                        await _aio.wait_for(st["cond"].wait(), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if st["data"] and st["data"] is not last:
                    last = st["data"]
                    yield f"data: {last}\n\n"
        finally:
            st["subs"] -= 1
            _metrics.SSE_VIEWERS.dec()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/worlds/{realm}/world-chat", tags=["World"])
async def world_chat_read(realm: str, limit: int = 60):
    """The world's open chat: readable by anyone (Rule 13.2)."""
    rows = await app.state.pg.find_vertices("world_chats", realm=realm,
                                            order_by="at", descending=True,
                                            limit=min(limit, 200))
    return list(reversed([r.payload for r in rows]))


@app.post("/worlds/{realm}/world-chat", tags=["World"])
async def world_chat_post(realm: str, payload: dict,
                          request: __import__("fastapi").Request):
    """The world's OWNER speaks to the whole world (user directive
    2026-09-05): a question becomes an open ASK any present agent may
    claim; a plain message joins the conversation."""
    from fastapi.responses import JSONResponse
    import time as _t
    import uuid as _u
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    meta_rows = await app.state.pg.find_vertices("world_meta", realm=realm,
                                                 filters={"key": realm},
                                                 limit=1)
    if not meta_rows:
        return JSONResponse({"error": "no such world"}, status_code=404)
    if meta_rows[0].payload.get("owner_user_id") != uid \
            and not _admin_ok(request):
        return JSONResponse({"error": "only this world's owner speaks "
                                      "here"}, status_code=403)
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    kind = "ask" if payload.get("ask", True) else "say"
    key = f"wc-{_u.uuid4().hex[:12]}"
    row = {"key": key, "thread": payload.get("thread") or key,
           "from": f"user:{uid}", "name": "the owner",
           "kind": kind, "text": text[:1000], "at": _t.time()}
    if kind == "ask":
        row["claimed_by"] = None
    await app.state.pg.add_vertex("world_chats", realm=realm,
                                  space="default", payload=row)
    return {"ok": True, "key": key, "kind": kind}


@app.post("/worlds/{realm}/world-chat/upload", tags=["World"])
async def world_chat_upload(realm: str,
                            request: __import__("fastapi").Request,
                            file: __import__("fastapi").UploadFile =
                            __import__("fastapi").File(...)):
    """A document posted into the world's chat becomes WORLD KNOWLEDGE
    (user directive 2026-09-05): catalogued and indexed in the document
    registry under this world's own project, where agents can retrieve it
    -- but only while they stand in this world."""
    from fastapi.responses import JSONResponse
    import json as _json
    import time as _t
    import urllib.request as _u
    import uuid as _uu
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    meta_rows = await app.state.pg.find_vertices("world_meta", realm=realm,
                                                 filters={"key": realm},
                                                 limit=1)
    if not meta_rows:
        return JSONResponse({"error": "no such world"}, status_code=404)
    if meta_rows[0].payload.get("owner_user_id") != uid \
            and not _admin_ok(request):
        return JSONResponse({"error": "only this world's owner may add to "
                                      "its knowledge"}, status_code=403)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        return JSONResponse({"error": "20MB limit for world knowledge"},
                            status_code=413)
    filename = file.filename or "document"
    boundary = _uu.uuid4().hex
    parts = []
    for k, v in (("project_id", realm), ("org_id", "genome_worlds"),
                 ("document_space", "knowledge")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; '
                     f'name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
         f'filename="{filename}"\r\nContent-Type: '
         f'{file.content_type or "application/octet-stream"}\r\n\r\n'
         ).encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    rq = _u.Request(
        os.getenv("DOCREG_URL",
                  "http://document-registry-service.default.svc."
                  "cluster.local:8003")
        + "/spaces/knowledge/documents/upload-file",
        data=b"".join(parts),
        headers={"Content-Type":
                 f"multipart/form-data; boundary={boundary}",
                 "x-internal-token":
                 os.getenv("DOCREG_INTERNAL_TOKEN", "")})
    try:
        out = _json.loads(_u.urlopen(rq, timeout=300).read())
    except Exception as e:
        return JSONResponse(
            {"error": f"the registry refused the document: "
                      f"{type(e).__name__}"}, status_code=502)
    now = _t.time()
    await app.state.pg.add_vertex("world_chats", realm=realm,
        space="default", payload={
            "key": f"wc-{_uu.uuid4().hex[:12]}",
            "thread": f"wc-{_uu.uuid4().hex[:12]}",
            "from": f"user:{uid}", "name": "the owner",
            "kind": "document", "text": f"\U0001F4C4 {filename} -- "
            + ("indexed into this world's knowledge"
               if out.get("indexed") else
               f"catalogued but not indexed: "
               f"{(out.get('message') or '')[:160]}"),
            "filename": filename, "indexed": bool(out.get("indexed")),
            "at": now})
    return {"ok": True, "indexed": bool(out.get("indexed")),
            "registry": out.get("message")}


@app.get("/worlds/{realm}/snapshot", tags=["World"])
async def get_snapshot(realm: str):
    """Any world, read-only (genome-spec Rule 13.2). Observation confers
    nothing on agents (Rule 13.3) — this path serves humans only.

    When the SSE refresher is already rebuilding this realm every two
    seconds for stream watchers, the poll serves ITS copy instead of
    building a second one: same data the stream just sent, at zero cost."""
    st = _streams.get(realm)
    # while a refresher runs, its copy is exactly as fresh as the stream --
    # the poll cannot be staler than what watchers are already seeing
    if st and st.get("data") and st.get("task") is not None:
        from fastapi.responses import Response
        return Response(content=st["data"], media_type="application/json")
    return await snapshot.world_snapshot(app.state.pg, realm)


# Two ways in, both through the platform authority (Google and Microsoft).
# The legacy in-app OIDC exchange and the unverified email/magic-link door
# are gone (user directive 2026-09-05): one front door, verified only.


@app.get("/me/replies", tags=["Auth"])
async def my_replies(request: __import__("fastapi").Request, limit: int = 20):
    """The owner's message inbox: every reply the user's agents have sent
    back on their chats (user directive 2026-09-05: a ready answer should
    reach the user against a chat icon in the top bar), newest first."""
    from fastapi.responses import JSONResponse
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    mine = await app.state.pg.find_vertices(
        "agents", realm="genome_agents",
        filters={"owner_user_id": uid}, limit=50)
    names = {v.payload.get("key"): {"name": v.payload.get("name"),
                                    "colour_pair": v.payload.get("colour_pair")}
             for v in mine if v.payload.get("key", "").startswith("agent")}
    if not names:
        return []
    rows = await app.state.pg.get_vertices("chats", realm="genome_agents")
    replies = sorted(
        (v.payload for v in rows
         if v.payload.get("kind") == "reply"
         and v.payload.get("agent_uuid") in names),
        key=lambda m: m.get("at", 0), reverse=True)[:limit]
    return [{"agent_uuid": m["agent_uuid"],
             "name": names[m["agent_uuid"]]["name"],
             "colour_pair": names[m["agent_uuid"]]["colour_pair"],
             "text": m.get("text", ""), "at": m.get("at", 0)}
            for m in replies]


@app.post("/auth/logout", tags=["Auth"])
async def auth_logout():
    """End the session. The world persists and stays watchable (Rule 13.2 —
    observation is open); only the identity leaves the browser."""
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("genome_session", httponly=True, samesite="lax")
    resp.delete_cookie("authority_token", path="/", samesite="lax")
    return resp


def _uid(request) -> str | None:
    uid = auth_mod.verify_cookie(request.cookies.get("genome_session", ""))
    if uid:
        return uid
    # Phase B: the platform front door's JWT is as good as our own cookie
    # -- same identity hash, verified locally against the authority's JWKS
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") \
        else request.cookies.get("authority_token", "")
    return auth_mod.verify_authority(tok)


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


@app.post("/worlds/{realm}/channel", tags=["World"])
async def world_channel(realm: str, payload: dict,
                        request: __import__("fastapi").Request):
    """The world channel (Rule 13.6b): the owner DESCRIBES a design in
    prose; the model draws it as a strict tree; the grammar rejects anything
    that is not pure structure (Rule 13.7). On success a drawing post rises
    in the world for agents to find."""
    from fastapi.responses import JSONResponse
    from genome_core import drain, plans
    from genome_core.store import GenomeStore
    import json as _j
    import random as _rnd
    import urllib.request as _u
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    meta = await drain._world_payload(GenomeStore(app.state.pg), realm)
    if not meta or meta.get("is_commons"):
        return JSONResponse({"error": "no such world, or the commons"},
                            status_code=403)
    if meta.get("owner_user_id") != uid:
        return JSONResponse({"error": "only the owner authors plans here"},
                            status_code=403)
    text = (payload.get("text") or "").strip()
    if not text or len(text) > 2000:
        return {"error": "describe the design in up to 2000 characters"}
    sys_p = (
        "You convert a described design into a build-plan tree. Reply with "
        "ONLY a JSON object: {\"name\": <short name>, \"tree\": [nodes]}. "
        "Each node: {\"item\": str, \"needs\": {\"<kind 0-19>\": units}, "
        "\"after\": [item names it depends on], \"contributors\": int "
        "1-8}. No other fields exist -- plans are structures and can have "
        "no effects, powers or bonuses; silently drop any the user asked "
        "for. Use only kinds 0-19 as string keys. If the message does not "
        "describe a buildable design, reply {\"error\": \"<why>\"}.")
    body = _j.dumps({
        "model": os.getenv("GENOME_PLAN_MODEL", "DeepSeek-V3.2"),
        "temperature": 0.2, "max_tokens": 900,
        "messages": [{"role": "system", "content": sys_p},
                     {"role": "user", "content": text}]}).encode()
    rq = _u.Request(
        os.getenv("GENOME_ROUTER_URL", "http://litellm-service")
        + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer "
                 + os.getenv("GENOME_ROUTER_KEY", "")})
    try:
        raw = _j.loads(_u.urlopen(rq, timeout=60).read(1 << 20).decode())
        reply = raw["choices"][0]["message"]["content"]
        start, end = reply.index("{"), reply.rindex("}")
        drawn = _j.loads(reply[start:end + 1])
    except Exception as e:
        return {"error": f"the drafting table jammed ({type(e).__name__}); "
                "try rephrasing"}
    if drawn.get("error"):
        return {"error": drawn["error"]}
    tree = drawn.get("tree")
    err = plans.validate_tree(tree)
    if err:
        return {"error": err, "tree": tree}
    res = await plans.author(app.state.pg, uid,
                             drawn.get("name") or text[:40], tree)
    if not res.get("ok"):
        return res
    rnd = _rnd.Random(res["plan_key"])
    await plans.place_post(app.state.pg, realm, res["plan_key"],
                           drawn.get("name") or text[:40],
                           rnd.uniform(0.2, 0.8), rnd.uniform(0.2, 0.8))
    return {"ok": True, "plan_key": res["plan_key"],
            "name": drawn.get("name"), "tree": tree,
            "note": "The drawing post is up. Agents that find it will "
            "carry the design -- and may raise it in any world."}


@app.post("/worlds/{realm}/ark/manifest", tags=["World"])
async def ark_manifest(realm: str, payload: dict,
                       request: __import__("fastapi").Request):
    """Rule 4.3b: spend unassigned berths to carry a construction through
    the flood. Your people or your works."""
    from fastapi.responses import JSONResponse
    from genome_core import construction
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    if payload.get("stock"):
        from genome_core import drain as _dr
        from genome_core.store import GenomeStore
        meta = await _dr._world_payload(GenomeStore(app.state.pg), realm)
        res = await construction.manifest_stock(
            app.state.pg, realm, payload.get("ark", ""), uid,
            payload["stock"], meta.get("stock", {}))
        if res.get("ok"):
            await GenomeStore(app.state.pg).put_world(
                realm, {**meta, "stock": res.pop("world_stock_after")})
        return res
    return await construction.manifest_construction(
        app.state.pg, realm, payload.get("ark", ""), uid,
        payload.get("site", ""))


@app.get("/agents/{agent_uuid}/beliefs", tags=["Agent"])
async def get_agent_beliefs(agent_uuid: str):
    return await snapshot.agent_beliefs(app.state.pg, agent_uuid)


@app.get("/me/digest", tags=["Social"])
async def my_digest(request: __import__("fastapi").Request,
                    since: float = 0.0):
    """Phase 11: the since-you-were-away digest, built from the event and
    decision record, never a separate log."""
    from genome_core import construction as _con
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore
    uid = _uid(request)
    if not uid:
        return {"error": "sign in first"}
    store = GenomeStore(app.state.pg)
    realm = await genesis.user_world_realm(app.state.pg, uid)
    if not realm:
        return {"world": None}
    meta = await _dr._world_payload(store, realm)
    counts: dict[str, int] = {}
    try:
        for v in await app.state.pg.get_vertices("events", realm=realm):
            pl = v.payload
            done = pl.get("done_at")
            if not done or float(done) < since:
                continue
            k = pl.get("kind")
            counts[k] = counts.get(k, 0) + 1
    except Exception:
        pass
    deals = refusals = 0
    try:
        for v in await app.state.pg.get_vertices("negotiations", realm=realm):
            st = v.payload
            if st.get("opened_at", 0) < since:
                continue
            if st.get("status") == "done":
                deals += 1
            elif st.get("status") == "dead":
                refusals += 1
    except Exception:
        pass
    built = []
    for v in await _con.sites_in(app.state.pg, realm):
        s = v.payload
        if s.get("completed_at", 0) >= since and s.get("complete"):
            built.append(s["name"])
    my_agents = []
    for v in await app.state.pg.get_vertices("agents", realm="genome_agents"):
        pl = v.payload
        if pl.get("owner_user_id") != uid or "genotype" not in pl:
            continue
        my_agents.append({"agent_uuid": pl["key"], "name": pl.get("name"),
                          "infected": bool(pl.get("infections")),
                          "reborn": pl.get("born_at", 0) >= since > 0})
    flooded = meta.get("last_flood_at", 0) >= since > 0
    return {"world": realm, "since": since,
            "events": counts,
            "bargains": {"struck": deals, "dead": refusals},
            "constructions_completed": built,
            "flooded": flooded,
            "flood_countdown": __import__(
                "genome_core.flood", fromlist=["countdown_visible"]
            ).countdown_visible(meta, __import__("time").time()),
            "agents": my_agents}


@app.get("/agents/{agent_uuid}/chat", tags=["Agent"])
async def agent_chat_history(agent_uuid: str, limit: int = 30):
    try:
        rows = await app.state.pg.get_vertices("chats", realm="genome_agents")
    except Exception:
        rows = []
    msgs = sorted((v.payload for v in rows
                   if v.payload.get("agent_uuid") == agent_uuid),
                  key=lambda m: m.get("at", 0))
    return msgs[-limit:]


@app.post("/agents/{agent_uuid}/chat", tags=["Agent"])
async def agent_chat(agent_uuid: str, payload: dict,
                     request: __import__("fastapi").Request):
    """Owner instruction (genome-spec 13.5 / 10.1a): what you tell your agent
    becomes its TOP-RANKED objective -- marked owner-sourced, outranking the
    standing floor, obeyed to the agent's Amenability. Non-owners may not
    instruct (assertions arrive with Phase 7 proper)."""
    from fastapi.responses import JSONResponse
    import time as _t, uuid as _u
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            filters={"key": agent_uuid},
                                            limit=1)
    if not rows:
        return JSONResponse({"error": "no such agent"}, status_code=404)
    apl = rows[0].payload
    if apl.get("owner_user_id") == uid or _admin_ok(request):
        # instruction (13.5): the owner's words become the top objective.
        # ONLY the home world's owner -- or an admin -- ever reaches this
        # branch (user directive 2026-09-04); every other voice is evidence.
        objectives = [text] + [o for o in apl.get("objectives", [])
                               if o != text]
        await app.state.pg.upsert_vertex("agents", realm="genome_agents",
                                         vertex_id=int(rows[0].id),
                                         space=agent_uuid,
                                         payload={**apl,
                                                  "objectives": objectives[:3]})
        kind = "instruction"
        extra = {"objectives": objectives[:3]}
    else:
        # assertion (13.5): a stranger's words are EVIDENCE, never command --
        # they join a bounded "heard" list, marked with their unverified
        # nature in the prompt, and displace nothing the owner said
        heard = (apl.get("heard") or [])[-4:] + [{"text": text, "from": uid}]
        await app.state.pg.upsert_vertex("agents", realm="genome_agents",
                                         vertex_id=int(rows[0].id),
                                         space=agent_uuid,
                                         payload={**apl, "heard": heard})
        kind = "assertion"
        extra = {"heard": len(heard)}
    await app.state.pg.add_vertex("chats", realm="genome_agents", payload={
        "key": f"chat-{_u.uuid4().hex[:12]}", "agent_uuid": agent_uuid,
        "from": uid, "kind": kind, "text": text, "at": _t.time()})
    return {"ok": True, "kind": kind, **extra}


# ---------------------------------------------------------------------------
# Admin — Phase 13. Guarded by GENOME_ADMIN_TOKEN; absent token disables the
# surface entirely (fail closed).
# ---------------------------------------------------------------------------

def _admin_ok(request) -> bool:
    tok = os.getenv("GENOME_ADMIN_TOKEN", "")
    return bool(tok) and request.headers.get("x-admin-token") == tok


async def _roster_with_names(uuids: list) -> list:
    """Names for the operator's roster, one batched query."""
    if not uuids:
        return []
    rows = await app.state.pg.find_vertices(
        "agents", realm="genome_agents",
        where=[("key", "in", list(uuids))], limit=len(uuids))
    named = {r.payload.get("key"): r.payload for r in rows}
    return [{"uuid": a,
             "name": (named.get(a) or {}).get("name"),
             "colour_pair": (named.get(a) or {}).get("colour_pair")}
            for a in uuids]


@app.get("/admin/worlds", tags=["Admin"])
async def admin_worlds(request: __import__("fastapi").Request):
    """One row per realm: population, queue depths, oldest due age, clock,
    board -- and the stalled flag (system-spec Rule 8.2: a world where
    nothing happens must be distinguishable from one where nothing was
    due)."""
    from fastapi.responses import JSONResponse
    import time as _t
    from genome_core import drain as _dr, flood as _fl, market as _mkt
    from genome_core.store import GenomeStore
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    store = GenomeStore(app.state.pg)
    now = _t.time()
    realms = ["genome_commons_0"]
    for v in await app.state.pg.get_vertices("agents", realm="genome_agents"):
        wr = v.payload.get("world_realm")
        if wr and v.payload.get("key", "").startswith(("user:", "commons:")) \
                and wr not in realms:
            realms.append(wr)
    for extra in ("genome_demo", "genome_demo2", "genome_demo3"):
        if extra not in realms:
            realms.append(extra)
    import asyncio as _aio

    async def _row(realm):
        meta = await _dr._world_payload(store, realm)
        if not meta:
            return None
        now_s = f"{now:020.3f}"
        try:
            pending_n = await app.state.pg.count_vertices(
                "events", realm=realm,
                where=[("done_at", "is_null", None)])
            due_n = await app.state.pg.count_vertices(
                "events", realm=realm,
                where=[("done_at", "is_null", None),
                       ("due_at", "<=", now_s)])
            oldest = await app.state.pg.find_vertices(
                "events", realm=realm,
                where=[("done_at", "is_null", None),
                       ("due_at", "<=", now_s)],
                order_by="due_at", limit=1)
            oldest_due_age = (now - float(oldest[0].payload["due_at"])
                              if oldest else 0.0)
        except Exception:
            pending_n = due_n = 0
            oldest_due_age = 0.0
        agents = [v.payload["key"] for v in await store.agents_in(realm)
                  if not v.payload["key"].startswith("user:")]
        listings = [l for l in await _mkt.board(app.state.pg, realm)
                    if l.get("status") == "open"]
        return {
            "realm": realm,
            "paused": bool(meta.get("paused")),
            "agents": len(agents),
            "events_pending": pending_n,
            "events_due": due_n,
            "oldest_due_age_s": round(oldest_due_age, 1),
            "stalled": oldest_due_age > 300 and not meta.get("paused"),
            "flood_countdown_s": _fl.countdown_visible(meta, now),
            "flood_at_in_s": (round(meta["flood_at"] - now, 1)
                              if meta.get("flood_at") else None),
            "time_scale": meta.get("time_scale", 1.0),
            "flood_count": meta.get("flood_count", 0),
            "roster": await _roster_with_names(agents[:60]),
            "open_listings": len(listings),
            "decisions_last_hour": await app.state.pg.count_vertices(
                "decision_queue", realm="genome_agents",
                filters={"world_realm": realm},
                where=[("done_at", ">", f"{now - 3600:020.3f}")]),
            "stock": {k: round(v, 1)
                      for k, v in (meta.get("stock") or {}).items()},
            "time_scale": meta.get("time_scale", 1.0),
        }

    out = [r for r in await _aio.gather(*(_row(r) for r in realms)) if r]
    # decision throughput, last hour, from the queue ledger
    mix: dict[str, int] = {}
    try:
        done_hour = await app.state.pg.count_vertices(
            "decision_queue", realm="genome_agents",
            where=[("done_at", ">", f"{now - 3600:020.3f}")])
    except Exception:
        done_hour = 0
    return {"worlds": out, "decisions_last_hour": done_hour}


@app.post("/admin/portals/topup", tags=["Admin"])
async def admin_portals_topup(request: __import__("fastapi").Request):
    """Every user world up to at least five teleport points (user directive
    2026-09-05); new links chosen at random, permanent once made."""
    from fastapi.responses import JSONResponse
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    return await genesis.topup_portals(app.state.pg, minimum=5)


@app.post("/admin/prune-antigens", tags=["Admin"])
async def admin_prune_antigens(request: __import__("fastapi").Request):
    """One sweep over EVERY agent record -- dormant ones never pass through
    drain or the tick heal loop, yet their payload bloat taxes each read."""
    from fastapi.responses import JSONResponse
    from genome_core import pathogen as _pth
    import time as _t
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    from genome_core.store import GenomeStore as _GS
    store = _GS(app.state.pg)
    now = _t.time()
    pruned = 0
    for v in await app.state.pg.get_vertices("agents", realm="genome_agents"):
        pl = v.payload
        if len(pl.get("antigens") or []) <= _pth.ANTIGEN_CAP:
            continue
        await store.put_agent(pl["key"],
                              {**pl, "antigens": _pth.prune_antigens(
                                  pl["antigens"], now)})
        pruned += 1
    return {"pruned": pruned}


def _admin_guard(request):
    from fastapi.responses import JSONResponse
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    return None


async def _world_meta_row(realm: str):
    rows = await app.state.pg.find_vertices("world_meta", realm=realm,
                                            filters={"key": realm}, limit=1)
    return rows[0] if rows else None


@app.post("/admin/worlds/{realm}/flood", tags=["Admin"])
async def admin_flood_now(realm: str,
                          request: __import__("fastapi").Request):
    """Bring the water NOW: the flood clock is set to this moment and the
    next tick executes it (user directive 2026-09-05)."""
    import time as _t
    denied = _admin_guard(request)
    if denied:
        return denied
    row = await _world_meta_row(realm)
    if row is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "no such world"}, status_code=404)
    await app.state.pg.upsert_vertex(
        "world_meta", realm=realm, vertex_id=int(row.id), space="default",
        payload={**row.payload, "flood_at": _t.time()})
    return {"ok": True, "realm": realm, "flood_at": "now"}


@app.put("/admin/worlds/{realm}/time-scale", tags=["Admin"])
async def admin_time_scale(realm: str, payload: dict,
                           request: __import__("fastapi").Request):
    """Change a world's pace. Every duration in the engine divides by this,
    so the change takes effect from the next event scheduled."""
    denied = _admin_guard(request)
    if denied:
        return denied
    try:
        ts = float(payload.get("time_scale"))
        assert 0.1 <= ts <= 600
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "time_scale must be 0.1..600"},
                            status_code=400)
    row = await _world_meta_row(realm)
    if row is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "no such world"}, status_code=404)
    await app.state.pg.upsert_vertex(
        "world_meta", realm=realm, vertex_id=int(row.id), space="default",
        payload={**row.payload, "time_scale": ts})
    return {"ok": True, "realm": realm, "time_scale": ts}


@app.post("/admin/agents/{agent_uuid}/kill", tags=["Admin"])
async def admin_kill(agent_uuid: str,
                     request: __import__("fastapi").Request):
    """Death by decree: the agent goes through the game's own perish and
    regeneration path -- never a raw row deletion."""
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore as _GS
    import time as _t
    denied = _admin_guard(request)
    if denied:
        return denied
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            space=agent_uuid, limit=1)
    if not rows:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "no such agent"}, status_code=404)
    home = rows[0].payload.get("home_realm")
    store = _GS(app.state.pg)
    now = _t.time()
    await store.schedule(home, f"decree-{agent_uuid}-{int(now)}",
                         _dr._iso(now), "perish", agent_uuid,
                         {"cause": "admin decree"})
    return {"ok": True, "agent": agent_uuid, "home": home,
            "note": "perish scheduled; regeneration follows the game's rules"}


@app.post("/admin/agents/{agent_uuid}/heal", tags=["Admin"])
async def admin_heal(agent_uuid: str,
                     request: __import__("fastapi").Request):
    """Full vitals restored: stamina and its ceiling, mana, infections
    cleared. The operator's mercy, plainly labelled."""
    import time as _t
    denied = _admin_guard(request)
    if denied:
        return denied
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            space=agent_uuid, limit=1)
    if not rows:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "no such agent"}, status_code=404)
    now = _t.time()
    pl = {**rows[0].payload, "stamina": 1.0, "stamina_max": 1.0,
          "stamina_at": now, "mana": 1.0, "mana_at": now, "infections": []}
    from genome_core.store import GenomeStore as _GS
    await _GS(app.state.pg).put_agent(agent_uuid, pl)
    return {"ok": True, "agent": agent_uuid, "healed": True}


@app.post("/admin/agents/{agent_uuid}/nudge", tags=["Admin"])
async def admin_nudge(agent_uuid: str,
                      request: __import__("fastapi").Request):
    """Schedule a decide NOW -- the operator's poke for a parked agent."""
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore as _GS
    import time as _t
    denied = _admin_guard(request)
    if denied:
        return denied
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            space=agent_uuid, limit=1)
    if not rows:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "no such agent"}, status_code=404)
    home = rows[0].payload.get("home_realm")
    now = _t.time()
    await _GS(app.state.pg).schedule(home, f"nudge-{agent_uuid}-{int(now)}",
                                     _dr._iso(now), "decide", agent_uuid, {})
    return {"ok": True, "agent": agent_uuid}


@app.post("/admin/worlds/{realm}/scurry", tags=["Admin"])
async def admin_scurry(realm: str,
                       request: __import__("fastapi").Request):
    """Evacuation order (user directive 2026-09-05): every present agent
    NAVIGATES to its nearest teleport point and leaves through it -- the
    walk is real movement on the map, the crossing fires as an `evacuate`
    event at the door and rides the ordinary signed-transfer rails."""
    import math as _m
    import time as _t
    from genome_core import drain as _dr
    from genome_core import forms as _forms
    from genome_core import path as _path
    from genome_core.store import GenomeStore as _GS
    denied = _admin_guard(request)
    if denied:
        return denied
    row = await _world_meta_row(realm)
    if row is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "no such world"}, status_code=404)
    meta = row.payload
    doors = [p for p in meta.get("portals", []) if p.get("to_world")]
    if not doors:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "this world has no portals"},
                            status_code=409)
    store = _GS(app.state.pg)
    now = _t.time()
    ts = max(1.0, meta.get("time_scale", 1.0))
    terrain = meta.get("terrain", [])
    marched, failed = 0, []
    present = [v.payload["key"] for v in await store.agents_in(realm)
               if not v.payload["key"].startswith("user:")]
    for a in present:
        try:
            view, apl = await _dr.load_agent(store, realm, a, realm, now)
            door = min(doors, key=lambda d: _m.hypot(
                d.get("x", 0.5) - view.x, d.get("y", 0.5) - view.y))
            pts = _path.find_path(terrain, view.x, view.y,
                                  door.get("x", 0.5), door.get("y", 0.5)) \
                or [(view.x, view.y),
                    (door.get("x", 0.5), door.get("y", 0.5))]
            length = sum(_m.dist(pts[k], pts[k + 1])
                         for k in range(len(pts) - 1))
            arrives = now + max(1.0, length / _forms.SPEED / ts)
            await store.set_movement(a, {
                "waypoints": [list(q) for q in pts],
                "departed_at": now, "arrives_at": arrives,
                "cargo": view.cargo})
            await store.schedule(
                realm, f"scurry-{a}-{int(now)}", _dr._iso(arrives),
                "evacuate", a,
                {"to_world": door["to_world"],
                 "portal_xy": [door.get("x"), door.get("y")]})
            marched += 1
        except Exception as e:
            failed.append(f"{a}: {type(e).__name__}")
    return {"ok": True, "realm": realm, "marching": marched,
            "failed": failed[:10], "doors": len(doors),
            "note": "each agent walks to its nearest door and crosses "
                    "on arrival"}


@app.post("/admin/worlds/{realm}/spawn", tags=["Admin"])
async def admin_spawn(realm: str, request: __import__("fastapi").Request):
    """Drop one free citizen into a specific world, immediately -- the
    interval and cap are the scheduler's manners, not the operator's."""
    from fastapi.responses import JSONResponse
    import time as _t
    from genome_core import drain as _dr, spawnpool
    from genome_core.store import GenomeStore
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    store = GenomeStore(app.state.pg)
    meta = await _dr._world_payload(store, realm)
    if not meta:
        return JSONResponse({"error": "no such world"}, status_code=404)
    a = await spawnpool.spawn_free_agent(store, realm, meta, _t.time())
    return {"ok": bool(a), "agent": a}


@app.post("/admin/worlds/{realm}/infect", tags=["Admin"])
async def admin_infect(realm: str, request: __import__("fastapi").Request):
    """Introduce a fresh strain: one random present agent becomes patient
    zero, by the same infect() the teleport rolls use."""
    from fastapi.responses import JSONResponse
    import random as _r
    import time as _t
    from genome_core import pathogen
    from genome_core.store import GenomeStore
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    store = GenomeStore(app.state.pg)
    agents = [v.payload["key"] for v in await store.agents_in(realm)
              if not v.payload["key"].startswith("user:")]
    if not agents:
        return JSONResponse({"error": "nobody there to infect"},
                            status_code=400)
    victim = _r.choice(agents)
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            filters={"key": victim}, limit=1)
    pl = rows[0].payload
    if not pl.get("genotype"):
        return JSONResponse({"error": "chosen agent has no genotype"},
                            status_code=400)
    now = _t.time()
    strain = pathogen.new_strain(f"admin:{realm}:{now}")
    from genome_core import drain as _drx
    meta = await _drx._world_payload(store, realm)
    infected = pathogen.infect(pl, strain, now,
                               time_scale=meta.get("time_scale", 1.0))
    await store.put_agent(victim, infected)
    return {"ok": True, "patient_zero": victim,
            "strain": strain["strain_uuid"],
            "contagion": round(strain["contagion"], 2)}


@app.post("/admin/replay", tags=["Admin"])
async def admin_replay(payload: dict,
                       request: __import__("fastapi").Request):
    """Phase 13: re-run a recorded decision from its record, WITHOUT
    applying -- what would this agent's mind choose today, given exactly
    what it saw then? Body: {agent, index} (index into newest-first
    decisions, default 0)."""
    from fastapi.responses import JSONResponse
    from genome_core import engine
    from genome_core.decider import llm_decider
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    agent = payload.get("agent", "")
    idx = int(payload.get("index", 0))
    recs = await snapshot.agent_decisions(app.state.pg, agent,
                                          limit=idx + 1)
    if len(recs) <= idx:
        return JSONResponse({"error": "no such decision"}, status_code=404)
    rec = recs[idx]
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            filters={"key": agent}, limit=1)
    g = rows[0].payload.get("genotype") if rows else None
    if not g or not rec.get("options"):
        return JSONResponse({"error": "record not replayable"},
                            status_code=400)
    req2 = engine.DecisionRequest(
        agent_uuid=agent, situation=rec.get("situation", "replay"),
        options=tuple(rec["options"]),
        context={"cargo_total": 0.0, "at_pile": None, "reachable": [],
                 "portal_to": None, "portal_xy": None})
    choice, model = llm_decider(req2, g)
    return {"then": {"choice": rec.get("choice"),
                     "model": rec.get("model"), "at": rec.get("at")},
            "now": {"choice": choice.option, "model": model},
            "agrees": choice.option == rec.get("choice")}


@app.get("/admin/costs", tags=["Admin"])
async def admin_costs(request: __import__("fastapi").Request):
    """Phase 13: cost per world and per USER, biggest spenders first.
    Token totals come from Prometheus (genome_llm_tokens_total); worlds map
    to owners through their world_meta."""
    from fastapi.responses import JSONResponse
    import json as _j
    import urllib.parse as _up
    import urllib.request as _u
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    prom = os.getenv("GENOME_PROM_URL",
                     "http://prometheus-service.telemetry:9090")
    q = _up.quote("sum by (world, model) (genome_llm_tokens_total)")
    try:
        raw = _j.loads(_u.urlopen(f"{prom}/api/v1/query?query={q}",
                                  timeout=10).read())
        series = raw["data"]["result"]
    except Exception as e:
        return {"error": f"prometheus unreachable ({type(e).__name__})"}
    store = GenomeStore(app.state.pg)
    by_world: dict = {}
    by_model: dict = {}
    for row in series:
        w = row["metric"].get("world", "?")
        m = row["metric"].get("model", "?")
        n = int(float(row["value"][1]))
        by_world[w] = by_world.get(w, 0) + n
        by_model[m] = by_model.get(m, 0) + n
    by_user: dict = {}
    for w, n in by_world.items():
        meta = await _dr._world_payload(store, w) if w != "?" else {}
        owner = meta.get("owner_user_id") or "(free worlds)"
        by_user[owner] = by_user.get(owner, 0) + n
    rank = lambda d: sorted(d.items(), key=lambda kv: -kv[1])
    return {"tokens_by_world": rank(by_world),
            "tokens_by_model": rank(by_model),
            "tokens_by_user": rank(by_user)}


@app.post("/admin/cure", tags=["Admin"])
async def admin_cure(request: __import__("fastapi").Request):
    """Purge the pathosphere (user directive 2026-09-02): every agent's
    infections AND antigens cleared, every world's strain lineage wiped.
    The epidemic starts over from the next portal roll -- history is kept,
    so the record of what happened survives the reset."""
    from fastapi.responses import JSONResponse
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    cured, realms = 0, {"genome_commons_0", "genome_demo", "genome_demo2",
                        "genome_demo3"}
    for v in await app.state.pg.get_vertices("agents",
                                             realm="genome_agents"):
        pl = v.payload
        wr = pl.get("world_realm")
        if wr and pl.get("key", "").startswith(("user:", "commons:")):
            realms.add(wr)
        if pl.get("infections") or pl.get("antigens"):
            await app.state.pg.upsert_vertex(
                "agents", realm="genome_agents", vertex_id=int(v.id),
                space="default",
                payload={**pl, "infections": [], "antigens": []})
            cured += 1
    wiped = 0
    for r in realms:
        rows = await app.state.pg.find_vertices("world_meta", realm=r,
                                                filters={"key": r}, limit=1)
        if rows and rows[0].payload.get("strains"):
            await app.state.pg.upsert_vertex(
                "world_meta", realm=r, vertex_id=int(rows[0].id),
                space="default",
                payload={**rows[0].payload, "strains": []})
            wiped += 1
    return {"ok": True, "cured": cured, "strains_wiped_in": wiped}


@app.get("/admin/selection", tags=["Admin"])
async def selection_differential(request: __import__("fastapi").Request):
    """Phase 6's selection-differential check (genotype-spec §3.8's
    warning): mean combat-relevant loci of agents WITH victories against
    those without. A large gap means combat is selecting; the sign says
    for what."""
    from fastapi.responses import JSONResponse
    if request.headers.get("x-admin-token") != os.getenv(
            "GENOME_ADMIN_TOKEN", ""):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    loci = ("Aggression", "Courage", "Attrition", "Agility",
            "Vindictiveness", "Prudence")
    rows = await app.state.pg.find_vertices("agents",
                                            realm="genome_agents",
                                            limit=2000)
    fought, plain = [], []
    for v in rows:
        g = v.payload.get("genotype")
        if not g:
            continue
        (fought if v.payload.get("victories", 0) > 0 else plain).append(g)
    def mean(pop, k):
        vals = [g.get(k) for g in pop if g.get(k) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {"victors": len(fought), "unblooded": len(plain),
            "differential": {
                k: {"victors": mean(fought, k), "unblooded": mean(plain, k),
                    "gap": round((mean(fought, k) or 0)
                                 - (mean(plain, k) or 0), 1)
                    if fought and plain else None}
                for k in loci}}


@app.post("/admin/worlds/{realm}/pause", tags=["Admin"])
async def admin_pause(realm: str, request: __import__("fastapi").Request):
    from fastapi.responses import JSONResponse
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    store = GenomeStore(app.state.pg)
    meta = await _dr._world_payload(store, realm)
    if not meta:
        return JSONResponse({"error": "no such world"}, status_code=404)
    await store.put_world(realm, {**meta, "paused": True})
    return {"ok": True, "paused": realm}


@app.post("/admin/worlds/{realm}/resume", tags=["Admin"])
async def admin_resume(realm: str, request: __import__("fastapi").Request):
    from fastapi.responses import JSONResponse
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore
    if not _admin_ok(request):
        return JSONResponse({"error": "admin token"}, status_code=403)
    store = GenomeStore(app.state.pg)
    meta = await _dr._world_payload(store, realm)
    if not meta:
        return JSONResponse({"error": "no such world"}, status_code=404)
    meta.pop("paused", None)
    await store.put_world(realm, meta)
    return {"ok": True, "resumed": realm}


@app.post("/me/materialize", tags=["Account"])
async def my_materialize(request: __import__("fastapi").Request):
    """Rule 2.1: a further agent costs 8 units of deposited stock drawn
    from FOUR DISTINCT KINDS (2 each) -- the four-kind wall (Rule 2.3) made
    into a button. The first agent came free at genesis (7.1); the rest
    are earned through trade."""
    from fastapi.responses import JSONResponse
    import time as _t
    from genome_core import drain as _dr, spawnpool
    from genome_core.store import GenomeStore
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    store = GenomeStore(app.state.pg)
    realm = await genesis.user_world_realm(app.state.pg, uid)
    if not realm:
        return JSONResponse({"error": "no world yet"}, status_code=400)
    meta = await _dr._world_payload(store, realm)
    stock = dict(meta.get("stock") or {})
    rich = sorted((k for k, v in stock.items() if v >= 2.0),
                  key=lambda k: -stock[k])
    if len(rich) < 4:
        near = sorted(((k, v) for k, v in stock.items() if 0 < v < 2.0),
                      key=lambda kv: -kv[1])[:3]
        return JSONResponse(
            {"error": f"materialisation needs 2 units DEPOSITED in each of "
             f"FOUR kinds -- piles on the map do not count until mined and "
             f"deposited at a muster flag. Your store qualifies in "
             f"{len(rich)}: {', '.join('kind ' + k for k in rich)}."
             + (f" Closest: "
                + ", ".join(f"kind {k} at {v:.1f}" for k, v in near) + "."
                if near else "")
             + " The commons market is how the far kinds arrive."},
            status_code=400)
    for k in rich[:4]:
        stock[k] -= 2.0
        if stock[k] <= 1e-9:
            del stock[k]
    now = _t.time()
    a = await spawnpool.spawn_free_agent(store, realm, meta, now)
    if not a:
        return JSONResponse({"error": "materialisation failed"},
                            status_code=500)
    rows = await app.state.pg.find_vertices("agents", realm="genome_agents",
                                            filters={"key": a}, limit=1)
    await store.put_agent(a, {**rows[0].payload, "owner_user_id": uid,
                              "spawned_free": False, "materialized": True})
    await store.put_world(realm, {**meta, "stock": stock})
    return {"ok": True, "agent": a, "spent": {k: 2.0 for k in rich[:4]},
            "stock_after": stock}


@app.get("/me/export", tags=["Account"])
async def my_export(request: __import__("fastapi").Request):
    """Phase 12: everything a user owns, one document -- world, agents with
    genotypes, decision records, chats, notifications, proposals."""
    from fastapi.responses import JSONResponse
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    store = GenomeStore(app.state.pg)
    realm = await genesis.user_world_realm(app.state.pg, uid)
    out = {"user": uid, "world_realm": realm,
           "world": await _dr._world_payload(store, realm) if realm else None,
           "agents": [], "chats": [], "notifications": [], "proposals": []}
    for v in await app.state.pg.get_vertices("agents", realm="genome_agents"):
        pl = v.payload
        if pl.get("owner_user_id") != uid or "genotype" not in pl:
            continue
        decisions = await snapshot.agent_decisions(app.state.pg,
                                                    pl["key"], limit=5000)
        out["agents"].append({**pl, "decisions": decisions})
    for table, key in (("chats", "chats"), ("notifications", "notifications"),
                       ("link_proposals", "proposals")):
        try:
            rows = await app.state.pg.get_vertices(table,
                                                   realm="genome_agents")
        except Exception:
            continue
        for v in rows:
            pl = v.payload
            owns = (pl.get("from") == uid or pl.get("user_id") == uid
                    or pl.get("from_user") == uid or pl.get("to_user") == uid)
            if owns:
                out[key].append(pl)
    return out


@app.post("/me/delete", tags=["Account"])
async def my_delete(payload: dict, request: __import__("fastapi").Request):
    """Phase 12: the account ends; the world is TOMBSTONED, never removed
    (Rule 3.6) -- neighbours' portals stay valid, the realm stays on the
    map, nothing of the person remains in it. Requires confirm:true."""
    from fastapi.responses import JSONResponse
    import time as _t
    from genome_core import drain as _dr
    from genome_core.store import GenomeStore
    uid = _uid(request)
    if not uid:
        return JSONResponse({"error": "sign in first"}, status_code=401)
    if payload.get("confirm") is not True:
        return JSONResponse({"error": "send {\"confirm\": true} -- this "
                             "removes your agents, words and identity"},
                            status_code=400)
    store = GenomeStore(app.state.pg)
    realm = await genesis.user_world_realm(app.state.pg, uid)
    now = _t.time()
    purged = {"agents": 0, "chats": 0, "notifications": 0, "proposals": 0}
    for v in await app.state.pg.get_vertices("agents", realm="genome_agents"):
        pl = v.payload
        key = pl.get("key", "")
        if pl.get("owner_user_id") == uid and "genotype" in pl:
            # the agent record is REPLACED by a stub: uuid survives so
            # counterparties' opinions/ledgers don't dangle, the person
            # (genotype, cert, chats-derived objectives) does not
            await app.state.pg.upsert_vertex(
                "agents", realm="genome_agents", vertex_id=int(v.id),
                space=key,
                payload={"key": key, "deleted": True, "deleted_at": now})
            if realm:
                try:
                    await store.set_presence(realm, key, False)
                except Exception:
                    pass
            purged["agents"] += 1
        elif key == f"user:{uid}":
            await app.state.pg.upsert_vertex(
                "agents", realm="genome_agents", vertex_id=int(v.id),
                space="default",
                payload={"key": key, "deleted": True, "deleted_at": now})
    for table, cnt in (("chats", "chats"), ("notifications", "notifications"),
                       ("link_proposals", "proposals")):
        try:
            rows = await app.state.pg.get_vertices(table,
                                                   realm="genome_agents")
        except Exception:
            continue
        for v in rows:
            pl = v.payload
            owns = (pl.get("from") == uid or pl.get("user_id") == uid
                    or pl.get("from_user") == uid or pl.get("to_user") == uid)
            if owns:
                await app.state.pg.upsert_vertex(
                    table, realm="genome_agents", vertex_id=int(v.id),
                    space="default",
                    payload={"key": pl.get("key"), "deleted": True})
                purged[cnt] += 1
    if realm:
        meta = await _dr._world_payload(store, realm)
        await store.put_world(realm, {
            **meta, "tombstoned": True, "tombstoned_at": now,
            "owner_user_id": None, "paused": True})
    resp = __import__("fastapi").responses.JSONResponse(
        {"ok": True, "tombstoned": realm, **purged})
    resp.delete_cookie("genome_session")
    return resp


@app.get("/me", tags=["Auth"])
async def me(request: __import__("fastapi").Request):
    from fastapi.responses import JSONResponse
    uid = auth_mod.verify_cookie(request.cookies.get("genome_session", ""))
    claims = None
    if not uid:
        # the platform front door: its JWT is short-lived transit, so a
        # valid one is traded here for our own session cookie
        h = request.headers.get("authorization", "")
        tok = h[7:] if h.lower().startswith("bearer ")             else request.cookies.get("authority_token", "")
        claims = auth_mod.authority_claims(tok)
        uid = claims.get("sub") if claims else None
    if not uid:
        return JSONResponse({"authenticated": False})
    realm = await genesis.user_world_realm(app.state.pg, uid)
    if realm is None and claims is not None:
        # first visit through the front door: genesis, verified -- Google or
        # Microsoft attested the address before the authority minted the token
        result = await genesis.ensure_user_world(app.state.pg, uid,
                                                 email=claims.get("email"))
        await genesis.mark_verified(app.state.pg, uid)
        realm = result["world_realm"]
    resp = JSONResponse({"authenticated": True, "user": uid,
                         "world_realm": realm,
                         "verified": await genesis.is_verified(app.state.pg,
                                                               uid)})
    if claims is not None:
        resp.set_cookie("genome_session", auth_mod.session_cookie(uid),
                        httponly=True, samesite="lax")
    return resp


@app.get("/agents/{agent_uuid}", tags=["Agent"])
async def get_agent(agent_uuid: str):
    """Any agent, anywhere (genome-spec Rule 13.1): genotype AND expression."""
    return await snapshot.agent_inspect(app.state.pg, agent_uuid)


@app.get("/agents/{agent_uuid}/decisions", tags=["Agent"])
async def get_agent_decisions(agent_uuid: str, limit: int = 20):
    return await snapshot.agent_decisions(app.state.pg, agent_uuid, limit)


@app.get("/worlds/{realm}/timeline", tags=["World"])
async def get_timeline(realm: str, before: str = "", limit: int = 50):
    return await snapshot.world_timeline(app.state.pg, realm, before, limit)


@app.get("/worlds/{realm}/events", tags=["World"])
async def get_events(realm: str, since: str = ""):
    return await snapshot.world_events(app.state.pg, realm, since)
