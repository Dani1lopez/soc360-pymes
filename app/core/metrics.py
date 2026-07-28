"""PR3 #260 — Multiprocess-safe metrics registry with canonical ``flow`` label.

Exports the exhaustive seven-metric set from design rev 9:
- Six Counters (outages, retry, partial revocation, partial rate-limit
  mutation, coordination failure, cancellation)
- One Histogram (operation latency)

All metrics carry the canonical ``flow`` label bound to a FlowId constant
from ``app.core.outage`` at observation time.

Multiprocess safety:
    Set ``PROMETHEUS_MULTIPROC_DIR`` *before* importing this module (or
    prometheus_client).  The ``entrypoint.sh`` script prepares the directory
    and Gunicorn ``child_exit`` calls ``mark_process_dead`` to finalise each
    worker's metrics.
"""

from __future__ import annotations

import prometheus_client

# ─────────────────────────────────────────────────────────────────────────────
# 3.2 — Seven-metric registry (exhaustive — design rev 9)
# ─────────────────────────────────────────────────────────────────────────────

METRIC_OUTAGES = prometheus_client.Counter(
    "soc360_redis_outages_total",
    "Total Redis transport-level outages observed.",
    ["flow"],
)

METRIC_RETRY = prometheus_client.Counter(
    "soc360_redis_retry_total",
    "Total idempotent Redis operations retried.",
    ["flow"],
)

METRIC_PARTIAL_REVOCATION = prometheus_client.Counter(
    "soc360_redis_partial_revocation_total",
    "Total partial-revocation batches (some JTIs succeeded, others failed).",
    ["flow"],
)

METRIC_PARTIAL_RATE_LIMIT = prometheus_client.Counter(
    "soc360_redis_partial_rate_limit_total",
    "Total partial rate-limit mutations (some keys succeeded, others failed).",
    ["flow"],
)

METRIC_COORDINATION_FAILURE = prometheus_client.Counter(
    "soc360_redis_coordination_failure_total",
    "Total coordination-level failures (lock timeouts, lease loss).",
    ["flow"],
)

METRIC_CANCELLATION = prometheus_client.Counter(
    "soc360_redis_cancellation_total",
    "Total operations cancelled via asyncio.CancelledError.",
    ["flow"],
)

METRIC_OPERATION_LATENCY = prometheus_client.Histogram(
    "soc360_redis_operation_latency_seconds",
    "Redis operation latency in seconds, tagged by flow.",
    ["flow"],
    buckets=(
        0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical ordered list — consumers iterate this for per-flow telemetry.
# ─────────────────────────────────────────────────────────────────────────────

SEVEN_METRICS: list[prometheus_client.Collector] = [
    METRIC_OUTAGES,
    METRIC_RETRY,
    METRIC_PARTIAL_REVOCATION,
    METRIC_PARTIAL_RATE_LIMIT,
    METRIC_COORDINATION_FAILURE,
    METRIC_CANCELLATION,
    METRIC_OPERATION_LATENCY,
]
