"""Tests for the rules that were specified and not implemented (spec §13).

Each test names the rule it covers. Several of these are regressions against
code that *looked* like it implemented a rule — the `inherit` branch that built
an identical context in both arms, the `retry_count` field nothing incremented,
the `min_reputation_score` stored and never read.
"""
import pytest

from registry_model import (
    DRAFT, PUBLISHED, AgentIdentity, RegistrationError, check_cross_realm,
    resolve_tool_pins,
)
from registry_store import (
    AGENTS, DERIVED_FROM, INVOKES, PIPELINES, PROMPTS, _newest, _semver_key,
    pipelines_pinning, register_agent_version, register_pipeline_version,
    set_lifecycle, set_version_status, slug_owner,
)
from test_registry_model import OBJ, agent
from test_registry_store import FakeClient, IDENTITY, _pipeline, _seed_agents


# ------------------------------------------------------------- semver order

def test_semver_sorts_numerically_not_lexically():
    """"1.10.0" is newer than "1.9.0"; string comparison says otherwise."""
    assert _semver_key("1.10.0") > _semver_key("1.9.0")
    assert _newest({"1.9.0": {}, "1.10.0": {}, "1.2.0": {}}) == "1.10.0"


def test_newest_survives_a_malformed_version():
    assert _newest({"1.0.0": {}, "garbage": {}}) == "1.0.0"


# --------------------------------------------------------------- tool pins

CATALOGUE = {
    "mcp-search": {"version": "1.2.0", "content_hash": "sha256:aaa"},
    "mcp-sql": {"version": "2.0.0", "content_hash": "sha256:bbb"},
}


def test_bare_tool_ids_resolve_to_pins():
    """Rule 3.5 — a bare id inside the hash certifies behaviour that can change."""
    pins = resolve_tool_pins(["mcp-search"], CATALOGUE)
    assert pins == [{"tool_id": "mcp-search", "version": "1.2.0",
                     "content_hash": "sha256:aaa"}]


def test_an_unknown_tool_fails_registration():
    with pytest.raises(RegistrationError, match="Rule 3.5"):
        resolve_tool_pins(["mcp-ghost"], CATALOGUE)


def test_a_pin_whose_hash_no_longer_matches_is_rejected():
    """The hash exists to detect exactly this."""
    with pytest.raises(RegistrationError, match="was altered"):
        resolve_tool_pins(
            [{"tool_id": "mcp-search", "version": "1.2.0",
              "content_hash": "sha256:stale"}], CATALOGUE)


def test_pins_are_sorted_so_ordering_is_not_behaviour():
    a = resolve_tool_pins(["mcp-sql", "mcp-search"], CATALOGUE)
    b = resolve_tool_pins(["mcp-search", "mcp-sql"], CATALOGUE)
    assert a == b


def test_an_agent_with_no_tools_needs_no_catalogue():
    assert resolve_tool_pins([], {}) == []


def test_tool_pins_change_the_agent_content_hash():
    """They are inside the hash (§4.2), which is the whole point of Rule 3.5."""
    plain = agent()
    pinned = plain.model_copy(update={"tools": resolve_tool_pins(["mcp-search"],
                                                                CATALOGUE)})
    assert plain.hash() != pinned.hash()


# ------------------------------------------------------------- cross realm

def test_a_cross_realm_version_id_is_rejected():
    """§9 rejection 8 — a realm is a schema; the reference cannot carry a key."""
    with pytest.raises(RegistrationError, match="Rule 2.2"):
        check_cross_realm("org_b::agv_x_1.0.0", "org_a")


def test_a_same_realm_qualified_id_is_fine():
    check_cross_realm("org_a::agv_x_1.0.0", "org_a")
    check_cross_realm("agv_x_1.0.0", "org_a")


# ------------------------------------------------------------------- slugs

def test_a_slug_must_be_url_and_mcp_safe():
    with pytest.raises(Exception):
        AgentIdentity(agent_id="a", name="A", slug="Not A Slug")


@pytest.mark.asyncio
async def test_two_agents_cannot_share_a_slug():
    """§9 rejection 9 — the slug is the MCP tool name and the A2A card URL."""
    c = FakeClient()
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "shared"},
                                 agent(name="first"))
    with pytest.raises(RegistrationError, match="rejection 9"):
        await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "shared"},
                                     agent(name="second"))


@pytest.mark.asyncio
async def test_an_agent_may_keep_its_own_slug_across_versions():
    c = FakeClient()
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "mine"},
                                 agent(name="a", version="1.0.0"))
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "mine"},
                                 agent(name="a", version="1.1.0", prompt="new"))
    assert await slug_owner(c, AGENTS, "org", "proj", "mine") == "a"


@pytest.mark.asyncio
async def test_the_same_slug_in_another_project_is_free():
    c = FakeClient()
    await register_agent_version(c, "org", "proj_a", {**IDENTITY, "slug": "shared"},
                                 agent(name="first"))
    await register_agent_version(c, "org", "proj_b", {**IDENTITY, "slug": "shared"},
                                 agent(name="second"))


# ------------------------------------------------------------------ drafts

@pytest.mark.asyncio
async def test_an_agent_can_be_registered_as_a_draft():
    """§13.2 — the status was overwritten unconditionally, so drafts were
    unreachable and Rule 4.3's premise could not be produced for agents."""
    c = FakeClient()
    record = await register_agent_version(c, "org", "proj", IDENTITY,
                                          agent(name="a"), publish=False)
    assert record["status"] == DRAFT
    assert "published_at" not in record


@pytest.mark.asyncio
async def test_publishing_is_still_the_default():
    c = FakeClient()
    record = await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a"))
    assert record["status"] == PUBLISHED
    assert record["published_at"]


@pytest.mark.asyncio
async def test_a_draft_agent_version_cannot_be_pinned():
    """Rule 4.3, now reachable for agents."""
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a"),
                                 publish=False)
    with pytest.raises(RegistrationError, match="Rule 4.3"):
        await register_pipeline_version(c, "org", "proj", IDENTITY,
                                        _pipeline(["a"], [], ["a"]))


# ----------------------------------------------------------------- prompts

@pytest.mark.asyncio
async def test_the_prompt_is_versioned_in_its_own_table():
    """§3.2 — `prompts` had a table and no writer."""
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a"))
    assert any(t == PROMPTS for k, t, *_ in c.calls if k == "add_vertex")
    prompt_pk = c.vertices[(PROMPTS, "prm_a")]
    assert len(c.data[prompt_pk]) == 1


@pytest.mark.asyncio
async def test_an_unchanged_prompt_appends_no_prompt_version():
    """A prompt that did not change is not a new version of the prompt."""
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY,
                                 agent(name="a", version="1.0.0"))
    prompt_pk = c.vertices[(PROMPTS, "prm_a")]
    # A different agent version, same prompt: the model changes, not the text.
    from registry_model import ModelBinding
    changed = agent(name="a", version="1.1.0").model_copy(
        update={"model": ModelBinding(name="MiniMax-M2.7")})
    await register_agent_version(c, "org", "proj", IDENTITY, changed)
    assert len(c.data[prompt_pk]) == 1


@pytest.mark.asyncio
async def test_a_changed_prompt_appends_a_prompt_version():
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY,
                                 agent(name="a", version="1.0.0"))
    await register_agent_version(c, "org", "proj", IDENTITY,
                                 agent(name="a", version="1.1.0",
                                       prompt="do the thing differently"))
    prompt_pk = c.vertices[(PROMPTS, "prm_a")]
    assert len(c.data[prompt_pk]) == 2


# ------------------------------------------------------------------ lineage

@pytest.mark.asyncio
async def test_a_local_fork_writes_a_derived_from_edge():
    c = FakeClient()
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "origin"},
                                 agent(name="origin"))
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "fork"},
                                 agent(name="fork", prompt="forked behaviour"),
                                 derived_from={"agent_id": "origin"})
    assert any(t == DERIVED_FROM for k, t, *_ in c.calls if k == "add_edge")


@pytest.mark.asyncio
async def test_a_cross_org_copy_records_a_local_origin_stub():
    """§11.1 — a realm is a schema, so the edge points at a local stub."""
    c = FakeClient()
    await register_agent_version(
        c, "org_b", "proj", {**IDENTITY, "slug": "copy"}, agent(name="copy"),
        derived_from={"realm": "org_a", "agent_id": "origin", "version": "1.0.0",
                      "content_hash": "sha256:aaa"})
    stub_pk = c.vertices[(AGENTS, "org_a::origin")]
    assert c.payloads[stub_pk]["is_origin_stub"] is True
    assert c.payloads[stub_pk]["origin_content_hash"] == "sha256:aaa"
    assert c.payloads[stub_pk]["lifecycle"] == "dormant"


@pytest.mark.asyncio
async def test_lineage_to_an_unknown_local_agent_is_rejected():
    c = FakeClient()
    with pytest.raises(RegistrationError, match="unknown agent"):
        await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a"),
                                     derived_from={"agent_id": "ghost"})


# --------------------------------------------------------------- retirement

@pytest.mark.asyncio
async def test_revoking_a_pinned_version_without_a_replacement_is_rejected():
    """Rule 4.4 — silent revocation breaks pipelines that report success."""
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "p"},
                                    _pipeline(["a"], [], ["a"]))
    with pytest.raises(RegistrationError, match="Rule 4.4"):
        await set_version_status(c, AGENTS, "org", "proj", "a", "1.0.0", "revoked")


@pytest.mark.asyncio
async def test_revoking_with_a_replacement_is_allowed():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "p"},
                                    _pipeline(["a"], [], ["a"]))
    out = await set_version_status(c, AGENTS, "org", "proj", "a", "1.0.0", "revoked",
                                   replacement_version_id="agv_a_2.0.0")
    assert out["status"] == "revoked"
    assert out["replacement_version_id"] == "agv_a_2.0.0"


@pytest.mark.asyncio
async def test_cascade_revokes_the_pipelines_that_pinned_it():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "p"},
                                    _pipeline(["a"], [], ["a"]))
    out = await set_version_status(c, AGENTS, "org", "proj", "a", "1.0.0", "revoked",
                                   cascade=True)
    assert out["cascaded"] == ["pln_p@1.0.0"]


@pytest.mark.asyncio
async def test_an_unpinned_version_revokes_freely():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await set_version_status(c, AGENTS, "org", "proj", "a", "1.0.0", "revoked")


@pytest.mark.asyncio
async def test_deprecation_needs_no_replacement():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    out = await set_version_status(c, AGENTS, "org", "proj", "a", "1.0.0", "deprecated")
    assert out["status"] == "deprecated"


@pytest.mark.asyncio
async def test_retirement_appends_rather_than_edits():
    """The record of what a version was when pipelines pinned it survives."""
    c = FakeClient()
    await _seed_agents(c, ["a"])
    pk = c.vertices[(AGENTS, "a")]
    before = len(c.data[pk])
    await set_version_status(c, AGENTS, "org", "proj", "a", "1.0.0", "deprecated")
    assert len(c.data[pk]) == before + 1


@pytest.mark.asyncio
async def test_which_pipelines_pin_a_version_is_one_hop():
    """§10, by structure — the query composition-as-edges exists to enable."""
    c = FakeClient()
    await _seed_agents(c, ["a"])
    await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "p"},
                                    _pipeline(["a"], [], ["a"]))
    found = await pipelines_pinning(c, "org", "proj", "a", "1.0.0")
    assert found == [{"pipeline_id": "pln_p", "pipeline_version": "1.0.0"}]


# ----------------------------------------------------------------- lifecycle

@pytest.mark.asyncio
async def test_deletion_is_dormancy():
    """Rule 3.2 — the spawns edges are the provenance record below this agent."""
    c = FakeClient()
    await _seed_agents(c, ["a"])
    payload = await set_lifecycle(c, AGENTS, "org", "proj", "a", "dormant")
    assert payload["lifecycle"] == "dormant"
    pk = c.vertices[(AGENTS, "a")]
    assert c.payloads[pk]["lifecycle"] == "dormant"


@pytest.mark.asyncio
async def test_an_unknown_lifecycle_is_rejected():
    c = FakeClient()
    await _seed_agents(c, ["a"])
    with pytest.raises(RegistrationError, match="unknown lifecycle"):
        await set_lifecycle(c, AGENTS, "org", "proj", "a", "deleted")


# -------------------------------------------------------------------- latest

@pytest.mark.asyncio
async def test_latest_is_resolved_at_publish_and_stored_resolved():
    """§4.3 — `@latest` is a convenience for authors, never a stored value."""
    c = FakeClient()
    await _seed_agents(c, ["a"], version="1.0.0")
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "a"},
                                 agent(name="a", version="1.10.0", prompt="newer"))
    spec = _pipeline(["a"], [], ["a"])
    spec.steps["a"] = spec.steps["a"].model_copy(update={"version_id": "agv_a_latest"})
    record = await register_pipeline_version(c, "org", "proj",
                                             {**IDENTITY, "slug": "p"}, spec)
    # Resolved to the newest by semver, and stored resolved.
    assert record["steps"]["a"]["version_id"] == "agv_a_1.10.0"


@pytest.mark.asyncio
async def test_latest_with_no_published_version_is_rejected():
    c = FakeClient()
    await register_agent_version(c, "org", "proj", IDENTITY, agent(name="a"),
                                 publish=False)
    spec = _pipeline(["a"], [], ["a"])
    spec.steps["a"] = spec.steps["a"].model_copy(update={"version_id": "agv_a_latest"})
    with pytest.raises(RegistrationError, match="Rule 4.3"):
        await register_pipeline_version(c, "org", "proj", IDENTITY, spec)


# ---------------------------------------------------------------- recursion

@pytest.mark.asyncio
async def test_an_invokes_pipeline_edge_is_written():
    """§13.1 — recursion had a table and no writer, so §6.3 was unreachable."""
    c = FakeClient()
    await _seed_agents(c, ["inner"])
    await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "inner-p"},
                                    _pipeline(["inner"], [], ["inner"]).model_copy(
                                        update={"pipeline_id": "pln_inner"}))
    # An agent version declaring that it invokes that pipeline.
    caller = agent(name="caller", prompt="calls a pipeline")
    caller = caller.model_copy(update={"capabilities": ["invoke"]})
    await register_agent_version(c, "org", "proj", {**IDENTITY, "slug": "caller"},
                                 caller)
    pk = c.vertices[(AGENTS, "caller")]
    c.data[pk][-1]["invokes_pipeline"] = {"pipeline_id": "pln_inner",
                                          "version": "1.0.0"}

    outer = _pipeline(["caller"], [], ["caller"]).model_copy(
        update={"pipeline_id": "pln_outer"})
    await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "outer-p"},
                                    outer)
    assert any(t == INVOKES for k, t, *_ in c.calls if k == "add_edge")


@pytest.mark.asyncio
async def test_invoking_an_unknown_pipeline_is_rejected():
    c = FakeClient()
    await _seed_agents(c, ["caller"])
    pk = c.vertices[(AGENTS, "caller")]
    c.data[pk][-1]["invokes_pipeline"] = {"pipeline_id": "pln_ghost"}
    with pytest.raises(RegistrationError, match="invokes unknown pipeline"):
        await register_pipeline_version(c, "org", "proj", {**IDENTITY, "slug": "p"},
                                        _pipeline(["caller"], [], ["caller"]))


# --------------------------------------------------------- resource limits

@pytest.mark.asyncio
async def test_resource_limits_are_carried_onto_the_step_binding():
    """§3.2.1 — hashed into every version and enforced nowhere until now."""
    c = FakeClient()
    limited = agent(name="a").model_copy(
        update={"resource_limits": {"max_wall_secs": 5}})
    await register_agent_version(c, "org", "proj", IDENTITY, limited)
    record = await register_pipeline_version(c, "org", "proj",
                                             {**IDENTITY, "slug": "p"},
                                             _pipeline(["a"], [], ["a"]))
    assert record["steps"]["a"]["resource_limits"] == {"max_wall_secs": 5}
