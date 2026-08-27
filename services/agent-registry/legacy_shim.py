"""The pre-graph registration surface, translated onto the graph (spec §13.3).

Two agent models used to coexist here. The older one wrote an `agent_registry`
vertex table with cryptographic attestation, token balances, reputation and
progeny lists; the newer one writes `agents` and `pipelines` with versions,
content hashes and pinnable compositions. They were not connected — an agent
registered through one was invisible to the other, with different tables,
different id conventions and different notions of a version.

This module removes the second store. `POST /agents/register` keeps its exact
request and response shape, because the frontend and `apps/civilization/backend/main.py` call it,
and it now writes the graph:

    AgentRegistrationRequest  ->  AgentIdentity  (the stable vertex)
                              +   AgentVersionSpec (the immutable version)

The economic and attestation fields move onto the identity vertex, which is
where §3.1 says they belong. Nothing is dropped.

**Progeny is derived, not stored.** The old surface kept a `progeny_agent_ids`
list on each parent and appended to it. A list and the `spawns` edges are two
records of one fact, and they drift the moment a write fails: the edge is the
provenance record (Rule 3.2), so the list is computed from it on read.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from registry_model import (
    PUBLISHED, AgentIdentity, AgentVersionSpec, RegistrationError,
)
from registry_store import AGENTS, SPAWNS, _latest_versions, resolve_vertex

logger = logging.getLogger(__name__)

# The model an agent version gets when it declares none. Set once for the
# whole system via DEFAULT_LLM_MODEL; the literal is only the fallback.
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "gemini-3.5-flash-lite")

# The legacy surface sends "v1.0.0"; semver has no leading v (§4.1).
_V_PREFIX = re.compile(r"^v(?=\d)")

# The legacy request declares no schemas, and Rule 3.4 makes them required.
# A permissive text contract is honest about what the caller actually declared:
# one text field in, one text field out. Inventing a richer schema would put a
# contract in the content hash that the agent was never written against.
LEGACY_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string",
                              "description": "The task or question for this agent"}},
    "required": ["prompt"],
}
LEGACY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"result": {"type": "string",
                              "description": "The agent's response"}},
}


class MemoryPolicy(BaseModel):
    policy_type: str = "shared_session"
    session_segregation: bool = True
    read_access: bool = True
    write_access: bool = True


class Guardrail(BaseModel):
    guardrail_id: str
    source: str = "constitution"
    level: str = "project"
    rule: str
    action_on_violation: str = "block_and_audit"


class AgentRegistrationRequest(BaseModel):
    """Unchanged from the pre-graph surface. Callers do not need updating."""
    agent_id: str = Field(..., description="Unique agent entity identifier")
    uaid: Optional[str] = Field(None, description="Unique Agent Identifier (UAID) Digital Passport issued by Federated Root CA")
    entra_agent365_principal_id: Optional[str] = Field(None, description="Entra Agent 365 Security Principal ID")
    codebase_hash_attestation: Optional[str] = Field(None, description="Cryptographic SHA256 codebase and prompt hash digest")
    x509_certificate: Dict[str, Any] = Field(default_factory=dict, description="X.509 Digital Passport Certificate issued by Federated Root CA")
    parent_agent_id: Optional[str] = Field(None, description="ID of parent agent if spawned as progeny")
    org_id: str
    user_id: str
    project_id: str
    name: str
    caste: str = Field("task_workforce", description="genesis, archivist, economist, judicature, architect, task_workforce, auditor")
    role: str = Field("worker", description="permanent_governor, permanent_creator, permanent_inspector, permanent_conductor, permanent_react, worker")
    telos: str = Field(..., description="Definable core objective of the agent")
    version: str = "v1.0.0"
    system_prompt: str
    tools: List[str] = Field(default_factory=list, description="List of linked MCP tool IDs")
    memory_policy: MemoryPolicy = Field(default_factory=MemoryPolicy)
    guardrails: List[Guardrail] = Field(default_factory=list)
    token_balance: float = 10000000.0
    reputation_score: float = 100.0
    public_key: Optional[str] = None
    signature: Optional[str] = None
    hash_digest: Optional[str] = None
    replicas: int = 1
    # Optional, and absent from the original surface: a description worth
    # embedding. Falls back to the telos, which every agent has.
    description: Optional[str] = None
    model: Optional[Dict[str, Any]] = None
    capabilities: List[str] = Field(default_factory=list)

    # ------------------------------------------------------------ translation

    def semver(self) -> str:
        return _V_PREFIX.sub("", self.version) or "1.0.0"

    def slug(self) -> str:
        """A URL and MCP safe slug derived from the name, falling back to the id.

        Deterministic, so re-registering the same agent produces the same slug
        and does not trip the uniqueness check against itself.
        """
        base = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return (base or re.sub(r"[^a-z0-9]+", "-", self.agent_id.lower()).strip("-"))[:63]

    def attestation(self) -> Dict[str, Optional[str]]:
        """Fill in the digest, key and signature the old surface generated.

        Kept byte-identical to the previous implementation so an agent
        re-registered after this change keeps the same `hash_digest` and
        `public_key` it had before — a caller that recorded them still matches.
        """
        digest = self.hash_digest
        if not digest:
            raw = (f"{self.agent_id}:{self.telos}:{self.system_prompt}:"
                   f"{self.parent_agent_id or 'none'}")
            digest = hashlib.sha256(raw.encode()).hexdigest()
        public_key = self.public_key or (
            "ed25519:" + hashlib.sha256((self.agent_id + "_pub").encode()).hexdigest()[:32])
        signature = self.signature or (
            "sig:" + hashlib.sha256((digest + "_sig").encode()).hexdigest()[:48])
        return {"hash_digest": digest, "public_key": public_key,
                "signature": signature}

    def split(self) -> Tuple[AgentIdentity, AgentVersionSpec]:
        attested = self.attestation()
        identity = AgentIdentity(
            agent_id=self.agent_id, name=self.name, slug=self.slug(),
            telos=self.telos, description=self.description or self.telos,
            caste=self.caste, role=self.role, owner=self.user_id,
            lifecycle="active", lifecycle_status="INSTANTIATED",
            token_balance=self.token_balance,
            reputation_score=self.reputation_score,
            uaid=self.uaid, x509_certificate=self.x509_certificate,
            entra_agent365_principal_id=self.entra_agent365_principal_id,
            codebase_hash_attestation=self.codebase_hash_attestation,
            memory_policy=self.memory_policy.model_dump(),
            guardrails=[g.model_dump() for g in self.guardrails],
            replicas=self.replicas, **attested)
        version = AgentVersionSpec(
            agent_id=self.agent_id, version=self.semver(),
            system_prompt=self.system_prompt,
            model=self.model or {"name": DEFAULT_MODEL},
            tools=list(self.tools),
            capabilities=self.capabilities,
            input_schema=LEGACY_INPUT_SCHEMA,
            output_schema=LEGACY_OUTPUT_SCHEMA)
        return identity, version


# ------------------------------------------------------------------- reading

async def load_agent(client, realm: str, agent_id: str,
                     space: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One agent in the shape the old surface returned.

    Merges the identity vertex with its current version record, so a caller
    that read `system_prompt` or `tools` off the flat object still finds them.
    """
    pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
    if pk is None:
        return None
    ref = client._get_table_ref(AGENTS, realm)
    rows = await client._fetch(
        f"SELECT payload FROM {ref} WHERE realm = $1 AND id = $2", realm, pk)
    if not rows:
        return None
    identity = rows[0]["payload"]
    if isinstance(identity, str):
        import json
        identity = json.loads(identity)

    versions = await _latest_versions(client, AGENTS, realm, pk)
    current = identity.get("current_version")
    body = versions.get(current) if current else None
    if body is None and versions:
        from registry_store import _newest
        body = versions[_newest(versions)]
    return _flatten(identity, body or {}, realm)


def _flatten(identity: Dict[str, Any], version: Dict[str, Any],
             realm: str) -> Dict[str, Any]:
    """The flat object the old surface returned, assembled from both records."""
    return {
        **identity,
        "org_id": identity.get("org_id", realm),
        "system_prompt": version.get("system_prompt", ""),
        "tools": version.get("tools", []),
        "model": version.get("model", {}),
        "capabilities": version.get("capabilities", []),
        # The old surface reported "v1.0.0"; the graph stores semver. Both are
        # given so a caller matching either keeps working.
        "version": version.get("version"),
        "version_id": version.get("version_id"),
        "content_hash": version.get("content_hash"),
        "version_status": version.get("status"),
        # What constrains this agent, and what memory it may touch. Both are
        # recorded on the identity and were being dropped on the way out, so
        # every caller asking what rules an agent carries got an empty list.
        "guardrails": identity.get("guardrails", []),
        "memory_policy": identity.get("memory_policy", {}),
    }


async def load_all(client, realm: str,
                   space: Optional[str] = None) -> List[Dict[str, Any]]:
    ref = client._get_table_ref(AGENTS, realm)
    args: List[Any] = [realm]
    space_filter = ""
    if space:
        space_filter = " AND space = $2"
        args.append(space)
    try:
        rows = await client._fetch(
            f"SELECT id, payload FROM {ref} WHERE realm = $1{space_filter} ORDER BY id",
            *args)
    except Exception as e:
        # A realm nobody has registered an agent in has no table yet. That is an
        # empty registry, not a broken one — this used to surface as a 500, and
        # every caller above read it as "the registry is down".
        if "does not exist" in str(e).lower():
            return []
        raise

    out = []
    for row in rows:
        identity = row["payload"]
        if isinstance(identity, str):
            import json
            identity = json.loads(identity)
        if identity.get("is_origin_stub"):
            continue
        versions = await _latest_versions(client, AGENTS, realm, int(row["id"]))
        current = identity.get("current_version")
        body = versions.get(current) if current else None
        if body is None and versions:
            from registry_store import _newest
            body = versions[_newest(versions)]
        out.append(_flatten(identity, body or {}, realm))
    return out


async def progeny_of(client, realm: str, agent_id: str,
                     space: Optional[str] = None) -> List[str]:
    """Children of an agent, from the `spawns` edges (Rule 3.2).

    Derived, never stored. The old surface kept a `progeny_agent_ids` list and
    appended to it in a fire-and-forget task; the list and the edges are two
    records of one fact, and a failed write left them disagreeing with nothing
    to reconcile them.
    """
    pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
    if pk is None:
        return []
    ref = client._get_table_ref(SPAWNS, realm)
    rows = await client._fetch(
        f"SELECT to_id FROM {ref} WHERE realm = $1 AND from_id = $2", realm, pk)

    agents_ref = client._get_table_ref(AGENTS, realm)
    children: List[str] = []
    for row in rows:
        found = await client._fetch(
            f"SELECT payload->>'agent_id' AS aid FROM {agents_ref} "
            f"WHERE realm = $1 AND id = $2", realm, int(row["to_id"]))
        if found and found[0]["aid"]:
            children.append(found[0]["aid"])
    return children


async def version_history(client, realm: str, agent_id: str,
                          space: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every version of one agent, oldest first."""
    pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
    if pk is None:
        return []
    versions = await _latest_versions(client, AGENTS, realm, pk)
    from registry_store import _semver_key
    return [versions[v] for v in sorted(versions, key=_semver_key)]


# ------------------------------------------------------------------- writing

async def update_identity(client, realm: str, space: str, agent_id: str,
                          changes: Dict[str, Any]) -> Dict[str, Any]:
    """Patch the identity vertex — reputation, tokens, lifecycle status.

    These are identity fields, not version fields: auditing an agent or moving
    its token balance does not change what it does, so it must not produce a
    new version or alter a content hash (§4.2).
    """
    pk = await resolve_vertex(client, AGENTS, realm, agent_id, space)
    if pk is None:
        raise RegistrationError(f"unknown agent {agent_id!r} in realm {realm!r}")
    ref = client._get_table_ref(AGENTS, realm)
    rows = await client._fetch(
        f"SELECT payload FROM {ref} WHERE realm = $1 AND id = $2", realm, pk)
    payload = rows[0]["payload"] if rows else {}
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    payload.update(changes)
    await client.upsert_vertex(AGENTS, realm=realm, vertex_id=pk, space=space,
                               payload=payload)
    return payload
