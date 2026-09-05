"""A token has to prove something before a session is granted on it.

There is now exactly one door: the platform authority. Google and Microsoft
sign people in over there; what arrives here is the authority's own RS256
token, checked against the authority's JWKS. The routes that used to accept
provider id_tokens directly — and the email route that accepted a bare
address as an identity — are gone, and these tests pin that they stay gone.
"""
from __future__ import annotations

import base64
import json
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import main


def forged(payload: dict) -> str:
    """A JWT with no signing key behind it. This is the whole attack."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.not-a-signature"


@pytest.fixture()
def client():
    return TestClient(main.app)


# ------------------------------------------------------- the doors that closed

def test_the_email_door_is_gone(client):
    r = client.post("/api/auth/email/session", json={"email": "a@b.com"})
    assert r.status_code in (404, 405)


def test_the_direct_google_door_is_gone(client):
    r = client.post("/api/auth/google/verify", json={"id_token": "x"})
    assert r.status_code in (404, 405)


def test_the_direct_microsoft_door_is_gone(client):
    r = client.post("/api/auth/ms/verify", json={"id_token": "x"})
    assert r.status_code in (404, 405)


# ------------------------------------------------------ the door that remains

class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    """Stands in for PyJWKClient so the test never leaves the process."""

    def __init__(self, public_key):
        self._pub = public_key

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(self._pub)


@pytest.fixture()
def authority_keys(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(main, "_authority_jwks_client",
                        _FakeJWKSClient(private.public_key()))
    issuer = "https://agents.london/authority"
    monkeypatch.setenv("AUTHORITY_ISSUER", issuer)

    def mint(claims: dict) -> str:
        now = int(time.time())
        doc = {"iss": issuer, "sub": "u:test", "iat": now, "exp": now + 300}
        doc.update(claims)
        return pyjwt.encode(doc, private, algorithm="RS256")

    return mint


def test_a_forged_token_is_refused(client, monkeypatch):
    monkeypatch.setattr(main, "_authority_jwks_client", None)
    r = client.post("/api/auth/authority/session",
                    json={"token": forged({"email": "attacker@corp.com"})})
    assert r.status_code == 401


def test_not_a_jwt_at_all_is_refused(client, monkeypatch):
    monkeypatch.setattr(main, "_authority_jwks_client", None)
    r = client.post("/api/auth/authority/session", json={"token": "rubbish"})
    assert r.status_code == 401


def test_a_valid_token_without_email_is_refused(client, authority_keys):
    r = client.post("/api/auth/authority/session",
                    json={"token": authority_keys({})})
    assert r.status_code == 400
    assert "email" in r.json()["detail"]


def test_a_valid_token_grants_a_verified_session(client, authority_keys):
    r = client.post("/api/auth/authority/session",
                    json={"token": authority_keys({"email": "Dev@Corp.com"})})
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True
    assert body["method"] == "authority"
    assert body["email"] == "dev@corp.com"
    assert body["user_id"]
    assert body["org_id"]


def test_an_expired_token_is_refused(client, authority_keys):
    token = authority_keys({"email": "dev@corp.com",
                            "exp": int(time.time()) - 10})
    r = client.post("/api/auth/authority/session", json={"token": token})
    assert r.status_code == 401
