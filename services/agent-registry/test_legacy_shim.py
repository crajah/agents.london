"""Tests for the legacy surface translated onto the graph (spec §13.3).

The contract these protect: `POST /agents/register` keeps its request and
response shape, so `backend/main.py` and the frontend need no change, while the
data lands in the one graph store instead of a second parallel table.
"""
import pytest

import legacy_shim
from legacy_shim import AgentRegistrationRequest
from registry_model import PUBLISHED
from registry_store import AGENTS, SPAWNS, register_agent_version
from test_registry_store import FakeClient


def request(**kw):
    base = dict(agent_id="agt_researcher", org_id="org_a", user_id="user_1",
                project_id="proj_a", name="Corpus Researcher",
                telos="Find and summarise filings.",
                system_prompt="You are a researcher.")
    base.update(kw)
    return AgentRegistrationRequest(**base)


# ---------------------------------------------------------------- translation

def test_a_v_prefixed_version_becomes_semver():
    """The legacy surface sends "v1.0.0"; semver has no leading v (§4.1)."""
    assert request(version="v1.0.0").semver() == "1.0.0"
    assert request(version="2.3.4").semver() == "2.3.4"


def test_the_slug_is_derived_from_the_name_and_is_stable():
    assert request().slug() == "corpus-researcher"
    assert request().slug() == request().slug()


def test_an_unnameable_name_falls_back_to_the_id():
    assert request(name="!!!").slug() == "agt-researcher"


def test_the_attestation_is_byte_identical_to_the_old_implementation():
    """A caller that recorded a hash_digest or public_key still matches."""
    import hashlib
    req = request()
    raw = f"{req.agent_id}:{req.telos}:{req.system_prompt}:none"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert req.attestation()["hash_digest"] == expected
    assert req.attestation()["public_key"] == (
        "ed25519:" + hashlib.sha256((req.agent_id + "_pub").encode()).hexdigest()[:32])


def test_a_supplied_digest_is_not_overwritten():
    assert request(hash_digest="given").attestation()["hash_digest"] == "given"


def test_identity_and_version_carry_the_right_fields():
    """Economic and attestation state on the identity; behaviour on the version."""
    identity, version = request(token_balance=42.0, reputation_score=88.0,
                                tools=[], caste="archivist").split()
    assert identity.token_balance == 42.0
    assert identity.reputation_score == 88.0
    assert identity.caste == "archivist"
    assert identity.public_key.startswith("ed25519:")
    assert version.system_prompt == "You are a researcher."
    assert version.version == "1.0.0"
    # Rule 3.4 — schemas are required, so the shim declares an honest text
    # contract rather than inventing a richer one the agent never saw.
    assert version.input_schema["required"] == ["prompt"]
    assert version.output_schema["type"] == "object"


def test_nothing_from_the_legacy_request_is_dropped():
    identity, _ = request(uaid="uaid-1",
                          entra_agent365_principal_id="entra-1",
                          codebase_hash_attestation="sha256:code",
                          x509_certificate={"issuer": "root"},
                          replicas=3).split()
    assert identity.uaid == "uaid-1"
    assert identity.entra_agent365_principal_id == "entra-1"
    assert identity.codebase_hash_attestation == "sha256:code"
    assert identity.x509_certificate == {"issuer": "root"}
    assert identity.replicas == 3


def test_guardrails_and_memory_policy_survive():
    identity, _ = request(guardrails=[{"guardrail_id": "g1", "rule": "no PII"}]).split()
    assert identity.guardrails[0]["rule"] == "no PII"
    assert identity.memory_policy["policy_type"] == "shared_session"


# --------------------------------------------------------------- round trip

@pytest.mark.asyncio
async def test_a_legacy_registration_is_readable_as_one_flat_agent():
    c = FakeClient()
    identity, version = request().split()
    await register_agent_version(c, "org_a", "proj_a",
                                 identity.model_dump(mode="json"), version)

    agent = await legacy_shim.load_agent(c, "org_a", "agt_researcher", "proj_a")
    assert agent is not None
    # Identity fields and version fields on one object, as the old surface returned.
    assert agent["name"] == "Corpus Researcher"
    assert agent["caste"] == "task_workforce"
    assert agent["token_balance"] == 10000000.0
    assert agent["system_prompt"] == "You are a researcher."
    assert agent["version"] == "1.0.0"
    assert agent["content_hash"].startswith("sha256:")
    assert agent["version_status"] == PUBLISHED


@pytest.mark.asyncio
async def test_version_history_is_ordered_by_semver():
    c = FakeClient()
    for v, prompt in (("1.0.0", "one"), ("1.10.0", "ten"), ("1.9.0", "nine")):
        identity, version = request(version=v, system_prompt=prompt).split()
        await register_agent_version(c, "org_a", "proj_a",
                                     identity.model_dump(mode="json"), version)
    history = await legacy_shim.version_history(c, "org_a", "agt_researcher", "proj_a")
    assert [h["version"] for h in history] == ["1.0.0", "1.9.0", "1.10.0"]


@pytest.mark.asyncio
async def test_progeny_is_derived_from_spawns_edges():
    """The old surface kept a list and appended to it in a fire-and-forget task."""
    c = FakeClient()
    parent_i, parent_v = request(agent_id="agt_parent", name="Parent").split()
    await register_agent_version(c, "org_a", "proj_a",
                                 parent_i.model_dump(mode="json"), parent_v)
    for child in ("agt_child_a", "agt_child_b"):
        ci, cv = request(agent_id=child, name=child.replace("_", " "),
                         parent_agent_id="agt_parent").split()
        await register_agent_version(c, "org_a", "proj_a",
                                     ci.model_dump(mode="json"), cv,
                                     spawned_by="agt_parent")

    children = await legacy_shim.progeny_of(c, "org_a", "agt_parent", "proj_a")
    assert sorted(children) == ["agt_child_a", "agt_child_b"]
    assert any(t == SPAWNS for t, *_ in c.edges)


@pytest.mark.asyncio
async def test_an_agent_with_no_children_has_no_progeny():
    c = FakeClient()
    identity, version = request().split()
    await register_agent_version(c, "org_a", "proj_a",
                                 identity.model_dump(mode="json"), version)
    assert await legacy_shim.progeny_of(c, "org_a", "agt_researcher", "proj_a") == []


@pytest.mark.asyncio
async def test_listing_returns_every_agent_in_the_realm():
    c = FakeClient()
    for n in ("a", "b"):
        identity, version = request(agent_id=f"agt_{n}", name=f"Agent {n}").split()
        await register_agent_version(c, "org_a", "proj_a",
                                     identity.model_dump(mode="json"), version)
    listed = await legacy_shim.load_all(c, "org_a", "proj_a")
    assert sorted(a["agent_id"] for a in listed) == ["agt_a", "agt_b"]


@pytest.mark.asyncio
async def test_origin_stubs_are_not_listed_as_agents():
    """A lineage stub records where a copy came from; it is not a callable agent."""
    c = FakeClient()
    identity, version = request().split()
    await register_agent_version(
        c, "org_a", "proj_a", identity.model_dump(mode="json"), version,
        derived_from={"realm": "org_z", "agent_id": "origin", "version": "1.0.0",
                      "content_hash": "sha256:x"})
    listed = await legacy_shim.load_all(c, "org_a", "proj_a")
    assert [a["agent_id"] for a in listed] == ["agt_researcher"]


# ------------------------------------------------------------- identity edits

@pytest.mark.asyncio
async def test_an_audit_changes_reputation_without_a_new_version():
    """§4.2 — auditing does not change behaviour, so it must not change the hash."""
    c = FakeClient()
    identity, version = request().split()
    record = await register_agent_version(c, "org_a", "proj_a",
                                          identity.model_dump(mode="json"), version)
    pk = c.vertices[(AGENTS, "agt_researcher")]
    versions_before = len(c.data[pk])

    await legacy_shim.update_identity(c, "org_a", "proj_a", "agt_researcher",
                                      {"reputation_score": 55.0})
    agent = await legacy_shim.load_agent(c, "org_a", "agt_researcher", "proj_a")
    assert agent["reputation_score"] == 55.0
    assert agent["content_hash"] == record["content_hash"]
    assert len(c.data[pk]) == versions_before


@pytest.mark.asyncio
async def test_updating_an_unknown_agent_is_an_error():
    from registry_model import RegistrationError
    c = FakeClient()
    with pytest.raises(RegistrationError, match="unknown agent"):
        await legacy_shim.update_identity(c, "org_a", "proj_a", "ghost",
                                          {"reputation_score": 1.0})
