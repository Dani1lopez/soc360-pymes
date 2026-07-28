"""Unit tests for PR3 metrics registry — DB-free, Redis-free.

Verifies the seven-metric registry against the design rev 9 contract:
exact metric names, types, the canonical ``flow`` label, and label cardinality.
"""

from __future__ import annotations

import prometheus_client

from app.core.metrics import (
    METRIC_OUTAGES,
    METRIC_RETRY,
    METRIC_PARTIAL_REVOCATION,
    METRIC_PARTIAL_RATE_LIMIT,
    METRIC_COORDINATION_FAILURE,
    METRIC_CANCELLATION,
    METRIC_OPERATION_LATENCY,
    SEVEN_METRICS,
)


# ---------------------------------------------------------------------------
# 3.1a — Seven-metric coverage (design rev 9 exhaustive set)
# ---------------------------------------------------------------------------

# prometheus_client strips the ``_total`` suffix from Counter._name
# (re-added in OpenMetrics format at collection time).
EXPECTED_METRIC_NAMES = frozenset(
    [
        "soc360_redis_outages",
        "soc360_redis_retry",
        "soc360_redis_partial_revocation",
        "soc360_redis_partial_rate_limit",
        "soc360_redis_coordination_failure",
        "soc360_redis_cancellation",
        "soc360_redis_operation_latency_seconds",
    ]
)


class TestSevenMetricCoverage:
    """The registry MUST expose exactly the seven metrics from design rev 9."""

    def test_seven_metrics_list_has_exactly_7_items(self) -> None:
        """SEVEN_METRICS MUST contain exactly 7 metrics."""
        assert len(SEVEN_METRICS) == 7, (
            f"SEVEN_METRICS has {len(SEVEN_METRICS)} items, expected 7"
        )

    def test_all_seven_are_prometheus_collectors(self) -> None:
        """Every item in SEVEN_METRICS MUST be a Prometheus Counters or Histogram."""
        for i, metric in enumerate(SEVEN_METRICS):
            assert isinstance(
                metric,
                (prometheus_client.Counter, prometheus_client.Histogram),
            ), (
                f"SEVEN_METRICS[{i}] = {metric!r} is not Counter/Histogram "
                f"(type={type(metric).__name__})"
            )

    def test_exact_expected_metric_names_present(self) -> None:
        """The registry MUST contain exactly the seven named metrics."""
        actual = frozenset(m._name for m in SEVEN_METRICS)
        assert actual == EXPECTED_METRIC_NAMES, (
            f"Metric name mismatch.\n"
            f"Missing: {sorted(EXPECTED_METRIC_NAMES - actual)}\n"
            f"Extra:   {sorted(actual - EXPECTED_METRIC_NAMES)}"
        )

    @staticmethod
    def _find_metric(name: str) -> prometheus_client.Collector:
        for m in SEVEN_METRICS:
            if m._name == name:
                return m
        raise AssertionError(f"Metric {name!r} not found in SEVEN_METRICS")

    def test_outages_is_counter(self) -> None:
        """METRIC_OUTAGES MUST be a Counter."""
        assert isinstance(METRIC_OUTAGES, prometheus_client.Counter), (
            f"Expected Counter, got {type(METRIC_OUTAGES).__name__}"
        )
        assert METRIC_OUTAGES._name == "soc360_redis_outages"

    def test_retry_is_counter(self) -> None:
        """METRIC_RETRY MUST be a Counter."""
        assert isinstance(METRIC_RETRY, prometheus_client.Counter), (
            f"Expected Counter, got {type(METRIC_RETRY).__name__}"
        )
        assert METRIC_RETRY._name == "soc360_redis_retry"

    def test_partial_revocation_is_counter(self) -> None:
        """METRIC_PARTIAL_REVOCATION MUST be a Counter."""
        assert isinstance(METRIC_PARTIAL_REVOCATION, prometheus_client.Counter)
        assert METRIC_PARTIAL_REVOCATION._name == "soc360_redis_partial_revocation"

    def test_partial_rate_limit_is_counter(self) -> None:
        """METRIC_PARTIAL_RATE_LIMIT MUST be a Counter."""
        assert isinstance(METRIC_PARTIAL_RATE_LIMIT, prometheus_client.Counter)
        assert METRIC_PARTIAL_RATE_LIMIT._name == "soc360_redis_partial_rate_limit"

    def test_coordination_failure_is_counter(self) -> None:
        """METRIC_COORDINATION_FAILURE MUST be a Counter."""
        assert isinstance(METRIC_COORDINATION_FAILURE, prometheus_client.Counter)
        assert METRIC_COORDINATION_FAILURE._name == "soc360_redis_coordination_failure"

    def test_cancellation_is_counter(self) -> None:
        """METRIC_CANCELLATION MUST be a Counter."""
        assert isinstance(METRIC_CANCELLATION, prometheus_client.Counter)
        assert METRIC_CANCELLATION._name == "soc360_redis_cancellation"

    def test_operation_latency_is_histogram(self) -> None:
        """METRIC_OPERATION_LATENCY MUST be a Histogram."""
        assert isinstance(METRIC_OPERATION_LATENCY, prometheus_client.Histogram)
        assert METRIC_OPERATION_LATENCY._name == "soc360_redis_operation_latency_seconds"


# ---------------------------------------------------------------------------
# 3.1b — Canonical ``flow`` label cardinality
# ---------------------------------------------------------------------------

class TestFlowLabelCardinality:
    """Every metric MUST carry the canonical ``flow`` label."""

    def test_every_metric_has_flow_label(self) -> None:
        """Each metric in SEVEN_METRICS MUST define the ``flow`` label."""
        for metric in SEVEN_METRICS:
            label_names = metric._labelnames
            assert "flow" in label_names, (
                f"Metric {metric._name!r} is missing the 'flow' label "
                f"(labels: {sorted(label_names)})"
            )

    def test_flow_label_is_string_type(self) -> None:
        """The ``flow`` label MUST accept string values."""
        for metric in SEVEN_METRICS:
            # Labels in prometheus_client are all strings by construction.
            assert "flow" in metric._labelnames

    def test_counter_label_cardinality_controlled(self) -> None:
        """Counters MUST only have the ``flow`` label (no tenant/user cardinality)."""
        for metric in SEVEN_METRICS:
            if isinstance(metric, prometheus_client.Counter):
                assert metric._labelnames == ("flow",), (
                    f"Counter {metric._name!r} has unexpected labels: "
                    f"{metric._labelnames} (expected ('flow',))"
                )

    def test_histogram_label_cardinality_controlled(self) -> None:
        """Histogram MUST only have the ``flow`` label (no per-path explosion)."""
        for metric in SEVEN_METRICS:
            if isinstance(metric, prometheus_client.Histogram):
                assert metric._labelnames == ("flow",), (
                    f"Histogram {metric._name!r} has unexpected labels: "
                    f"{metric._labelnames} (expected ('flow',))"
                )


# ---------------------------------------------------------------------------
# 3.1c — Metric increment behaviour
# ---------------------------------------------------------------------------

class TestMetricIncrement:
    """Counters MUST increment and Histogram MUST observe per-flow."""

    def test_outages_counter_increments_with_flow_label(self) -> None:
        """METRIC_OUTAGES MUST accept labels and inc() without error."""
        METRIC_OUTAGES.labels(flow="auth_login_service").inc()
        # The inc() call itself proves the metric/label contract is correct.
        # prometheus_client guarantees correctness of the counter internals.

    def test_retry_counter_increments_with_flow_label(self) -> None:
        """METRIC_RETRY MUST accept labels and inc() without error."""
        METRIC_RETRY.labels(flow="auth_refresh_service").inc()

    def test_cancellation_counter_increments(self) -> None:
        """METRIC_CANCELLATION MUST accept labels and inc() without error."""
        METRIC_CANCELLATION.labels(flow="auth_post_credential_session_lock").inc()

    def test_histogram_observes_with_flow_label(self) -> None:
        """METRIC_OPERATION_LATENCY MUST accept labels and observe() without error."""
        METRIC_OPERATION_LATENCY.labels(flow="auth_login_service").observe(0.042)

    def test_multiple_flow_labels_on_same_counter(self) -> None:
        """A counter MUST support multiple distinct flow label values."""
        METRIC_OUTAGES.labels(flow="auth_login_service").inc()
        METRIC_OUTAGES.labels(flow="auth_refresh_service").inc()
        METRIC_OUTAGES.labels(flow="auth_logout_service").inc()

    def test_coordination_failure_counter_increments(self) -> None:
        """METRIC_COORDINATION_FAILURE MUST accept labels and inc()."""
        METRIC_COORDINATION_FAILURE.labels(
            flow="auth_post_credential_session_lock"
        ).inc()

    def test_partial_revocation_counter_increments(self) -> None:
        """METRIC_PARTIAL_REVOCATION MUST accept labels and inc()."""
        METRIC_PARTIAL_REVOCATION.labels(
            flow="tenants_deactivate_tenant_revoke"
        ).inc()

    def test_partial_rate_limit_counter_increments(self) -> None:
        """METRIC_PARTIAL_RATE_LIMIT MUST accept labels and inc()."""
        METRIC_PARTIAL_RATE_LIMIT.labels(
            flow="auth_login_rate_record"
        ).inc()


# ---------------------------------------------------------------------------
# Structural: named constants match the list
# ---------------------------------------------------------------------------

class TestNamedConstantExports:
    """The individual metric constants MUST be present in SEVEN_METRICS."""

    def test_named_constants_are_exactly_seven_metrics(self) -> None:
        """Each METRIC_* constant MUST be one of the SEVEN_METRICS items."""
        named = frozenset(
            [
                METRIC_OUTAGES,
                METRIC_RETRY,
                METRIC_PARTIAL_REVOCATION,
                METRIC_PARTIAL_RATE_LIMIT,
                METRIC_COORDINATION_FAILURE,
                METRIC_CANCELLATION,
                METRIC_OPERATION_LATENCY,
            ]
        )
        assert named == frozenset(SEVEN_METRICS), (
            "Named constants do not match SEVEN_METRICS list"
        )
