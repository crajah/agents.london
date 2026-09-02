"""Telemetry — every service exports Prometheus metrics the cluster's
telemetry stack (marty infra/telemetry) scrapes via pod annotations.

prometheus_client is a soft dependency: absent, every hook is a no-op, so
core logic never fails on an unbuilt image.
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, start_http_server
    _ON = True
except Exception:                                  # pragma: no cover
    _ON = False

    class _Noop:
        def labels(self, *a, **k): return self
        def inc(self, *a, **k): pass
        def dec(self, *a, **k): pass
        def set(self, *a, **k): pass
    def Counter(*a, **k): return _Noop()           # noqa: N802
    def Gauge(*a, **k): return _Noop()             # noqa: N802
    def start_http_server(*a, **k): pass           # noqa

EVENTS = Counter("genome_events_drained_total",
                 "World events drained, by kind and outcome class",
                 ["kind"])
DECISIONS = Counter("genome_decisions_total",
                    "Agent decisions taken, by situation and model tier",
                    ["situation", "model"])
TRANSFERS = Counter("genome_transfers_total",
                    "Agent teleport crossings")
PORTAGE = Counter("genome_portage_total",
                  "Construction portage operations", ["op"])
FLOODS = Counter("genome_floods_total", "Flood executions")
CONTRIBUTIONS = Counter("genome_contributions_total",
                        "Cargo poured into construction sites")
QUEUE_DEPTH = Gauge("genome_decision_queue_depth",
                    "Undecided items in the decision queue (per shard scan)")
HTTP = Counter("genome_api_requests_total",
               "API requests, by method and status", ["method", "status"])
SSE_VIEWERS = Gauge("genome_sse_viewers", "Open world-stream connections")


def serve(port: int = 9100) -> None:
    """Expose /metrics for the pod annotation scrape; workers call this."""
    start_http_server(port)
