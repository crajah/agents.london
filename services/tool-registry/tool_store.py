"""Writing tools into post-graph, and reading them back.

Validation lives in tool_model.py and runs before anything here is called.

**On identity vs. history.** `mcp_tools` holds one vertex per tool for the life
of the tool; `mcp_tools_data` holds one append-only record per version. That
split is the whole point (§3.3): if the endpoint and schemas lived on the
identity vertex, editing them in place would change what every published agent
naming that `tool_id` actually does, while those agents' content hashes went on
certifying the old behaviour.

**On publication ordering.** Same four-phase order as the agent registry: the
version record is appended as `draft`, and re-appended as `published` once
everything else has succeeded. The data table is append-only and newest wins,
so a failure part-way leaves a draft, and a draft is not resolvable, not
discoverable and not invocable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from tool_model import (
    ACTIVE, DEPRECATED, DRAFT, PUBLISHED, REVOKED, RegistrationError,
    ToolIdentity, ToolVersionSpec, validate_registration,
)

logger = logging.getLogger(__name__)

TOOLS = "mcp_tools"
EMBEDDING_DIM = 1536


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_schema(client, realm: str) -> None:
    """Create the vertex table for one realm. Idempotent.

    Carries a vector column: tools are discovered by description (§5), which is
    how an orchestrator finds one without knowing its id in advance.
    """
    await client.create_vertex_table(TOOLS, realm=realm, vector_dim=EMBEDDING_DIM)


async def list_realms(client) -> List[str]:
    """Every realm holding a tool table (Rule 10.3).

    Enumerated from the database, never from a hardcoded list: a hardcoded list
    means a new organisation's tools stay invisible until someone edits and
    redeploys the service, and nothing anywhere reports that.
    """
    if getattr(client, "schema_per_realm", False):
        # A realm is a schema, so the realms are the schemas holding the table.
        rows = await client._fetch(
            "SELECT table_schema FROM information_schema.tables "
            "WHERE table_name = $1 ORDER BY table_schema", TOOLS)
        return [r["table_schema"] for r in rows]
    rows = await client._fetch(
        f'SELECT DISTINCT realm FROM "{TOOLS}" ORDER BY realm')
    return [r["realm"] for r in rows]


async def resolve_vertex(client, realm: str, tool_id: str) -> Optional[int]:
    """Map a `tool_id` to post-graph's integer vertex id.

    post-graph assigns vertex ids from a BIGSERIAL; `tool_id` is a business key
    living in the payload, so the two are not interchangeable. Passing a
    business key where post-graph expects an id raises `ValueError: invalid
    literal for int()`.
    """
    ref = client._get_table_ref(TOOLS, realm)
    rows = await client._fetch(
        f"SELECT id FROM {ref} WHERE realm = $1 AND payload->>'tool_id' = $2 "
        f"ORDER BY id LIMIT 1", realm, tool_id)
    return int(rows[0]["id"]) if rows else None


def _body(record: Any) -> Dict[str, Any]:
    """Unwrap one history record into its payload dict."""
    payload = record.to_dict() if hasattr(record, "to_dict") else record
    body = payload.get("payload", payload)
    if isinstance(body, str):
        import json
        body = json.loads(body)
    return body if isinstance(body, dict) else {}


async def latest_versions(client, realm: str, pk: int) -> Dict[str, Dict[str, Any]]:
    """Every version of one tool, keyed by version, newest record winning.

    The data table is append-only, so a version may appear more than once — a
    draft followed by its published counterpart. `get_vertex_data` returns
    newest first, so the first record seen for a version is the current one.
    """
    records = await client.get_vertex_data(table_name=TOOLS, realm=realm, vertex_id=pk)
    out: Dict[str, Dict[str, Any]] = {}
    for record in records or []:
        body = _body(record)
        version = body.get("version")
        if version and version not in out:
            out[version] = body
    return out


async def identity_of(client, realm: str, pk: int) -> Optional[ToolIdentity]:
    ref = client._get_table_ref(TOOLS, realm)
    rows = await client._fetch(
        f"SELECT payload FROM {ref} WHERE realm = $1 AND id = $2", realm, pk)
    if not rows:
        return None
    payload = rows[0]["payload"]
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    try:
        return ToolIdentity(**{k: v for k, v in payload.items()
                               if k in ToolIdentity.model_fields})
    except Exception:
        logger.exception("tool vertex %s in realm %r has an unreadable identity", pk, realm)
        return None


# --------------------------------------------------------------- registration

async def register_tool_version(
    client, identity: ToolIdentity, spec: ToolVersionSpec,
    embedding: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Register one immutable tool version (§3, §4, §8).

    Idempotent on `(realm, tool_id, content_hash)` (Rule 8.1): re-registering
    identical content returns the existing record rather than appending a
    duplicate. Deployment tooling retries registration, and a retry must not
    become a new version.
    """
    realm = identity.org_id
    digest = spec.hash()

    pk = await resolve_vertex(client, realm, spec.tool_id)
    existing = await latest_versions(client, realm, pk) if pk else {}

    prior = existing.get(spec.version)
    if prior and prior.get("content_hash") == digest and prior.get("status") == PUBLISHED:
        # Rule 8.1. Identity fields may still have moved, so refresh the vertex,
        # but do not append a second identical version record.
        await _write_identity(client, realm, pk, identity, spec.version, embedding)
        return prior

    validate_registration(identity, spec, existing)

    pk = await _write_identity(client, realm, pk, identity, spec.version, embedding)

    record = spec.model_dump(mode="json")
    record.update({
        "tool_version_id": spec.version_id(),
        "content_hash": digest,
        "status": DRAFT,
        "registered_at": _now(),
    })
    await client.add_vertex_data(table_name=TOOLS, realm=realm, vertex_id=pk,
                                 payload=record)

    # The commit marker. Anything that failed above leaves the newest record
    # saying "draft", and a draft is not resolvable, discoverable or invocable.
    record = dict(record)
    record["status"] = PUBLISHED
    record["published_at"] = _now()
    await client.add_vertex_data(table_name=TOOLS, realm=realm, vertex_id=pk,
                                 payload=record)

    logger.info("registered tool %s@%s in realm %r", spec.tool_id, spec.version, realm)
    return record


def _semver_key(version: str):
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return (0,)


async def register_or_bump(client, identity: ToolIdentity,
                           spec: ToolVersionSpec,
                           embedding: Optional[List[float]] = None) -> Dict[str, Any]:
    """Register, moving to the next patch when the content has changed.

    For the **first-party catalogue only** (§7.3). An explicit registration
    keeps the immutability rule: the caller chose a version number and must be
    told when it collides (Rule 3.3). But the seeded defaults carry a version
    this service picked, and their endpoints move with the deployment — a
    cluster URL changes, and Rule 4.1 says that is at least a PATCH. Failing the
    seed instead would start the registry with a catalogue that still advertises
    the old address, and only a log line would say so.
    """
    realm = identity.org_id
    digest = spec.hash()
    pk = await resolve_vertex(client, realm, spec.tool_id)
    existing = await latest_versions(client, realm, pk) if pk else {}

    # This exact content may already be published under another number — a
    # previous seed that bumped, then a restart that computes the same hash
    # again. Bumping into it collides with Rule 4.2 and the whole seed of that
    # tool fails, which is how `mcp-web-search` ended up published but with no
    # discovery vector: the identity write that carries the vector never ran.
    # Reusing the version is what the rule's own error message advises.
    same = next((v for v, body in existing.items()
                 if body.get("content_hash") == digest), None)
    if same and same != spec.version:
        logger.info("default tool %s already published as %s; reusing it",
                    spec.tool_id, same)
        spec = spec.model_copy(update={"version": same})

    prior = existing.get(spec.version)
    if prior and prior.get("content_hash") != digest:
        newest = max(existing, key=_semver_key)
        major, minor, patch = (list(_semver_key(newest)) + [0, 0, 0])[:3]
        spec = spec.model_copy(update={
            "version": f"{major}.{minor}.{patch + 1}",
            "changelog": "Automatic patch: the first-party catalogue's declared "
                         "content changed (Rule 4.1)."})
        logger.info("default tool %s changed; publishing %s rather than editing %s",
                    spec.tool_id, spec.version, newest)

    return await register_tool_version(client, identity, spec, embedding)


async def _write_identity(client, realm: str, pk: Optional[int],
                          identity: ToolIdentity, current_version: str,
                          embedding: Optional[List[float]]) -> int:
    """Upsert the identity vertex, never append a second one (Rule 8.1)."""
    payload = identity.model_dump(mode="json")
    payload.update({"current_version": current_version, "updated_at": _now()})
    payload["embedding_status"] = "present" if embedding else "missing"

    if pk is None:
        payload["created_at"] = _now()
        vertex = await client.add_vertex(
            TOOLS, realm=realm, space=identity.project_id, payload=payload,
            embedding=embedding)
        return int(vertex.id)
    await client.upsert_vertex(
        TOOLS, realm=realm, vertex_id=pk, space=identity.project_id,
        payload=payload, embedding=embedding)
    return pk


async def set_lifecycle(client, realm: str, tool_id: str, lifecycle: str) -> Dict[str, Any]:
    """Move a tool between `active` and `dormant` (Rule 9.1, Rule 9.2).

    Written to post-graph, not only to a cache. A delete that mutates a
    process-local dictionary alone reports success, survives until the next
    restart, and then reappears — with no error anywhere in that sequence.
    """
    pk = await resolve_vertex(client, realm, tool_id)
    if pk is None:
        raise RegistrationError(f"unknown tool {tool_id!r} in realm {realm!r}")
    identity = await identity_of(client, realm, pk)
    if identity is None:
        raise RegistrationError(f"tool {tool_id!r} has no readable identity")

    payload = identity.model_dump(mode="json")
    payload["lifecycle"] = lifecycle
    payload["updated_at"] = _now()
    await client.upsert_vertex(TOOLS, realm=realm, vertex_id=pk,
                               space=identity.project_id, payload=payload)
    return payload


async def set_version_status(client, realm: str, tool_id: str, version: str,
                             status: str,
                             replacement_version_id: Optional[str] = None) -> Dict[str, Any]:
    """Deprecate or revoke one published version (Rule 4.5, Rule 9.3).

    Appends a new history record rather than editing the old one: the history
    is append-only, and the record of what a version *was* when agents pinned it
    is exactly what an audit needs.
    """
    if status not in (DEPRECATED, REVOKED):
        raise RegistrationError(
            f"status {status!r} is not a retirement state; use 'deprecated' or 'revoked'")
    pk = await resolve_vertex(client, realm, tool_id)
    if pk is None:
        raise RegistrationError(f"unknown tool {tool_id!r} in realm {realm!r}")
    versions = await latest_versions(client, realm, pk)
    body = versions.get(version)
    if body is None:
        raise RegistrationError(f"{tool_id} has no version {version}")

    if status == REVOKED and not replacement_version_id:
        # Rule 4.5 — silent revocation leaves agents reporting success while one
        # of their capabilities is gone.
        raise RegistrationError(
            f"Rule 4.5: revoking {tool_id}@{version} requires a "
            f"replacement_version_id; agents pin this version and would fail at "
            f"resolution with nothing to move to")

    record = dict(body)
    record["status"] = status
    record["retired_at"] = _now()
    if replacement_version_id:
        record["replacement_version_id"] = replacement_version_id
    await client.add_vertex_data(table_name=TOOLS, realm=realm, vertex_id=pk,
                                 payload=record)
    return record


# ------------------------------------------------------------------- reading

async def get_tool(client, realm: str, tool_id: str,
                   version: Optional[str] = None) -> Optional[Tuple[ToolIdentity, Dict[str, Any]]]:
    """One tool's identity and one of its versions.

    With no `version`, returns `current_version`. This is the only read path
    that may return a non-current record, because it is what an agent's runtime
    uses to resolve a pin.
    """
    pk = await resolve_vertex(client, realm, tool_id)
    if pk is None:
        return None
    identity = await identity_of(client, realm, pk)
    if identity is None:
        return None
    versions = await latest_versions(client, realm, pk)
    if not versions:
        return None

    if version is None:
        ref = client._get_table_ref(TOOLS, realm)
        rows = await client._fetch(
            f"SELECT payload->>'current_version' AS v FROM {ref} "
            f"WHERE realm = $1 AND id = $2", realm, pk)
        version = rows[0]["v"] if rows else None
    body = versions.get(version) if version else None
    if body is None:
        # Fall back to the newest published version rather than to nothing: a
        # current_version pointer that has drifted should degrade to a correct
        # answer, not to "no such tool".
        published = {v: b for v, b in versions.items() if b.get("status") == PUBLISHED}
        if not published:
            return None
        body = published[max(published)]
    return identity, body


async def list_tools(client, realm: str, project_id: Optional[str] = None,
                     include_inactive: bool = False) -> List[Dict[str, Any]]:
    """Every tool visible in one realm, optionally narrowed to one project.

    `realm` is required and has no default (Rule 2.1). A listing without one is
    not "all tools", it is a cross-tenant leak.
    """
    ref = client._get_table_ref(TOOLS, realm)
    try:
        rows = await client._fetch(
            f"SELECT id, payload FROM {ref} WHERE realm = $1 ORDER BY id", realm)
    except Exception as e:
        # A realm in which no tool has ever been registered has no table. That
        # is an empty catalogue, not a failure — as a 500 it travelled up as
        # "tool registry unreachable" and blocked every agent registration in
        # a fresh organisation, which is every organisation on its first day.
        if "does not exist" in str(e).lower():
            return []
        raise

    out: List[Dict[str, Any]] = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        try:
            identity = ToolIdentity(**{k: v for k, v in payload.items()
                                       if k in ToolIdentity.model_fields})
        except Exception:
            logger.warning("skipping unreadable tool vertex %s in realm %r",
                           row["id"], realm)
            continue
        if not include_inactive and identity.lifecycle != ACTIVE:
            continue
        if project_id is not None and not identity.visible_to(project_id):
            continue

        versions = await latest_versions(client, realm, int(row["id"]))
        current = payload.get("current_version")
        body = versions.get(current) if current else None
        if body is None:
            published = {v: b for v, b in versions.items()
                         if b.get("status") == PUBLISHED}
            body = published[max(published)] if published else None
        if body is None or (not include_inactive and body.get("status") != PUBLISHED):
            continue
        out.append({"identity": identity, "version": body.get("version"),
                    "record": body})
    return out
