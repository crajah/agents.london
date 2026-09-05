"""OIDC login — Phase 5 (user decision: Google or Microsoft, OAuth code flow).

Credentials come from the oidc-auth-secret already provisioned in the cluster.
On FIRST login a user receives their world and their free first agent
(genome-spec Rules 2.1/7.1: the genesis exemption), generated from a seed
derived from their subject id so re-login is idempotent.

Sessions are signed cookies (HMAC over the user id) — enough for the demo
surface; hardening (expiry, rotation, CSRF) is deploy-phase work, listed in
BUILD Phase 5.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

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

SESSION_KEY = os.getenv("GENOME_SESSION_KEY", "dev-only-key").encode()
REDIRECT_BASE = os.getenv("GENOME_REDIRECT_BASE", "http://localhost:8800")


def login_url(provider: str, state: str) -> str:
    p = PROVIDERS[provider]
    q = urllib.parse.urlencode({
        "client_id": os.environ[p["id_env"]],
        "redirect_uri": f"{REDIRECT_BASE}/auth/{provider}/callback",
        "response_type": "code", "scope": p["scope"], "state": state})
    return f"{p['auth']}?{q}"


def exchange_code(provider: str, code: str) -> dict:
    p = PROVIDERS[provider]
    body = urllib.parse.urlencode({
        "client_id": os.environ[p["id_env"]],
        "client_secret": os.environ[p["secret_env"]],
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": f"{REDIRECT_BASE}/auth/{provider}/callback"}).encode()
    rq = urllib.request.Request(p["token"], data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(rq, timeout=30) as r:
        tok = json.load(r)
    rq2 = urllib.request.Request(p["userinfo"],
        headers={"Authorization": f"Bearer {tok['access_token']}"})
    with urllib.request.urlopen(rq2, timeout=30) as r:
        return json.load(r)


def session_cookie(user_id: str) -> str:
    payload = json.dumps({"uid": user_id, "iat": int(time.time())})
    sig = hmac.new(SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.quote(f"{payload}|{sig}")


def verify_cookie(value: str) -> str | None:
    try:
        raw = urllib.parse.unquote(value)
        payload, sig = raw.rsplit("|", 1)
        good = hmac.new(SESSION_KEY, payload.encode(),
                        hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good):
            return json.loads(payload)["uid"]
    except Exception:
        pass
    return None


def magic_token(user_id: str, ttl: int = 86400) -> str:
    """One-day link token: same HMAC key as sessions, distinct prefix so a
    session cookie can never be replayed as a verification and vice versa."""
    payload = json.dumps({"m": user_id, "exp": int(time.time()) + ttl})
    sig = hmac.new(SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.quote(f"{payload}|{sig}")


def verify_magic(token: str) -> str | None:
    try:
        raw = urllib.parse.unquote(token)
        payload, sig = raw.rsplit("|", 1)
        good = hmac.new(SESSION_KEY, payload.encode(),
                        hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good):
            doc = json.loads(payload)
            if doc.get("exp", 0) > time.time():
                return doc.get("m")
    except Exception:
        pass
    return None


def normalise_email(email: str) -> str:
    return email.strip().lower()


def user_id_from_email(email: str) -> str:
    """Rule 6.2i: ONE identity per person -- the hash of the normalised email,
    whatever door they came through."""
    return f"u:{hashlib.sha256(normalise_email(email).encode()).hexdigest()[:20]}"


def user_id_from(provider: str, userinfo: dict) -> str:
    email = userinfo.get("email")
    if email:
        return user_id_from_email(email)
    # a provider that withholds email falls back to its subject -- the same
    # person via another door will NOT converge; surfaced in /me as unlinked
    sub = userinfo.get("sub")
    return f"{provider}:{hashlib.sha256(str(sub).encode()).hexdigest()[:16]}"


# --- authority acceptance (Phase B, 2026-09-04) -------------------------
# The platform front door mints RS256 JWTs whose sub is THE SAME Rule 6.2i
# hash this file computes -- so accepting one is verification plus nothing.
AUTHORITY_JWKS = os.getenv("AUTHORITY_JWKS_URL",
                           "http://authority-service:8810/jwks.json")
AUTHORITY_ISS = os.getenv("AUTHORITY_ISSUER",
                          "https://agents.london/authority")
_jwks_client = None


def authority_claims(token: str) -> dict | None:
    """The full claim set from a valid authority JWT, else None. The email
    claim rides along for world genesis; the sub is the Rule 6.2i hash.
    Key fetch is cached by PyJWKClient; the authority stays out of the
    request path."""
    global _jwks_client
    if not token:
        return None
    try:
        import jwt as _jwt
        from jwt import PyJWKClient
        if _jwks_client is None:
            _jwks_client = PyJWKClient(AUTHORITY_JWKS, cache_keys=True)
        key = _jwks_client.get_signing_key_from_jwt(token).key
        return _jwt.decode(token, key, algorithms=["RS256"],
                           issuer=AUTHORITY_ISS,
                           options={"require": ["exp", "iss", "sub"]})
    except Exception:
        return None


def verify_authority(token: str) -> str | None:
    """Returns the platform user id from a valid authority JWT, else None."""
    claims = authority_claims(token)
    return claims.get("sub") if claims else None
