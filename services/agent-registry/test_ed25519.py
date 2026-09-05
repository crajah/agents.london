"""Signature verification: real Ed25519 when a real key is registered,
the honest checksum answer otherwise. Only the cryptographic path may
say `verified`."""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app as registry


def _keypair():
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes_raw()
    return private, raw.hex()


def test_hex_key_parses_and_pem_key_parses():
    _, hexkey = _keypair()
    assert registry._parse_ed25519_key(hexkey) is not None
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat)
    private = Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    assert registry._parse_ed25519_key(pem) is not None


def test_labels_are_not_keys():
    assert registry._parse_ed25519_key("pk_agent_alpha") is None
    assert registry._parse_ed25519_key("") is None
    assert registry._parse_ed25519_key("zz" * 32) is None   # not hex


def test_signature_roundtrip_verifies():
    private, hexkey = _keypair()
    payload = b"the agent's manifest, exactly these bytes"
    sig = private.sign(payload).hex()
    key = registry._parse_ed25519_key(hexkey)
    key.verify(bytes.fromhex(sig), payload)   # raises on mismatch


def test_wrong_signature_fails():
    import pytest
    private, hexkey = _keypair()
    other = Ed25519PrivateKey.generate()
    sig = other.sign(b"payload").hex()
    key = registry._parse_ed25519_key(hexkey)
    with pytest.raises(Exception):
        key.verify(bytes.fromhex(sig), b"payload")
