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

# The Consumption Unit (user directive 2026-09-05): ONE unit for every data
# processing action -- ingestion, RAG, model inference -- denominated in
# bytes processed. A token to a model is considered 4 bytes, so an event
# measured in tokens converts at that rate and an event measured in bytes
# counts as itself. Stored on each event rather than applied at read time:
# the rate will change, and recomputing history under a new one would
# silently restate past invoices.
BYTES_PER_TOKEN = 4

KINDS = (
    "document_ingest", "index_compute", "document_reindex", "rag_lookup",
    "room_use", "search_query", "search_results", "llm_call",
    "model_inference",
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
    def consumption_units(self) -> int:
        """Bytes processed, with tokens counted at BYTES_PER_TOKEN each."""
        return self.bytes + self.tokens_total * BYTES_PER_TOKEN

    def to_payload(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tokens_total"] = self.tokens_total
        d["consumption_units"] = self.consumption_units
        return d


def _counter(name: str, documentation: str, labelnames: List[str]):
    """A counter registered once per process, however often this is called.

    `Counter(...)` registers into a global registry and raises on a second
    registration of the same name. Every `Meter` builds a sink, and this module
    is imported twice in the same process under two names — `metering` inside a
    service image, `backend.metering` in the backend — so the second one raised
    `DuplicateTimeseries` and took the service down with it. Nothing showed it
    until prometheus_client arrived as a transitive dependency and the
    ImportError guard stopped catching everything.

    So: build it, and if the name is already taken, use the collector that
    already holds it.
    """
    from prometheus_client import REGISTRY, Counter
    try:
        return Counter(name, documentation, labelnames)
    except Exception:
        existing = getattr(REGISTRY, "_names_to_collectors", {})
        # prometheus strips the `_total` suffix for the collector's own name.
        found = existing.get(name) or existing.get(name.removesuffix("_total"))
        if found is None:
            raise
        return found


class PrometheusSink:
    """Counters for the existing scrape. No new infrastructure (spec §12.2).

    Degrades to a no-op when prometheus_client is absent, because observability
    is not worth failing a request over — unlike the ledger, which is.
    """

    def __init__(self) -> None:
        self.enabled = False
        try:
            import prometheus_client  # noqa: F401
        except ImportError:
            logger.info("prometheus_client not installed; metrics endpoint disabled")
            return
        labels = ["org_id", "kind"]
        try:
            self.bytes = _counter("agentslondon_bytes_processed_total",
                                  "Bytes processed, by organisation and operation", labels)
            self.tokens_in = _counter("agentslondon_tokens_input_total",
                                      "Input tokens, by organisation and operation", labels)
            self.tokens_out = _counter("agentslondon_tokens_output_total",
                                       "Output tokens, by organisation and operation", labels)
            self.compute = _counter("agentslondon_consumption_units_total",
                                    "Compute units (total tokens x 4)", labels)
            self.dropped = _counter("agentslondon_usage_events_dropped_total",
                                    "Usage events lost to a full queue", ["org_id"])
        except Exception:
            # Observability is not worth failing a service over — the same
            # judgement as the ImportError above. The ledger is what must not
            # be lost, and it is written regardless.
            logger.exception("prometheus counters unavailable; metrics disabled")
            return
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
            self.compute.labels(**lab).inc(e.consumption_units)

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
        # Realms whose ledger table is known to exist. DDL is not free and, more
        # importantly, it is not concurrency-safe: two services flushing to one
        # realm at the same moment both ran CREATE TABLE and PostgreSQL raised
        # `tuple concurrently updated` on the system catalogue, losing both
        # batches. Rule 12.3 says overflow is counted and logged, not that a
        # write may be silently lost to a race we caused ourselves.
        self._ready: set = set()
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
                # Not a swallowed failure: awaiting a task we just cancelled
                # raises this by definition, and it is the confirmation the
                # cancel took effect. Left bare so a sweep for silent handlers
                # finds this comment rather than an unexplained `pass`.
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
                    await self._ensure_ledger(client, org_id)
                    for e in events:
                        await client.add_vertex(
                            USAGE_TABLE, realm=org_id, space=e.project_id,
                            payload=e.to_payload())
                self.written += len(events)
            except Exception:
                self.dropped += len(events)
                # A failed create leaves the realm out of `_ready`, so the next
                # flush tries again rather than assuming a table that is not there.
                self._ready.discard(org_id)
                logger.exception(
                    "failed to write %d usage events for org '%s'; accounting for "
                    "this period is now incomplete", len(events), org_id)

    async def _ensure_ledger(self, client, org_id: str) -> None:
        """Create the ledger table for one realm, once, tolerating a race.

        Two processes creating the same table concurrently is not an error in
        this system — it is the normal startup of a second replica — but
        PostgreSQL reports it as one, on the system catalogue, in a way that
        rolls back the batch riding along behind it. So the loser of the race
        checks whether the table now exists and carries on if it does.
        """
        if org_id in self._ready:
            return
        try:
            await client.create_vertex_table(USAGE_TABLE, realm=org_id)
        except Exception:
            if not await client._table_exists(USAGE_TABLE, realm=org_id):
                raise
            logger.debug("lost the race to create %s in realm %r; it exists",
                         USAGE_TABLE, org_id)
        self._ready.add(org_id)


# A module-level meter so call sites do not thread one through every signature.
# Configured once at startup by the host application.
METER = Meter()


def configure(client_factory, **kw) -> Meter:
    global METER
    METER = Meter(client_factory=client_factory, **kw)
    return METER
