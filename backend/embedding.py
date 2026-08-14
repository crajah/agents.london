"""Embedding vectors for discovery, shared by the agent and tool registries.

One module because one dimension: agent-graph-spec §3 and tool-registry-spec
§3.1 both declare `vector(1536)`, and a second implementation is a second place
for that to drift. A mismatch is not caught by a type — it surfaces as a
pgvector dimension error at query time, in a code path far from the config.

Embedding is a *discovery* concern, not a correctness one. A registration whose
embedding could not be computed is still a valid registration: the agent runs,
the pipeline pins it, the audit trail is intact. Only similarity search is
degraded. So `embed()` returns None on failure rather than raising, and the
caller records that it is missing (§Rule E.2) so it can be backfilled instead
of being silently absent forever.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = int(os.getenv("RAG_EMBEDDING_DIM", "1536"))
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001")
MODEL_ROUTER_URL = os.getenv("OPENAI_API_BASE",
                             os.getenv("LITELLM_URL", "http://localhost:4000/v1"))
API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "20"))


def discovery_text(*parts: Optional[str]) -> str:
    """The text an entity is embedded from: its name, purpose and capabilities.

    Joined with newlines rather than spaces so the model sees them as distinct
    fields. Empty parts are dropped rather than contributing blank lines, which
    would otherwise make two entities with different missing fields embed
    differently for no semantic reason.
    """
    return "\n".join(p.strip() for p in parts if p and p.strip())


async def embed(text: str) -> Optional[List[float]]:
    """One embedding, or None if the embedding service could not produce it.

    Never raises. See the module docstring: a discovery index is worth having
    and is not worth failing a write for.
    """
    if not text.strip():
        return None
    # `dimensions` is stated rather than assumed. Several embedding models can
    # return more than one width, and the one they default to is a provider
    # decision that can change between deployments — while the `vector(N)`
    # column cannot. Asking for the width the schema declares turns a silent
    # mismatch into a request the provider either honours or rejects.
    body = {"model": EMBEDDING_MODEL, "input": text, "dimensions": EMBEDDING_DIM}
    try:
        async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as http:
            res = await http.post(f"{MODEL_ROUTER_URL.rstrip('/')}/embeddings",
                                  headers={"Authorization": f"Bearer {API_KEY}"},
                                  json=body)
    except httpx.HTTPError as e:
        logger.warning("embedding service unreachable (%s); "
                       "registration proceeds without a discovery vector", e)
        return None
    if res.status_code != 200:
        logger.warning("embedding service returned %s: %s; registration proceeds "
                       "without a discovery vector", res.status_code, res.text[:200])
        return None

    try:
        vector = res.json()["data"][0]["embedding"]
    except (KeyError, IndexError, ValueError):
        logger.warning("embedding response was not in the expected shape; "
                       "registration proceeds without a discovery vector")
        return None

    if len(vector) != EMBEDDING_DIM:
        # Stored anyway would mean a pgvector dimension error on the next
        # search, attributed to whichever query happened to run first rather
        # than to the misconfigured model that caused it.
        logger.error("embedding model %r returned %d dimensions, expected %d; "
                     "discarding. Check RAG_EMBEDDING_MODEL.",
                     EMBEDDING_MODEL, len(vector), EMBEDDING_DIM)
        return None
    return vector


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, for ranking candidates already in memory.

    Used only where the candidate set is small and already loaded; anything
    larger belongs in pgvector, which has an index.
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def mark(payload: Dict[str, Any], vector: Optional[List[float]]) -> Dict[str, Any]:
    """Record on the payload whether a discovery vector was computed.

    A NULL embedding column is indistinguishable from one that was never
    attempted, so a backfill job cannot tell what it still owes. This makes the
    absence explicit and queryable.
    """
    payload["embedding_status"] = "present" if vector else "missing"
    return payload
