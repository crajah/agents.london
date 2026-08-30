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


def user_id_from(provider: str, userinfo: dict) -> str:
    sub = userinfo.get("sub") or userinfo.get("email")
    return f"{provider}:{hashlib.sha256(str(sub).encode()).hexdigest()[:16]}"
