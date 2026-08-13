"""Runtime tests: termination, bounds, and the guarantees that stop a cycle
being mistaken for a completed run."""
import sys

import pytest

sys.path.insert(0, "../services/agent-registry")

from pipeline_runtime import (
    FAILED, HALTED, SUCCEEDED, PipelineError, PipelineExecutor,
    RecursionDepthExceeded, SharedContext,
)
from registry_model import ExecutionPolicy, PipelineVersionSpec, StepBinding, StepDependency

OBJ = {"type": "object", "properties": {"x": {"type": "string"}}}


def spec(steps, deps, entry, **kw):
    return PipelineVersionSpec(
        pipeline_id="p", version="1.0.0",
        steps={s: StepBinding(version_id=f"agv_{s}_1.0.0") for s in steps},
        dependencies=[StepDependency(from_step=a, to_step=b, **d) for a, b, d in deps],
        entry_steps=entry, input_schema=OBJ, output_schema=OBJ, **kw)


def runner(outputs=None):
    calls = []

    async def _run(step_id, version_id, payload, context):
        calls.append(step_id)
        return (outputs or {}).get(step_id, {})
    _run.calls = calls
    return _run


# ------------------------------------------------------------------ context

def test_undeclared_write_is_an_error_not_a_no_op():
    ctx = SharedContext({"default": "read", "steps": {"a": {"read": [], "write": ["ok"]}}})
    with pytest.raises(PipelineError, match="Rule 8.4"):
        ctx.write("a", "not_declared", 1)


def test_writes_are_append_only_with_revisions():
    """Rule 8.5: a cycle overwriting a key must not destroy the prior value."""
    ctx = SharedContext({"steps": {"a": {"write": ["k"], "read": ["k"]}}})
    ctx.write("a", "k", "first")
    ctx.write("a", "k", "second")
    assert [e.revision for e in ctx.history("k")] == [1, 2]
    assert [e.value for e in ctx.history("k")] == ["first", "second"]
    assert ctx.read("a", "k") == "second"


def test_conflicting_writers_are_recorded():
    """Rule 8.6: last-writer-wins, but never silently."""
    ctx = SharedContext({"steps": {"a": {"write": ["k"]}, "b": {"write": ["k"]}}})
    ctx.write("a", "k", 1)
    ctx.write("b", "k", 2)
    assert ctx.conflicts == [("k", "a", "b")]


# ------------------------------------------------------------------- bounds

@pytest.mark.asyncio
async def test_linear_pipeline_succeeds():
    s = spec(["a", "b"], [("a", "b", {})], ["a"])
    ex = PipelineExecutor(runner({"b": {"done": True}}))
    run = await ex.execute(s, {"x": 1})
    assert run.status == SUCCEEDED and run.succeeded


@pytest.mark.asyncio
async def test_cycle_terminates_when_the_condition_stops_firing():
    """The condition is absent from the output, so the back edge does not fire."""
    s = spec(["a", "b"], [("a", "b", {}), ("b", "a", {"relationship": "on_condition",
                                                     "condition": "again"})],
             ["a"], execution=ExecutionPolicy(max_iterations=10))
    ex = PipelineExecutor(runner())
    run = await ex.execute(s, {})
    assert run.status == SUCCEEDED
    assert run.iteration_count == 2


@pytest.mark.asyncio
async def test_runaway_cycle_fails_at_the_limit():
    s = spec(["a", "b"], [("a", "b", {}), ("b", "a", {"relationship": "on_condition",
                                                     "condition": "again"})],
             ["a"], execution=ExecutionPolicy(max_iterations=6))
    ex = PipelineExecutor(runner({"a": {"again": True}, "b": {"again": True}}))
    run = await ex.execute(s, {})
    assert run.status == FAILED
    assert run.iteration_count == 6
    assert "max_iterations" in run.error["message"]


@pytest.mark.asyncio
async def test_halt_and_return_is_not_success():
    """Rule 6.3: exhaustion must be distinguishable from completion."""
    s = spec(["a", "b"], [("a", "b", {}), ("b", "a", {"relationship": "on_condition",
                                                     "condition": "again"})],
             ["a"], execution=ExecutionPolicy(max_iterations=4,
                                              on_limit="halt_and_return"))
    ex = PipelineExecutor(runner({"a": {"again": True}, "b": {"again": True}}))
    run = await ex.execute(s, {})
    assert run.status == HALTED
    assert run.succeeded is False, "halted must never report success"
    assert run.halt_reason and "max_iterations" in run.halt_reason


@pytest.mark.asyncio
async def test_recursion_depth_is_enforced_before_work():
    s = spec(["a"], [], ["a"], execution=ExecutionPolicy(max_recursion_depth=1))
    r = runner()
    ex = PipelineExecutor(r)
    parent = await ex.execute(s, {})
    child = ex.create_run(s, parent)          # depth 1, allowed
    with pytest.raises(RecursionDepthExceeded, match="Rule 6.5"):
        ex.create_run(s, child)               # depth 2, rejected
    # The rejected run did no work.
    assert r.calls == ["a"]


@pytest.mark.asyncio
async def test_step_failure_is_recorded_not_swallowed():
    async def boom(step_id, version_id, payload, context):
        raise RuntimeError("model unreachable")
    run = await PipelineExecutor(boom).execute(spec(["a"], [], ["a"]), {})
    assert run.status == FAILED
    assert run.error["message"] == "model unreachable"


@pytest.mark.asyncio
async def test_payload_map_renames_fields_between_steps():
    s = spec(["a", "b"], [("a", "b", {"payload_map": {"out": "in"}})], ["a"])
    seen = {}

    async def capture(step_id, version_id, payload, context):
        seen[step_id] = payload
        return {"out": 42}
    await PipelineExecutor(capture).execute(s, {})
    assert seen["b"] == {"in": 42}
