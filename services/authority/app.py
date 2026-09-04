"""Authority — the platform's one front door (Phase A).

One OIDC broker for Google and Microsoft; one identity (the Rule 6.2i
normalised-email hash, byte-identical to genome's, so no migration); short
RS256 JWTs verified LOCALLY by every service via /jwks.json — the authority
sits in the login path, never the request path.

Phase C (realm grants / token exchange) and Phase D (BYOK vault) land on
this base; /exchange is stubbed to say so.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("authority")

app = FastAPI(title="authority", docs_url=None, redoc_url=None)

PROVIDERS = {
    "google": {
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "id_env": "GOOGLE_CLIENT_ID", "secret_env": "GOOGLE_CLIENT_SECRET",
    },
    "microsoft": {
        "auth": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
        "id_env": "MS_CLIENT_ID", "secret_env": "MS_CLIENT_SECRET",
    },
}

BASE = os.getenv("AUTHORITY_REDIRECT_BASE", "http://localhost:8810")
PREFIX = os.getenv("AUTHORITY_PATH_PREFIX", "")
STATE_KEY = os.getenv("AUTHORITY_STATE_KEY", "dev-only").encode()
TOKEN_TTL = int(os.getenv("AUTHORITY_TOKEN_TTL", "900"))       # 15 minutes
ALLOWED_RETURN = tuple(os.getenv(
    "AUTHORITY_ALLOWED_RETURN",
    "https://agents.london/,http://localhost").split(","))

_PRIV = os.getenv("AUTHORITY_JWT_KEY", "")
if not _PRIV:
    raise SystemExit("AUTHORITY_JWT_KEY (PEM private key) is required")
from cryptography.hazmat.primitives import serialization
_key = serialization.load_pem_private_key(_PRIV.encode(), password=None)
_pub_pem = _key.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo).decode()
KID = hashlib.sha256(_pub_pem.encode()).hexdigest()[:12]


@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    if PREFIX and request.url.path.startswith(PREFIX):
        request.scope["path"] = request.url.path[len(PREFIX):] or "/"
    return await call_next(request)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def user_id_from_email(email: str) -> str:
    """BYTE-IDENTICAL to genome's Rule 6.2i hash: one person, one id,
    whatever door they came through and whichever app they land in."""
    return "u:" + hashlib.sha256(
        normalise_email(email).encode()).hexdigest()[:20]


def _sign_state(doc: dict) -> str:
    payload = json.dumps(doc, separators=(",", ":"))
    sig = hmac.new(STATE_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.quote(payload + "|" + sig)


def _verify_state(raw: str) -> dict | None:
    try:
        payload, sig = urllib.parse.unquote(raw).rsplit("|", 1)
        good = hmac.new(STATE_KEY, payload.encode(),
                        hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good):
            doc = json.loads(payload)
            if doc.get("exp", 0) > time.time():
                return doc
    except Exception:
        pass
    return None


def mint(sub: str, provider: str, grants: list | None = None,
         email: str | None = None) -> str:
    """The email rides as a CLAIM in a 15-minute same-site token -- transit,
    not storage; the authority itself keeps nothing. Apps that key tenancy
    off the address (civilization) read it; apps that key off the hash
    (genome) ignore it."""
    now = int(time.time())
    doc = {"iss": BASE, "sub": sub, "iat": now, "exp": now + TOKEN_TTL,
           "provider": provider, "grants": grants or []}
    if email:
        doc["email"] = normalise_email(email)
    return jwt.encode(doc, _key, algorithm="RS256", headers={"kid": KID})


def verify(token: str) -> dict | None:
    try:
        return jwt.decode(token, _pub_pem, algorithms=["RS256"],
                          issuer=BASE)
    except Exception:
        return None


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:]
    return request.cookies.get("authority_token")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "authority", "kid": KID}


@app.get("/jwks.json")
async def jwks():
    from cryptography.hazmat.primitives.asymmetric import rsa
    pub = _key.public_key().public_numbers()

    def b64u(i: int, length: int) -> str:
        import base64
        return base64.urlsafe_b64encode(
            i.to_bytes(length, "big")).rstrip(b"=").decode()
    n_len = (pub.n.bit_length() + 7) // 8
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256",
                      "kid": KID, "n": b64u(pub.n, n_len),
                      "e": b64u(pub.e, 3)}]}


@app.get("/login/{provider}")
async def login(provider: str, return_to: str = ""):
    if provider not in PROVIDERS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)
    if return_to and not (return_to.startswith("/") or
                          return_to.startswith(ALLOWED_RETURN)):
        return JSONResponse({"error": "return_to not allowed"},
                            status_code=400)
    p = PROVIDERS[provider]
    state = _sign_state({"r": return_to or "/",
                         "exp": int(time.time()) + 600})
    q = urllib.parse.urlencode({
        "client_id": os.environ[p["id_env"]],
        "redirect_uri": BASE + "/callback/" + provider,
        "response_type": "code", "scope": p["scope"], "state": state})
    return RedirectResponse(p["auth"] + "?" + q)


@app.get("/callback/{provider}")
async def callback(provider: str, code: str = "", state: str = "",
                   error: str = ""):
    if provider not in PROVIDERS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)
    doc = _verify_state(state)
    if doc is None:
        return JSONResponse({"error": "state invalid or expired"},
                            status_code=400)
    if error or not code:
        return JSONResponse({"error": error or "no code"}, status_code=400)
    p = PROVIDERS[provider]
    body = urllib.parse.urlencode({
        "client_id": os.environ[p["id_env"]],
        "client_secret": os.environ[p["secret_env"]],
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": BASE + "/callback/" + provider}).encode()
    rq = urllib.request.Request(
        p["token"], data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(rq, timeout=30) as r:
        tok = json.load(r)
    rq2 = urllib.request.Request(
        p["userinfo"],
        headers={"Authorization": "Bearer " + tok["access_token"]})
    with urllib.request.urlopen(rq2, timeout=30) as r:
        userinfo = json.load(r)
    email = userinfo.get("email")
    if not email:
        return JSONResponse({"error": "provider withheld the email claim"},
                            status_code=400)
    token = mint(user_id_from_email(email), provider, email=email)
    dest = doc.get("r") or "/"
    sep = "&" if "?" in dest else "?"
    resp = RedirectResponse(dest + sep + "authority_token=" + token)
    resp.set_cookie("authority_token", token, max_age=TOKEN_TTL,
                    secure=BASE.startswith("https"), samesite="lax",
                    path="/")
    return resp


@app.get("/me")
async def me(request: Request):
    tok = _bearer(request)
    claims = verify(tok) if tok else None
    if not claims:
        return JSONResponse({"authenticated": False}, status_code=401)
    return {"authenticated": True, **claims}


@app.post("/refresh")
async def refresh(request: Request):
    tok = _bearer(request)
    claims = verify(tok) if tok else None
    if not claims:
        return JSONResponse({"error": "invalid token"}, status_code=401)
    return {"token": mint(claims["sub"], claims.get("provider", "?"),
                          claims.get("grants"), claims.get("email"))}


import re as _re

APP_RE = _re.compile(r"^[a-z][a-z0-9-]{1,23}$")
SPACE_RE = _re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
EXCHANGE_TTL = int(os.getenv("AUTHORITY_EXCHANGE_TTL", "300"))


@app.post("/exchange")
async def exchange(request: Request):
    """Phase C: a service presents the user's token and asks for a realm.
    The FIRST policy is a namespace convention, and it is stateless on
    purpose: the realm `{app}--{sub}` (plus an optional `--{space}`) is the
    user's own ground in that app -- docs--u:abc123--contracts -- and
    OWNERSHIP of one's own namespace needs no grant table. The scoped
    token that comes back lives five minutes and names exactly one realm;
    the service enforces the claim at its own boundary, post-graph stays
    auth-blind. Cross-user sharing is the day a grant TABLE arrives; the
    token shape will not change."""
    tok = _bearer(request)
    claims = verify(tok) if tok else None
    if not claims:
        return JSONResponse({"error": "invalid token"}, status_code=401)
    try:
        body = json.loads((await request.body()) or b"{}")
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    app_name = str(body.get("app", ""))
    space = str(body.get("space", "") or "")
    if not APP_RE.match(app_name):
        return JSONResponse(
            {"error": "app must be 2-24 chars of [a-z0-9-], starting "
             "with a letter"}, status_code=400)
    if space and not SPACE_RE.match(space):
        return JSONResponse(
            {"error": "space must be 1-24 chars of [a-z0-9-]"},
            status_code=400)
    realm = f"{app_name}--{claims['sub']}" + (f"--{space}" if space else "")
    now = int(time.time())
    scoped = jwt.encode(
        {"iss": BASE, "sub": claims["sub"], "iat": now,
         "exp": now + EXCHANGE_TTL, "provider": claims.get("provider", "?"),
         "grants": [{"realm": realm, "role": "owner"}]},
        _key, algorithm="RS256", headers={"kid": KID})
    return {"realm": realm, "token": scoped, "ttl": EXCHANGE_TTL}
