"""Document registry model: the namespace, identity, and request shapes.

Rule numbers refer to spec/document-registry-spec.md.

**The namespace is the thing most likely to be misread**, because "space" means
two different things one level apart:

    org_id       ->  post-graph realm    ->  a PostgreSQL schema      (physical)
    project_id   ->  post-graph space    ->  a column in that schema  (logical)
    document_space ->  a grouping         ->  metadata on the document (filter)

`document_space` is the third tier and is **not** a post-graph space. It is
carried as `collection` in the RAG metadata and as `document_space` on the
catalogue vertex, and it is filtered on at query time. Passing it where
post-graph expects the project puts a project's documents in a partition its
own queries do not read, and the symptom is an empty result set from a corpus
that uploaded successfully (Rule 2.1).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Slug rule for a document space: it appears in URL paths and in RAG metadata
# filters, and a name needing escaping in one will eventually not be escaped in
# the other (Rule 3.1).
DOCUMENT_SPACE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$|^[a-z0-9]$")

DEFAULT_DOCUMENT_SPACE = "default"

INDEXED = "indexed"
PENDING = "pending"
FAILED = "failed"

ACTIVE = "active"
SUPERSEDED = "superseded"
WITHDRAWN = "withdrawn"


class DocumentError(ValueError):
    """A document operation was rejected. The message names the rule."""


def now() -> str:
    """ISO 8601 UTC.

    Not `asyncio.get_event_loop().time()`, which returns a monotonic float whose
    origin is the process start — a number that sorts correctly within one
    process run and means nothing across a restart or between replicas
    (Rule 3.4).
    """
    return datetime.now(timezone.utc).isoformat()


def content_hash(data: bytes) -> str:
    """sha256 of the uploaded bytes, before extraction (Rule 5.3).

    Hashing the bytes rather than the extracted text is deliberate: two
    different files can extract to the same text, and the same file can extract
    differently after a parser upgrade. The question this hash answers is "have
    I already ingested this exact artefact", and that is a question about the
    artefact.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalise_document_space(value: Optional[str]) -> str:
    """Accept a document space, or raise naming the rule (Rule 3.1)."""
    name = (value or DEFAULT_DOCUMENT_SPACE).strip()
    if not DOCUMENT_SPACE.match(name):
        raise DocumentError(
            f"Rule 3.1: document space {name!r} is not a slug — lowercase "
            f"alphanumerics, hyphen and underscore only. It appears in URL "
            f"paths and in RAG metadata filters.")
    return name


def document_id(project_id: str, document_space: str, filename: str) -> str:
    """Document identity is `(org, project, document_space, filename)` (Rule 7.1).

    The org is the realm and so is already the table's schema; it is not
    repeated in the id. Separators in the filename are flattened because this
    string is a post-graph vertex id.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "doc"
    return f"doc_{project_id}_{document_space}_{safe}"


class SpaceKey(BaseModel):
    """The full three-tier address of a document space."""
    org_id: str = "org_default"
    project_id: str
    document_space: str = DEFAULT_DOCUMENT_SPACE

    @field_validator("document_space")
    @classmethod
    def _slug(cls, v: str) -> str:
        return normalise_document_space(v)

    @property
    def key(self) -> str:
        return f"{self.project_id}:{self.document_space}"


class CreateSpaceRequest(BaseModel):
    """Create a document space.

    `space_name` is the field the backend and frontend send; `document_space` is
    the canonical name. Both are accepted and mean the same thing — renaming a
    field across three services at once is how a UI silently stops creating
    spaces.
    """
    org_id: str = Field("org_default", description="post-graph realm — physical isolation")
    project_id: str = Field(..., description="post-graph space — logical isolation")
    document_space: Optional[str] = Field(
        None, description="Document space, e.g. engineering_docs (third tier)")
    space_name: Optional[str] = Field(None, description="Alias for document_space")
    description: Optional[str] = "Document space for project domain knowledge"

    @model_validator(mode="after")
    def _one_name(self) -> "CreateSpaceRequest":
        chosen = self.document_space or self.space_name
        if not chosen:
            raise ValueError("document_space (or space_name) is required")
        normalised = normalise_document_space(chosen)
        self.document_space = normalised
        self.space_name = normalised
        return self


class UploadTextRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str
    document_space: Optional[str] = None
    space_name: Optional[str] = None
    document_name: str
    content: str
    category: Optional[str] = "unstructured"

    @model_validator(mode="after")
    def _one_name(self) -> "UploadTextRequest":
        normalised = normalise_document_space(
            self.document_space or self.space_name or DEFAULT_DOCUMENT_SPACE)
        self.document_space = normalised
        self.space_name = normalised
        return self


class RAGQueryRequest(BaseModel):
    org_id: str = "org_default"
    project_id: str
    query: str
    document_space: Optional[str] = Field(
        None, description="Target document space; omit to search the whole project")
    space_name: Optional[str] = Field(None, description="Alias for document_space")
    top_k: int = Field(5, ge=1, le=100)
    mode: str = "mix"

    @model_validator(mode="after")
    def _one_name(self) -> "RAGQueryRequest":
        # Unlike the upload requests, absent means project-wide (Rule 2.3), so
        # this must not default to "default" — that would silently narrow every
        # unscoped query to one folder.
        chosen = self.document_space or self.space_name
        normalised = normalise_document_space(chosen) if chosen else None
        self.document_space = normalised
        self.space_name = normalised
        return self


class ExtractionResult(BaseModel):
    method: str
    text: str
    characters: int
    extracted_at: str = Field(default_factory=now)

    def summary(self) -> Dict[str, Any]:
        return {"method": self.method, "characters": self.characters,
                "extracted_at": self.extracted_at}


def _count(value: Any) -> int:
    """A count, whatever shape the engine reported it in.

    post-graph-rag returns `entities` as a *list of names* and
    `entities_extracted` as the number. Reading the wrong one raised
    `TypeError: int() argument must be ... not 'list'` from inside the success
    path, which turned a successful index into a failed one — the worst
    direction for this particular error to go.
    """
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class IndexOutcome(BaseModel):
    """What happened when a document was handed to post-graph-rag (Rule 6.2)."""
    status: str = PENDING
    chunks: int = 0
    entities: int = 0
    relationships: int = 0
    engine: str = "post-graph-rag"
    error: Optional[str] = None
    indexed_at: Optional[str] = None

    @classmethod
    def succeeded(cls, raw: Dict[str, Any]) -> "IndexOutcome":
        """Read post-graph-rag's own reply, by its own field names.

        `index_document` indexes one chunk and returns the vertex id it wrote,
        so a returned `document_id` is one chunk — there is no chunk count to
        read, and inventing one would put a number in the catalogue that means
        nothing.
        """
        raw = raw or {}
        chunks = _count(raw.get("chunks")) or (1 if raw.get("document_id") else 0)
        entities = _count(raw.get("entities_extracted",
                                  raw.get("entities", raw.get("entity_count"))))
        relationships = _count(
            raw.get("relations_added",
                    raw.get("triples_extracted",
                            raw.get("relationships", raw.get("relationship_count")))))
        return cls(status=INDEXED, chunks=chunks, entities=entities,
                   relationships=relationships, indexed_at=now())

    @classmethod
    def failed(cls, error: str) -> "IndexOutcome":
        return cls(status=FAILED, error=error, indexed_at=now())


def catalogue_entry(*, key: SpaceKey, filename: str, digest: str, size: int,
                    extraction: ExtractionResult, index: IndexOutcome,
                    content_type: Optional[str] = None, revision: int = 1,
                    uploaded_by: Optional[str] = None) -> Dict[str, Any]:
    """One catalogue vertex payload (§3.2).

    `space_name` is emitted alongside `document_space` because the frontend and
    the backend both read it. One canonical field with one alias beats two
    fields that can disagree.
    """
    return {
        "document_id": document_id(key.project_id, key.document_space, filename),
        "org_id": key.org_id,
        "project_id": key.project_id,
        "document_space": key.document_space,
        "space_name": key.document_space,
        "filename": filename,
        "document_name": filename,
        "content_type": content_type,
        "content_hash": digest,
        "bytes": size,
        # Read by the frontend; kept as the extracted-character count, which is
        # what it has always meant here.
        "content_length": extraction.characters,
        "extraction_method": extraction.method,
        "extraction": extraction.summary(),
        "index": index.model_dump(mode="json"),
        "revision": revision,
        "lifecycle": ACTIVE,
        "uploaded_by": uploaded_by,
        "uploaded_at": now(),
    }
