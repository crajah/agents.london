"""Tool registration model — the spec's rules, made executable.

Everything here is validation that runs *before* anything reaches the graph.
Rule numbers refer to spec/tool-registry-spec.md; where a rule is inherited
from the agent graph it is marked "AG".

The single constraint the rest of this module follows from: a `tool_id` inside
a published agent's `content_hash` (AG §4.2) must refer to something that
cannot change underneath it. That is why tools are versioned, why versions are
hashed, and why an agent stores a resolved pin rather than a bare id.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
# Also the slug rule: a tool_id appears in URL paths and in MCP tool names.
TOOL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}[a-z0-9]$")

DRAFT = "draft"
PUBLISHED = "published"
DEPRECATED = "deprecated"
REVOKED = "revoked"

ACTIVE = "active"
DORMANT = "dormant"

SCOPE_ORG = "org"
SCOPE_PROJECT = "project"

# Rule 6.2. `read` may be invoked speculatively and retried freely; the other
# two may not, because at-least-once delivery over a side-effecting tool means
# the effect happens at least once too.
SIDE_EFFECTS = ("read", "write", "external")

AUTH_MODES = ("none", "bearer", "service_account", "secret_ref")

# Fields that look like a credential rather than a reference to one. Checked by
# name, because the failure being prevented is someone pasting a key into a
# registry row that every service in the realm can read (Rule 6.3).
CREDENTIAL_KEYS = ("token", "key", "api_key", "password", "secret", "credential",
                   "bearer", "authorization")


class RegistrationError(ValueError):
    """A registration was rejected. The message names the rule that rejected it."""


# --------------------------------------------------------------- content hash

def canonical_json(obj: Any) -> str:
    """Stable JSON for hashing: sorted keys, no insignificant whitespace.

    Byte-identical to the agent registry's implementation (AG §4.2) on purpose:
    two canonicalisations that differ in whitespace produce two hashes for one
    piece of content, and the difference only shows up when the registries are
    asked to agree about a pin.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(fields: Dict[str, Any]) -> str:
    """Hash of what determines a tool's behaviour (Rule 4.2).

    Excludes name, description, capabilities, changelog, cost_hint and
    timestamps: a reworded description is not a behaviour change, and including
    it would force a version bump for a typo while telling the caller nothing.
    """
    material = {k: fields.get(k) for k in (
        "endpoint_url", "transport", "input_schema", "output_schema",
        "auth", "limits", "min_reputation_score", "side_effects",
    )}
    return "sha256:" + hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- models

class ToolAuth(BaseModel):
    mode: str = "none"
    secret_ref: Optional[Dict[str, str]] = None

    @field_validator("mode")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in AUTH_MODES:
            raise ValueError(f"auth.mode must be one of {AUTH_MODES}")
        return v

    @model_validator(mode="after")
    def _no_literal_credentials(self) -> "ToolAuth":
        """Rule 6.3 — a catalogue is not a secret store.

        A registry row is readable by every service that can read the realm, so
        a credential written here is a credential distributed to all of them.
        """
        ref = self.secret_ref or {}
        for key, value in ref.items():
            if key.lower() in CREDENTIAL_KEYS and key.lower() not in ("key",):
                raise ValueError(
                    f"Rule 6.3: auth.secret_ref.{key} looks like a literal credential; "
                    f"store a reference (name/key) and keep the value in a secret")
            if isinstance(value, str) and len(value) > 128:
                raise ValueError(
                    f"Rule 6.3: auth.secret_ref.{key} is too long to be a reference; "
                    f"it looks like an embedded credential")
        if self.mode == "secret_ref" and not ref.get("name"):
            raise ValueError("auth.mode 'secret_ref' requires secret_ref.name")
        return self


class ToolLimits(BaseModel):
    timeout_secs: float = 30.0
    max_calls_per_run: Optional[int] = None
    max_bytes: Optional[int] = None


class ToolVersionSpec(BaseModel):
    """One immutable tool version (§3.2)."""
    tool_id: str
    version: str
    endpoint_url: str
    transport: str = "http_post_json"
    # Required, not optional (Rule 3.2). The input schema is what a model is
    # shown when the tool is offered to it; the output schema is what lets a
    # pipeline's payload_map be checked at publish time (AG §9, rejection 7).
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    # No default (registration rejection 6): guessing `read` for a writing tool
    # licenses speculative execution of it.
    side_effects: str
    auth: ToolAuth = Field(default_factory=ToolAuth)
    limits: ToolLimits = Field(default_factory=ToolLimits)
    min_reputation_score: float = 0.0
    cost_hint: Dict[str, Any] = Field(default_factory=dict)
    status: str = DRAFT
    changelog: str = ""

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.match(v):
            raise ValueError(f"version {v!r} is not semver MAJOR.MINOR.PATCH")
        return v

    @field_validator("tool_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not TOOL_ID.match(v):
            raise ValueError(
                f"tool_id {v!r} is not a slug; it appears in URL paths and MCP "
                f"tool names, and a name needing escaping in one will eventually "
                f"not be escaped in the other")
        return v

    @field_validator("side_effects")
    @classmethod
    def _side_effects(cls, v: str) -> str:
        if v not in SIDE_EFFECTS:
            raise ValueError(f"side_effects must be one of {SIDE_EFFECTS}")
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
        return f"tlv_{self.tool_id}_{self.version}"

    def pin(self) -> Dict[str, Any]:
        """The pin an agent version stores in its `tools` list (Rule 4.3)."""
        return {"tool_id": self.tool_id, "version": self.version,
                "content_hash": self.hash()}

    def requires_idempotency_key(self) -> bool:
        return self.side_effects != "read"


class ToolIdentity(BaseModel):
    """The stable identity vertex (§3.1)."""
    tool_id: str
    name: str
    description: str = ""
    scope_type: str = SCOPE_PROJECT
    org_id: str
    project_id: Optional[str] = None
    kind: str = "http"
    capabilities: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    lifecycle: str = ACTIVE

    @field_validator("tool_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not TOOL_ID.match(v):
            raise ValueError(f"tool_id {v!r} is not a slug")
        return v

    @model_validator(mode="after")
    def _scope_is_consistent(self) -> "ToolIdentity":
        """Rule 2.2 — rejected rather than normalised.

        Either normalisation silently widens or narrows visibility, and the
        author cannot tell from the response which one happened.
        """
        if self.scope_type not in (SCOPE_ORG, SCOPE_PROJECT):
            raise ValueError(f"scope_type must be '{SCOPE_ORG}' or '{SCOPE_PROJECT}'")
        if self.scope_type == SCOPE_ORG and self.project_id:
            raise ValueError(
                "Rule 2.2: scope_type 'org' must not carry a project_id; an "
                "org-scoped tool is visible to every project in the realm")
        if self.scope_type == SCOPE_PROJECT and not self.project_id:
            raise ValueError(
                "Rule 2.2: scope_type 'project' requires a project_id")
        return self

    def visible_to(self, project_id: Optional[str]) -> bool:
        """Whether a caller in `project_id` may see and invoke this tool."""
        if self.scope_type == SCOPE_ORG:
            return True
        return project_id is not None and project_id == self.project_id


class ToolPin(BaseModel):
    """A resolved reference, as stored inside an agent version's `tools`."""
    tool_id: str
    version: str
    content_hash: str


# ----------------------------------------------------------------- discovery

def discovery_text(identity: ToolIdentity, version: ToolVersionSpec) -> str:
    """What the tool's embedding is computed from (§3.1).

    Includes the input schema's property *descriptions* — not the property
    names — because "the search query text" retrieves for a natural-language
    question in a way that the identifier `q` never will.
    """
    props = (version.input_schema or {}).get("properties", {}) or {}
    described = [d.get("description", "") for d in props.values()
                 if isinstance(d, dict) and d.get("description")]
    parts = [identity.name, identity.description,
             ", ".join(identity.capabilities), " ".join(described)]
    return "\n".join(p.strip() for p in parts if p and p.strip())


# --------------------------------------------------------------- validation

def validate_registration(identity: ToolIdentity, version: ToolVersionSpec,
                          existing: Dict[str, Dict[str, Any]]) -> None:
    """Apply the publish-time rules of §8, or raise naming the one that failed.

    `existing` maps version string -> stored version record for this tool, so
    this stays free of I/O and is directly testable.
    """
    if identity.tool_id != version.tool_id:
        raise RegistrationError(
            f"identity names tool {identity.tool_id!r} and the version names "
            f"{version.tool_id!r}")

    digest = version.hash()

    # Rule 3.3 — a published version is immutable.
    prior = existing.get(version.version)
    if prior and prior.get("status") == PUBLISHED and prior.get("content_hash") != digest:
        raise RegistrationError(
            f"Rule 3.3: version {version.version} of {version.tool_id} is published "
            f"and immutable; publish a new version instead of editing it")

    # Rule 4.2 — a duplicate hash under a different version is either a
    # pointless bump or a change to something the hash deliberately excludes.
    for other, body in existing.items():
        if other != version.version and body.get("content_hash") == digest \
                and body.get("status") == PUBLISHED:
            raise RegistrationError(
                f"Rule 4.2: this content is already published as version {other}; "
                f"reuse it, or change what actually determines behaviour")

    # Rejection 7a — a CREDENTIALED tool may not point outside the
    # cluster at all (audit 2026-09-04): secret_ref + external endpoint is
    # an exfiltration machine whatever the declared side_effects.
    if getattr(version.auth, "secret_ref", None) \
            and _is_external(version.endpoint_url):
        raise RegistrationError(
            f"endpoint {version.endpoint_url!r} leaves the cluster and the "
            f"tool carries a credential reference; credentials never travel "
            f"to external endpoints")
    # Rejection 7 — an outward-facing endpoint declared as a read.
    if version.side_effects == "read" and _is_external(version.endpoint_url):
        raise RegistrationError(
            f"endpoint {version.endpoint_url!r} leaves the cluster but the tool "
            f"declares side_effects 'read'; declare 'external' so callers know "
            f"the request is observable outside the system")


def _is_external(url: str) -> bool:
    """Whether a URL leaves the cluster. Conservative: unknown means external."""
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return False        # non-HTTP transports are judged by their own rules
    host = lowered.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
    # only the cluster's own DNS zone and loopback count as internal;
    # bare .local / .internal are resolvable by whoever runs the resolver
    return not (host.endswith(".svc.cluster.local")
                or host in ("localhost", "127.0.0.1", "::1")
                or (host.endswith("-service") and "." not in host))


def validate_arguments(arguments: Dict[str, Any],
                       schema: Dict[str, Any]) -> Optional[str]:
    """Check call arguments against a tool's input schema (Rule 7.1).

    Returns an error message, or None when the arguments are acceptable. A
    deliberately small checker — required keys, declared types, no unexpected
    keys when the schema forbids them — rather than a full JSON Schema
    implementation: the failure being prevented is a tool receiving an argument
    shape it did not declare, and that is what these three checks catch.
    """
    if schema.get("type") != "object":
        return None
    props = schema.get("properties", {}) or {}
    for key in schema.get("required", []) or []:
        if key not in arguments:
            return f"missing required argument {key!r}"
    if schema.get("additionalProperties") is False:
        for key in arguments:
            if key not in props:
                return f"unexpected argument {key!r}"
    for key, value in arguments.items():
        declared = props.get(key)
        if not isinstance(declared, dict):
            continue
        expected = declared.get("type")
        if expected and not _type_matches(value, expected):
            return f"argument {key!r} should be {expected}, got {type(value).__name__}"
    return None


_JSON_TYPES = {
    "string": str, "integer": int, "number": (int, float),
    "boolean": bool, "array": list, "object": dict,
}


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    python_type = _JSON_TYPES.get(expected)
    if python_type is None:
        return True
    # bool is a subclass of int in Python; a boolean passed where an integer is
    # declared is a caller error worth reporting, not an implicit widening.
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, python_type)
