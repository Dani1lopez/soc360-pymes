import pytest

from app.core import metrics

COUNTERS = ((metrics.METRIC_LOCK_ACQUIRE_TOTAL, "soc360_redis_lock_acquire", ("flow", "outcome")), (metrics.METRIC_LOCK_RENEW_TOTAL, "soc360_redis_lock_renew", ("flow", "outcome")), (metrics.METRIC_LOCK_RELEASE_TOTAL, "soc360_redis_lock_release", ("flow", "outcome")), (metrics.METRIC_LOCK_CONTENTION_TOTAL, "soc360_redis_lock_contention", ("flow", "operation", "outcome")))  # fmt: skip


@pytest.mark.parametrize(("metric", "name", "labels"), COUNTERS)
def test_lock_counters_have_canonical_contract(metric, name, labels) -> None:
    assert metric._name == name
    assert metric._labelnames == labels


def test_lock_wait_histogram_has_canonical_contract() -> None:
    metric = metrics.METRIC_LOCK_WAIT_SECONDS
    assert metric._name == "soc360_redis_lock_wait_seconds"
    assert metric._labelnames == ("flow", "operation")
    assert tuple(metric._upper_bounds) == (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))  # fmt: skip
