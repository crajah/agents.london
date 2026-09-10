"""Phase 0 tenant-directory regression: the tenant_id derivation and claim.

The storage half (post-graph) is exercised live against the deployed service;
these cover the pure logic that must never regress — one person maps to one
deterministic tenant, and every minted token carries the tenant_id claim.
"""
import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# app.py fails closed without a signing key, so provision a throwaway one
# before importing it.
_k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ.setdefault("AUTHORITY_JWT_KEY", _k.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode())
os.environ.setdefault("AUTHORITY_VAULT_KEY",
                      base64.b64encode(os.urandom(32)).decode())

import app as app_mod  # noqa: E402


def test_tenant_id_is_deterministic_from_sub():
    assert app_mod.tenant_id_from_sub("u:abc123") == "t:abc123"
    assert app_mod.tenant_id_from_sub("u:abc123") == \
        app_mod.tenant_id_from_sub("u:abc123")
    # a sub without the u: prefix still maps stably
    assert app_mod.tenant_id_from_sub("plain") == "t:plain"


def test_minted_token_carries_tenant_claim():
    import jwt
    tok = app_mod.mint("u:deadbeef", "google", email="A@Example.com")
    claims = jwt.decode(tok, app_mod._pub_pem, algorithms=["RS256"],
                        issuer=app_mod.BASE)
    assert claims["tenant_id"] == "t:deadbeef"
    assert claims["sub"] == "u:deadbeef"
    assert claims["email"] == "a@example.com"      # normalised


def test_explicit_tenant_id_overrides_default():
    """Multi-owner tenants: an explicit tenant_id (from the directory) wins
    over the sub-derived default, so two subs can share one tenant."""
    import jwt
    tok = app_mod.mint("u:someone", "google", tenant_id="t:shared_co")
    claims = jwt.decode(tok, app_mod._pub_pem, algorithms=["RS256"],
                        issuer=app_mod.BASE)
    assert claims["tenant_id"] == "t:shared_co"
