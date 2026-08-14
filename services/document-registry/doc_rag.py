"""Indexing into and retrieving from post-graph-rag (spec §6, §8).

Every engine is opened with **realm = org_id, space = project_id**. The document
space travels as `collection` in the metadata and as a `document_space` extra,
because it is a filter within the project, not a partition of it (Rule 2.2):
two document spaces in one project share a knowledge graph, and entities
extracted from one may legitimately link to entities from the other. A caller
needing genuine isolation uses two projects.

The engine is opened per operation and closed on every path, including error
paths (Rule 6.4). Failing to close leaks a pooled connection per upload, and a
bulk ingest exhausts the pool.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from post_graph_rag import DocumentMetadata, GraphRAG, QueryParam, RAGConfig
from post_graph_rag.graph_store import RAGGraphStore

from doc_model import IndexOutcome, SpaceKey

logger = logging.getLogger(__name__)


def _require_capabilities() -> None:
    """Fail at import if post-graph-rag is too old, naming what is missing.

    Two capabilities are load-bearing here and both arrived in 1.5:
    `DocumentMetadata.doc_key`, which is how a document's chunks are found
    again, and `delete_document_chunks`, which is how a superseded revision's
    chunks are removed (Rule 7.2).

    Checked once at import rather than per request, for the same reason
    Rule 10.2 checks the API key at import: a service that starts and fails
    only on the first upload has already told the caller it was healthy.
    Feature-detecting and silently degrading would be worse still — it would
    leave superseded chunks in the index, where a query cites two contradictory
    revisions under one filename and nothing reports why.
    """
    missing = []
    if "doc_key" not in getattr(DocumentMetadata, "__dataclass_fields__", {}):
        missing.append("DocumentMetadata.doc_key")
    if not hasattr(RAGGraphStore, "delete_document_chunks"):
        missing.append("RAGGraphStore.delete_document_chunks")
    if missing:
        import post_graph_rag
        raise RuntimeError(
            f"post-graph-rag {getattr(post_graph_rag, '__version__', 'unknown')} is "
            f"too old: {', '.join(missing)} not available. The document registry "
            f"needs >= 1.5.2 (see requirements.txt) to identify and supersede a "
            f"document's chunks. Upgrade with: pip install -U 'post-graph-rag>=1.5.2'")


_require_capabilities()

MODEL_ROUTER_URL = os.getenv(
    "OPENAI_API_BASE",
    os.getenv("LITELLM_URL", "http://litellm-service.default.svc.cluster.local:80/v1"))

# Must match the agent and tool registries' vector columns (Rule 6.1). A
# mismatch is not caught by a type — it surfaces as a pgvector dimension error
# at query time, in a code path far from the config.
EMBEDDING_DIM = int(os.getenv("RAG_EMBEDDING_DIM", "1536"))


def config_for(key: SpaceKey, db_uri: str, api_key: str) -> RAGConfig:
    return RAGConfig(
        api_base=MODEL_ROUTER_URL,
        api_key=api_key,
        model=os.getenv("RAG_MODEL", os.getenv("DEFAULT_LLM_MODEL",
                                              "gemini-3.5-flash-lite")),
        embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dim=EMBEDDING_DIM,
        db_uri=db_uri,
        realm=key.org_id,          # organisation — physical isolation
        space=key.project_id,      # project — logical isolation
    )


@asynccontextmanager
async def engine(key: SpaceKey, db_uri: str, api_key: str):
    """An initialised GraphRAG engine, closed on every path (Rule 6.4)."""
    rag = GraphRAG(config_for(key, db_uri, api_key))
    await rag.initialize()
    try:
        yield rag
    finally:
        try:
            await rag.close()
        except Exception:
            # Indexing or querying already succeeded or failed on its own terms;
            # a close error must not change that outcome, but leaking a pooled
            # connection is worth seeing in the log.
            logger.exception("failed to close the GraphRAG engine")


def metadata_for(key: SpaceKey, filename: str, doc_id: str, digest: str,
                 source: str, category: str) -> DocumentMetadata:
    """RAG metadata for one document.

    `doc_key` is the registry's own `document_id`, which is what makes Rule 7.2
    possible: superseding a document can find and remove exactly its chunks
    rather than guessing from the filename.
    """
    return DocumentMetadata(
        source=source,
        category=category,
        collection=key.document_space,     # the third tier — a filter
        document=filename,
        space=key.project_id,              # post-graph space — the project
        doc_key=doc_id,
        content_hash=digest,
        extra={"document_space": key.document_space, "org_id": key.org_id},
    )


async def index(rag: GraphRAG, key: SpaceKey, text: str,
                metadata: DocumentMetadata) -> IndexOutcome:
    """Index one document, returning an outcome rather than raising (Rule 6.2).

    A failure here is recorded on the catalogue entry and returned to the
    caller. The document was extracted successfully, so it belongs in the
    catalogue (Rule 4.1) — but it is not retrievable, and those are different
    states that must not both be reported as success. A document that uploads
    cleanly and is silently absent from every subsequent search is the hardest
    failure in this service to diagnose from the outside.
    """
    try:
        raw = await rag.index_document(text, metadata=metadata, space=key.project_id)
        return IndexOutcome.succeeded(raw if isinstance(raw, dict) else {})
    except Exception as e:
        logger.exception("GraphRAG indexing failed for %s", metadata.document)
        return IndexOutcome.failed(f"{type(e).__name__}: {e}")


async def drop_chunks(rag: GraphRAG, key: SpaceKey, doc_id: str) -> Dict[str, Any]:
    """Remove a superseded revision's chunks from the index (Rule 7.2).

    Leaving them means a query can retrieve and cite the old revision alongside
    the new one, and the citation names the same filename in both cases — so
    the caller has no way to see that two contradictory passages came from two
    versions of one file.
    """
    try:
        return await rag.store.delete_document_chunks(doc_id, space=key.project_id)
    except Exception as e:
        logger.exception("could not remove superseded chunks for %s", doc_id)
        return {"error": str(e)}


async def query(rag: GraphRAG, key: SpaceKey, question: str, top_k: int, mode: str,
                document_space: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve, scoped to the project and optionally filtered by document space.

    `document_space` is passed separately from `key` rather than read off it,
    because None here means *project-wide* (Rule 2.3) while `key.document_space`
    always has a concrete value. Reading the filter off the key would silently
    narrow every unscoped query to the "default" folder — the corpus would look
    mysteriously small and nothing would say why.
    """
    param = QueryParam(mode=mode, top_k=top_k, space=key.project_id)
    result = await rag.query_data(question, param=param)
    data = result.get("data", {}) if isinstance(result, dict) else {}
    metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    return {"data": filter_by_document_space(data, document_space),
            "metadata": metadata}


def filter_by_document_space(data: Dict[str, Any],
                             document_space: Optional[str]) -> Dict[str, Any]:
    """Narrow retrieved chunks to one document space (Rule 2.3).

    With no document space the whole project is in scope, which is the useful
    default: an agent asking a question rarely knows which folder the answer is
    filed under.
    """
    if not document_space or not isinstance(data, dict):
        return data
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        return data

    kept: List[Any] = []
    for chunk in chunks:
        meta = chunk.get("metadata", chunk) if isinstance(chunk, dict) else {}
        if not isinstance(meta, dict):
            continue
        name = (meta.get("document_space") or meta.get("collection")
                or (meta.get("extra") or {}).get("document_space"))
        if name == document_space:
            kept.append(chunk)
    return {**data, "chunks": kept}
