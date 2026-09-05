"""The catalogue: document spaces and documents in post-graph.

Every call here uses **realm = org_id, space = project_id** (Rule 2.1). The
document space is a payload field, never a post-graph space — passing it where
post-graph expects the project puts a project's documents in a partition its own
queries do not read.

The catalogue is separate from the index on purpose (§1). The catalogue answers
"what was ingested, from what file, by which parser, when" — a bookkeeping
question with an exact answer. The index answers "what is relevant to this
question" — a retrieval question with an approximate one. Collapsing them means
the only evidence a document exists is that a search happened to return it, and
a document that indexed badly becomes indistinguishable from one never uploaded.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from doc_model import (
    ACTIVE, SUPERSEDED, WITHDRAWN, DocumentError, SpaceKey, document_id, now,
)

logger = logging.getLogger(__name__)

SPACES = "document_spaces"
CATALOG = "documents_catalog"


async def ensure_schema(client, org_id: str) -> None:
    """Create both catalogue tables for one realm. Idempotent."""
    await client.create_vertex_table(SPACES, realm=org_id)
    await client.create_vertex_table(CATALOG, realm=org_id)


async def _fetch_or_empty(client, query: str, *args) -> List[Any]:
    """Read, treating a realm that has never been written to as empty.

    A tenant with no documents has no tables, and that is not an error — it is
    the answer. Creating tables on the read path instead would put DDL behind
    every listing, where concurrent readers race on the system catalogue for a
    table nobody is going to write to.
    """
    try:
        return await client._fetch(query, *args)
    except Exception as e:
        if "does not exist" in str(e).lower():
            return []
        raise


def _payload(row: Any) -> Dict[str, Any]:
    """The `payload` column of a row, as a dict.

    Written against `asyncpg.Record`, which supports `row["payload"]` but is
    **not** a `dict`. An earlier version guarded with `isinstance(row, dict)`
    and so returned `{}` for every real database row while passing every unit
    test, because the test double returned dicts. The symptom was silent:
    `get_space` found nothing, so `create_space` appended a duplicate space on
    every call and Rule 3.2 held only in the fake.
    """
    value = row
    if not isinstance(value, (str, bytes, dict)):
        try:
            value = row["payload"]
        except (TypeError, KeyError, IndexError):
            value = row
    elif isinstance(value, dict) and "payload" in value:
        value = value["payload"]
    if isinstance(value, (str, bytes)):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


# ------------------------------------------------------------------- spaces

async def get_space(client, key: SpaceKey) -> Optional[Dict[str, Any]]:
    ref = client._get_table_ref(SPACES, key.org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT id, payload FROM {ref} WHERE realm = $1 AND space = $2 "
        f"AND payload->>'document_space' = $3 ORDER BY id LIMIT 1",
        key.org_id, key.project_id, key.document_space)
    return _payload(rows[0]) if rows else None


async def create_space(client, key: SpaceKey, description: str) -> Dict[str, Any]:
    """Create a document space, or return the one that already exists.

    Rule 3.2 — idempotent. Space creation is called from UI flows that retry,
    and a duplicate space is one that silently splits a corpus in half.
    """
    await ensure_schema(client, key.org_id)
    existing = await get_space(client, key)
    if existing:
        return existing

    payload = {
        "space_key": key.key,
        "org_id": key.org_id,
        "project_id": key.project_id,
        "document_space": key.document_space,
        # The frontend reads `space_name`; one canonical field with one alias
        # beats two fields that can disagree.
        "space_name": key.document_space,
        "key": key.key,
        "description": description,
        "created_at": now(),
    }
    await client.add_vertex(SPACES, realm=key.org_id, space=key.project_id,
                            payload=payload)
    return payload


async def list_spaces(client, org_id: str, project_id: str) -> List[Dict[str, Any]]:
    """Every document space in a project, with a **derived** document count.

    Rule 3.3 — counted from the catalogue on every read, never maintained as a
    stored counter. A counter incremented on upload and not decremented on
    withdrawal drifts, and the drift is visible to users as a space claiming
    documents it cannot list.
    """
    ref = client._get_table_ref(SPACES, org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT payload FROM {ref} WHERE realm = $1 AND space = $2 ORDER BY id",
        org_id, project_id)

    counts: Dict[str, int] = {}
    for document in await list_documents(client, org_id, project_id):
        name = document.get("document_space", "default")
        counts[name] = counts.get(name, 0) + 1

    spaces = []
    for row in rows:
        payload = _payload(row)
        name = payload.get("document_space") or payload.get("space_name", "default")
        payload["document_space"] = name
        payload["space_name"] = name
        payload["document_count"] = counts.get(name, 0)
        spaces.append(payload)

    # A project with documents but no explicitly created space still has one:
    # uploads may name a space that was never created through /spaces.
    known = {s["document_space"] for s in spaces}
    for name, count in counts.items():
        if name not in known:
            spaces.append({
                "space_key": f"{project_id}:{name}", "key": f"{project_id}:{name}",
                "org_id": org_id, "project_id": project_id,
                "document_space": name, "space_name": name,
                "description": "Implicitly created by an upload",
                "created_at": None, "document_count": count})
    return spaces


# ----------------------------------------------------------------- documents

async def find_document(client, org_id: str, project_id: str,
                        doc_id: str) -> Optional[Dict[str, Any]]:
    ref = client._get_table_ref(CATALOG, org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT id, payload FROM {ref} WHERE realm = $1 AND space = $2 "
        f"AND payload->>'document_id' = $3 ORDER BY id LIMIT 1",
        org_id, project_id, doc_id)
    if not rows:
        return None
    payload = _payload(rows[0])
    payload["_pk"] = int(rows[0]["id"])
    return payload


async def list_documents(client, org_id: str, project_id: str,
                         document_space: Optional[str] = None,
                         include_withdrawn: bool = False,
                         limit: Optional[int] = None,
                         offset: int = 0) -> List[Dict[str, Any]]:
    """Catalogue listing, filtered and paged in SQL: a corpus of ten
    thousand documents must not travel to answer for one page of it."""
    ref = client._get_table_ref(CATALOG, org_id)
    conditions = ["realm = $1", "space = $2"]
    args: List[Any] = [org_id, project_id]
    if document_space:
        args.append(document_space)
        conditions.append(f"payload->>'document_space' = ${len(args)}")
    if not include_withdrawn:
        conditions.append("coalesce(payload->>'lifecycle', 'active') "
                          f"NOT IN ('{WITHDRAWN}', 'erased')")
    sql = (f"SELECT payload FROM {ref} WHERE {' AND '.join(conditions)} "
           f"ORDER BY id")
    if limit is not None:
        args.append(int(limit))
        sql += f" LIMIT ${len(args)}"
    if offset:
        args.append(int(offset))
        sql += f" OFFSET ${len(args)}"
    return [_payload(row) for row in await _fetch_or_empty(client, sql, *args)]


async def find_by_hash(client, org_id: str, project_id: str, document_space: str,
                       digest: str) -> Optional[Dict[str, Any]]:
    """An existing active document with these exact bytes (Rule 5.6).

    Re-extracting and re-indexing an identical file costs an embedding run and
    produces duplicate chunks that compete with each other in retrieval, which
    degrades every subsequent answer from that corpus.
    """
    ref = client._get_table_ref(CATALOG, org_id)
    # Targeted: the old shape listed EVERY document -- each carrying up to
    # 512KB of retained text -- to compare one hash per upload.
    rows = await _fetch_or_empty(
        client,
        f"SELECT payload FROM {ref} WHERE realm = $1 AND space = $2 "
        f"AND payload->>'content_hash' = $3 ORDER BY id",
        org_id, project_id, digest)
    for row in rows:
        payload = _payload(row)
        if payload.get("lifecycle") == WITHDRAWN:
            continue
        name = payload.get("document_space") or payload.get("space_name")
        if document_space and name != document_space:
            continue
        payload.pop("_pk", None)
        payload.pop("_text", None)   # the dedupe answer, not the corpus
        return payload
    return None


async def save_document(client, key: SpaceKey, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Write a document to the catalogue, as a new document or a new revision.

    Rule 7.1 — uploading a new file under an existing name is a **revision**,
    not a second document. The previous payload is preserved in
    `documents_catalog_data`, so the record of what was indexed under that name
    last month survives (§3.3).
    """
    await ensure_schema(client, key.org_id)
    doc_id = entry["document_id"]
    existing = await find_document(client, key.org_id, key.project_id, doc_id)

    if existing is None:
        vertex = await client.add_vertex(
            CATALOG, realm=key.org_id, space=key.project_id, payload=entry)
        pk = int(vertex.id)
    else:
        pk = existing["_pk"]
        entry["revision"] = int(existing.get("revision", 1)) + 1
        entry["created_at"] = existing.get("created_at") or existing.get("uploaded_at")
        await client.upsert_vertex(
            CATALOG, realm=key.org_id, vertex_id=pk, space=key.project_id,
            payload=entry)

    # Rule 3.3 / §3.3 — one record per revision, append-only.
    await client.add_vertex_data(
        table_name=CATALOG, realm=key.org_id, vertex_id=pk,
        payload={**entry, "kind": "revision", "recorded_at": now()})
    entry["_pk"] = pk
    return entry


async def revisions_of(client, org_id: str, doc_pk: int) -> List[Dict[str, Any]]:
    records = await client.get_vertex_data(table_name=CATALOG, realm=org_id,
                                           vertex_id=doc_pk)
    out = []
    for record in records or []:
        body = record.to_dict() if hasattr(record, "to_dict") else record
        body = body.get("payload", body)
        if isinstance(body, str):
            body = json.loads(body)
        if isinstance(body, dict):
            out.append(body)
    return out


async def erase_document(client, org_id: str, project_id: str,
                         doc_id: str) -> Dict[str, Any]:
    """Erase a document's content from the catalogue (right-to-erasure).

    Withdrawal retains the record AND the retained text and every revision;
    erasure removes them. What remains is a tombstone that carries no
    content -- enough to explain that something was here and was erased,
    nothing more. The index chunks are the caller's job (drop_chunks),
    because they live behind the RAG engine, not this table.
    """
    document = await find_document(client, org_id, project_id, doc_id)
    if document is None:
        raise DocumentError(f"unknown document {doc_id!r} in project {project_id!r}")
    pk = document["_pk"]
    revision_count = len(await client.get_vertex_data(
        table_name=CATALOG, realm=org_id, vertex_id=pk))
    # the vertex goes, and its revision rows cascade with it
    await client.delete_vertex(CATALOG, realm=org_id, vertex_id=str(pk))
    tombstone = {
        "document_id": doc_id,
        "org_id": org_id,
        "project_id": project_id,
        "document_space": document.get("document_space", "default"),
        "space_name": document.get("document_space", "default"),
        "lifecycle": "erased",
        "erased_at": now(),
        "revisions_erased": revision_count,
    }
    await client.add_vertex(CATALOG, realm=org_id, space=project_id,
                            payload=tombstone)
    return tombstone


async def set_lifecycle(client, org_id: str, project_id: str, doc_id: str,
                        lifecycle: str) -> Dict[str, Any]:
    """Withdraw or supersede a document (Rule 7.3).

    Removal is withdrawal: the catalogue record is retained, because it is what
    explains why a run from last month cited a document no longer in the corpus.
    """
    if lifecycle not in (ACTIVE, SUPERSEDED, WITHDRAWN):
        raise DocumentError(f"unknown lifecycle {lifecycle!r}")
    document = await find_document(client, org_id, project_id, doc_id)
    if document is None:
        raise DocumentError(f"unknown document {doc_id!r} in project {project_id!r}")

    pk = document.pop("_pk")
    document["lifecycle"] = lifecycle
    document["lifecycle_changed_at"] = now()
    await client.upsert_vertex(CATALOG, realm=org_id, vertex_id=pk,
                               space=project_id, payload=document)
    await client.add_vertex_data(
        table_name=CATALOG, realm=org_id, vertex_id=pk,
        payload={**document, "kind": "lifecycle", "recorded_at": now()})
    return document


async def update_index_outcome(client, org_id: str, project_id: str, doc_id: str,
                               index: Dict[str, Any]) -> Dict[str, Any]:
    """Record a (re)indexing outcome against an existing catalogue entry."""
    document = await find_document(client, org_id, project_id, doc_id)
    if document is None:
        raise DocumentError(f"unknown document {doc_id!r} in project {project_id!r}")
    pk = document.pop("_pk")
    document["index"] = index
    await client.upsert_vertex(CATALOG, realm=org_id, vertex_id=pk,
                               space=project_id, payload=document)
    await client.add_vertex_data(
        table_name=CATALOG, realm=org_id, vertex_id=pk,
        payload={**document, "kind": "reindex", "recorded_at": now()})
    return document


# ------------------------------------------------------------------- usage

PLANS = "registry_plans"


async def org_plan(client, org_id: str) -> Optional[Dict[str, Any]]:
    """The org's plan row, if the platform has set one. Absent = defaults."""
    ref = client._get_table_ref(PLANS, org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT payload FROM {ref} WHERE realm = $1 ORDER BY id DESC LIMIT 1",
        org_id)
    return _payload(rows[0]) if rows else None


async def usage_month_to_date(client, org_id: str, kind: str) -> Dict[str, int]:
    """Sum of bytes and count of events for one kind since the month began.

    Read from the durable ledger, so it lags the meter's flush interval by a
    few seconds -- a quota check that is marginally generous, never wrong."""
    ref = client._get_table_ref("usage_events", org_id)
    month_start = now()[:7] + "-01"
    rows = await _fetch_or_empty(
        client,
        f"SELECT coalesce(sum((payload->>'bytes')::bigint), 0) AS b, "
        f"count(*) AS n FROM {ref} WHERE realm = $1 "
        f"AND payload->>'kind' = $2 AND payload->>'occurred_at' >= $3",
        org_id, kind, month_start)
    if not rows:
        return {"bytes": 0, "events": 0}
    row = rows[0]
    try:
        return {"bytes": int(row["b"]), "events": int(row["n"])}
    except (TypeError, KeyError):
        return {"bytes": 0, "events": 0}


async def consumption_month_to_date(client, org_id: str) -> int:
    """Consumption Units since the month began, every kind (§9; user
    directive 2026-09-05: one unit for all processing). Older ledger rows
    predate the unit and fall back to their bytes."""
    ref = client._get_table_ref("usage_events", org_id)
    month_start = now()[:7] + "-01"
    rows = await _fetch_or_empty(
        client,
        f"SELECT coalesce(sum(coalesce((payload->>'consumption_units')::bigint, "
        f"(payload->>'bytes')::bigint, 0)), 0) AS cu FROM {ref} "
        f"WHERE realm = $1 AND payload->>'occurred_at' >= $2",
        org_id, month_start)
    try:
        return int(rows[0]["cu"]) if rows else 0
    except (TypeError, KeyError):
        return 0


async def count_documents(client, org_id: str, project_id: str) -> int:
    ref = client._get_table_ref(CATALOG, org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT count(*) AS n FROM {ref} WHERE realm = $1 AND space = $2 "
        f"AND coalesce(payload->>'lifecycle', 'active') "
        f"NOT IN ('{WITHDRAWN}', 'erased')",
        org_id, project_id)
    try:
        return int(rows[0]["n"]) if rows else 0
    except (TypeError, KeyError):
        return 0


# -------------------------------------------------------------- ingest jobs

JOBS = "ingest_jobs"


async def create_job(client, key: SpaceKey, job_id: str,
                     filename: str) -> Dict[str, Any]:
    await client.create_vertex_table(JOBS, realm=key.org_id)
    payload = {
        "job_id": job_id,
        "org_id": key.org_id,
        "project_id": key.project_id,
        "document_space": key.document_space,
        "filename": filename,
        "status": "queued",
        "created_at": now(),
    }
    vertex = await client.add_vertex(JOBS, realm=key.org_id,
                                     space=key.project_id, payload=payload)
    payload["_pk"] = int(vertex.id)
    return payload


async def update_job(client, org_id: str, pk: int,
                     **changes: Any) -> Dict[str, Any]:
    ref = client._get_table_ref(JOBS, org_id)
    rows = await _fetch_or_empty(
        client, f"SELECT id, payload FROM {ref} WHERE realm = $1 AND id = $2",
        org_id, pk)
    if not rows:
        raise DocumentError(f"unknown ingest job pk {pk}")
    payload = {**_payload(rows[0]), **changes}
    await client.upsert_vertex(JOBS, realm=org_id, vertex_id=pk,
                               space=payload.get("project_id", "default"),
                               payload=payload)
    return payload


async def get_job(client, org_id: str, project_id: str,
                  job_id: str) -> Optional[Dict[str, Any]]:
    ref = client._get_table_ref(JOBS, org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT id, payload FROM {ref} WHERE realm = $1 AND space = $2 "
        f"AND payload->>'job_id' = $3 ORDER BY id LIMIT 1",
        org_id, project_id, job_id)
    if not rows:
        return None
    payload = _payload(rows[0])
    payload["_pk"] = int(rows[0]["id"])
    return payload


async def orphan_running_jobs(client, org_id: str) -> int:
    """Jobs still 'running' when a registry starts died with the last one.

    In-process workers do not survive a restart, and a job that reads
    'running' forever is a lie. Marked failed with the honest reason."""
    ref = client._get_table_ref(JOBS, org_id)
    rows = await _fetch_or_empty(
        client,
        f"SELECT id, payload FROM {ref} WHERE realm = $1 "
        f"AND payload->>'status' IN ('queued', 'running')",
        org_id)
    for row in rows:
        payload = _payload(row)
        payload.update(status="failed", finished_at=now(),
                       error="The registry restarted mid-ingest; this job "
                             "did not survive it. Re-upload the file.")
        await client.upsert_vertex(JOBS, realm=org_id,
                                   vertex_id=int(row["id"]),
                                   space=payload.get("project_id", "default"),
                                   payload=payload)
    return len(rows)
