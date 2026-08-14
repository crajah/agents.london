"""Agent and pipeline registration model — the spec's rules, made executable.

Everything here is validation that happens *before* anything is written to the
graph. The ordering is deliberate: a pipeline that is half-registered runs and
produces a plausible wrong answer, which is far more expensive than a rejected
registration.

Rule numbers refer to spec/agent-graph-spec.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, field_validator

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")

PUBLISHED = "published"
DRAFT = "draft"
DEPRECATED = "deprecated"
REVOKED = "revoked"

# Edge relationships that can end a cycle. An `on_condition` edge may or may not
# fire; `depends_on` always does, so a cycle built only from those cannot exit.
EXIT_CAPABLE = {"on_condition", "on_success", "on_failure"}


class RegistrationError(ValueError):
    """A registration was rejected. The message names the rule that rejected it."""


# --------------------------------------------------------------- content hash

def canonical_json(obj: Any) -> str:
    """Stable JSON for hashing: sorted keys, no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(fields: Dict[str, Any]) -> str:
    """Hash of the fields that determine behaviour (Rule 4.2).

    Excludes description, changelog and timestamps: re-wording a description is
    not a behaviour change, and including it would force a version bump for a
    typo fix while telling the caller nothing.
    """
    material = {k: fields.get(k) for k in (
        "system_prompt", "model", "tools", "input_schema", "output_schema",
        "capabilities", "resource_limits",
        # An agent that invokes a pipeline behaves differently from one that
        # does not, so the declaration is part of what the hash certifies.
        "invokes_pipeline",
    )}
    return "sha256:" + hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


# -------------------------------------------------------------------- models

class ModelBinding(BaseModel):
    name: str
    api_base: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    fallback_models: List[str] = Field(default_factory=list)


class AgentVersionSpec(BaseModel):
    """One immutable agent version (§3.2)."""
    agent_id: str
    version: str
    system_prompt: str
    model: ModelBinding
    # Required, not optional (Rule 3.4): these are what make MCP exposure
    # mechanical and let pipeline edges be checked at publish rather than at run.
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    # Bare strings are accepted from authors and resolved to pins against the
    # tool registry before the hash is computed (Rule 3.5, Rule 4.3).
    tools: List[Any] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    resource_limits: Dict[str, Any] = Field(default_factory=dict)
    # §6.3 — a pipeline this agent calls. Declared here because it is a property
    # of the agent's behaviour, and it is what the `invokes_pipeline` edge is
    # written from at publish time. Without a field to declare it, the edge had
    # a writer that nothing could ever trigger.
    invokes_pipeline: Optional[Dict[str, Any]] = None
    status: str = DRAFT
    changelog: str = ""

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.match(v):
            raise ValueError(f"version {v!r} is not semver MAJOR.MINOR.PATCH")
        return v

    @field_validator("invokes_pipeline")
    @classmethod
    def _names_a_pipeline(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is not None and not v.get("pipeline_id"):
            raise ValueError("invokes_pipeline requires a pipeline_id")
        return v

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _object_schema(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if v.get("type") != "object":
            raise ValueError("schema must be a JSON Schema of type 'object'")
        return v

    def hash(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def version_id(self) -> str:
        """Logical key for this version.

        Not a vertex id: versions live as append-only records in `agents_data`
        (§3.2), so this identifies a record within an agent's history and is
        what an edge payload pins. Edges themselves attach to the `agents`
        vertex, because post-graph edges connect vertices, not data records.
        """
        return f"agv_{self.agent_id}_{self.version}"

    def pin(self) -> Dict[str, Any]:
        """The payload an edge carries to pin this exact version (Rule 3.2a).

        Both fields are needed: the version says which record, the hash proves
        it has not been altered since it was pinned.
        """
        return {"agent_version": self.version, "content_hash": self.hash()}


class ToolPin(BaseModel):
    """A resolved tool reference (Rule 3.5).

    Stored resolved, and inside the agent's content hash. A bare `tool_id` is a
    reference to whatever that tool currently is, so an agent's hash would
    certify a behaviour that changes when someone edits a tool's endpoint or
    input schema.
    """
    tool_id: str
    version: str
    content_hash: str


class StepBinding(BaseModel):
    version_id: str
    alias: Optional[str] = None
    # Copied from the pinned agent version at publish time so the executor can
    # enforce it without a second resolution per step (§3.2.1).
    resource_limits: Dict[str, Any] = Field(default_factory=dict)
    # Set when the pinned agent version declares an `invokes_pipeline` target
    # (§6.3). Carried onto the binding for the same reason: the executor must be
    # able to see it without resolving the agent version again mid-run.
    invokes_pipeline: Optional[Dict[str, Any]] = None


class StepDependency(BaseModel):
    from_step: str
    to_step: str
    relationship: str = "depends_on"
    condition: Optional[str] = None
    payload_map: Dict[str, str] = Field(default_factory=dict)


class ExecutionPolicy(BaseModel):
    max_iterations: Optional[int] = None
    max_recursion_depth: int = 1
    on_limit: str = "fail"
    concurrency: int = 1
    # Retries are bounded and counted separately from iterations (§11.2): a
    # retried step and a one-node cycle are not the same event, and conflating
    # them let transport retries exhaust a cycle allowance.
    max_retries: int = 0
    # Whole-run budget including recursive children (spec §11.4). None means
    # unbounded, which is only safe for an acyclic, non-recursive pipeline.
    max_compute_units: Optional[int] = None

    @field_validator("on_limit")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in ("fail", "halt_and_return"):
            raise ValueError("on_limit must be 'fail' or 'halt_and_return'")
        return v


class PipelineVersionSpec(BaseModel):
    """One immutable pipeline composition (§3.4)."""
    pipeline_id: str
    version: str
    steps: Dict[str, StepBinding]
    dependencies: List[StepDependency] = Field(default_factory=list)
    entry_steps: List[str]
    exit_steps: List[str] = Field(default_factory=list)
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    context_policy: Dict[str, Any] = Field(default_factory=dict)
    # A pipeline is exposed as one agent (Rule 7.3), so it needs its own
    # capabilities: the union of its steps' would describe the parts rather
    # than the whole, and is what a delegating caller must not be handed.
    capabilities: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    status: str = DRAFT
    changelog: str = ""

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.match(v):
            raise ValueError(f"version {v!r} is not semver")
        return v

    def pipeline_version_id(self) -> str:
        return f"plv_{self.pipeline_id}_{self.version}"


# ------------------------------------------------------------ graph analysis

class AgentIdentity(BaseModel):
    """The stable identity vertex (§3.1).

    Carries the economic and attestation fields the older registration surface
    owned, so there is one place an agent is described rather than two that can
    disagree (§13.3).
    """
    agent_id: str
    name: str
    slug: str
    telos: str = ""
    description: str = ""
    caste: str = "task_workforce"
    role: str = "worker"
    owner: Optional[str] = None
    lifecycle: str = "active"
    # Economic and attestation state, from the legacy surface.
    token_balance: float = 0.0
    reputation_score: float = 100.0
    hash_digest: Optional[str] = None
    public_key: Optional[str] = None
    signature: Optional[str] = None
    uaid: Optional[str] = None
    x509_certificate: Dict[str, Any] = Field(default_factory=dict)
    entra_agent365_principal_id: Optional[str] = None
    codebase_hash_attestation: Optional[str] = None
    lifecycle_status: Optional[str] = None
    memory_policy: Dict[str, Any] = Field(default_factory=dict)
    guardrails: List[Dict[str, Any]] = Field(default_factory=list)
    replicas: int = 1

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError(
                f"slug {v!r} is not URL and MCP safe; it appears in MCP tool "
                f"names and A2A card URLs")
        return v


def resolve_tool_pins(tools: List[Any],
                      catalogue: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    """Turn a `tools` list into resolved pins, or raise (Rule 3.5, §9 rejection 10).

    `catalogue` maps tool_id -> {"version": …, "content_hash": …} for tools that
    are published and in scope for this agent's realm and space. A tool absent
    from it is absent for this agent, whatever exists elsewhere.

    Bare strings are resolved to the current version. An already-resolved pin is
    checked against the catalogue rather than trusted: a pin whose hash no longer
    matches names a version that has been altered, which is exactly what the
    hash is for.
    """
    resolved: List[Dict[str, str]] = []
    for tool in tools or []:
        if isinstance(tool, str):
            entry = catalogue.get(tool)
            if entry is None:
                raise RegistrationError(
                    f"Rule 3.5: tool {tool!r} is not a published, in-scope tool in "
                    f"this realm and project; an agent cannot pin what it cannot call")
            resolved.append({"tool_id": tool, "version": entry["version"],
                             "content_hash": entry["content_hash"]})
            continue

        pin = tool if isinstance(tool, dict) else tool.model_dump(mode="json")
        tool_id = pin.get("tool_id")
        if not tool_id:
            raise RegistrationError(f"malformed tool entry {tool!r}: no tool_id")
        entry = catalogue.get(tool_id)
        if entry is None:
            raise RegistrationError(
                f"Rule 3.5: tool {tool_id!r} is not a published, in-scope tool in "
                f"this realm and project")
        version = pin.get("version") or entry["version"]
        digest = pin.get("content_hash")
        if digest and version == entry["version"] and digest != entry["content_hash"]:
            raise RegistrationError(
                f"Rule 3.5: tool {tool_id}@{version} has content_hash "
                f"{entry['content_hash']}, but the pin claims {digest}. The tool "
                f"was altered, or the pin was copied from another realm.")
        resolved.append({"tool_id": tool_id, "version": version,
                         "content_hash": digest or entry["content_hash"]})
    # Sorted so two agents naming the same tools in different orders hash alike:
    # ordering is not behaviour, and letting it change the hash would produce
    # spurious Rule 4.2 collisions and pointless version bumps.
    return sorted(resolved, key=lambda p: p["tool_id"])


def check_cross_realm(version_id: str, realm: str) -> None:
    """Reject a version id carrying another realm's prefix (§9 rejection 8).

    A realm is a PostgreSQL schema, so a cross-realm reference cannot carry a
    foreign key — it would resolve to nothing at run time, in a place far from
    the registration that created it.
    """
    if "::" not in version_id:
        return
    origin, _, _ = version_id.partition("::")
    if origin != realm:
        raise RegistrationError(
            f"Rule 2.2: {version_id!r} names realm {origin!r} from within {realm!r}; "
            f"cross-realm references cannot carry a foreign key. Publish a copy "
            f"and record its origin in derived_from.")


def find_back_edges(
    steps: Set[str], deps: List[StepDependency], entry_steps: List[str]
) -> Set[Tuple[str, str]]:
    """Edges closing a cycle, by DFS from the entry steps (§6.1).

    An edge into a step already on the current DFS stack is a back edge. Computed
    once at publish and stored, because it is a property of the definition and
    every run needs it.

    Iterative rather than recursive: a deeply nested pipeline would otherwise
    exhaust the Python stack during validation, which is a poor way to learn
    that a pipeline is large.
    """
    out: Dict[str, List[str]] = {s: [] for s in steps}
    for d in deps:
        out.setdefault(d.from_step, []).append(d.to_step)

    back: Set[Tuple[str, str]] = set()
    colour: Dict[str, int] = {s: 0 for s in steps}   # 0 unvisited, 1 on stack, 2 done

    for root in entry_steps:
        if colour.get(root, 0) != 0:
            continue
        stack: List[Tuple[str, int]] = [(root, 0)]
        colour[root] = 1
        while stack:
            node, i = stack[-1]
            if i < len(out.get(node, [])):
                stack[-1] = (node, i + 1)
                nxt = out[node][i]
                if colour.get(nxt, 0) == 1:
                    back.add((node, nxt))
                elif colour.get(nxt, 0) == 0:
                    colour[nxt] = 1
                    stack.append((nxt, 0))
            else:
                colour[node] = 2
                stack.pop()
    return back


def cycle_members(
    steps: Set[str], deps: List[StepDependency], back: Set[Tuple[str, str]]
) -> List[Set[str]]:
    """Steps participating in each cycle, one set per back edge.

    Found by walking forward from the back edge's target until the source is
    reached again — the path between them is the cycle.
    """
    out: Dict[str, List[str]] = {s: [] for s in steps}
    for d in deps:
        out.setdefault(d.from_step, []).append(d.to_step)

    cycles: List[Set[str]] = []
    for src, dst in back:
        seen: Set[str] = set()
        stack = [dst]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for nxt in out.get(node, []):
                if nxt != src:
                    stack.append(nxt)
        cycles.append(seen | {src})
    return cycles


# ------------------------------------------------------------- registration

def validate_pipeline_version(
    spec: PipelineVersionSpec,
    resolve_version_status: Dict[str, str],
    resolve_schemas: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]],
    realm: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply every publish-time rule, or raise naming the one that failed (§9).

    `resolve_version_status` maps version_id -> status, and `resolve_schemas`
    maps version_id -> (input_schema, output_schema). Both are supplied by the
    caller so this function stays free of I/O and is directly testable.

    Returns the derived facts the writer needs: back edges and cycle membership.
    """
    step_ids = set(spec.steps)

    # Rule 5.2 — edges must name steps that exist.
    for d in spec.dependencies:
        if d.from_step not in step_ids:
            raise RegistrationError(
                f"Rule 5.2: dependency from unknown step {d.from_step!r}")
        if d.to_step not in step_ids:
            raise RegistrationError(
                f"Rule 5.2: dependency to unknown step {d.to_step!r}")

    for name, field in (("entry_steps", spec.entry_steps), ("exit_steps", spec.exit_steps)):
        for s in field:
            if s not in step_ids:
                raise RegistrationError(f"{name} names unknown step {s!r}")
    if not spec.entry_steps:
        raise RegistrationError("a pipeline needs at least one entry step")

    # Rule 4.3 — every pinned version must exist and be published.
    for step_id, binding in spec.steps.items():
        if realm:
            check_cross_realm(binding.version_id, realm)
        status = resolve_version_status.get(binding.version_id)
        if status is None:
            raise RegistrationError(
                f"Rule 4.3: step {step_id!r} pins unknown version {binding.version_id!r}")
        if status != PUBLISHED:
            raise RegistrationError(
                f"Rule 4.3: step {step_id!r} pins {binding.version_id!r} "
                f"with status {status!r}; only 'published' may be pinned")

    # Rejection 7 — payload_map must connect fields that actually exist, in the
    # direction the edge runs. Caught here, this is a typo; caught at run time,
    # it is a step receiving a silently absent input.
    for d in spec.dependencies:
        if not d.payload_map:
            continue
        up = spec.steps[d.from_step].version_id
        down = spec.steps[d.to_step].version_id
        up_out = resolve_schemas.get(up, ({}, {}))[1].get("properties", {})
        down_in = resolve_schemas.get(down, ({}, {}))[0].get("properties", {})
        for src_field, dst_field in d.payload_map.items():
            if src_field not in up_out:
                raise RegistrationError(
                    f"payload_map on {d.from_step}->{d.to_step}: {src_field!r} is not "
                    f"in the output schema of {d.from_step!r}")
            if dst_field not in down_in:
                raise RegistrationError(
                    f"payload_map on {d.from_step}->{d.to_step}: {dst_field!r} is not "
                    f"in the input schema of {d.to_step!r}")

    back = find_back_edges(step_ids, spec.dependencies, spec.entry_steps)

    # Rule 6.1 — a cyclic pipeline must be bounded.
    if back and not spec.execution.max_iterations:
        raise RegistrationError(
            "Rule 6.1: pipeline contains a cycle "
            f"({', '.join(f'{a}->{b}' for a, b in sorted(back))}) but declares no "
            "execution.max_iterations; an unbounded cycle exhausts a budget silently")

    # Rule 6.2 — every cycle needs a way out.
    cycles = cycle_members(step_ids, spec.dependencies, back)
    for members in cycles:
        # A cycle terminates if control can leave it, or if an edge inside it is
        # conditional and so may not fire. A cycle of purely unconditional edges
        # with no way out runs until the iteration cap every single time.
        leaves = any(
            d.from_step in members and d.to_step not in members
            for d in spec.dependencies)
        conditional_inside = any(
            d.from_step in members and d.to_step in members
            and d.relationship in EXIT_CAPABLE
            for d in spec.dependencies)
        if not (leaves or conditional_inside):
            raise RegistrationError(
                "Rule 6.2: cycle over steps "
                f"{{{', '.join(sorted(members))}}} has no conditional edge and no edge "
                "leaving it, so it cannot terminate")

    return {
        "back_edges": sorted(back),
        "cycles": [sorted(c) for c in cycles],
        "is_cyclic": bool(back),
    }
