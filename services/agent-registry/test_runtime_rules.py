"""Runtime tests for the rules the executor contradicted (spec §13.2).

The three regressions worth naming, because each one *looked* implemented:

  - `context_policy.inherit` branched and built an identical fresh context in
    both arms, so declaring it changed nothing (Rule 6.6);
  - `msg_id` was generated per envelope and never checked, so at-least-once
    delivery was not idempotent and `retry_count` was a field nothing
    incremented (Rule 8.2, §11.2);
  - `execution.concurrency` was declared, stored, and ignored.
"""
import asyncio

import pytest

from pipeline_runtime import (
    FAILED, HALTED, SUCCEEDED, ContextSchemaError, PipelineError,
    PipelineExecutor, PipelineRun, RedisTransport, SharedContext,
)
from registry_model import (
    ExecutionPolicy, PipelineVersionSpec, StepBinding, StepDependency,
)

OBJ = {"type": "object", "properties": {"text": {"type": "string"}}}


def spec(steps, deps=(), entry=None, **kw):
    return PipelineVersionSpec(
        pipeline_id="pln_t", version="1.0.0",
        steps={s: StepBinding(version_id=f"agv_{s}_1.0.0") for s in steps},
        dependencies=[StepDependency(from_step=a, to_step=b, **d) for a, b, d in deps],
        entry_steps=list(entry or [steps[0]]),
        input_schema=OBJ, output_schema=OBJ, **kw)


def runner(record=None, fail_times=0, delay=0.0, output=None):
    """A step runner that records calls and can fail a set number of times."""
    state = {"failures": fail_times}

    async def _run(step_id, version_id, payload, context):
        if record is not None:
            record.append(step_id)
        if delay:
            await asyncio.sleep(delay)
        if state["failures"] > 0:
            state["failures"] -= 1
            raise RuntimeError("transient")
        return dict(output or {"ok": True, "usage": {"input_tokens": 1,
                                                     "output_tokens": 1}})
    return _run


# ----------------------------------------------------------------- Rule 6.6

@pytest.mark.asyncio
async def test_a_child_run_does_not_see_the_parent_context_by_default():
    """Rule 6.6 — sharing a mutable bag is how a recursion corrupts its inputs."""
    parent_context = SharedContext({"default": "read_write"})
    parent_context.write("step_a", "seed", "from parent")

    executor = PipelineExecutor(runner())
    parent = executor.create_run(spec(["a"]))
    child = await executor.execute(spec(["a"]), {}, parent=parent,
                                   parent_context=parent_context)
    assert child.succeeded
    # The child's own context is empty: nothing inherited.
    assert child.output.get("seed") is None


@pytest.mark.asyncio
async def test_inherit_true_actually_shares_the_parent_context():
    """The branch used to build an identical fresh context in both arms."""
    policy = {"default": "read_write", "inherit": True}
    parent_context = SharedContext(policy)
    parent_context.write("step_a", "seed", "from parent")

    seen = {}

    async def _run(step_id, version_id, payload, context):
        seen["value"] = context.read(step_id, "seed")
        return {"ok": True}

    executor = PipelineExecutor(_run)
    child_spec = spec(["a"], context_policy=policy)
    parent = executor.create_run(child_spec)
    await executor.execute(child_spec, {}, parent=parent,
                           parent_context=parent_context)
    assert seen["value"] == "from parent"


@pytest.mark.asyncio
async def test_inherit_without_a_parent_is_still_a_fresh_scope():
    policy = {"default": "read_write", "inherit": True}
    executor = PipelineExecutor(runner())
    run = await executor.execute(spec(["a"], context_policy=policy), {})
    assert run.succeeded


# ----------------------------------------------------------------- Rule 8.2

def test_a_message_is_processed_once():
    run = PipelineRun(pipeline_version_id="plv_x")
    assert run.seen("m1") is False
    assert run.seen("m1") is True


@pytest.mark.asyncio
async def test_a_redelivered_message_does_not_re_execute_the_step():
    calls = []
    executor = PipelineExecutor(runner(calls))
    run = executor.create_run(spec(["a"]))
    run.seen("already-done")

    from pipeline_runtime import _Pending
    out = await executor._dispatch(run, spec(["a"]),
                                   _Pending(None, "a", {}, "already-done"),
                                   SharedContext(), 0)
    assert out is None
    assert calls == []
    assert run.retry_count == 1


@pytest.mark.asyncio
async def test_a_retry_reuses_the_msg_id_and_counts_separately():
    """§11.2 — a retried step and a one-node cycle are not the same event."""
    published = []

    class Recorder(RedisTransport):
        async def publish(self, channel, message):
            published.append((message["msg_id"], message["attempt"]))

    executor = PipelineExecutor(runner(fail_times=2), transport=Recorder(object()))
    run = await executor.execute(spec(["a"], execution=ExecutionPolicy(max_retries=3)),
                                 {})
    assert run.succeeded
    assert run.retry_count == 2
    # One iteration: the step was reached once along one edge.
    assert run.iteration_count == 1
    # And every attempt carried the same dedup key.
    assert len({msg_id for msg_id, _ in published}) == 1
    assert [attempt for _, attempt in published] == [1, 2, 3]


@pytest.mark.asyncio
async def test_retries_are_bounded():
    executor = PipelineExecutor(runner(fail_times=99))
    run = await executor.execute(spec(["a"], execution=ExecutionPolicy(max_retries=2)),
                                 {})
    assert run.status == FAILED
    assert run.retry_count == 2


@pytest.mark.asyncio
async def test_a_rule_violation_is_not_retried():
    """Retrying a step that broke a rule just breaks it again, more expensively."""
    async def _run(step_id, version_id, payload, context):
        raise PipelineError("Rule 8.4: undeclared key")

    executor = PipelineExecutor(_run)
    run = await executor.execute(spec(["a"], execution=ExecutionPolicy(max_retries=5)),
                                 {})
    assert run.status == FAILED
    assert run.retry_count == 0


# ------------------------------------------------------------- concurrency

@pytest.mark.asyncio
async def test_independent_branches_run_concurrently():
    """`concurrency` was declared, stored and ignored."""
    order = []

    async def _run(step_id, version_id, payload, context):
        order.append(("start", step_id))
        await asyncio.sleep(0.01)
        order.append(("end", step_id))
        return {"ok": True}

    executor = PipelineExecutor(_run)
    parallel = spec(["a", "b"], entry=["a", "b"],
                    execution=ExecutionPolicy(concurrency=2))
    await executor.execute(parallel, {})
    # Both started before either finished — impossible one-at-a-time.
    assert order[0][0] == "start" and order[1][0] == "start"


@pytest.mark.asyncio
async def test_concurrency_one_stays_sequential():
    order = []

    async def _run(step_id, version_id, payload, context):
        order.append(("start", step_id))
        await asyncio.sleep(0.01)
        order.append(("end", step_id))
        return {"ok": True}

    executor = PipelineExecutor(_run)
    sequential = spec(["a", "b"], entry=["a", "b"],
                      execution=ExecutionPolicy(concurrency=1))
    await executor.execute(sequential, {})
    assert order[1][0] == "end"


@pytest.mark.asyncio
async def test_concurrency_does_not_exceed_the_iteration_bound():
    """The bound is checked before dispatch, so a wide batch cannot overshoot."""
    calls = []
    executor = PipelineExecutor(runner(calls))
    wide = spec(["a", "b", "c"], entry=["a", "b", "c"],
                execution=ExecutionPolicy(concurrency=5, max_iterations=2,
                                          on_limit="halt_and_return"))
    run = await executor.execute(wide, {})
    assert run.iteration_count <= 2
    assert len(calls) <= 2
    assert run.status == HALTED


# ------------------------------------------------------- context schemas

def test_a_context_write_matching_its_schema_is_stored():
    context = SharedContext({
        "default": "read_write",
        "schemas": {"entities": {"type": "array"}}})
    context.write("step_a", "entities", ["acme"])
    assert context.snapshot()["entities"] == ["acme"]


def test_a_context_write_failing_its_schema_raises():
    """§11.3 — a declared schema that is never checked is documentation."""
    context = SharedContext({
        "default": "read_write",
        "schemas": {"entities": {"type": "array"}}})
    with pytest.raises(ContextSchemaError, match="expected array"):
        context.write("step_a", "entities", "not a list")


def test_a_key_with_no_schema_is_unvalidated():
    """Requiring one for every scratch value pushes authors to one untyped bag."""
    context = SharedContext({"default": "read_write"})
    context.write("step_a", "scratch", object())


def test_a_nested_required_key_is_checked():
    context = SharedContext({
        "default": "read_write",
        "schemas": {"report": {"type": "object", "required": ["title"]}}})
    context.write("step_a", "report", {"title": "ok"})
    with pytest.raises(ContextSchemaError, match="missing required key"):
        context.write("step_a", "report", {"body": "no title"})


def test_undeclared_writes_still_raise():
    """Rule 8.4 — a step whose writes vanish produces a stale read downstream."""
    context = SharedContext({"default": "read",
                             "steps": {"step_a": {"read": ["x"], "write": []}}})
    with pytest.raises(PipelineError, match="Rule 8.4"):
        context.write("step_a", "x", 1)


# ------------------------------------------------------------ Rule 8.3

@pytest.mark.asyncio
async def test_a_broken_configured_transport_fails_the_run():
    """Rule 8.3 — an event log missing steps that ran is worse than a failure."""
    class Broken:
        async def publish(self, channel, message):
            raise ConnectionError("redis gone")

    executor = PipelineExecutor(runner(), transport=RedisTransport(Broken()))
    run = await executor.execute(spec(["a"]), {})
    assert run.status == FAILED
    assert "Rule 8.3" in run.error["message"]


@pytest.mark.asyncio
async def test_no_transport_is_a_mode_not_a_failure():
    """Without REDIS_URL the transport is a declared no-op and runs execute."""
    transport = RedisTransport(None)
    assert transport.configured is False
    executor = PipelineExecutor(runner(), transport=transport)
    run = await executor.execute(spec(["a"]), {})
    assert run.succeeded


# --------------------------------------------------- resource limits, trigger

@pytest.mark.asyncio
async def test_a_step_exceeding_its_wall_clock_limit_fails():
    """§3.2.1 — hashed into every agent version and enforced nowhere."""
    limited = spec(["a"])
    limited.steps["a"] = limited.steps["a"].model_copy(
        update={"resource_limits": {"max_wall_secs": 0.01}})
    executor = PipelineExecutor(runner(delay=0.2))
    run = await executor.execute(limited, {})
    assert run.status == FAILED
    assert "max_wall_secs" in run.error["message"]


@pytest.mark.asyncio
async def test_a_step_within_its_limit_succeeds():
    limited = spec(["a"])
    limited.steps["a"] = limited.steps["a"].model_copy(
        update={"resource_limits": {"max_wall_secs": 5}})
    executor = PipelineExecutor(runner(delay=0.01))
    run = await executor.execute(limited, {})
    assert run.succeeded


@pytest.mark.asyncio
async def test_a_run_records_what_started_it_and_what_it_was_given():
    """§3.5 — a run that cannot say what caused it is hard to explain later."""
    executor = PipelineExecutor(runner())
    run = await executor.execute(spec(["a"]), {"prompt": "hello"},
                                 trigger={"kind": "mcp", "by": "agent:x@1.0.0"})
    assert run.trigger == {"kind": "mcp", "by": "agent:x@1.0.0"}
    assert run.input == {"prompt": "hello"}
    payload = run.to_payload()
    assert payload["trigger"]["kind"] == "mcp"
    # The dedup set is transport detail, not part of the run record.
    assert "processed_msg_ids" not in payload
    assert payload["processed_messages"] == 1


# ------------------------------------------------------------------ budgets

@pytest.mark.asyncio
async def test_the_compute_budget_halts_rather_than_succeeds():
    """Rule 6.3 — exhaustion is never reported as success."""
    executor = PipelineExecutor(
        runner(output={"ok": True, "usage": {"input_tokens": 100, "output_tokens": 100}}))
    budgeted = spec(["a"], execution=ExecutionPolicy(max_compute_units=10))
    run = await executor.execute(budgeted, {})
    assert run.status == HALTED
    assert "compute budget" in run.halt_reason


@pytest.mark.asyncio
async def test_recursion_depth_is_enforced_before_any_work():
    """Rule 6.5 — enforcing on completion means the work is already spent."""
    from pipeline_runtime import RecursionDepthExceeded

    calls = []
    executor = PipelineExecutor(runner(calls))
    bounded = spec(["a"], execution=ExecutionPolicy(max_recursion_depth=1))
    parent = executor.create_run(bounded)
    child = executor.create_run(bounded, parent=parent)
    with pytest.raises(RecursionDepthExceeded):
        executor.create_run(bounded, parent=child)
    assert calls == []


@pytest.mark.asyncio
async def test_a_nested_invocation_links_to_its_parent():
    """§6.3 — the parent_run_id chain is the recursion stack."""
    executor = PipelineExecutor(runner())
    nested = spec(["a"], execution=ExecutionPolicy(max_recursion_depth=3))
    parent = executor.create_run(nested)
    child = await executor.invoke_nested(nested, {}, parent=parent)
    assert child.parent_run_id == parent.run_id
    assert child.depth == 1
    assert child.trigger == {"kind": "agent", "by": parent.run_id}


# ------------------------------------------------- following an invocation

@pytest.mark.asyncio
async def test_a_step_declaring_an_invocation_runs_the_nested_pipeline():
    """§6.3 — the edge is written at publish; this is the executor following it."""
    calls = []
    inner = spec(["inner"])

    async def resolve(pipeline_id, version=None):
        assert pipeline_id == "pln_inner"
        return inner

    executor = PipelineExecutor(runner(calls), pipeline_resolver=resolve)
    outer = spec(["a"], execution=ExecutionPolicy(max_recursion_depth=2))
    outer.steps["a"] = outer.steps["a"].model_copy(
        update={"invokes_pipeline": {"pipeline_id": "pln_inner"}})

    run = await executor.execute(outer, {})
    assert run.succeeded
    assert calls == ["a", "inner"]
    assert run.output["nested_status"] == SUCCEEDED


@pytest.mark.asyncio
async def test_a_nested_run_counts_against_the_parents_compute_budget():
    """§11.4 — the budget covers the whole run tree, not one frame of it."""
    heavy = {"ok": True, "usage": {"input_tokens": 50, "output_tokens": 50}}
    inner = spec(["inner"])

    async def resolve(pipeline_id, version=None):
        return inner

    executor = PipelineExecutor(runner(output=heavy), pipeline_resolver=resolve)
    outer = spec(["a"], execution=ExecutionPolicy(max_recursion_depth=2,
                                                  max_compute_units=500))
    outer.steps["a"] = outer.steps["a"].model_copy(
        update={"invokes_pipeline": {"pipeline_id": "pln_inner"}})

    run = await executor.execute(outer, {})
    # 400 for the step plus 400 for the child, over the 500 budget.
    assert run.status == HALTED
    assert "compute budget" in run.halt_reason


def _exploding_runner():
    async def _run(step_id, version_id, payload, context):
        if step_id == "inner":
            raise RuntimeError("inner blew up")
        return {"ok": True}
    return _run


@pytest.mark.asyncio
async def test_an_unhandled_nested_failure_fails_the_parent():
    """Rule 6.3 — a complete result built on an incomplete nested run is not success."""
    inner = spec(["inner"])

    async def resolve(pipeline_id, version=None):
        return inner

    executor = PipelineExecutor(_exploding_runner(), pipeline_resolver=resolve)
    outer = spec(["a"], execution=ExecutionPolicy(max_recursion_depth=2))
    outer.steps["a"] = outer.steps["a"].model_copy(
        update={"invokes_pipeline": {"pipeline_id": "pln_inner"}})

    run = await executor.execute(outer, {})
    assert run.status == FAILED
    assert "not handled" in run.error["message"]


@pytest.mark.asyncio
async def test_an_on_failure_edge_routes_a_nested_failure():
    """With a declared handler, the author has said what to do about it."""
    inner = spec(["inner"])

    async def resolve(pipeline_id, version=None):
        return inner

    executor = PipelineExecutor(_exploding_runner(), pipeline_resolver=resolve)
    outer = spec(["a", "recover"], [("a", "recover", {"relationship": "on_failure"})],
                 entry=["a"], execution=ExecutionPolicy(max_recursion_depth=2))
    outer.steps["a"] = outer.steps["a"].model_copy(
        update={"invokes_pipeline": {"pipeline_id": "pln_inner"}})

    run = await executor.execute(outer, {})
    assert run.succeeded
    # The recovery step ran, and it is the run's output.
    assert run.output["ok"] is True


@pytest.mark.asyncio
async def test_an_invocation_with_no_resolver_fails_loudly():
    """Declaring an invocation and not performing it is a plausible wrong answer."""
    executor = PipelineExecutor(runner())
    outer = spec(["a"])
    outer.steps["a"] = outer.steps["a"].model_copy(
        update={"invokes_pipeline": {"pipeline_id": "pln_inner"}})
    run = await executor.execute(outer, {})
    assert run.status == FAILED
    assert "pipeline_resolver" in run.error["message"]


@pytest.mark.asyncio
async def test_recursion_stops_at_the_declared_depth():
    """Rule 6.5, now on a path that can actually be entered."""
    calls = []
    recursive = spec(["a"], execution=ExecutionPolicy(max_recursion_depth=2))
    recursive.steps["a"] = recursive.steps["a"].model_copy(
        update={"invokes_pipeline": {"pipeline_id": "pln_t"}})

    async def resolve(pipeline_id, version=None):
        return recursive

    executor = PipelineExecutor(runner(calls), pipeline_resolver=resolve)
    run = await executor.execute(recursive, {})
    # depth 0 -> 1 -> 2, then create_run refuses depth 3 and the run fails.
    assert run.status == FAILED
    assert len(calls) == 3
