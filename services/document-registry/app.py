"""Document Registry Microservice for agent.london

Manages document spaces per project and indexes their contents into
post-graph-rag. Docling parses uploads into structured Markdown before
indexing, because structure survives chunking and a flattened table does not.

Namespace (spec/document-registry-spec.md §2), three tiers:

    org_id         -> post-graph realm    -> a PostgreSQL schema      (physical)
    project_id     -> post-graph space    -> a column in that schema  (logical)
    document_space -> a grouping           -> metadata on the document (filter)

Every post-graph call is made with realm=org_id, space=project_id. The document
space is never passed as a post-graph space.
"""
import hashlib
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (FastAPI, File, Form, HTTPException, Query,
                     Request, UploadFile)

from post_graph import AsyncPostGraph

import doc_rag
import doc_store
from doc_extract import extract, extract_path
from env_file import load_env_file
from doc_model import (
    FAILED, INDEXED, WITHDRAWN, CreateSpaceRequest, DocumentError,
    ExtractionResult, RAGQueryRequest, SpaceKey, UploadTextRequest,
    catalogue_entry, content_hash, document_id, normalise_document_space,
)

logger = logging.getLogger(__name__)

# This service runs in its own container and cannot import the backend package,
# so it loads the same .env directly. It searches upward rather than indexing a
# fixed depth: the image flattens this file to /app/app.py, where the old
# `parents[2]` raised IndexError and the container could not start at all.
load_env_file()

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not _OPENAI_API_KEY:
    # Raised at import rather than at first query (Rule 10.2): a document
    # service that starts without a key accepts uploads and fails only once
    # embedding begins, after the caller has been told the upload succeeded.
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Add it to .env (see .env.example) or to the "
        "container environment.")
OPENAI_API_KEY: str = _OPENAI_API_KEY

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "crajah")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

DEFAULT_DB_URI = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
DB_URI = os.getenv("POSTGRES_URI", DEFAULT_DB_URI)

SCHEMA_PER_REALM = os.getenv("SCHEMA_PER_REALM", "1").lower() in ("1", "true", "yes")


@asynccontextmanager
async def pg_client(org_id: str = "org_default"):
    """A post-graph client at the configured DSN, or an error.

    Rule 10.1. Earlier behaviour tried the configured DSN and then three
    hardcoded localhost guesses with embedded credentials, returning whichever
    answered — so a typo in POSTGRES_URI did not fail; it silently wrote a
    tenant's documents to whatever local database happened to accept a guess.
    """
    client = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM)
    await client.connect()
    try:
        yield client
    finally:
        try:
            await client.close()
        except Exception:
            logger.exception("failed to close post-graph client for realm %r", org_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncPostGraph(dsn=DB_URI, schema_per_realm=SCHEMA_PER_REALM)
    await client.connect()
    app.state.pg_client = client
    app.state.pg_client_factory = pg_client

    # Metering is optional infrastructure: accounting must never be the reason
    # the registry will not start (AG Rule 12.2).
    app.state.meter = None
    try:
        from metering import configure
        app.state.meter = configure(pg_client)
        await app.state.meter.start()
    except Exception:
        logger.exception("metering unavailable; the document registry runs unmetered")

    try:
        yield
    finally:
        if app.state.meter:
            await app.state.meter.stop()
        await client.close()


tags_metadata = [
    {"name": "Document Spaces", "description": "Create and manage document spaces scoped per project."},
    {"name": "Document Upload & Ingestion", "description": "Upload PDFs, DOCX, PPTX, XLSX, Markdown with Docling extraction."},
    {"name": "GraphRAG Knowledge Queries", "description": "Query indexed knowledge graph vector memory across spaces or project-wide."},
    {"name": "Document Lifecycle", "description": "Revisions, reindexing and withdrawal."},
    {"name": "System", "description": "Health check and microservice status endpoints."},
]

app = FastAPI(
    title="agent.london Document Registry Microservice",
    description="""
    # 📄 agent.london Document Registry OpenAPI Specs

    Manages project document spaces, multi-document uploading, Docling structured text
    extraction, and `post-graph-rag` knowledge graph indexing.

    Namespace: `org_id` is the post-graph **realm**, `project_id` is the post-graph
    **space**, and `document_space` is a third tier — a filter within the project.

    - **Interactive Swagger Documentation:** [/docs](/docs)
    - **ReDoc API Documentation:** [/redoc](/redoc)
    - **OpenAPI Schema JSON:** [/openapi.json](/openapi.json)
    """,
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)


_OPEN_PREFIXES = ("/my/", "/health", "/docs", "/openapi.json", "/redoc")


@app.middleware("http")
async def _internal_gate(request: Request, call_next):
    """If DOCREG_INTERNAL_TOKEN is set, the org_id surface requires it --
    the /my/* routes are user-facing via authority tokens; everything else
    is internal plumbing and should not be reachable by whoever can reach
    the port (audit 2026-09-04). Unset = open, for compatibility.

    Two spellings are accepted because two kinds of caller exist: the
    civilization backend sends x-internal-token; the tool-registry executor
    dispatches with Authorization: Bearer (its `bearer` auth mode)."""
    tok = os.getenv("DOCREG_INTERNAL_TOKEN", "")
    path = request.url.path
    if tok and not any(path.startswith(p) for p in _OPEN_PREFIXES):
        offered = request.headers.get("x-internal-token", "")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            offered = offered or auth[7:]
        import hmac as _hmac
        if not _hmac.compare_digest(offered, tok):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "internal surface; token required"},
                                status_code=403)
    return await call_next(request)


def _client():
    client = getattr(app.state, "pg_client", None)
    if client is None:
        raise HTTPException(status_code=503,
                            detail="Document registry has no database connection.")
    return client


def _meter():
    return getattr(app.state, "meter", None)


def _record(kind: str, key: SpaceKey, payload_bytes: int, **extra) -> None:
    """One usage event (§9). Never raises into the request path (AG Rule 12.2)."""
    meter = _meter()
    if meter is None:
        return
    try:
        from metering import UsageEvent
        meter.record(UsageEvent(org_id=key.org_id, project_id=key.project_id,
                                kind=kind, bytes=payload_bytes, **extra))
    except Exception:
        logger.exception("metering failed for %s; the operation stands", kind)


# ----------------------------------------------------- authority (/my/*)
# The platform front door's scoped tokens (POST agents.london/authority/
# exchange, app="docs") open a USER'S OWN document ground here. On these
# routes the caller names no org: the token's grant IS the realm, verified
# against the authority's JWKS -- enforcement at this boundary, post-graph
# stays auth-blind. The org_id routes above remain the internal surface.
_authority_jwks_client = None


def _granted_docs_realm(request: Request) -> str:
    import jwt as _jwt
    from jwt import PyJWKClient
    global _authority_jwks_client
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("bearer "):
        raise HTTPException(status_code=401,
                            detail="A scoped authority token is required: "
                                   "POST /authority/exchange with "
                                   "app='docs'.")
    if _authority_jwks_client is None:
        _authority_jwks_client = PyJWKClient(
            os.getenv("AUTHORITY_JWKS_URL",
                      "http://authority-service:8810/jwks.json"),
            cache_keys=True)
    try:
        key = _authority_jwks_client.get_signing_key_from_jwt(h[7:]).key
        claims = _jwt.decode(
            h[7:], key, algorithms=["RS256"],
            issuer=os.getenv("AUTHORITY_ISSUER",
                             "https://agents.london/authority"),
            options={"require": ["exp", "iss", "sub"]})
    except Exception as e:
        raise HTTPException(status_code=401,
                            detail=f"Invalid authority token: {e}") from e
    for g in claims.get("grants") or []:
        realm = g.get("realm", "")
        if realm.startswith("docs_"):
            return realm
    raise HTTPException(status_code=403,
                        detail="This token grants no docs realm; exchange "
                               "with app='docs'.")


@app.post("/my/spaces", tags=["My Documents"])
async def my_create_space(request: Request, body: dict):
    realm = _granted_docs_realm(request)
    req = CreateSpaceRequest(org_id=realm,
                             project_id=body.get("project_id", "default"),
                             document_space=body.get("document_space",
                                                     "default"),
                             description=body.get("description"))
    return await create_document_space(req)


@app.get("/my/projects/{project_id}/documents", tags=["My Documents"])
async def my_list_documents(request: Request, project_id: str,
                            space_name: Optional[str] = Query(None)):
    realm = _granted_docs_realm(request)
    # a direct call resolves NO FastAPI defaults: every Query(...) param
    # must be passed, or the sentinel object reaches the handler
    return await list_project_documents(project_id,
                                        space_name=space_name,
                                        document_space=None,
                                        org_id=realm,
                                        include_withdrawn=False)


@app.post("/my/spaces/{space_name}/documents/upload-text",
          tags=["My Documents"])
async def my_upload_text(request: Request, space_name: str, body: dict):
    realm = _granted_docs_realm(request)
    try:
        req = UploadTextRequest(org_id=realm,
                                project_id=body.get("project_id", "default"),
                                space_name=space_name,
                                document_name=body["document_name"],
                                content=body["content"],
                                category=body.get("category", "unstructured"))
    except KeyError as e:
        raise HTTPException(status_code=422,
                            detail=f"missing field {e.args[0]!r}") from e
    return await upload_document_text(space_name, req)


@app.post("/my/query", tags=["My Documents"])
async def my_query(request: Request, body: dict):
    realm = _granted_docs_realm(request)
    if "query" not in body:
        raise HTTPException(status_code=422, detail="missing field 'query'")
    req = RAGQueryRequest(org_id=realm,
                          project_id=body.get("project_id", "default"),
                          document_space=body.get("document_space"),
                          query=body["query"])
    return await query_document_rag(req)


# --------------------------------------------------------------------- system

@app.get("/health", tags=["System"])
async def health_check():
    """Reports what is actually reachable (Rule 10.3).

    A health check that returns constants is a monitor for whether the process
    is running, which Kubernetes already knows.
    """
    database = "unreachable"
    try:
        await _client()._fetch("SELECT 1")
        database = "ok"
    except Exception as e:
        logger.warning("health: database unreachable: %s", e)

    docling = "unavailable"
    try:
        import importlib
        importlib.import_module("docling.document_converter")
        docling = "ok"
    except Exception as e:
        logger.warning("health: docling unavailable: %s", e)

    return {
        "status": "ok" if database == "ok" and docling == "ok" else "degraded",
        "service": "document-registry",
        "database": database,
        "docling": docling,
        "model_router": doc_rag.MODEL_ROUTER_URL,
        "embedding_dim": doc_rag.EMBEDDING_DIM,
        "metering": "on" if _meter() else "off",
    }


# --------------------------------------------------------------------- spaces

@app.post("/spaces", tags=["Document Spaces"])
async def create_document_space(req: CreateSpaceRequest):
    """Create a document space. Idempotent (Rule 3.2)."""
    key = SpaceKey(org_id=req.org_id, project_id=req.project_id,
                   document_space=req.document_space)
    space = await doc_store.create_space(
        _client(), key, req.description or "Document space for project domain knowledge")
    return {**space, "document_count": space.get("document_count", 0)}


@app.get("/projects/{project_id}/spaces", tags=["Document Spaces"])
async def list_document_spaces(project_id: str, org_id: str = Query("org_default")):
    """Every document space in a project, with derived counts (Rule 3.3)."""
    spaces = await doc_store.list_spaces(_client(), org_id, project_id)
    if not spaces:
        # A project with no spaces still has a default one to upload into.
        spaces = [{
            "space_key": f"{project_id}:default", "key": f"{project_id}:default",
            "org_id": org_id, "project_id": project_id,
            "document_space": "default", "space_name": "default",
            "description": "Default workspace document repository",
            "created_at": None, "document_count": 0}]
    return {"project_id": project_id, "org_id": org_id, "spaces": spaces}


@app.get("/projects/{project_id}/documents", tags=["Document Spaces"])
async def list_project_documents(project_id: str,
                                 space_name: Optional[str] = Query(None),
                                 document_space: Optional[str] = Query(None),
                                 org_id: str = Query("org_default"),
                                 include_withdrawn: bool = Query(False)):
    chosen = document_space or space_name
    documents = await doc_store.list_documents(
        _client(), org_id, project_id,
        normalise_document_space(chosen) if chosen else None, include_withdrawn)
    return {"project_id": project_id, "org_id": org_id,
            "document_space": chosen, "space_name": chosen,
            "documents": documents, "count": len(documents)}


# ------------------------------------------------------------------ ingestion

async def _ingest(key: SpaceKey, filename: str, digest: str, size: int,
                  text: str, extraction, content_type: Optional[str],
                  source: str, category: str) -> Dict[str, Any]:
    """Index one already-extracted document and catalogue the outcome.

    Order matters: extraction has already succeeded (Rule 4.1), so this
    document belongs in the catalogue whatever the index does. The index
    outcome is recorded rather than swallowed (Rule 6.2).
    """
    client = _client()
    # Retain the extracted text (capped) so /reindex can actually recover
    # a failed index -- without it every reindex 409ed forever (audit
    # 2026-09-04) and the only remedy was re-upload.
    retained_text = text[:524288] if text else ""

    # Rule 5.6 — identical bytes in the same document space is a no-op.
    duplicate = await doc_store.find_by_hash(
        client, key.org_id, key.project_id, key.document_space, digest)
    if duplicate:
        return {**duplicate, "deduplicated": True}

    doc_id = document_id(key.project_id, key.document_space, filename)
    existing = await doc_store.find_document(client, key.org_id, key.project_id, doc_id)

    async with doc_rag.engine(key, DB_URI, OPENAI_API_KEY) as rag:
        if existing:
            # Rule 7.2 — the superseded revision's chunks go, or a query can
            # cite both revisions under the same filename.
            await doc_rag.drop_chunks(rag, key, doc_id)
        metadata = doc_rag.metadata_for(key, filename, doc_id, digest, source, category)
        outcome = await doc_rag.index(rag, key, text, metadata)

    entry = catalogue_entry(key=key, filename=filename, digest=digest,
                            size=size, extraction=extraction,
                            index=outcome, content_type=content_type)
    entry["_text"] = retained_text
    saved = await doc_store.save_document(client, key, entry)
    saved.pop("_pk", None)

    _record("document_ingest", key, size)
    return saved


def _upload_response(document: Dict[str, Any], key: SpaceKey) -> Dict[str, Any]:
    """One upload's outcome, honest about whether it is retrievable (Rule 4.2)."""
    index = document.get("index", {})
    indexed = index.get("status") == INDEXED
    if document.get("deduplicated"):
        message = (f"'{document.get('filename')}' is already indexed in document "
                   f"space '{key.document_space}' with identical content.")
    elif indexed:
        message = (f"'{document.get('filename')}' extracted via "
                   f"{document.get('extraction_method')} and indexed into document "
                   f"space '{key.document_space}'.")
    else:
        message = (f"'{document.get('filename')}' was extracted via "
                   f"{document.get('extraction_method')} and catalogued, but "
                   f"INDEXING FAILED: {index.get('error')}. It is not retrievable "
                   f"until reindexed.")
    return {
        # Not "success" when the document is not retrievable: a document that
        # uploads cleanly and is absent from every subsequent search is the
        # hardest failure here to diagnose from the outside.
        "status": "success" if indexed or document.get("deduplicated") else "partial",
        "indexed": indexed,
        "message": message,
        "document_space": key.document_space,
        "space_name": key.document_space,
        "document": document,
    }


@app.post("/spaces/{space_name}/documents/upload-text",
          tags=["Document Upload & Ingestion"])
async def upload_document_text(space_name: str, req: UploadTextRequest):
    """Index raw text into a document space."""
    try:
        key = SpaceKey(org_id=req.org_id, project_id=req.project_id,
                       document_space=req.document_space or space_name)
    except DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    data = req.content.encode("utf-8")
    extraction = ExtractionResult(method="api_text", text=req.content,
                                  characters=len(req.content))
    document = await _ingest(key, req.document_name, content_hash(data),
                             len(data), req.content, extraction,
                             "text/plain", "api_upload", req.category or "text")
    return _upload_response(document, key)


MAX_UPLOAD_BYTES = int(os.getenv("DOCREG_MAX_UPLOAD_MB", "200")) * 1024 * 1024


async def _spool_upload(upload) -> tuple:
    """Stream an upload to a temp file in 64KB chunks, hashing as it goes.

    The raw bytes never sit whole in this process: two OOM kills came from
    `await upload.read()` holding entire files alongside the extractor's
    models (2026-09-05). Returns (path, digest, size); the caller owns the
    temp file and must unlink it. Over-limit uploads are refused with an
    honest 413 before they can take the pod down."""
    suffix = os.path.splitext(upload.filename or "")[1] or ".bin"
    digest = hashlib.sha256()
    size = 0
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await upload.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(f"{upload.filename!r} exceeds the "
                                f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload "
                                f"limit. Nothing was catalogued or indexed."))
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        os.unlink(path)
        raise
    return path, f"sha256:{digest.hexdigest()}", size


@app.post("/spaces/{space_name}/documents/upload-file",
          tags=["Document Upload & Ingestion"])
async def upload_document_file(space_name: str,
                               project_id: str = Form(...),
                               org_id: str = Form("org_default"),
                               document_space: Optional[str] = Form(None),
                               file: UploadFile = File(...)):
    """Upload one file, extract, index, catalogue."""
    try:
        key = SpaceKey(org_id=org_id, project_id=project_id,
                       document_space=document_space or space_name)
    except DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    path, digest, size = await _spool_upload(file)
    filename = file.filename or "uploaded_document"
    try:
        try:
            extraction = extract_path(path, filename)
        except DocumentError as e:
            # 415, not a placeholder (Rule 5.3). The file is not catalogued and
            # not indexed, because a catalogue entry is a claim the document is
            # in the corpus.
            raise HTTPException(status_code=415, detail=str(e)) from e
    finally:
        os.unlink(path)

    document = await _ingest(key, filename, digest, size, extraction.text,
                             extraction, file.content_type, filename,
                             "file_upload")
    return _upload_response(document, key)


@app.post("/spaces/{space_name}/documents/upload-multiple-files",
          tags=["Document Upload & Ingestion"])
async def upload_multiple_document_files(space_name: str,
                                         project_id: str = Form(...),
                                         org_id: str = Form("org_default"),
                                         document_space: Optional[str] = Form(None),
                                         files: List[UploadFile] = File(...)):
    """Upload several files. One file's failure does not fail the batch (Rule 5.5).

    Every file gets a per-file outcome and the response counts succeeded and
    failed separately. A batch that returns `status: success` with a count that
    silently excludes failures is a report the caller will read as complete.

    The extraction rule is identical to the single-file path (Rule 5.4). A batch
    endpoint more permissive than the endpoint it loops over is a way to bypass
    the check by uploading two files instead of one — which is exactly what the
    placeholder substitution that used to live here allowed.
    """
    try:
        key = SpaceKey(org_id=org_id, project_id=project_id,
                       document_space=document_space or space_name)
    except DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    succeeded: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for upload in files:
        filename = upload.filename or "uploaded_document"
        try:
            path, digest, size = await _spool_upload(upload)
        except HTTPException as e:
            failed.append({"filename": filename, "stage": "spool",
                           "error": e.detail})
            continue
        try:
            try:
                extraction = extract_path(path, filename)
            except DocumentError as e:
                failed.append({"filename": filename, "stage": "extraction",
                               "error": str(e)})
                continue
        finally:
            os.unlink(path)
        try:
            document = await _ingest(key, filename, digest, size,
                                     extraction.text, extraction,
                                     upload.content_type, filename,
                                     "file_upload")
        except Exception as e:
            logger.exception("ingest failed for %s", filename)
            failed.append({"filename": filename, "stage": "ingest", "error": str(e)})
            continue

        if document.get("index", {}).get("status") == FAILED:
            failed.append({"filename": filename, "stage": "indexing",
                           "error": document["index"].get("error"),
                           "catalogued": True})
            continue                      # catalogued, not a success
        succeeded.append(document)

    indexed = [d for d in succeeded if d.get("index", {}).get("status") == INDEXED
               or d.get("deduplicated")]
    return {
        "status": "success" if not failed else "partial",
        "message": (f"{len(indexed)} of {len(files)} files indexed into document "
                    f"space '{key.document_space}'"
                    + (f"; {len(failed)} failed" if failed else "")),
        "document_space": key.document_space,
        "space_name": key.document_space,
        "documents": succeeded,
        "failures": failed,
        "count": len(succeeded),
        "indexed_count": len(indexed),
        "failed_count": len(failed),
    }


# ------------------------------------------------------------------ lifecycle

@app.post("/projects/{project_id}/documents/{doc_id}/reindex",
          tags=["Document Lifecycle"])
async def reindex_document(project_id: str, doc_id: str,
                           org_id: str = Query("org_default")):
    """Re-index a document whose indexing previously failed (Rule 6.3).

    This exists precisely because Rule 6.2 leaves documents in a recoverable
    failed state. Without it the only remedy for a transient embedding outage
    is deleting and re-uploading every affected file.
    """
    client = _client()
    document = await doc_store.find_document(client, org_id, project_id, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"Unknown document {doc_id!r}.")

    revisions = await doc_store.revisions_of(client, org_id, document["_pk"])
    text = next((r.get("_text") for r in reversed(revisions) if r.get("_text")), None)
    if not text:
        # The extracted text is not retained on the catalogue entry — it lives
        # in the index. Re-indexing therefore needs the file again, and saying
        # so beats silently indexing an empty document.
        raise HTTPException(
            status_code=409,
            detail=(f"{doc_id} cannot be reindexed from the catalogue: the "
                    f"extracted text is not retained here. Re-upload the file "
                    f"to the same document space; it will be recorded as a new "
                    f"revision."))
    key = SpaceKey(org_id=org_id, project_id=project_id,
                   document_space=document.get("document_space", "default"))
    async with doc_rag.engine(key, DB_URI, OPENAI_API_KEY) as rag:
        await doc_rag.drop_chunks(rag, key, doc_id)
        metadata = doc_rag.metadata_for(key, document["filename"], doc_id,
                                        document.get("content_hash", ""),
                                        document["filename"], "reindex")
        outcome = await doc_rag.index(rag, key, text, metadata)
    updated = await doc_store.update_index_outcome(
        client, org_id, project_id, doc_id, outcome.model_dump(mode="json"))
    updated.pop("_pk", None)
    return {"status": outcome.status, "document": updated}


@app.delete("/projects/{project_id}/documents/{doc_id}", tags=["Document Lifecycle"])
async def withdraw_document(project_id: str, doc_id: str,
                            org_id: str = Query("org_default")):
    """Withdraw a document: chunks removed from the index, record retained (Rule 7.3).

    The record is what explains why a run from last month cited a document that
    is no longer in the corpus.
    """
    client = _client()
    document = await doc_store.find_document(client, org_id, project_id, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"Unknown document {doc_id!r}.")

    key = SpaceKey(org_id=org_id, project_id=project_id,
                   document_space=document.get("document_space", "default"))
    async with doc_rag.engine(key, DB_URI, OPENAI_API_KEY) as rag:
        removed = await doc_rag.drop_chunks(rag, key, doc_id)
    try:
        updated = await doc_store.set_lifecycle(client, org_id, project_id, doc_id,
                                                WITHDRAWN)
    except DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    updated.pop("_pk", None)
    return {"status": "withdrawn", "document_id": doc_id, "removed": removed,
            "document": updated,
            "note": "Catalogue record retained; chunks removed from the index."}


@app.get("/projects/{project_id}/documents/{doc_id}/revisions",
         tags=["Document Lifecycle"])
async def document_revisions(project_id: str, doc_id: str,
                             org_id: str = Query("org_default")):
    client = _client()
    document = await doc_store.find_document(client, org_id, project_id, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"Unknown document {doc_id!r}.")
    revisions = await doc_store.revisions_of(client, org_id, document["_pk"])
    document.pop("_pk", None)
    return {"document_id": doc_id, "current": document,
            "revisions": revisions, "count": len(revisions)}


# ------------------------------------------------------------------ retrieval

@app.post("/query", tags=["GraphRAG Knowledge Queries"])
async def query_document_rag(req: RAGQueryRequest):
    """Retrieve across a document space, or project-wide when none is named.

    Every response names the `engine` that produced it (Rule 8.1). An agent
    citing retrieved text is making a claim about provenance, and the strength
    of that claim depends on whether the text came from a graph traversal, a
    vector scan, or a filename listing.
    """
    key = SpaceKey(org_id=req.org_id, project_id=req.project_id,
                   document_space=req.document_space or "default")
    scope = req.document_space          # None means project-wide (Rule 2.3)

    try:
        async with doc_rag.engine(key, DB_URI, OPENAI_API_KEY) as rag:
            result = await doc_rag.query(rag, key, req.query, req.top_k, req.mode,
                                         document_space=scope)
        data = result["data"]
        chunks = data.get("chunks", []) if isinstance(data, dict) else []
        _record("rag_lookup", key, len(str(chunks).encode("utf-8")))
        return {
            "status": "success",
            "engine": "post-graph-rag",
            "org_id": req.org_id,
            "project_id": req.project_id,
            "document_space": scope or "all_document_spaces",
            "space_name": scope or "all_spaces",
            "data": data,
            "metadata": result.get("metadata", {}),
        }
    except Exception as e:
        logger.warning("GraphRAG query failed (%s); falling back to a direct "
                       "post-graph chunk read", e)
        rag_error = f"{type(e).__name__}: {e}"

    # Tier two: the chunks are there, the graph layer is not. Still a real
    # retrieval, but a weaker one, and it says so (Rule 8.2).
    try:
        chunks = await _direct_chunks(req, scope)
    except Exception as e:
        logger.exception("direct post-graph query failed")
        # Rule 8.3 — the in-memory tier is for an unreachable database, and
        # there is no in-memory corpus to fall back to. An empty corpus and a
        # broken index are different answers, and quietly turning the first
        # into a filename listing hides the second.
        raise HTTPException(
            status_code=503,
            detail=(f"Retrieval is unavailable: the knowledge graph failed "
                    f"({rag_error}) and the chunk store failed ({e}). No "
                    f"partial result is returned, because a filename listing "
                    f"presented as retrieval is evidence an agent will cite.")
        ) from e

    _record("rag_lookup", key, len(str(chunks).encode("utf-8")))
    return {
        "status": "degraded",
        "engine": "post-graph-direct",
        "warning": (f"The knowledge graph was unavailable ({rag_error}). These "
                    f"chunks come from a direct vector-free read: no entities, "
                    f"no relationships, no ranking."),
        "org_id": req.org_id,
        "project_id": req.project_id,
        "document_space": scope or "all_document_spaces",
        "space_name": scope or "all_spaces",
        "data": {
            "entities": [], "relationships": [],
            "chunks": chunks[:req.top_k],
            "references": [
                {"reference_id": f"[{i + 1}]",
                 "document": c.get("metadata", {}).get("document", f"Doc #{i + 1}")}
                for i, c in enumerate(chunks[:req.top_k])],
        },
    }


async def _direct_chunks(req: RAGQueryRequest,
                         document_space: Optional[str]) -> List[Dict[str, Any]]:
    """Read chunks straight from post-graph's `documents` table."""
    client = _client()
    vertices = await client.get_vertices("documents", realm=req.org_id,
                                         space=req.project_id)
    out = []
    for vertex in vertices:
        payload = vertex.payload if isinstance(vertex.payload, dict) else {}
        name = (payload.get("document_space") or payload.get("collection")
                or (payload.get("extra") or {}).get("document_space"))
        if document_space and name != document_space:
            continue
        out.append({"chunk_id": vertex.id,
                    "content": payload.get("text") or payload.get("content") or "",
                    "metadata": payload})
    return out


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
