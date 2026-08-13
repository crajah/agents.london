"""Tests for the registration rules. Run: python3 -m pytest services/agent-registry -q"""
import copy

import pytest

from registry_model import (
    AgentVersionSpec, ExecutionPolicy, PipelineVersionSpec, RegistrationError,
    StepBinding, StepDependency, content_hash, find_back_edges,
    validate_pipeline_version,
)

OBJ = {"type": "object", "properties": {"text": {"type": "string"},
                                        "entities": {"type": "array"}}}


def agent(name="a", version="1.0.0", prompt="do the thing"):
    return AgentVersionSpec(agent_id=name, version=version, system_prompt=prompt,
                            model={"name": "DeepSeek-V3.2"},
                            input_schema=OBJ, output_schema=OBJ)


def pipeline(steps, deps, entry, **kw):
    return PipelineVersionSpec(
        pipeline_id="p", version="1.0.0",
        steps={s: StepBinding(version_id=f"agv_{s}_1.0.0") for s in steps},
        dependencies=[StepDependency(from_step=a, to_step=b, **d) for a, b, d in deps],
        entry_steps=entry, input_schema=OBJ, output_schema=OBJ, **kw)


def statuses(steps):
    return {f"agv_{s}_1.0.0": "published" for s in steps}


def schemas(steps):
    return {f"agv_{s}_1.0.0": (OBJ, OBJ) for s in steps}


# ------------------------------------------------------------- content hash

def test_hash_ignores_description_but_not_prompt():
    """A prompt edit is a behaviour change; a changelog edit is not."""
    a = agent()
    b = agent(prompt="do the thing differently")
    assert a.hash() != b.hash()
    same = copy.deepcopy(a)
    same.changelog = "reworded entirely"
    assert same.hash() == a.hash()


def test_hash_is_order_independent():
    """Canonical JSON: dict ordering must not change identity."""
    one = content_hash({"tools": ["a", "b"], "model": {"x": 1, "y": 2}})
    two = content_hash({"model": {"y": 2, "x": 1}, "tools": ["a", "b"]})
    assert one == two


def test_schemas_are_required():
    with pytest.raises(Exception):
        AgentVersionSpec(agent_id="a", version="1.0.0", system_prompt="p",
                         model={"name": "m"}, input_schema={"type": "string"},
                         output_schema=OBJ)


# -------------------------------------------------------------- back edges

def test_acyclic_pipeline_has_no_back_edges():
    deps = [StepDependency(from_step="a", to_step="b"),
            StepDependency(from_step="b", to_step="c")]
    assert find_back_edges({"a", "b", "c"}, deps, ["a"]) == set()


def test_self_loop_is_a_back_edge():
    deps = [StepDependency(from_step="a", to_step="a")]
    assert find_back_edges({"a"}, deps, ["a"]) == {("a", "a")}


def test_longer_cycle_is_found():
    deps = [StepDependency(from_step="a", to_step="b"),
            StepDependency(from_step="b", to_step="c"),
            StepDependency(from_step="c", to_step="a")]
    assert find_back_edges({"a", "b", "c"}, deps, ["a"]) == {("c", "a")}


def test_diamond_is_not_a_cycle():
    """Two paths reconverging is not a cycle — a naive 'already seen' check
    would call it one, and reject a perfectly ordinary fan-out/fan-in."""
    deps = [StepDependency(from_step="a", to_step="b"),
            StepDependency(from_step="a", to_step="c"),
            StepDependency(from_step="b", to_step="d"),
            StepDependency(from_step="c", to_step="d")]
    assert find_back_edges({"a", "b", "c", "d"}, deps, ["a"]) == set()


def test_deep_chain_does_not_exhaust_the_stack():
    """Iterative DFS: 5000 steps would blow a recursive implementation."""
    n = 5000
    steps = {f"s{i}" for i in range(n)}
    deps = [StepDependency(from_step=f"s{i}", to_step=f"s{i+1}") for i in range(n - 1)]
    assert find_back_edges(steps, deps, ["s0"]) == set()


# ------------------------------------------------------------ registration

def test_cyclic_pipeline_without_bound_is_rejected():
    p = pipeline(["a", "b"], [("a", "b", {}), ("b", "a", {"relationship": "on_condition"})], ["a"])
    with pytest.raises(RegistrationError, match="Rule 6.1"):
        validate_pipeline_version(p, statuses(["a", "b"]), schemas(["a", "b"]))


def test_cyclic_pipeline_with_bound_and_exit_is_accepted():
    p = pipeline(["a", "b"], [("a", "b", {}), ("b", "a", {"relationship": "on_condition"})],
                 ["a"], execution=ExecutionPolicy(max_iterations=10))
    out = validate_pipeline_version(p, statuses(["a", "b"]), schemas(["a", "b"]))
    assert out["is_cyclic"] and out["back_edges"] == [["b", "a"]] or out["back_edges"] == [("b", "a")]


def test_inescapable_cycle_is_rejected():
    """All edges unconditional, nothing leaves: runs to the cap every time."""
    p = pipeline(["a", "b"], [("a", "b", {}), ("b", "a", {})], ["a"],
                 execution=ExecutionPolicy(max_iterations=10))
    with pytest.raises(RegistrationError, match="Rule 6.2"):
        validate_pipeline_version(p, statuses(["a", "b"]), schemas(["a", "b"]))


def test_cycle_with_edge_leaving_is_accepted():
    p = pipeline(["a", "b", "c"], [("a", "b", {}), ("b", "a", {}), ("b", "c", {})], ["a"],
                 execution=ExecutionPolicy(max_iterations=10))
    validate_pipeline_version(p, statuses(["a", "b", "c"]), schemas(["a", "b", "c"]))


def test_unpublished_version_cannot_be_pinned():
    p = pipeline(["a"], [], ["a"])
    with pytest.raises(RegistrationError, match="Rule 4.3"):
        validate_pipeline_version(p, {"agv_a_1.0.0": "draft"}, schemas(["a"]))


def test_unknown_version_is_rejected():
    p = pipeline(["a"], [], ["a"])
    with pytest.raises(RegistrationError, match="Rule 4.3"):
        validate_pipeline_version(p, {}, schemas(["a"]))


def test_dependency_on_unknown_step_is_rejected():
    p = pipeline(["a"], [("a", "ghost", {})], ["a"])
    with pytest.raises(RegistrationError, match="Rule 5.2"):
        validate_pipeline_version(p, statuses(["a"]), schemas(["a"]))


def test_payload_map_field_must_exist_upstream():
    p = pipeline(["a", "b"], [("a", "b", {"payload_map": {"absent": "text"}})], ["a"])
    with pytest.raises(RegistrationError, match="output schema"):
        validate_pipeline_version(p, statuses(["a", "b"]), schemas(["a", "b"]))


def test_payload_map_field_must_exist_downstream():
    p = pipeline(["a", "b"], [("a", "b", {"payload_map": {"text": "absent"}})], ["a"])
    with pytest.raises(RegistrationError, match="input schema"):
        validate_pipeline_version(p, statuses(["a", "b"]), schemas(["a", "b"]))


def test_valid_payload_map_is_accepted():
    p = pipeline(["a", "b"], [("a", "b", {"payload_map": {"entities": "text"}})], ["a"])
    validate_pipeline_version(p, statuses(["a", "b"]), schemas(["a", "b"]))


def test_pipeline_needs_an_entry_step():
    with pytest.raises(Exception):
        p = pipeline(["a"], [], [])
        validate_pipeline_version(p, statuses(["a"]), schemas(["a"]))
