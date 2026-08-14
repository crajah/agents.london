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

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from registry_model import (
    DEPRECATED, DRAFT, PUBLISHED, REVOKED, AgentVersionSpec, PipelineVersionSpec,
    RegistrationError, resolve_tool_pins, validate_pipeline_version,
)

logger = logging.getLogger(__name__)

AGENTS = "agents"
PIPELINES = "pipelines"
PROMPTS = "prompts"
RUNS = "pipeline_runs"

COMPOSES = "composes_pipeline"
STEP_DEPENDENCY = "pipeline_step_dependency"
SPAWNS = "spawns"
INVOKES = "invokes_pipeline"
DERIVED_FROM = "derived_from"
RUN_OF = "run_of"
RUN_STEP = "run_step"


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
    # Runs are reached from their definition or their id, never by similarity,
    # and a vector column on a table that grows one row per execution is an
    # index nothing queries (§3).
    await client.create_vertex_table(RUNS, realm=realm)

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
    # Fork and cross-org copy lineage (§5, §11.1). Within a realm always: a
    # realm is a schema, so a cross-realm edge cannot carry a foreign key, and
    # the copy records its origin in the payload instead.
    await client.create_edge_table(
        DERIVED_FROM, from_vertex_table=AGENTS, to_vertex_table=AGENTS, realm=realm)
    # A run to its definition, and to what actually executed (§5). Without
    # these a run is linked to its pipeline only by a string in its payload,
    # which no traversal can follow.
    await client.create_edge_table(
        RUN_OF, from_vertex_table=RUNS, to_vertex_table=PIPELINES, realm=realm)
    await client.create_edge_table(
        RUN_STEP, from_vertex_table=RUNS, to_vertex_table=AGENTS, realm=realm)


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


async def slug_owner(client, table: str, realm: str, space: str,
                     slug: str) -> Optional[str]:
    """Which business id already holds this slug in `(realm, space)`, if any.

    §9 rejection 9. A slug is not decoration: it is the MCP tool name and the
    A2A card URL, so two entities sharing one means a caller resolving that name
    gets whichever the query happened to order first.
    """
    ref = client._get_table_ref(table, realm)
    key = "agent_id" if table == AGENTS else "pipeline_id"
    rows = await client._fetch(
        f"SELECT payload->>'{key}' AS owner FROM {ref} "
        f"WHERE realm = $1 AND space = $2 AND payload->>'slug' = $3 LIMIT 1",
        realm, space, slug)
    return rows[0]["owner"] if rows else None


async def _assert_slug_free(client, table: str, realm: str, space: str,
                            identity: Dict[str, Any], business_id: str) -> None:
    slug = identity.get("slug")
    if not slug:
        return
    owner = await slug_owner(client, table, realm, space, slug)
    if owner and owner != business_id:
        raise RegistrationError(
            f"§9 rejection 9: slug {slug!r} is already used by {owner!r} in "
            f"({realm}, {space}); it is the MCP tool name and the A2A card URL, "
            f"so it must identify exactly one thing")


async def register_agent_version(
    client, realm: str, space: str, identity: Dict[str, Any], spec: AgentVersionSpec,
    embedding: Optional[List[float]] = None, spawned_by: Optional[str] = None,
    tool_catalogue: Optional[Dict[str, Dict[str, str]]] = None,
    derived_from: Optional[Dict[str, Any]] = None,
    publish: bool = True,
) -> Dict[str, Any]:
    """Register one agent version (§3.2, §4).

    `identity` supplies the stable fields — name, slug, telos, description,
    caste, owner. The version record carries everything behaviour depends on.

    `publish=False` registers a draft. Drafts were previously unreachable
    because the status was overwritten unconditionally, which made the state
    Rule 4.3 depends on impossible to produce for agents — a caller could not
    stage a version and pin it later after review.
    """
    agent_id = spec.agent_id
    await _assert_slug_free(client, AGENTS, realm, space, identity, agent_id)

    # Rule 3.5 — resolve tools to pins before hashing. A bare id inside the hash
    # would certify behaviour that changes when someone edits a tool.
    if tool_catalogue is not None:
        spec = spec.model_copy(
            update={"tools": resolve_tool_pins(spec.tools, tool_catalogue)})

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
                   "status": PUBLISHED if publish else DRAFT})
    if publish:
        record["published_at"] = _now()
    await client.add_vertex_data(
        table_name=AGENTS, realm=realm, vertex_id=pk, payload=record)

    # §3.2 — the prompt is versioned in its own right, so a prompt can be
    # reviewed, diffed and reused across agents without reading it out of an
    # agent's version record.
    await _record_prompt(client, realm, space, spec, digest)

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

    if derived_from:
        await _record_lineage(client, realm, space, pk, derived_from)

    return record


async def _record_prompt(client, realm: str, space: str, spec: AgentVersionSpec,
                         agent_digest: str) -> None:
    """Version the system prompt independently (§3.2).

    One `prompts` vertex per agent, one record per distinct prompt. Identical
    prompt text appends nothing: a prompt that did not change is not a new
    version of the prompt, however many times the agent around it is
    republished.
    """
    prompt_id = f"prm_{spec.agent_id}"
    ref = client._get_table_ref(PROMPTS, realm)
    rows = await client._fetch(
        f"SELECT id FROM {ref} WHERE realm = $1 AND payload->>'prompt_id' = $2 "
        f"ORDER BY id LIMIT 1", realm, prompt_id)

    identity = {"prompt_id": prompt_id, "agent_id": spec.agent_id,
                "updated_at": _now()}
    if rows:
        pk = int(rows[0]["id"])
        await client.upsert_vertex(PROMPTS, realm=realm, vertex_id=pk, space=space,
                                   payload=identity)
    else:
        vertex = await client.add_vertex(PROMPTS, realm=realm, space=space,
                                         payload=identity)
        pk = int(vertex.id)

    digest = "sha256:" + hashlib.sha256(
        spec.system_prompt.encode("utf-8")).hexdigest()
    for record in await client.get_vertex_data(
            table_name=PROMPTS, realm=realm, vertex_id=pk) or []:
        body = record.get("payload", record) if isinstance(record, dict) else record
        if isinstance(body, dict) and body.get("prompt_hash") == digest:
            return

    await client.add_vertex_data(
        table_name=PROMPTS, realm=realm, vertex_id=pk,
        payload={"prompt_id": prompt_id, "agent_id": spec.agent_id,
                 "agent_version": spec.version, "agent_content_hash": agent_digest,
                 "prompt_hash": digest, "system_prompt": spec.system_prompt,
                 "recorded_at": _now()})


async def _record_lineage(client, realm: str, space: str, pk: int,
                          origin: Dict[str, Any]) -> None:
    """Write a `derived_from` edge (§5, §11.1).

    Always **within** the realm. A realm is a PostgreSQL schema, so an edge
    across one cannot carry a foreign key; a cross-org copy therefore points at
    a local stub recording the origin realm, agent id, version and hash. The
    hash is what makes the copy honest — it proves the two are the same
    extraction without a live link the schema cannot express.
    """
    origin_agent = origin.get("agent_id")
    if not origin_agent:
        raise RegistrationError("derived_from requires an origin agent_id")

    origin_realm = origin.get("realm", realm)
    target_pk = await resolve_vertex(client, AGENTS, realm, origin_agent, space)
    if target_pk is None:
        if origin_realm == realm:
            raise RegistrationError(
                f"derived_from names unknown agent {origin_agent!r} in this realm")
        # A cross-org origin: record a local stub, so the lineage edge has a
        # local endpoint and the origin is still stated.
        stub = await client.add_vertex(
            AGENTS, realm=realm, space=space,
            payload={"agent_id": f"{origin_realm}::{origin_agent}",
                     "name": f"{origin_agent} (origin stub)",
                     "slug": f"origin-{origin_realm}-{origin_agent}".lower()[:63],
                     "lifecycle": "dormant", "is_origin_stub": True,
                     "origin_realm": origin_realm,
                     "origin_agent_id": origin_agent,
                     "origin_version": origin.get("version"),
                     "origin_content_hash": origin.get("content_hash"),
                     "created_at": _now()})
        target_pk = int(stub.id)

    await client.add_edge(
        DERIVED_FROM, realm=realm, from_id=pk, to_id=target_pk,
        relation_type="derived_from", space=space,
        payload={"at": _now(), "origin_realm": origin_realm,
                 "origin_agent_id": origin_agent,
                 "origin_version": origin.get("version"),
                 "origin_content_hash": origin.get("content_hash")})


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
    await _assert_slug_free(client, PIPELINES, realm, space, identity, pipeline_id)

    # Resolve every pinned version so validation can check status and schemas.
    status_by_version: Dict[str, str] = {}
    schemas_by_version: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    pin_by_step: Dict[str, Dict[str, Any]] = {}

    for step_id, binding in spec.steps.items():
        # version_id is "agv_{agent_id}_{version}", or "agv_{agent_id}_latest"
        # for an author's convenience (§4.3).
        agent_id, version = _split_version_id(binding.version_id)
        agent_pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
        versions = await _latest_versions(client, AGENTS, realm, agent_pk) if agent_pk else {}

        if version == "latest":
            # §4.3 — resolved here, at publish time, and the *resolved* id is
            # what gets stored. `@latest` is never a stored value: a pipeline
            # whose behaviour changes because a dependency was republished is
            # not reproducible, and its run history stops being interpretable.
            published = {v: b for v, b in versions.items()
                         if b.get("status") == PUBLISHED}
            if not published:
                status_by_version[binding.version_id] = None  # type: ignore[assignment]
                continue
            version = _newest(published)
            binding = binding.model_copy(
                update={"version_id": f"agv_{agent_id}_{version}"})
            spec.steps[step_id] = binding

        body = versions.get(version)
        if body is None:
            status_by_version[binding.version_id] = None  # type: ignore[assignment]
            continue
        status_by_version[binding.version_id] = body.get("status", DRAFT)
        schemas_by_version[binding.version_id] = (
            body.get("input_schema", {}), body.get("output_schema", {}))
        # §3.2.1 / §6.3 — carried onto the binding so the executor can enforce
        # the limit and follow the invocation without resolving the agent
        # version again on every step.
        carried: Dict[str, Any] = {}
        if body.get("resource_limits"):
            carried["resource_limits"] = body["resource_limits"]
        if body.get("invokes_pipeline"):
            carried["invokes_pipeline"] = body["invokes_pipeline"]
        if carried:
            binding = binding.model_copy(update=carried)
            spec.steps[step_id] = binding
        pin_by_step[step_id] = {
            "agent_id": agent_id,
            "agent_pk": agent_pk,          # post-graph id, for the edge endpoints
            "agent_version": version,
            "content_hash": body.get("content_hash"),
            "invokes_pipeline": body.get("invokes_pipeline"),
        }

    derived = validate_pipeline_version(
        spec, {k: v for k, v in status_by_version.items() if v is not None},
        schemas_by_version, realm=realm)

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

    # invokes_pipeline: a step's agent version declares a pipeline it calls
    # (§6.3). Without this edge written, recursion has a table and no writer,
    # and `max_recursion_depth` guards a path that cannot be entered.
    for step_id, pin in pin_by_step.items():
        target = pin.get("invokes_pipeline")
        if not target:
            continue
        target_id = target.get("pipeline_id") if isinstance(target, dict) else target
        if not isinstance(target_id, str) or not target_id:
            raise RegistrationError(
                f"step {step_id!r} declares invokes_pipeline without a pipeline_id")
        target_pk = await resolve_vertex(client, PIPELINES, realm, target_id, space)
        if target_pk is None:
            raise RegistrationError(
                f"step {step_id!r} invokes unknown pipeline {target_id!r}; an "
                f"invocation edge must point at a registered pipeline")
        await client.add_edge(
            INVOKES, realm=realm, from_id=pin["agent_pk"], to_id=target_pk,
            relation_type="invokes", space=space, check_cycle=False,
            payload={"step_id": step_id,
                     "from_pipeline_version_id": spec.pipeline_version_id(),
                     "pipeline_id": target_id,
                     "pipeline_version": target.get("version")
                     if isinstance(target, dict) else None,
                     "at": _now()})

    # 4. publish — the commit marker
    record["status"] = PUBLISHED
    record["published_at"] = _now()
    record["steps"] = {k: v.model_dump(mode="json") for k, v in spec.steps.items()}
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


def _semver_key(version: str) -> Tuple[int, ...]:
    """Sort key for a semver string.

    String comparison puts "1.10.0" before "1.9.0", which would make `@latest`
    resolve to an older version the moment a minor number reached double
    digits — silently, and only for projects that had been going long enough.
    """
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def _newest(versions: Dict[str, Any]) -> str:
    return max(versions, key=_semver_key)


async def set_version_status(client, table: str, realm: str, space: str,
                             business_id: str, version: str, status: str,
                             replacement_version_id: Optional[str] = None,
                             cascade: bool = False) -> Dict[str, Any]:
    """Deprecate or revoke one published version (§4.4, Rule 4.4).

    Appended as a new history record rather than edited in place: the history is
    append-only, and what a version *was* when pipelines pinned it is exactly
    what an audit needs.
    """
    if status not in (DEPRECATED, REVOKED):
        raise RegistrationError(
            f"{status!r} is not a retirement state; use 'deprecated' or 'revoked'")

    pk = await resolve_vertex(client, table, realm, business_id, space)
    if pk is None:
        raise RegistrationError(f"unknown {table[:-1]} {business_id!r} in {realm!r}")
    versions = await _latest_versions(client, table, realm, pk)
    body = versions.get(version)
    if body is None:
        raise RegistrationError(f"{business_id} has no version {version}")

    dependents: List[Dict[str, Any]] = []
    if status == REVOKED and table == AGENTS:
        dependents = await pipelines_pinning(client, realm, space, business_id, version)
        if dependents and not (cascade or replacement_version_id):
            # Rule 4.4 — silent revocation would break pipelines that report
            # success, and the break would surface at run time as an
            # unresolvable pin rather than here as a rejected request.
            names = ", ".join(sorted({d["pipeline_id"] for d in dependents}))
            raise RegistrationError(
                f"Rule 4.4: {business_id}@{version} is pinned by published "
                f"pipelines ({names}). Pass replacement_version_id, or cascade=true "
                f"to revoke those pipeline versions too.")

    record = dict(body)
    record["status"] = status
    record["retired_at"] = _now()
    if replacement_version_id:
        record["replacement_version_id"] = replacement_version_id
    await client.add_vertex_data(table_name=table, realm=realm, vertex_id=pk,
                                 payload=record)

    cascaded: List[str] = []
    if status == REVOKED and cascade:
        for dependent in dependents:
            try:
                await set_version_status(
                    client, PIPELINES, realm, space, dependent["pipeline_id"],
                    dependent["pipeline_version"], REVOKED, cascade=True)
                cascaded.append(f"{dependent['pipeline_id']}@{dependent['pipeline_version']}")
            except RegistrationError:
                logger.exception("could not cascade revocation to %s", dependent)

    return {**record, "cascaded": cascaded,
            "dependents": [f"{d['pipeline_id']}@{d['pipeline_version']}"
                           for d in dependents]}


async def pipelines_pinning(client, realm: str, space: str, agent_id: str,
                            version: str) -> List[Dict[str, Any]]:
    """Published pipeline versions pinning one agent version (§10, by structure).

    One hop backwards along `composes_pipeline` — the query the spec calls out
    as the reason composition is edges rather than a JSON blob on a row.
    """
    agent_pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
    if agent_pk is None:
        return []
    ref = client._get_table_ref(COMPOSES, realm)
    rows = await client._fetch(
        f"SELECT from_id, payload FROM {ref} WHERE realm = $1 AND to_id = $2",
        realm, agent_pk)

    out: List[Dict[str, Any]] = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        if payload.get("agent_version") != version:
            continue
        pipeline_ref = client._get_table_ref(PIPELINES, realm)
        found = await client._fetch(
            f"SELECT payload->>'pipeline_id' AS pid FROM {pipeline_ref} "
            f"WHERE realm = $1 AND id = $2", realm, int(row["from_id"]))
        if found and found[0]["pid"]:
            out.append({"pipeline_id": found[0]["pid"],
                        "pipeline_version": payload.get("pipeline_version")})
    return out


async def set_lifecycle(client, table: str, realm: str, space: str,
                        business_id: str, lifecycle: str) -> Dict[str, Any]:
    """Move an entity between `active`, `deprecated` and `dormant` (Rule 3.2).

    Deletion is dormancy. An agent whose last referencing pipeline is removed is
    excluded from discovery, not deleted, because its `spawns` edges are the
    provenance record of everything below it.
    """
    if lifecycle not in ("active", "deprecated", "dormant"):
        raise RegistrationError(f"unknown lifecycle {lifecycle!r}")
    pk = await resolve_vertex(client, table, realm, business_id, space)
    if pk is None:
        raise RegistrationError(f"unknown {table[:-1]} {business_id!r} in {realm!r}")

    ref = client._get_table_ref(table, realm)
    rows = await client._fetch(
        f"SELECT payload FROM {ref} WHERE realm = $1 AND id = $2", realm, pk)
    payload = rows[0]["payload"] if rows else {}
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    payload["lifecycle"] = lifecycle
    payload["updated_at"] = _now()
    await client.upsert_vertex(table, realm=realm, vertex_id=pk, space=space,
                               payload=payload)
    return payload


async def link_run(client, realm: str, space: str, run_pk: int,
                   pipeline_id: str, executed_steps: List[Dict[str, Any]]) -> None:
    """Write `run_of` and `run_step` edges for a finished run (§5).

    Without these a run is linked to its definition only by a string in its
    payload, which no traversal can follow — so "what has this agent version
    actually executed" is a scan rather than one hop.
    """
    pipeline_pk = await resolve_vertex(client, PIPELINES, realm, pipeline_id, space)
    if pipeline_pk is not None:
        await client.add_edge(
            RUN_OF, realm=realm, from_id=run_pk, to_id=pipeline_pk,
            relation_type="run_of", space=space, payload={"at": _now()})

    for step in executed_steps:
        agent_pk = await resolve_vertex(client, AGENTS, realm, step["agent_id"], space)
        if agent_pk is None:
            continue
        await client.add_edge(
            RUN_STEP, realm=realm, from_id=run_pk, to_id=agent_pk,
            relation_type="executed_step", space=space, check_cycle=False,
            payload={"step_id": step.get("step_id"),
                     "agent_version": step.get("agent_version"),
                     "started_at": step.get("started_at"),
                     "ended_at": step.get("ended_at"),
                     "status": step.get("status")})
