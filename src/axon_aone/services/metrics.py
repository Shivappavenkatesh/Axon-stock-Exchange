"""Prometheus metrics for order execution (ported from Axon Aone).

`prometheus-client` is optional: when it is not installed, every metric is a
no-op and `render_latest()` returns None, so trading keeps working unchanged.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the package
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


class _NoOpMetric:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        pass

    def observe(self, *args, **kwargs):
        pass


if PROMETHEUS_AVAILABLE:
    EXECUTE_COUNTER = Counter("axon_execute_total", "Total execute_trade calls", ["side", "status"])
    EXECUTE_LATENCY = Histogram("axon_execute_latency_seconds", "Latency for execute_trade")
    POSITION_COUNTER = Counter("axon_positions_total", "Position fetch calls", ["status"])
else:
    EXECUTE_COUNTER = EXECUTE_LATENCY = POSITION_COUNTER = _NoOpMetric()


@contextmanager
def timed_execution():
    """Observe execute latency for the wrapped block."""
    start = time.time()
    try:
        yield
    finally:
        EXECUTE_LATENCY.observe(time.time() - start)


def record_execution(side: str, status: str) -> None:
    EXECUTE_COUNTER.labels(side=side, status=status).inc()


def record_positions(status: str) -> None:
    POSITION_COUNTER.labels(status=status).inc()


def render_latest():
    """Return (payload, content_type) for a /metrics endpoint, or None if unavailable."""
    if not PROMETHEUS_AVAILABLE:
        return None
    return generate_latest(), CONTENT_TYPE_LATEST
