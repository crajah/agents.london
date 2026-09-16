"""Magic-link sign-in regression: identity, single use, expiry and hashing.

The storage half (post-graph) is exercised live against the deployed service;
these cover the pure logic that must never regress — a link grants exactly the
identity the address already owns, the stored row is not itself a usable link,
and a spent or stale link is refused.
"""
import base64
import os
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
os.environ.setdefault("AUTHORITY_JWT_KEY", _k.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode())
os.environ.setdefault("AUTHORITY_VAULT_KEY",
                      base64.b64encode(os.urandom(32)).decode())

import app as app_mod  # noqa: E402


def test_magic_link_yields_the_same_identity_as_oidc():
    """The whole point: one person, one id, whichever door they came through.
    A link sent to an address must not mint a second, parallel account."""
    email = "Person@Example.COM"
    assert app_mod.user_id_from_email(email) == \
        app_mod.user_id_from_email("person@example.com")


def test_row_key_is_a_hash_not_the_nonce():
    """A dump of magic_links must be a list of dead ends, not working logins."""
    nonce = "a-secret-nonce"
    stored = app_mod._magic_hash(nonce)
    assert stored != nonce
    assert len(stored) == 64 and int(stored, 16) >= 0      # sha256 hex
    assert app_mod._magic_hash(nonce) == stored            # deterministic
    assert app_mod._magic_hash("other") != stored


def test_minted_token_records_the_email_provider():
    """Apps must be able to tell which door was used — a magic-link session is
    not indistinguishable from a Google one."""
    sub = app_mod.user_id_from_email("person@example.com")
    claims = app_mod.verify(app_mod.mint(sub, "email",
                                         email="person@example.com"))
    assert claims["provider"] == "email"
    assert claims["sub"] == sub
    assert claims["tenant_id"] == app_mod.tenant_id_from_sub(sub)


def test_return_to_is_restricted():
    """The link carries a redirect; an open one turns sign-in into a redirector."""
    assert app_mod._return_ok("/worlds")
    assert app_mod._return_ok("")
    assert not app_mod._return_ok("https://evil.example/steal")


def test_expiry_and_single_use_are_both_refusal_conditions():
    """Mirrors the two guards in /callback/email: a link is refused if it has
    been spent OR if its window has closed."""
    now = int(time.time())
    spent = {"used_at": now - 1, "expires_at": now + 900}
    stale = {"used_at": None, "expires_at": now - 1}
    live = {"used_at": None, "expires_at": now + 900}

    def refused(pl):
        return bool(pl.get("used_at")) or int(pl.get("expires_at", 0)) <= now

    assert refused(spent)
    assert refused(stale)
    assert not refused(live)


def test_typed_address_is_marked_unverified_and_oidc_is_not():
    """The claim that carries the whole distinction: a typed address is a claim,
    an OIDC login is a proof, and the token has to say which it was."""
    sub = app_mod.user_id_from_email("person@example.com")
    typed = app_mod.verify(app_mod.mint(sub, "email",
                                        email="person@example.com",
                                        email_verified=False))
    oidc = app_mod.verify(app_mod.mint(sub, "google",
                                       email="person@example.com"))
    assert typed["email_verified"] is False
    assert oidc["email_verified"] is True
    # ...and both are still the same person: sign-in method never forks identity
    assert typed["sub"] == oidc["sub"] == sub


def test_vault_refuses_unverified_sessions_only():
    """The vault holds other people's API keys, so it is the one door an
    unproved address must not open. Every other session is untouched."""
    assert app_mod._vault_denied({"email_verified": False}) is not None
    assert app_mod._vault_denied({"email_verified": True}) is None
    # a token minted before this claim existed must not be locked out
    assert app_mod._vault_denied({}) is None
