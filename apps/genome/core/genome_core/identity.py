"""Identity and trust — genome-spec.md §6 (Rules 6.4–6.16).

Chain: root -> world -> agent. The root is a purpose-built self-signed CA
(Rule 6.5); each world holds an intermediate; an agent's identity is
H(genotype ‖ birth_world_uuid ‖ agent_uuid) (Rules 6.7/6.7a), certified by its
birth world. Certificates never expire and there is no agent-level revocation
(Rules 6.13/6.14). A transfer is a signed assertion bearing a monotonic
counter; a replayed counter is rejected (Rules 6.9/6.11/6.12).

Ed25519 via `cryptography`. The hash is stdlib; everything needing signatures
degrades with a clear ImportError so stdlib-only test runs can skip.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.hazmat.primitives import serialization
    HAVE_CRYPTO = True
except ImportError:            # stdlib-only environments skip signature tests
    HAVE_CRYPTO = False


def identity_hash(genotype: dict, birth_world_uuid: str, agent_uuid: str) -> str:
    """Rule 6.7: H(genotype ‖ birth_world_uuid ‖ agent_uuid). The genotype is
    hashed, never disclosed (Rule 6.8): canonical JSON keeps the digest stable
    across dict orderings."""
    canon = json.dumps(genotype, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        f"{canon}\x00{birth_world_uuid}\x00{agent_uuid}".encode()).hexdigest()


def _canon(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Keypair:
    private_pem: bytes
    public_pem: bytes

    @staticmethod
    def generate() -> "Keypair":
        k = Ed25519PrivateKey.generate()
        return Keypair(
            k.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()),
            k.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo))


def sign(private_pem: bytes, doc: dict) -> str:
    key = serialization.load_pem_private_key(private_pem, password=None)
    return key.sign(_canon(doc)).hex()


def verify(public_pem: bytes, doc: dict, signature_hex: str) -> bool:
    try:
        key = serialization.load_pem_public_key(public_pem)
        key.verify(bytes.fromhex(signature_hex), _canon(doc))
        return True
    except Exception:
        return False


# --- the chain ---

def make_root() -> dict:
    """Rule 6.5: purpose-built, self-signed. Never a public TLS leaf."""
    kp = Keypair.generate()
    doc = {"kind": "genome-root", "public_pem": kp.public_pem.decode()}
    return {"doc": doc, "signature": sign(kp.private_pem, doc),
            "private_pem": kp.private_pem.decode()}


def issue_world_cert(root: dict, world_uuid: str) -> dict:
    """Root signs a world's key (Rule 6.6). The world's private half stays with
    the world; only the signed doc travels."""
    kp = Keypair.generate()
    doc = {"kind": "genome-world", "world_uuid": world_uuid,
           "public_pem": kp.public_pem.decode()}
    return {"doc": doc,
            "signature": sign(root["private_pem"].encode(), doc),
            "private_pem": kp.private_pem.decode()}


def issue_agent_cert(world_cert: dict, agent_uuid: str, ident: str) -> dict:
    """Birth world certifies the agent's identity hash (Rules 6.6/6.7). No
    expiry (6.13). The agent needs no keypair of its own for transfers — the
    ORIGIN WORLD signs assertions about it (Rule 6.9)."""
    doc = {"kind": "genome-agent", "agent_uuid": agent_uuid,
           "identity": ident,
           "birth_world_uuid": world_cert["doc"]["world_uuid"]}
    return {"doc": doc,
            "signature": sign(world_cert["private_pem"].encode(), doc)}


def verify_chain(root_public_pem: bytes, world_cert: dict,
                 agent_cert: dict) -> bool:
    """root -> world -> agent (Rule 6.6)."""
    if not verify(root_public_pem, world_cert["doc"], world_cert["signature"]):
        return False
    wpub = world_cert["doc"]["public_pem"].encode()
    return verify(wpub, agent_cert["doc"], agent_cert["signature"])


# --- transfer assertions (Rules 6.9–6.12) ---

def make_transfer(world_cert: dict, agent_cert: dict, counter: int,
                  to_world_uuid: str) -> dict:
    doc = {"kind": "genome-transfer",
           "agent_uuid": agent_cert["doc"]["agent_uuid"],
           "identity": agent_cert["doc"]["identity"],
           "from_world": world_cert["doc"]["world_uuid"],
           "to_world": to_world_uuid,
           "counter": counter}
    return {"doc": doc,
            "signature": sign(world_cert["private_pem"].encode(), doc)}


def accept_transfer(root_public_pem: bytes, origin_world_cert: dict,
                    agent_cert: dict, assertion: dict,
                    last_counter_seen: int,
                    birth_world_cert: dict | None = None) -> tuple[bool, str]:
    """Destination-side check (Rules 6.6/6.9/6.11/6.12). Two distinct trust
    questions, learned the hard way when an agent tried to leave the commons:
    the agent's certificate chains through its BIRTH world (6.6), while the
    assertion is signed by the ORIGIN world of this crossing (6.9). They
    coincide only when an agent departs home."""
    chain_cert = birth_world_cert or origin_world_cert
    if not verify_chain(root_public_pem, chain_cert, agent_cert):
        return False, "chain invalid"
    if not verify(root_public_pem, origin_world_cert["doc"],
                  origin_world_cert["signature"]):
        return False, "origin world cert invalid"
    wpub = origin_world_cert["doc"]["public_pem"].encode()
    if not verify(wpub, assertion["doc"], assertion["signature"]):
        return False, "assertion signature invalid"
    if assertion["doc"]["identity"] != agent_cert["doc"]["identity"]:
        return False, "identity mismatch"
    if assertion["doc"]["counter"] <= last_counter_seen:
        return False, "replay: counter not fresh"
    return True, "ok"
