"""Executing pipelines: runs, cycles, recursion and shared context.

The registry stores definitions; this executes them. The split matters because
definitions are immutable and cyclic, while runs are mutable and finite — a
cycle in the definition becomes a bounded number of iterations in the run
(spec §6), and that boundary is the only thing that makes a cyclic pipeline
safe to execute at all.

Everything enforced here is enforced *before* work is spent, not after:
recursion depth at run creation (Rule 6.5), iteration count before dispatching
the next step, the compute budget before the next dispatch. Checking afterwards
means the budget is already gone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

QUEUED, RUNNING, SUCCEEDED, FAILED, HALTED = (
    "queued", "running", "succeeded", "failed", "halted")

# Terminal states that are NOT success. Rule 6.3: `halted` must never be
# reported as success at any layer — a caller that cannot distinguish "finished"
# from "ran out of iterations" will treat a partial result as a complete one.
UNSUCCESSFUL = {FAILED, HALTED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineError(RuntimeError):
    """Execution failed. The message names the step and the reason."""


class RecursionDepthExceeded(PipelineError):
    pass


class ContextSchemaError(PipelineError):
    """A context write failed its declared schema (spec §11.3)."""


# ------------------------------------------------------------------ context

@dataclass
class ContextEntry:
    key: str
    value: Any
    written_by: str
    revision: int
    written_at: str = field(default_factory=_now)


def _matches(value: Any, schema: Dict[str, Any]) -> Optional[str]:
    """A deliberately small JSON Schema check for context values (§11.3).

    Type, required keys, and declared property types. Not a full validator: the
    failure being prevented is a step writing a shape a later step cannot read,
    and these three catch it.
    """
    expected = schema.get("type")
    types = {"string": str, "integer": int, "number": (int, float),
             "boolean": bool, "array": list, "object": dict}
    if expected:
        if expected == "null":
            if value is not None:
                return "expected null"
        else:
            python_type = types.get(expected)
            if python_type is not None:
                if expected in ("integer", "number") and isinstance(value, bool):
                    return f"expected {expected}, got boolean"
                if not isinstance(value, python_type):
                    return f"expected {expected}, got {type(value).__name__}"
    if isinstance(value, dict):
        for key in schema.get("required", []) or []:
            if key not in value:
                return f"missing required key {key!r}"
        for key, sub in (schema.get("properties") or {}).items():
            if key in value and isinstance(sub, dict):
                problem = _matches(value[key], sub)
                if problem:
                    return f"{key}: {problem}"
    return None


class SharedContext:
    """Per-run key/value store with declared per-step access (spec §8.2).

    Access is declared in the pipeline version, not inferred from use. Without
    that, a cyclic pipeline's second iteration silently reads values its first
    iteration happened to write, and the coupling is invisible in the
    definition — which makes the pipeline unreproducible for a reason nobody
    can see by reading it.
    """

    def __init__(self, policy: Optional[Dict[str, Any]] = None) -> None:
        self._policy = policy or {}
        self._entries: Dict[str, List[ContextEntry]] = {}
        self.conflicts: List[Tuple[str, str, str]] = []

    def _allowed(self, step_id: str, key: str, mode: str) -> bool:
        steps = self._policy.get("steps", {})
        if step_id not in steps:
            # No declaration for this step: fall back to the pipeline default.
            return self._policy.get("default", "read") in (mode, "read_write")
        return key in (steps[step_id].get(mode) or [])

    def read(self, step_id: str, key: str) -> Any:
        if not self._allowed(step_id, key, "read"):
            raise PipelineError(
                f"Rule 8.4: step {step_id!r} read undeclared context key {key!r}")
        entries = self._entries.get(key)
        return entries[-1].value if entries else None

    def write(self, step_id: str, key: str, value: Any) -> ContextEntry:
        if not self._allowed(step_id, key, "write"):
            # An error, not a silent no-op: a step whose writes vanish produces
            # a downstream step that reads a stale value and cannot tell.
            raise PipelineError(
                f"Rule 8.4: step {step_id!r} wrote undeclared context key {key!r}")

        # §11.3 — where a key declares a schema, a write that fails it raises
        # rather than storing. Where a key has none, values are unvalidated:
        # requiring a schema for every scratch value would push authors toward
        # one untyped bag key to avoid the ceremony.
        schema = (self._policy.get("schemas") or {}).get(key)
        if isinstance(schema, dict):
            problem = _matches(value, schema)
            if problem:
                raise ContextSchemaError(
                    f"§11.3: step {step_id!r} wrote context key {key!r} failing its "
                    f"declared schema — {problem}")

        history = self._entries.setdefault(key, [])
        if history and history[-1].written_by != step_id:
            # Rule 8.6: last writer wins, but the overwrite is recorded. Silent
            # interleaving in a concurrent pipeline is not reproducible.
            self.conflicts.append((key, history[-1].written_by, step_id))
            logger.warning("context key %r overwritten by %r (previously %r)",
                           key, step_id, history[-1].written_by)
        # Rule 8.5: append-only. A step in a cycle overwriting a key does not
        # destroy the prior value, which is what makes a cyclic run debuggable.
        entry = ContextEntry(key=key, value=value, written_by=step_id,
                             revision=len(history) + 1)
        history.append(entry)
        return entry

    def snapshot(self) -> Dict[str, Any]:
        return {k: v[-1].value for k, v in self._entries.items()}

    def history(self, key: str) -> List[ContextEntry]:
        return list(self._entries.get(key, []))


# ---------------------------------------------------------------------- runs

@dataclass
class PipelineRun:
    pipeline_version_id: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_run_id: Optional[str] = None
    depth: int = 0
    status: str = QUEUED
    # What started this run (§3.5). Without it a run cannot say what caused it,
    # which is the first question asked of any run that misbehaved.
    trigger: Dict[str, Any] = field(default_factory=dict)
    input: Dict[str, Any] = field(default_factory=dict)
    # Separate counters (spec §11.2): a retried step and a one-node cycle are
    # not the same event, and conflating them made an iteration budget
    # uninterpretable — transport retries could exhaust a cycle allowance.
    iteration_count: int = 0
    retry_count: int = 0
    compute_units: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    halt_reason: Optional[str] = None
    # Rule 8.2: delivery is at-least-once, so every step must be idempotent on
    # msg_id. The ids already processed by this run are recorded here.
    processed_msg_ids: Set[str] = field(default_factory=set)
    # What actually ran, in order. Becomes the `run_step` edges (§5): without
    # it, "what has this agent version actually executed" is a scan of every
    # run payload rather than one hop.
    executed_steps: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCEEDED

    def seen(self, msg_id: str) -> bool:
        """Whether this message was already processed (Rule 8.2).

        Recording the id and reporting the duplicate are one operation, so
        there is no window between the check and the mark.
        """
        if msg_id in self.processed_msg_ids:
            return True
        self.processed_msg_ids.add(msg_id)
        return False

    def to_payload(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        # A set is not JSON. The count is what a run record needs; the ids
        # themselves are transport detail with no value after the run ends.
        d["processed_messages"] = len(self.processed_msg_ids)
        d.pop("processed_msg_ids", None)
        d["succeeded"] = self.succeeded
        return d


class RedisTransport:
    """Channel naming and the message envelope (spec §8.1).

    Redis carries messages, not state: an envelope references context by id
    rather than embedding it (Rule 8.1). post-graph is the system of record, so
    a Redis flush costs in-flight work and never committed history.
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    @property
    def configured(self) -> bool:
        """Whether a transport was configured at all.

        Rule 8.3 turns on this distinction: **no transport** is a mode the
        operator chose, **a broken transport** is a failure, and the second must
        not be silently rendered as the first.
        """
        return self._redis is not None

    @staticmethod
    def step_channel(run_id: str, step_id: str) -> str:
        return f"agent:run:{run_id}:step:{step_id}"

    @staticmethod
    def events_channel(run_id: str) -> str:
        return f"agent:run:{run_id}:events"

    def envelope(self, run: PipelineRun, from_step: Optional[str], to_step: str,
                 payload: Dict[str, Any], attempt: int = 1,
                 msg_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            # Rule 8.2 dedup key. A retry reuses the id of the message it is
            # retrying — a fresh id per attempt would make the dedup set
            # unable to recognise a redelivery, which is the only thing it is
            # there for.
            "msg_id": msg_id or uuid.uuid4().hex,
            "run_id": run.run_id,
            "from_step": from_step,
            "to_step": to_step,
            "attempt": attempt,
            "sent_at": _now(),
            "payload": payload,
            "context_ref": f"ctx_{run.run_id}",
        }

    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Publish, or raise (Rule 8.3).

        A step that cannot reach a *configured* Redis fails the run rather than
        publishing nothing and carrying on: that produces an event log missing
        steps that really happened, and anything reading the log treats absence
        as "did not run".
        """
        if self._redis is None:
            return
        try:
            await self._redis.publish(channel, json.dumps(message, default=str))
        except Exception as e:
            raise PipelineError(
                f"Rule 8.3: could not publish to {channel!r}: {e}. The run fails "
                f"rather than continuing with an incomplete event log.") from e


# ------------------------------------------------------------------ executor

@dataclass
class _Pending:
    """One step waiting to be dispatched, with the message identifying it."""
    from_step: Optional[str]
    step_id: str
    payload: Dict[str, Any]
    msg_id: str
    attempt: int = 1


class PipelineExecutor:
    """Runs one pipeline version to a terminal state.

    `step_runner(step_id, version_id, payload, context)` executes one step and
    returns its output. Injected rather than built in, so the traversal logic
    below is testable without a model, a database or a network.
    """

    def __init__(self, step_runner: Callable, transport: Optional[RedisTransport] = None,
                 meter=None, store: Optional["RunStore"] = None,
                 org_id: str = "org_default", project_id: str = "proj_default",
                 pipeline_resolver: Optional[Callable] = None) -> None:
        self._run_step = step_runner
        self._transport = transport or RedisTransport()
        self._meter = meter
        self._store = store
        self._org_id = org_id
        self._project_id = project_id
        # Resolves a pipeline_version_id to a spec, for recursion (§6.3). Absent,
        # a step that invokes a pipeline fails rather than silently doing nothing.
        self._resolve_pipeline = pipeline_resolver
        self.runs: Dict[str, PipelineRun] = {}

    def _meter_step(self, run: PipelineRun, step_id: str, spec,
                    payload: Dict[str, Any], output: Dict[str, Any]) -> None:
        """Account one step execution. Never raises into the run (Rule 12.2).

        Token counts come from the step's own output when it reports them: only
        the caller of the model knows what the model charged, and inferring it
        here would be a guess written into a ledger.
        """
        if self._meter is None:
            return
        try:
            from metering import UsageEvent
            usage = (output or {}).get("usage") or {}
            self._meter.record(UsageEvent(
                org_id=self._org_id, project_id=self._project_id, kind="llm_call",
                bytes=len(str(payload).encode("utf-8")) + len(str(output).encode("utf-8")),
                tokens_input=int(usage.get("input_tokens", 0)),
                tokens_output=int(usage.get("output_tokens", 0)),
                pipeline_id=spec.pipeline_id, run_id=run.run_id,
                agent_version=spec.steps[step_id].version_id,
                model=(output or {}).get("model")))
        except Exception:
            logger.exception("metering failed for step %s; run continues", step_id)

    def create_run(self, spec, parent: Optional[PipelineRun] = None,
                   trigger: Optional[Dict[str, Any]] = None,
                   inputs: Optional[Dict[str, Any]] = None) -> PipelineRun:
        """Rule 6.5: depth is enforced here, before the child does any work."""
        depth = (parent.depth + 1) if parent else 0
        limit = spec.execution.max_recursion_depth
        if depth > limit:
            raise RecursionDepthExceeded(
                f"Rule 6.5: recursion depth {depth} exceeds max_recursion_depth "
                f"{limit} for {spec.pipeline_version_id()}")
        run = PipelineRun(
            pipeline_version_id=spec.pipeline_version_id(),
            parent_run_id=parent.run_id if parent else None, depth=depth,
            trigger=trigger or ({"kind": "agent", "by": parent.run_id} if parent
                                else {"kind": "api", "by": None}),
            input=dict(inputs or {}))
        self.runs[run.run_id] = run
        return run

    @staticmethod
    def _outgoing(spec, step_id: str) -> List[Any]:
        return [d for d in spec.dependencies if d.from_step == step_id]

    async def execute(self, spec, inputs: Dict[str, Any],
                      parent: Optional[PipelineRun] = None,
                      parent_context: Optional[SharedContext] = None,
                      trigger: Optional[Dict[str, Any]] = None) -> PipelineRun:
        run = self.create_run(spec, parent, trigger=trigger, inputs=inputs)

        # Rule 6.6: a recursive child starts a *fresh* context scope unless the
        # pipeline opts in. Sharing a mutable bag between a parent and its own
        # recursive children is how a recursion corrupts its own inputs — so the
        # opt-in is explicit, and without it the parent's context is not reachable
        # from the child at all.
        if parent is not None and parent_context is not None \
                and spec.context_policy.get("inherit"):
            context = parent_context
        else:
            context = SharedContext(spec.context_policy)

        run.status = RUNNING
        run.started_at = _now()
        max_iter = spec.execution.max_iterations
        # Concurrency is a declared property of the pipeline (§3.4); running one
        # step at a time regardless would make it decoration.
        width = max(1, int(getattr(spec.execution, "concurrency", 1) or 1))
        max_retries = int(getattr(spec.execution, "max_retries", 0) or 0)

        pending: List[_Pending] = [
            _Pending(None, s, inputs, uuid.uuid4().hex) for s in spec.entry_steps]
        last_output: Dict[str, Any] = {}

        try:
            while pending:
                # Enforced before dispatch, not after: checking afterwards means
                # the iteration has already been paid for.
                if max_iter is not None and run.iteration_count >= max_iter:
                    # Persisted like any other terminal state: a run that hit
                    # its bound is the one most worth having a record of.
                    self._hit_limit(run, spec, context)
                    await self._persist(run, context)
                    return run

                remaining = None
                if max_iter is not None:
                    remaining = max_iter - run.iteration_count
                batch_size = min(width, len(pending),
                                 remaining if remaining is not None else width)
                batch = [pending.pop(0) for _ in range(max(1, batch_size))]

                results = await asyncio.gather(
                    *(self._dispatch(run, spec, item, context, max_retries)
                      for item in batch),
                    return_exceptions=True)

                halted = False
                for item, result in zip(batch, results):
                    if isinstance(result, BaseException):
                        raise result
                    if result is None:        # a duplicate delivery; nothing ran
                        continue
                    # §6.3 — a step whose agent version declares an invocation
                    # runs that pipeline as a child before its own edges fire,
                    # so downstream steps see the nested result rather than the
                    # step's output alone.
                    result = await self._maybe_recurse(
                        run, spec, item.step_id, result, context)

                    last_output = result
                    run.compute_units += self._step_compute_units(result)
                    self._meter_step(run, item.step_id, spec, item.payload, result)

                    budget = getattr(spec.execution, "max_compute_units", None)
                    if budget and run.compute_units > budget:
                        # §11.4: enforced against the running total before the
                        # next dispatch, like every other bound here.
                        run.status = HALTED
                        run.halt_reason = (
                            f"compute budget exhausted: {run.compute_units} > {budget}")
                        halted = True
                        break

                    for dep in self._outgoing(spec, item.step_id):
                        if not self._edge_fires(dep, result):
                            continue
                        pending.append(_Pending(
                            item.step_id, dep.to_step, self._map_payload(dep, result),
                            uuid.uuid4().hex))

                if halted:
                    run.ended_at = _now()
                    run.output = context.snapshot()
                    await self._persist(run, context)
                    return run

            run.status = SUCCEEDED
            run.output = last_output
        except PipelineError as e:
            run.status = FAILED
            run.error = {"type": type(e).__name__, "message": str(e)}
            logger.exception("pipeline run %s failed", run.run_id)
        except Exception as e:                      # noqa: BLE001 - recorded, not hidden
            run.status = FAILED
            run.error = {"type": type(e).__name__, "message": str(e)}
            logger.exception("pipeline run %s failed unexpectedly", run.run_id)

        run.ended_at = _now()
        run.output = run.output or context.snapshot()
        await self._persist(run, context)
        return run

    async def _dispatch(self, run: PipelineRun, spec, item: _Pending,
                        context: SharedContext, max_retries: int) -> Optional[Dict[str, Any]]:
        """Run one step, retrying on failure with the same msg_id.

        Returns None when the message was already processed — a redelivery is
        not a second execution (Rule 8.2).

        Retries and iterations are counted separately (§11.2). A step reached
        again along an edge is an iteration; a step re-executed for the same
        msg_id is a retry. Conflating them made an iteration budget
        uninterpretable, because transport retries could exhaust a cycle
        allowance.
        """
        if run.seen(item.msg_id):
            run.retry_count += 1
            logger.info("run %s: message %s already processed; not re-executing "
                        "step %s", run.run_id, item.msg_id, item.step_id)
            return None

        run.iteration_count += 1
        attempt = item.attempt
        started_at = _now()
        while True:
            await self._transport.publish(
                self._transport.step_channel(run.run_id, item.step_id),
                self._transport.envelope(run, item.from_step, item.step_id,
                                         item.payload, attempt=attempt,
                                         msg_id=item.msg_id))
            try:
                output = await self._run_with_limits(spec, item, context)
                run.executed_steps.append(self._step_record(
                    spec, item, started_at, "succeeded", output or {}))
                return output or {}
            except PipelineError:
                run.executed_steps.append(self._step_record(
                    spec, item, started_at, "failed", {}))
                raise                      # a rule violation is not retryable
            except Exception as e:
                if attempt > max_retries:
                    run.executed_steps.append(self._step_record(
                        spec, item, started_at, "failed", {}))
                    raise
                attempt += 1
                run.retry_count += 1
                logger.warning("run %s: step %s attempt %d failed (%s); retrying",
                               run.run_id, item.step_id, attempt - 1, e)

    @staticmethod
    def _step_record(spec, item: _Pending, started_at: str, status: str,
                     output: Dict[str, Any]) -> Dict[str, Any]:
        """One executed step, for the `run_step` edges (§5).

        `agent_id` comes from the step runner's own output when it reports one,
        and is otherwise parsed from the pinned version id — the runner knows
        what it resolved, and re-deriving it here would be a second answer to a
        question already answered.
        """
        version_id = spec.steps[item.step_id].version_id
        agent_id = output.get("agent_id")
        agent_version = output.get("agent_version")
        if not agent_id and version_id.startswith("agv_"):
            body = version_id[len("agv_"):]
            agent_id, _, agent_version = body.rpartition("_")
        return {"step_id": item.step_id, "version_id": version_id,
                "agent_id": agent_id, "agent_version": agent_version,
                "started_at": started_at, "ended_at": _now(), "status": status,
                "attempt": item.attempt, "msg_id": item.msg_id}

    async def _run_with_limits(self, spec, item: _Pending,
                               context: SharedContext) -> Dict[str, Any]:
        """Execute one step under its version's declared wall-clock limit.

        `resource_limits.max_wall_secs` (§3.2.1) was hashed into every agent
        version and enforced nowhere, which made it a number that looked like a
        control. A step with no declared limit is unbounded, as before.
        """
        binding = spec.steps[item.step_id]
        limits = getattr(binding, "resource_limits", None) or {}
        timeout = limits.get("max_wall_secs")
        coro = self._run_step(item.step_id, binding.version_id, item.payload, context)
        if not timeout:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout=float(timeout))
        except asyncio.TimeoutError as e:
            raise PipelineError(
                f"step {item.step_id!r} exceeded its declared max_wall_secs of "
                f"{timeout}") from e

    async def _maybe_recurse(self, run: PipelineRun, spec, step_id: str,
                             output: Dict[str, Any],
                             context: SharedContext) -> Dict[str, Any]:
        """Follow a step's `invokes_pipeline` declaration, if it has one (§6.3).

        Depth is enforced in `create_run`, before the child does any work
        (Rule 6.5). The child's compute units are added to this run's total, so
        `max_compute_units` covers the whole run *including* recursive children
        (§11.4) rather than only the frame that happens to be executing.
        """
        binding = spec.steps[step_id]
        target = getattr(binding, "invokes_pipeline", None)
        if not target:
            return output

        pipeline_id = target.get("pipeline_id") if isinstance(target, dict) else target
        if self._resolve_pipeline is None:
            # Not silently skipped: a pipeline that declares an invocation and
            # does not perform it produces a plausible partial answer, which is
            # exactly the failure Rule 9.1 exists to prevent at registration.
            raise PipelineError(
                f"step {step_id!r} invokes pipeline {pipeline_id!r}, but this "
                f"executor was built without a pipeline_resolver and cannot "
                f"load it")

        child_spec = await self._resolve_pipeline(
            pipeline_id, target.get("version") if isinstance(target, dict) else None)
        child = await self.invoke_nested(child_spec, output, parent=run,
                                         parent_context=context)
        run.compute_units += child.compute_units
        run.retry_count += child.retry_count

        if child.status in UNSUCCESSFUL:
            # Rule 6.3 — a failed or halted child is not a successful step.
            #
            # If the pipeline declares an `on_failure` edge from this step, the
            # author has said how to handle it: control routes there, and the
            # error travels in the output so the handler can see it. If there is
            # no such edge, nobody is handling it, and letting the parent finish
            # `succeeded` would report a complete result built on a nested run
            # that did not complete.
            handled = any(d.from_step == step_id and d.relationship == "on_failure"
                          for d in spec.dependencies)
            failure = child.error or {"halt_reason": child.halt_reason}
            if not handled:
                raise PipelineError(
                    f"step {step_id!r} invoked pipeline {pipeline_id!r}, which "
                    f"ended {child.status} ({failure}). No on_failure edge leaves "
                    f"this step, so the failure is not handled and the run cannot "
                    f"report success.")
            return {**output, "error": failure,
                    "nested_run_id": child.run_id, "nested_status": child.status}
        return {**output, **(child.output or {}), "nested_run_id": child.run_id,
                "nested_status": child.status}

    async def invoke_nested(self, spec, inputs: Dict[str, Any],
                            parent: PipelineRun,
                            parent_context: Optional[SharedContext] = None) -> PipelineRun:
        """Run a pipeline from inside another one (§6.3).

        This is the entry point an `invokes_pipeline` edge leads to. Depth is
        checked in `create_run`, before the child does any work (Rule 6.5).
        """
        return await self.execute(spec, inputs, parent=parent,
                                  parent_context=parent_context,
                                  trigger={"kind": "agent", "by": parent.run_id})

    async def _persist(self, run: PipelineRun, context: SharedContext) -> None:
        """Record the run and its context history. Never fails the run.

        A run that completed and could not be recorded is still a run that
        completed: raising here would turn a bookkeeping failure into a
        user-visible one, and the work is already done either way.
        """
        if self._store is None:
            return
        try:
            await self._store.save(run, context, self._org_id, self._project_id)
        except Exception:
            logger.exception("failed to persist run %s; execution result stands",
                             run.run_id)

    def _hit_limit(self, run: PipelineRun, spec, context: SharedContext) -> PipelineRun:
        """Rule 6.1 / 6.3: exhaustion is never success."""
        run.ended_at = _now()
        if spec.execution.on_limit == "halt_and_return":
            run.status = HALTED
            run.halt_reason = (
                f"reached max_iterations={spec.execution.max_iterations}; "
                f"returning partial context")
            run.output = context.snapshot()
        else:
            run.status = FAILED
            run.error = {"type": "IterationLimit",
                         "message": f"reached max_iterations="
                                    f"{spec.execution.max_iterations}"}
        logger.warning("run %s %s at the iteration limit", run.run_id, run.status)
        return run

    @staticmethod
    def _step_compute_units(output: Dict[str, Any]) -> int:
        """Consumption Units for one step (Rule 12.1; user directive
        2026-09-05): bytes processed, a token counting as BYTES_PER_TOKEN.
        When the step reports token usage that IS the byte measure of what
        the model processed; a step with no usage falls back to the byte
        size of what it produced, so no processing reads as free."""
        from metering import BYTES_PER_TOKEN
        usage = (output or {}).get("usage") or {}
        total = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        if total:
            return total * BYTES_PER_TOKEN
        try:
            import json as _json
            return len(_json.dumps(output or {}).encode("utf-8"))
        except Exception:
            return 0

    @staticmethod
    def _edge_fires(dep, output: Dict[str, Any]) -> bool:
        """Whether control follows this edge, given the upstream output."""
        rel = dep.relationship
        if rel == "on_success":
            return not output.get("error")
        if rel == "on_failure":
            return bool(output.get("error"))
        if rel == "on_condition":
            # The condition names a truthy field in the upstream output. An
            # absent field is false, which is what lets a cycle terminate.
            return bool(output.get(dep.condition)) if dep.condition else False
        return True

    @staticmethod
    def _map_payload(dep, output: Dict[str, Any]) -> Dict[str, Any]:
        if not dep.payload_map:
            return dict(output)
        return {dst: output.get(src) for src, dst in dep.payload_map.items()}


class RunStore:
    """Persists runs and their context history to post-graph (spec §3.5).

    Runs are vertices; each context revision is an append-only data record
    against the run, so the full sequence of writes in a cyclic execution is
    recoverable afterwards rather than collapsed to a final value (§3.6).
    """

    RUNS_TABLE = "pipeline_runs"

    def __init__(self, client_factory, linker=None) -> None:
        """`linker(client, realm, space, run_pk, pipeline_id, executed_steps)`.

        Injected rather than imported, because the edge writer lives in the
        agent registry's `registry_store` and this module is shared with the
        backend. Importing it here would make every consumer of the runtime
        depend on the registry's schema constants.
        """
        self._client_factory = client_factory
        self._linker = linker

    @staticmethod
    def _pipeline_id_of(run: PipelineRun) -> Optional[str]:
        """`plv_{pipeline_id}_{version}` -> pipeline_id.

        Split from the right on the last underscore: pipeline ids contain
        underscores and version strings do not.
        """
        vid = run.pipeline_version_id or ""
        if not vid.startswith("plv_"):
            return None
        pipeline_id, _, _version = vid[len("plv_"):].rpartition("_")
        return pipeline_id or None

    async def save(self, run: PipelineRun, context: SharedContext,
                   org_id: str, project_id: str) -> None:
        async with self._client_factory(org_id) as client:
            await client.create_vertex_table(self.RUNS_TABLE, realm=org_id)
            vertex = await client.add_vertex(
                self.RUNS_TABLE, realm=org_id, space=project_id,
                payload=run.to_payload())
            pk = int(vertex.id)

            # §5 — `run_of` to the definition, `run_step` to what executed.
            # Best-effort: the run itself is already recorded above, and losing
            # the traversal shortcut must not lose the run.
            if self._linker is not None:
                pipeline_id = self._pipeline_id_of(run)
                if pipeline_id:
                    try:
                        await self._linker(client, org_id, project_id, pk,
                                           pipeline_id, run.executed_steps)
                    except Exception:
                        logger.exception(
                            "could not link run %s to its definition; the run "
                            "record stands", run.run_id)
            # Every revision, not just the final snapshot (Rule 8.5 / Rule 3.6).
            for key, entries in context._entries.items():
                for entry in entries:
                    await client.add_vertex_data(
                        table_name=self.RUNS_TABLE, realm=org_id, vertex_id=pk,
                        payload={"kind": "context", "key": key, "value": entry.value,
                                 "written_by": entry.written_by,
                                 "revision": entry.revision,
                                 "written_at": entry.written_at})
            for key, prev, now in context.conflicts:
                await client.add_vertex_data(
                    table_name=self.RUNS_TABLE, realm=org_id, vertex_id=pk,
                    payload={"kind": "conflict", "key": key,
                             "previous_writer": prev, "writer": now})
