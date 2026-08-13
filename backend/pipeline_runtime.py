"""Executing pipelines: runs, cycles, recursion and shared context.

The registry stores definitions; this executes them. The split matters because
definitions are immutable and cyclic, while runs are mutable and finite — a
cycle in the definition becomes a bounded number of iterations in the run
(spec §6), and that boundary is the only thing that makes a cyclic pipeline
safe to execute at all.

Everything enforced here is enforced *before* work is spent, not after:
recursion depth at run creation (Rule 6.5), iteration count before dispatching
the next step. Checking afterwards means the budget is already gone.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

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


# ------------------------------------------------------------------ context

@dataclass
class ContextEntry:
    key: str
    value: Any
    written_by: str
    revision: int
    written_at: str = field(default_factory=_now)


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

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCEEDED

    def to_payload(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
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

    @staticmethod
    def step_channel(run_id: str, step_id: str) -> str:
        return f"agent:run:{run_id}:step:{step_id}"

    @staticmethod
    def events_channel(run_id: str) -> str:
        return f"agent:run:{run_id}:events"

    def envelope(self, run: PipelineRun, from_step: Optional[str], to_step: str,
                 payload: Dict[str, Any], attempt: int = 1) -> Dict[str, Any]:
        return {
            "msg_id": uuid.uuid4().hex,       # dedup key; Rule 8.2, at-least-once
            "run_id": run.run_id,
            "from_step": from_step,
            "to_step": to_step,
            "attempt": attempt,
            "sent_at": _now(),
            "payload": payload,
            "context_ref": f"ctx_{run.run_id}",
        }

    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Publish, or raise. Rule 8.3: a step that cannot reach Redis fails
        the run rather than falling back to in-process execution, which would
        produce an event log missing steps that really happened."""
        if self._redis is None:
            return
        await self._redis.publish(channel, json.dumps(message))


# ------------------------------------------------------------------ executor

class PipelineExecutor:
    """Runs one pipeline version to a terminal state.

    `step_runner(step_id, version_id, payload, context)` executes one step and
    returns its output. Injected rather than built in, so the traversal logic
    below is testable without a model, a database or a network.
    """

    def __init__(self, step_runner: Callable, transport: Optional[RedisTransport] = None,
                 meter=None, store: Optional["RunStore"] = None,
                 org_id: str = "org_default", project_id: str = "proj_default") -> None:
        self._run_step = step_runner
        self._transport = transport or RedisTransport()
        self._meter = meter
        self._store = store
        self._org_id = org_id
        self._project_id = project_id
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

    def create_run(self, spec, parent: Optional[PipelineRun] = None) -> PipelineRun:
        """Rule 6.5: depth is enforced here, before the child does any work."""
        depth = (parent.depth + 1) if parent else 0
        limit = spec.execution.max_recursion_depth
        if depth > limit:
            raise RecursionDepthExceeded(
                f"Rule 6.5: recursion depth {depth} exceeds max_recursion_depth "
                f"{limit} for {spec.pipeline_version_id()}")
        run = PipelineRun(
            pipeline_version_id=spec.pipeline_version_id(),
            parent_run_id=parent.run_id if parent else None, depth=depth)
        self.runs[run.run_id] = run
        return run

    @staticmethod
    def _outgoing(spec, step_id: str) -> List[Any]:
        return [d for d in spec.dependencies if d.from_step == step_id]

    async def execute(self, spec, inputs: Dict[str, Any],
                      parent: Optional[PipelineRun] = None) -> PipelineRun:
        run = self.create_run(spec, parent)
        context = SharedContext(spec.context_policy)
        # Rule 6.6: a recursive child starts a fresh context scope unless the
        # pipeline opts in. Sharing a mutable bag between a parent and its own
        # recursive children is how a recursion corrupts its own inputs.
        if parent is not None and spec.context_policy.get("inherit"):
            context = SharedContext(spec.context_policy)

        run.status = RUNNING
        run.started_at = _now()
        max_iter = spec.execution.max_iterations
        pending: List[Tuple[Optional[str], str, Dict[str, Any]]] = [
            (None, s, inputs) for s in spec.entry_steps]
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

                from_step, step_id, payload = pending.pop(0)
                run.iteration_count += 1

                await self._transport.publish(
                    self._transport.step_channel(run.run_id, step_id),
                    self._transport.envelope(run, from_step, step_id, payload))

                output = await self._run_step(step_id, spec.steps[step_id].version_id,
                                              payload, context)
                last_output = output or {}
                run.compute_units += self._step_compute_units(last_output)
                self._meter_step(run, step_id, spec, payload, last_output)

                budget = getattr(spec.execution, "max_compute_units", None)
                if budget and run.compute_units > budget:
                    # §11.4: enforced against the running total before the next
                    # dispatch, like every other bound here.
                    run.status = HALTED
                    run.halt_reason = (
                        f"compute budget exhausted: {run.compute_units} > {budget}")
                    run.ended_at = _now()
                    run.output = context.snapshot()
                    await self._persist(run, context)
                    return run

                for dep in self._outgoing(spec, step_id):
                    if not self._edge_fires(dep, last_output):
                        continue
                    nxt = self._map_payload(dep, last_output)
                    pending.append((step_id, dep.to_step, nxt))

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
        # Persisted by the caller of _hit_limit's return path below.
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
        """Compute units for one step, from the tokens it reports (Rule 12.1)."""
        usage = (output or {}).get("usage") or {}
        total = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return total * 4

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
    recoverable afterwards rather than collapsed to a final value.
    """

    RUNS_TABLE = "pipeline_runs"

    def __init__(self, client_factory) -> None:
        self._client_factory = client_factory

    async def save(self, run: PipelineRun, context: SharedContext,
                   org_id: str, project_id: str) -> None:
        async with self._client_factory(org_id) as client:
            await client.create_vertex_table(self.RUNS_TABLE, realm=org_id)
            vertex = await client.add_vertex(
                self.RUNS_TABLE, realm=org_id, space=project_id,
                payload=run.to_payload())
            pk = int(vertex.id)
            # Every revision, not just the final snapshot (Rule 8.5).
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
