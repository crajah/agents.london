"""Per-organisation usage accounting: bytes, tokens and compute units.

Two sinks, deliberately, because one store cannot serve both purposes:

  ledger        post-graph `usage_events`, exact and durable. This is what an
                invoice is derived from.
  observability Prometheus counters scraped from /metrics by the existing
                stack. Sampled, ephemeral, 7-day retention on emptyDir — fine
                for a dashboard, disqualifying for money (spec §12.2).

Metering must never slow down or break the thing it measures (Rule 12.2), so
`record()` only puts an event on a bounded in-memory queue and returns. A
background task drains it in batches. Everything that can go wrong here —
a full queue, a database outage, a malformed event — degrades accounting and
leaves the request path untouched.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

USAGE_TABLE = "usage_events"

# Compute units per token (Rule 12.1). Stored on each event rather than applied
# at read time: this multiplier will change, and recomputing history under a new
# one would silently restate past invoices.
COMPUTE_UNITS_PER_TOKEN = 4

KINDS = (
    "document_ingest", "rag_lookup", "room_use",
    "search_query", "search_results", "llm_call",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UsageEvent:
    org_id: str
    kind: str
    project_id: str = "proj_default"
    bytes: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    agent_id: Optional[str] = None
    agent_version: Optional[str] = None
    pipeline_id: Optional[str] = None
    run_id: Optional[str] = None
    model: Optional[str] = None
    # Event time, captured when the operation happened rather than when the
    # batch is flushed (Rule 12.4). Month-end is a period boundary and batching
    # would otherwise smear usage across it.
    occurred_at: str = field(default_factory=_now)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def compute_units(self) -> int:
        return self.tokens_total * COMPUTE_UNITS_PER_TOKEN

    def to_payload(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tokens_total"] = self.tokens_total
        d["compute_units"] = self.compute_units
        return d


class PrometheusSink:
    """Counters for the existing scrape. No new infrastructure (spec §12.2).

    Degrades to a no-op when prometheus_client is absent, because observability
    is not worth failing a request over — unlike the ledger, which is.
    """

    def __init__(self) -> None:
        self.enabled = False
        try:
            from prometheus_client import Counter
        except ImportError:
            logger.info("prometheus_client not installed; metrics endpoint disabled")
            return
        labels = ["org_id", "kind"]
        self.bytes = Counter("agentslondon_bytes_processed_total",
                             "Bytes processed, by organisation and operation", labels)
        self.tokens_in = Counter("agentslondon_tokens_input_total",
                                 "Input tokens, by organisation and operation", labels)
        self.tokens_out = Counter("agentslondon_tokens_output_total",
                                  "Output tokens, by organisation and operation", labels)
        self.compute = Counter("agentslondon_compute_units_total",
                               "Compute units (total tokens x 4)", labels)
        self.dropped = Counter("agentslondon_usage_events_dropped_total",
                               "Usage events lost to a full queue", ["org_id"])
        self.enabled = True

    def observe(self, e: UsageEvent) -> None:
        if not self.enabled:
            return
        # org_id is a label here and a realm in the ledger. Prometheus label
        # cardinality grows with the number of organisations, which is why the
        # ledger — not this — is the system of record.
        lab = {"org_id": e.org_id, "kind": e.kind}
        if e.bytes:
            self.bytes.labels(**lab).inc(e.bytes)
        if e.tokens_input:
            self.tokens_in.labels(**lab).inc(e.tokens_input)
        if e.tokens_output:
            self.tokens_out.labels(**lab).inc(e.tokens_output)
        if e.tokens_total:
            self.compute.labels(**lab).inc(e.compute_units)

    def note_dropped(self, org_id: str) -> None:
        if self.enabled:
            self.dropped.labels(org_id=org_id).inc()


class Meter:
    """Bounded queue in front of a batched writer.

    The queue is bounded on purpose (Rule 12.3): unbounded, a slow database
    becomes an out-of-memory kill instead of a bounded loss. Overflow is counted
    and logged rather than dropped silently, because a silent drop is an
    undetectable revenue leak.
    """

    def __init__(self, client_factory=None, max_queue: int = 10_000,
                 batch_size: int = 200, flush_interval: float = 5.0) -> None:
        self._queue: asyncio.Queue[UsageEvent] = asyncio.Queue(maxsize=max_queue)
        self._client_factory = client_factory
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._task: Optional[asyncio.Task] = None
        self._prom = PrometheusSink()
        self.dropped = 0
        self.written = 0

    # ------------------------------------------------------------ recording

    def record(self, event: UsageEvent) -> bool:
        """Queue one event. Never raises, never blocks, never awaits.

        Returns False if the event was dropped, so a caller that cares can
        react. Most callers ignore it — the counter and the log are the signal.
        """
        if event.kind not in KINDS:
            logger.warning("unknown usage kind %r; recording anyway", event.kind)
        self._prom.observe(event)
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            self._prom.note_dropped(event.org_id)
            logger.error(
                "usage event dropped for org '%s' (%s): queue full at %d. "
                "Accounting is now under-counting for this organisation.",
                event.org_id, event.kind, self._queue.maxsize)
            return False

    def measure_bytes(self, org_id: str, kind: str, payload: Any, **kw) -> bool:
        """Convenience: size a payload without the caller computing it."""
        if isinstance(payload, (bytes, bytearray)):
            size = len(payload)
        elif isinstance(payload, str):
            size = len(payload.encode("utf-8"))
        else:
            size = len(str(payload).encode("utf-8"))
        return self.record(UsageEvent(org_id=org_id, kind=kind, bytes=size, **kw))

    # ------------------------------------------------------------- draining

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        """Flush what is queued, then stop. Called on shutdown."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._flush(self._take_batch())

    def _take_batch(self) -> List[UsageEvent]:
        batch: List[UsageEvent] = []
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _drain(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            batch = self._take_batch()
            if batch:
                await self._flush(batch)

    async def _flush(self, batch: List[UsageEvent]) -> None:
        """Write one batch to the ledger. Failure loses the batch, loudly.

        Retrying inside the flush would grow the queue behind it, so a failed
        batch is reported rather than replayed. The alternative — blocking the
        drain on a database outage — converts an accounting problem into a
        memory problem.
        """
        if not batch or self._client_factory is None:
            return
        by_realm: Dict[str, List[UsageEvent]] = {}
        for e in batch:
            by_realm.setdefault(e.org_id, []).append(e)
        for org_id, events in by_realm.items():
            try:
                async with self._client_factory(org_id) as client:
                    await client.create_vertex_table(USAGE_TABLE, realm=org_id)
                    for e in events:
                        await client.add_vertex(
                            USAGE_TABLE, realm=org_id, space=e.project_id,
                            payload=e.to_payload())
                self.written += len(events)
            except Exception:
                self.dropped += len(events)
                logger.exception(
                    "failed to write %d usage events for org '%s'; accounting for "
                    "this period is now incomplete", len(events), org_id)


# A module-level meter so call sites do not thread one through every signature.
# Configured once at startup by the host application.
METER = Meter()


def configure(client_factory, **kw) -> Meter:
    global METER
    METER = Meter(client_factory=client_factory, **kw)
    return METER
