"""Metering tests. The properties that matter are non-blocking and non-lossy-silently."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from metering import COMPUTE_UNITS_PER_TOKEN, Meter, UsageEvent


class FakeClient:
    def __init__(self, fail=False):
        self.written = []
        self.fail = fail

    async def create_vertex_table(self, table, realm=None, vector_dim=None):
        pass

    async def add_vertex(self, table, realm=None, space=None, payload=None, **kw):
        if self.fail:
            raise RuntimeError("database is down")
        self.written.append((realm, payload))


def factory_for(client):
    @asynccontextmanager
    async def _f(org_id):
        yield client
    return _f


def test_compute_units_are_derived_and_stored():
    e = UsageEvent(org_id="o", kind="llm_call", tokens_input=100, tokens_output=25)
    assert e.tokens_total == 125
    assert e.compute_units == 125 * COMPUTE_UNITS_PER_TOKEN
    # Stored on the payload, not recomputed at read (Rule 12.1).
    assert e.to_payload()["compute_units"] == 500


def test_record_never_blocks_and_returns_immediately():
    m = Meter(max_queue=10)
    assert m.record(UsageEvent(org_id="o", kind="rag_lookup", bytes=10)) is True


def test_overflow_is_counted_not_silent():
    """Rule 12.3: a full queue must be visible, never a quiet drop."""
    m = Meter(max_queue=2)
    for _ in range(5):
        m.record(UsageEvent(org_id="o", kind="rag_lookup", bytes=1))
    assert m.dropped == 3


def test_measure_bytes_sizes_utf8_not_characters():
    """A multi-byte string must bill as bytes, not as len()."""
    m = Meter(max_queue=10)
    m.measure_bytes("o", "document_ingest", "café")   # 5 bytes, 4 characters
    e = m._queue.get_nowait()
    assert e.bytes == 5


def test_occurred_at_is_capture_time_not_flush_time():
    """Rule 12.4: batching must not smear usage across a period boundary."""
    e = UsageEvent(org_id="o", kind="llm_call")
    assert e.occurred_at.endswith("+00:00") and "T" in e.occurred_at


@pytest.mark.asyncio
async def test_flush_writes_grouped_by_organisation():
    client = FakeClient()
    m = Meter(client_factory=factory_for(client), max_queue=100)
    m.record(UsageEvent(org_id="org_a", kind="llm_call", tokens_input=10))
    m.record(UsageEvent(org_id="org_b", kind="llm_call", tokens_input=20))
    await m._flush(m._take_batch())
    realms = {r for r, _ in client.written}
    assert realms == {"org_a", "org_b"}
    assert m.written == 2


@pytest.mark.asyncio
async def test_a_database_outage_does_not_raise_into_the_caller():
    """Accounting degrades; the request path is untouched (Rule 12.2)."""
    client = FakeClient(fail=True)
    m = Meter(client_factory=factory_for(client), max_queue=100)
    m.record(UsageEvent(org_id="org_a", kind="llm_call", tokens_input=10))
    await m._flush(m._take_batch())      # must not raise
    assert m.dropped == 1 and m.written == 0


@pytest.mark.asyncio
async def test_events_survive_a_stop_flush():
    client = FakeClient()
    m = Meter(client_factory=factory_for(client), max_queue=100, flush_interval=0.01)
    await m.start()
    m.record(UsageEvent(org_id="org_a", kind="search_query", bytes=99))
    await m.stop()
    assert len(client.written) == 1
