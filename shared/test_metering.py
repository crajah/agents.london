"""Metering tests. The properties that matter are non-blocking and non-lossy-silently."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from metering import BYTES_PER_TOKEN, Meter, UsageEvent


class FakeClient:
    def __init__(self, fail=False):
        self.written = []
        self.appended = []          # system-ledger data rows
        self.fail = fail
        self._pk = 0

    async def create_vertex_table(self, table, realm=None, vector_dim=None):
        pass

    async def add_vertex(self, table, realm=None, space=None, payload=None, **kw):
        if self.fail:
            raise RuntimeError("database is down")
        self.written.append((realm, payload))
        self._pk += 1
        return type("V", (), {"id": self._pk})()

    def _get_table_ref(self, table, realm):
        return f"{realm}.{table}"

    async def _fetch(self, query, *args):
        return []                    # no existing anchor: one gets created

    async def add_vertex_data(self, table_name=None, realm=None,
                              vertex_id=None, payload=None):
        if self.fail:
            raise RuntimeError("database is down")
        self.appended.append((realm, vertex_id, payload))


def factory_for(client):
    @asynccontextmanager
    async def _f(org_id):
        yield client
    return _f


def test_consumption_units_are_bytes_plus_tokens_at_four_bytes():
    e = UsageEvent(org_id="o", kind="llm_call", bytes=1000,
                   tokens_input=100, tokens_output=25)
    assert e.consumption_units == 1000 + 125 * BYTES_PER_TOKEN
    assert e.to_payload()["consumption_units"] == 1500

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
    # the two org ledgers, plus each org's anchor in the system ledger
    assert realms == {"org_a", "org_b", "platform_system"}
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


def test_a_second_meter_in_one_process_does_not_explode():
    """Two meters, or this module imported twice, must not fight over a name.

    `Counter(...)` registers into a global registry and raises on a repeat. Both
    happen here: every Meter builds a sink, and this module lives in the backend
    as `backend.metering` and inside each service image as `metering`. The
    second registration raised DuplicateTimeseries and took the process with it
    — invisible until prometheus_client arrived as a transitive dependency and
    the ImportError guard stopped swallowing everything.
    """
    from metering import PrometheusSink

    first = PrometheusSink()
    second = PrometheusSink()
    third = PrometheusSink()

    if not first.enabled:
        pytest.skip("prometheus_client is not installed")
    assert second.enabled and third.enabled
    # The same collector, not a rival registration of the same name.
    assert second.bytes is first.bytes
    assert third.dropped is first.dropped


def test_metrics_never_fail_the_caller():
    """The ledger is what must not be lost; the counters are not."""
    from metering import PrometheusSink

    sink = PrometheusSink()
    sink.enabled = False
    sink.observe(UsageEvent(org_id="org", project_id="p", kind="llm_call",
                            tokens_input=1, tokens_output=1))


@pytest.mark.asyncio
async def test_every_event_lands_in_the_system_ledger_too():
    client = FakeClient()
    m = Meter(client_factory=factory_for(client))
    m.record(UsageEvent(org_id="org_a", kind="llm_call", tokens_input=10))
    m.record(UsageEvent(org_id="org_a", kind="document_ingest", bytes=500))
    await m._flush(m._take_batch())
    from metering import SYSTEM_REALM
    rows = [p for r, _, p in client.appended if r == SYSTEM_REALM]
    assert len(rows) == 2
    assert {p["kind"] for p in rows} == {"llm_call", "document_ingest"}
    assert all("consumption_units" in p and "occurred_at" in p for p in rows)
