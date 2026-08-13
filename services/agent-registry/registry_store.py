"""Writing agents and pipelines into post-graph.

Validation lives in registry_model.py and runs before anything here is called.
This module is only concerned with getting a validated registration into the
graph without ever leaving a half-registered pipeline visible.

**On atomicity (Rule 9.1).** post-graph's public API opens a transaction per
call, so `add_vertex` + N x `add_edge` cannot be wrapped in one. Reaching into
the private `_run_in_tx` would mean re-implementing the vertex and edge logic
against a raw connection, which is a worse trade than the alternative below.

Instead, publication is ordered so that a partial write is never *resolvable*:

    1. upsert the identity vertex
    2. append the version record with status "draft"
    3. write every edge
    4. append the same record again with status "published"

Version records live in the append-only `{table}_data` history, so the latest
record wins. If anything fails between 2 and 4, the newest record still says
"draft" — and draft versions cannot be pinned (Rule 4.3), are not discoverable
(Rule 10.1) and are not exposed over MCP or A2A (Rule 7.4). The failure is
therefore inert rather than silently live, which is the property Rule 9.1
exists to guarantee. Orphaned edges pointing at a draft version are unreachable
for the same reason.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from registry_model import (
    DRAFT, PUBLISHED, AgentVersionSpec, PipelineVersionSpec, RegistrationError,
    validate_pipeline_version,
)

logger = logging.getLogger(__name__)

AGENTS = "agents"
PIPELINES = "pipelines"
PROMPTS = "prompts"

COMPOSES = "composes_pipeline"
STEP_DEPENDENCY = "pipeline_step_dependency"
SPAWNS = "spawns"
INVOKES = "invokes_pipeline"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_schema(client, realm: str, embedding_dim: int = 1536) -> None:
    """Create the vertex and edge tables for one realm. Idempotent.

    Vertex tables get a vector column so agents and pipelines are discoverable
    by description (§10). Edge tables do not: an edge is found by traversing
    from a vertex, never by similarity.
    """
    for table in (AGENTS, PIPELINES, PROMPTS):
        await client.create_vertex_table(table, realm=realm, vector_dim=embedding_dim)

    # composes_pipeline runs pipelines -> agents, not pipelines -> versions:
    # post-graph edges connect vertices, and versions are history records. The
    # pinned version travels in the edge payload (§3.2).
    await client.create_edge_table(
        COMPOSES, from_vertex_table=PIPELINES, to_vertex_table=AGENTS, realm=realm)
    await client.create_edge_table(
        STEP_DEPENDENCY, from_vertex_table=AGENTS, to_vertex_table=AGENTS, realm=realm)
    await client.create_edge_table(
        SPAWNS, from_vertex_table=AGENTS, to_vertex_table=AGENTS, realm=realm)
    await client.create_edge_table(
        INVOKES, from_vertex_table=AGENTS, to_vertex_table=PIPELINES, realm=realm)


async def resolve_vertex(client, table: str, realm: str, business_id: str,
                         space: Optional[str] = None) -> Optional[int]:
    """Map a business id (`agt_…`, `pln_…`) to post-graph's integer vertex id.

    post-graph assigns vertex ids from a BIGSERIAL; `agent_id` is a business key
    living in the payload, so the two are not interchangeable. Every id crossing
    this boundary must be translated — passing a business key where post-graph
    expects an id raises `ValueError: invalid literal for int()`.
    """
    key = "agent_id" if table == AGENTS else "pipeline_id"
    ref = client._get_table_ref(table, realm)
    args: List[Any] = [realm, business_id]
    space_filter = ""
    if space:
        space_filter = " AND space = $3"
        args.append(space)
    rows = await client._fetch(
        f"SELECT id FROM {ref} WHERE realm = $1 AND payload->>'{key}' = $2{space_filter} "
        f"ORDER BY id LIMIT 1", *args)
    return int(rows[0]["id"]) if rows else None


async def _latest_versions(client, table: str, realm: str,
                           vertex_pk: int) -> Dict[str, Dict[str, Any]]:
    """Every version of one vertex, keyed by version string, newest record wins.

    The data table is append-only, so a version may appear more than once — a
    draft followed by its published counterpart. `get_vertex_data` returns
    newest first, so the first record seen for a version is the current one.
    """
    records = await client.get_vertex_data(
        table_name=table, realm=realm, vertex_id=vertex_pk)
    out: Dict[str, Dict[str, Any]] = {}
    for rec in records or []:
        payload = rec.to_dict() if hasattr(rec, "to_dict") else rec
        body = payload.get("payload", payload)
        if isinstance(body, str):
            import json as _json
            body = _json.loads(body)
        version = body.get("version")
        if version and version not in out:      # newest-first: keep the first
            out[version] = body
    return out


async def register_agent_version(
    client, realm: str, space: str, identity: Dict[str, Any], spec: AgentVersionSpec,
    embedding: Optional[List[float]] = None, spawned_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Register one immutable agent version (§3.2, §4).

    `identity` supplies the stable fields — name, slug, telos, description,
    caste, owner. The version record carries everything behaviour depends on.
    """
    agent_id = spec.agent_id
    digest = spec.hash()

    pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
    existing = await _latest_versions(client, AGENTS, realm, pk) if pk else {}

    # Rule 3.3 — a published version is immutable.
    prior = existing.get(spec.version)
    if prior and prior.get("status") == PUBLISHED and prior.get("content_hash") != digest:
        raise RegistrationError(
            f"Rule 3.3: version {spec.version} of {agent_id} is published and "
            f"immutable; publish a new version instead of editing it")

    # Rule 4.2 — a duplicate hash under a different version number means either
    # a pointless bump or a change to something the hash deliberately excludes.
    for version, body in existing.items():
        if version != spec.version and body.get("content_hash") == digest \
                and body.get("status") == PUBLISHED:
            raise RegistrationError(
                f"Rule 4.2: this content is already published as version {version}; "
                f"reuse it, or change what actually determines behaviour")

    identity_payload = {**identity, "agent_id": agent_id,
                        "current_version": spec.version,
                        "lifecycle": identity.get("lifecycle", "active"),
                        "updated_at": _now()}
    if pk is None:
        vertex = await client.add_vertex(
            AGENTS, realm=realm, space=space, payload=identity_payload, embedding=embedding)
        pk = int(vertex.id)
    else:
        await client.upsert_vertex(
            AGENTS, realm=realm, vertex_id=pk, space=space,
            payload=identity_payload, embedding=embedding)

    record = spec.model_dump(mode="json")
    record.update({"version_id": spec.version_id(), "content_hash": digest,
                   "status": PUBLISHED, "published_at": _now()})
    await client.add_vertex_data(
        table_name=AGENTS, realm=realm, vertex_id=pk, payload=record)

    if spawned_by:
        # Provenance is why agents are never deleted (Rule 3.2); losing this
        # edge loses the record of everything below it.
        parent_pk = await resolve_vertex(client, AGENTS, realm, spawned_by, space)
        if parent_pk is None:
            raise RegistrationError(
                f"spawned_by names unknown agent {spawned_by!r}; provenance edges "
                f"must point at a registered agent")
        await client.add_edge(
            SPAWNS, realm=realm, from_id=parent_pk, to_id=pk,
            relation_type="spawned", space=space,
            payload={"at": _now(), "version": spec.version})

    return record


async def register_pipeline_version(
    client, realm: str, space: str, identity: Dict[str, Any], spec: PipelineVersionSpec,
    embedding: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Register one immutable pipeline composition (§3.4, §5, §6, §9).

    Validated in full before the first write, then published in the four-phase
    order described in this module's docstring so a failure part-way leaves a
    draft rather than a live pipeline missing edges.
    """
    pipeline_id = spec.pipeline_id

    # Resolve every pinned version so validation can check status and schemas.
    status_by_version: Dict[str, str] = {}
    schemas_by_version: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    pin_by_step: Dict[str, Dict[str, Any]] = {}

    for step_id, binding in spec.steps.items():
        # version_id is "agv_{agent_id}_{version}" (§3.2.1).
        agent_id, version = _split_version_id(binding.version_id)
        agent_pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
        versions = await _latest_versions(client, AGENTS, realm, agent_pk) if agent_pk else {}
        body = versions.get(version)
        if body is None:
            status_by_version[binding.version_id] = None  # type: ignore[assignment]
            continue
        status_by_version[binding.version_id] = body.get("status", DRAFT)
        schemas_by_version[binding.version_id] = (
            body.get("input_schema", {}), body.get("output_schema", {}))
        pin_by_step[step_id] = {
            "agent_id": agent_id,
            "agent_pk": agent_pk,          # post-graph id, for the edge endpoints
            "agent_version": version,
            "content_hash": body.get("content_hash"),
        }

    derived = validate_pipeline_version(
        spec, {k: v for k, v in status_by_version.items() if v is not None},
        schemas_by_version)

    back_edges = {tuple(e) for e in derived["back_edges"]}

    # 1. identity
    identity_payload = {**identity, "pipeline_id": pipeline_id,
                        "current_version": spec.version,
                        "lifecycle": identity.get("lifecycle", "active"),
                        "updated_at": _now()}
    pipeline_pk = await resolve_vertex(client, PIPELINES, realm, pipeline_id, space)
    if pipeline_pk is None:
        vertex = await client.add_vertex(
            PIPELINES, realm=realm, space=space, payload=identity_payload,
            embedding=embedding)
        pipeline_pk = int(vertex.id)
    else:
        await client.upsert_vertex(
            PIPELINES, realm=realm, vertex_id=pipeline_pk, space=space,
            payload=identity_payload, embedding=embedding)

    # 2. version record, draft — not resolvable until step 4
    record = spec.model_dump(mode="json")
    record.update({
        "pipeline_version_id": spec.pipeline_version_id(),
        "status": DRAFT,
        "is_cyclic": derived["is_cyclic"],
        "back_edges": derived["back_edges"],
        "cycles": derived["cycles"],
        "pins": pin_by_step,
    })
    await client.add_vertex_data(
        table_name=PIPELINES, realm=realm, vertex_id=pipeline_pk, payload=record)

    # 3. edges
    for step_id, binding in spec.steps.items():
        pin = pin_by_step[step_id]
        await client.add_edge(
            COMPOSES, realm=realm, from_id=pipeline_pk, to_id=pin["agent_pk"],
            relation_type="contains_step", space=space,
            payload={"step_id": step_id, "alias": binding.alias,
                     "agent_version": pin["agent_version"],
                     "content_hash": pin["content_hash"],
                     "pipeline_version": spec.version})

    for dep in spec.dependencies:
        src = pin_by_step[dep.from_step]
        dst = pin_by_step[dep.to_step]
        await client.add_edge(
            STEP_DEPENDENCY, realm=realm, from_id=src["agent_pk"], to_id=dst["agent_pk"],
            # Rule 5.1: the relationship IS the relation_type, and it is required.
            relation_type=dep.relationship, space=space,
            # check_cycle=False is deliberate — cycles are legitimate here (§6.1).
            check_cycle=False,
            payload={
                # Rule 5.1: every structural query must filter on this.
                "pipeline_version_id": spec.pipeline_version_id(),
                "pipeline_version": spec.version,
                "from_step": dep.from_step, "to_step": dep.to_step,
                "relationship": dep.relationship, "condition": dep.condition,
                "payload_map": dep.payload_map,
                "is_back_edge": (dep.from_step, dep.to_step) in back_edges,
            })

    # 4. publish — the commit marker
    record["status"] = PUBLISHED
    record["published_at"] = _now()
    await client.add_vertex_data(
        table_name=PIPELINES, realm=realm, vertex_id=pipeline_pk, payload=record)

    logger.info("registered pipeline %s@%s: %d steps, %d edges, cyclic=%s",
                pipeline_id, spec.version, len(spec.steps), len(spec.dependencies),
                derived["is_cyclic"])
    return record


def _split_version_id(version_id: str) -> Tuple[str, str]:
    """Split "agv_{agent_id}_{version}" into (agent_id, version).

    Split from the right on the last underscore, because agent ids contain
    underscores and version strings never do.
    """
    if not version_id.startswith("agv_"):
        raise RegistrationError(f"malformed version id {version_id!r}; expected agv_…")
    body = version_id[len("agv_"):]
    agent_id, _, version = body.rpartition("_")
    if not agent_id or not version:
        raise RegistrationError(f"malformed version id {version_id!r}")
    return agent_id, version
