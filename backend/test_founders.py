"""The roster, and the prompts it renders.

These are unit tests: they hold shut the properties that made the founding
agents unusable before, without needing a database or a model router.
"""
from __future__ import annotations

import json

import pytest

from founders import (AUTONOMOUS, BY_ID, CORE_DIRECTIVES, FOUNDERS,
                      NO_FABRICATION, founder, founder_prompt, render_prompt,
                      roster)
from platform_tools import PLATFORM_TOOL_IDS, platform_tools


def test_the_roster_is_one_roster():
    """Three lists of founders was three civilisations, and only one was made."""
    assert len(FOUNDERS) == len(BY_ID), "duplicate founder ids"
    assert len(FOUNDERS) >= 30
    ids = [f.id for f in FOUNDERS]
    assert len(ids) == len(set(ids))


def test_the_castes_are_the_four_the_architecture_declares():
    assert {f.caste for f in FOUNDERS} == {"genesis", "archivist", "architect", "auditor"}


def test_the_civilisation_can_reproduce():
    """Publishing a tool, an agent and a pipeline each has an owner.

    Without these three the roster executes a fixed repertoire until somebody
    edits Python, which is not a civilisation — it is a program with characters.
    """
    assert founder("toolwright"), "nothing can publish a tool"
    assert founder("progenitor"), "nothing can publish an agent"
    assert founder("pipeline-conductor"), "nothing can publish a pipeline"
    assert founder("corpus-librarian"), "nothing owns the document spaces"
    assert founder("intake-praetor"), "nothing receives the prompt first"


def test_every_founder_states_the_same_eight_things():
    for f in FOUNDERS:
        rendered = render_prompt(f)
        for heading in ("YOUR MANDATE", "CONSTITUTIONAL BINDINGS",
                        "WHAT YOU ARE GIVEN", "WHAT YOU MAY CALL",
                        "HOW YOU DECIDE", "WHAT YOU EMIT", "WHAT YOU WRITE",
                        "WHEN YOU STOP OR ESCALATE", "WHAT YOU MUST NEVER DO"):
            assert heading in rendered, f"{f.id} is missing {heading}"


def test_no_founder_is_licensed_to_fabricate():
    """The one prohibition that outranks everything else, in every prompt."""
    for f in FOUNDERS:
        assert NO_FABRICATION in render_prompt(f), f.id


def test_the_directives_are_stated_once_and_reach_everyone():
    for f in FOUNDERS:
        rendered = render_prompt(f)
        for directive in CORE_DIRECTIVES:
            assert directive in rendered, f.id


def test_the_prompts_are_operational_not_atmospheric():
    """The previous generation averaged a thousand characters of register.

    Length is not the point; what it stands in for is: a prompt cannot state a
    mandate, a procedure, an output schema, a stopping rule and its
    prohibitions in a paragraph.
    """
    for f in FOUNDERS:
        rendered = render_prompt(f)
        assert len(rendered) > 2000, f"{f.id} is {len(rendered)} chars"
        assert len(f.procedure) >= 3, f.id
        assert len(f.emits) >= 3, f.id
        assert f.stops_when and f.never, f.id


def test_a_founder_only_names_tools_that_are_actually_published():
    """A prompt naming a tool nobody registered is a prompt whose agent guesses."""
    for f in FOUNDERS:
        for tool_line in f.tools:
            tool_id = tool_line.split(" — ")[0]
            assert tool_id in PLATFORM_TOOL_IDS, f"{f.id} names {tool_id}"


def test_the_seeded_toolbelt_is_exactly_what_the_founders_pin():
    seeded = {t["identity"]["tool_id"] for t in platform_tools("org_x")}
    assert seeded == set(PLATFORM_TOOL_IDS)
    pinned = {line.split(" — ")[0] for f in FOUNDERS for line in f.tools}
    assert pinned <= seeded


def test_seeded_tools_declare_their_side_effects_honestly():
    """`read` licenses speculative execution and free retries (Rule 6.2)."""
    by_id = {t["identity"]["tool_id"]: t["version"] for t in platform_tools("org_x")}
    assert by_id["mcp-pgvector-search"]["side_effects"] == "read"
    assert by_id["mcp-agent-discovery"]["side_effects"] == "read"
    assert by_id["mcp-tool-discovery"]["side_effects"] == "read"
    # These two change something somewhere, so they must not be retried freely.
    assert by_id["mcp-document-ingest"]["side_effects"] == "write"
    assert by_id["mcp-agent-invoke"]["side_effects"] == "write"


def test_seeded_tools_are_org_scoped_and_carry_schemas():
    for spec in platform_tools("org_x"):
        assert spec["identity"]["scope_type"] == "org"
        assert spec["identity"]["project_id"] is None
        assert spec["version"]["input_schema"]["properties"], spec["identity"]["tool_id"]
        assert spec["version"]["output_schema"]["properties"], spec["identity"]["tool_id"]
        # No literal credential ever reaches a registry row (Rule 6.3).
        assert spec["version"]["auth"] == {"mode": "none"}


def test_the_duty_bearers_declare_what_they_watch_and_what_they_change():
    assert {f.id for f in AUTONOMOUS} == {
        "quarantine-warden", "anomaly-detector", "proving-ground", "adversary"}
    for f in AUTONOMOUS:
        assert f.duty.interval_seconds >= 60, f.id
        assert f.duty.watches and f.duty.effect
        assert 1 <= f.duty.budget_per_cycle <= 20
        rendered = render_prompt(f)
        assert "YOUR DUTY CYCLE" in rendered
        assert "A cycle that finds nothing is a successful cycle" in rendered


def test_only_the_warden_may_quarantine():
    """Separation of powers, asserted rather than hoped for."""
    for f in FOUNDERS:
        if f.id == "quarantine-warden":
            continue
        assert "quarantine" not in " ".join(f.emits.keys()).lower(), f.id


def test_the_roster_renders_registration_payloads_for_a_project():
    members = roster("proj_test")
    assert len(members) == len(FOUNDERS)
    for member in members:
        assert member["agent_id"].endswith("-proj_test")
        assert member["system_prompt"].startswith("You are ")
        assert isinstance(member["tools"], list)
        assert member["token_balance"] > 0
        # Tool ids reach registration as ids, not as the prose used in prompts.
        for tool_id in member["tools"]:
            assert " " not in tool_id


def test_a_founders_prompt_is_found_by_its_project_scoped_agent_id():
    """Agents are `{founder_id}-{project_id}` once a project exists."""
    assert founder_prompt("intake-praetor-proj_abc123")
    assert founder("proving-ground-proj_abc123").id == "proving-ground"
    assert founder_prompt("not-a-founder-at-all") is None


def test_the_emitted_contract_is_valid_json_in_every_prompt():
    for f in FOUNDERS:
        rendered = render_prompt(f)
        start = rendered.index("no markdown fence:") + len("no markdown fence:")
        body = rendered[start:].lstrip()
        depth, end = 0, None
        for i, ch in enumerate(body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        assert end, f.id
        parsed = json.loads(body[:end])
        assert set(parsed) == set(f.emits), f.id


@pytest.mark.parametrize("founder_id,expected", [
    ("intake-praetor", "route"),
    ("progenitor", "action"),
    ("toolwright", "side_effects"),
    ("pipeline-conductor", "payload_map"),
    ("quarantine-warden", "release_condition"),
    ("adversary", "verdict"),
    ("proving-ground", "proposals"),
])
def test_the_founders_that_matter_emit_the_field_that_makes_them_useful(founder_id, expected):
    assert expected in BY_ID[founder_id].emits
