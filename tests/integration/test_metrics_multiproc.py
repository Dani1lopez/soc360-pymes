"""Integration tests for PR3 multiprocess-safe metrics registry.

Verifies that Prometheus multiprocess mode correctly persists counter values
across worker processes using ``mark_process_dead``.

This is a **state-observation** test — NOT labelled as a Toxiproxy transport
scenario (design rev 9, PR3 row: "NONE").
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import prometheus_client
from prometheus_client import CollectorRegistry, multiprocess


# ─────────────────────────────────────────────────────────────────────────────
# Helper: spawn a real OS process in multiprocess mode
# ─────────────────────────────────────────────────────────────────────────────

_WORKER_SCRIPT = """\
import os
os.environ["PROMETHEUS_MULTIPROC_DIR"] = {tmpdir!r}

from prometheus_client import Counter, multiprocess

counter = Counter({metric_name!r}, {metric_help!r}, {labels!r})
counter.labels(**{label_values!r}).inc({count!r})

# Mark the process dead so the master aggregator can include this worker.
multiprocess.mark_process_dead(os.getpid())
"""


def _spawn_multiproc_worker(
    tmpdir: str,
    metric_name: str,
    metric_help: str,
    labels: list[str],
    label_values: dict[str, str],
    count: int,
) -> None:
    """Spawn a real OS process that creates a multiprocess metric file."""
    script = _WORKER_SCRIPT.format(
        tmpdir=tmpdir,
        metric_name=metric_name,
        metric_help=metric_help,
        labels=labels,
        label_values=label_values,
        count=count,
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Worker process failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


def _collect_multiproc(tmpdir: str) -> str:
    """Set up a master registry with multiprocess collector and return
    the Prometheus text output.
    """
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = tmpdir
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return prometheus_client.generate_latest(registry).decode()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiprocessCounterPersistence:
    """PR3 multiprocess counter persists across real process boundaries."""

    def test_pr3_multiproc_counter_persists_after_mark_process_dead(self) -> None:
        """When a worker process exits after ``mark_process_dead(pid)``,
        the counter increments contributed by that process MUST survive and be
        visible in the aggregated multiprocess registry.

        This is the canonical PR3 integration test — NOT a Toxiproxy transport
        scenario (no proxy, no toxics, just multiprocess state observation).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Spawn a worker process that creates + increments + marks dead.
            _spawn_multiproc_worker(
                tmpdir=tmpdir,
                metric_name="soc360_redis_outages_total",
                metric_help="Redis outages",
                labels=["flow"],
                label_values={"flow": "auth_login_service"},
                count=3,
            )

            # 2. Verify .db files exist in the multiprocess directory.
            db_files = list(Path(tmpdir).glob("*.db"))
            assert len(db_files) > 0, (
                f"No .db files in {tmpdir}: {os.listdir(tmpdir)}"
            )

            # 3. Collect aggregated metrics from the master.
            collected = _collect_multiproc(tmpdir)

            # 4. Assert: counter from dead worker is visible.
            assert "soc360_redis_outages_total" in collected, (
                f"Counter not found in multiprocess output:\n{collected}"
            )
            assert 'flow="auth_login_service"' in collected, (
                f"Flow label not preserved in multiprocess output:\n{collected}"
            )

    def test_multiproc_counter_aggregates_across_workers(self) -> None:
        """When two workers increment counters with different flows,
        the aggregated registry MUST contain both labels.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Worker 1 — auth_login_service, count=2
            _spawn_multiproc_worker(
                tmpdir=tmpdir,
                metric_name="soc360_redis_retry_total",
                metric_help="Retries",
                labels=["flow"],
                label_values={"flow": "auth_login_service"},
                count=2,
            )

            # Worker 2 — auth_refresh_service, count=1
            _spawn_multiproc_worker(
                tmpdir=tmpdir,
                metric_name="soc360_redis_retry_total",
                metric_help="Retries",
                labels=["flow"],
                label_values={"flow": "auth_refresh_service"},
                count=1,
            )

            output = _collect_multiproc(tmpdir)

            assert "soc360_redis_retry_total" in output
            assert 'flow="auth_login_service"' in output
            assert 'flow="auth_refresh_service"' in output

    def test_multiproc_directory_required_for_multiprocess_mode(
        self, monkeypatch
    ) -> None:
        """When PROMETHEUS_MULTIPROC_DIR is not set, a single-process
        Counter MUST still work correctly.
        """
        monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
        registry = CollectorRegistry()
        counter = prometheus_client.Counter(
            "soc360_test_counter_total",
            "Test",
            registry=registry,
        )
        counter.inc()
        output = prometheus_client.generate_latest(registry).decode()
        assert "soc360_test_counter_total" in output, (
            f"Single-process counter should be visible:\n{output}"
        )

    def test_multiproc_cancellation_counter_is_persisted(self) -> None:
        """The cancellation counter from a dead worker MUST be visible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _spawn_multiproc_worker(
                tmpdir=tmpdir,
                metric_name="soc360_redis_cancellation_total",
                metric_help="Cancellations",
                labels=["flow"],
                label_values={"flow": "auth_post_credential_session_lock"},
                count=5,
            )

            output = _collect_multiproc(tmpdir)

            assert "soc360_redis_cancellation_total" in output
            assert 'flow="auth_post_credential_session_lock"' in output
