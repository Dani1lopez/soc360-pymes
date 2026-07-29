"""Tests for ``gunicorn_conf.py`` — PR4 #260 multiprocess worker exit hook.

Covers spec scenario #10: a worker marked dead drops out of merged multiproc scrape.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import prometheus_client
import pytest
from prometheus_client import CollectorRegistry, multiprocess


_WORKER_SCRIPT = """\
import os, sys
os.environ["PROMETHEUS_MULTIPROC_DIR"] = {tmpdir!r}
from prometheus_client import Gauge
g = Gauge("soc360_metrics_auth_test", "Live gauge for child_exit test", multiprocess_mode="liveall")
g.set({value!r})
sys.stdout.write(str(os.getpid()))
sys.stdout.flush()
"""


def _spawn_liveall_worker(tmpdir: str, value: float, timeout: int = 10) -> int:
    script = _WORKER_SCRIPT.format(tmpdir=tmpdir, value=value)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"worker failed: rc={result.returncode} stderr={result.stderr!r}")
    return int(result.stdout.strip())


def _render_merged(tmpdir: str) -> str:
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = tmpdir
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return prometheus_client.generate_latest(registry).decode()


def _mock_worker(pid: int) -> object:
    """Minimal worker-like object exposing ``.pid`` (Gunicorn contract)."""
    return type("Worker", (), {"pid": pid})()


def _load_gunicorn_conf():
    """Import the repo-root ``gunicorn_conf`` module by file path."""
    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf", os.path.join(os.getcwd(), "gunicorn_conf.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load gunicorn_conf.py from repo root")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestChildExitMarksDeadPid:
    """``child_exit(server, worker)`` MUST call ``mark_process_dead(worker.pid)``."""

    def test_child_exit_marks_dead_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        monkeypatch.setattr(
            multiprocess,
            "mark_process_dead",
            lambda pid, path=None: calls.append(pid),
        )

        gconf = _load_gunicorn_conf()
        gconf.child_exit(server=None, worker=_mock_worker(12345))

        assert calls == [12345]


class TestDoubleChildExitIsIdempotent:
    def test_double_child_exit_is_idempotent(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling ``child_exit`` twice for the same pid MUST NOT raise."""
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
        gconf = _load_gunicorn_conf()
        worker = _mock_worker(54321)

        # First call — file does not exist, mark_process_dead is silent.
        gconf.child_exit(server=None, worker=worker)
        # Second call — idempotent.
        gconf.child_exit(server=None, worker=worker)


class TestMergedScrapeExcludesDeadWorker:
    """A worker marked dead MUST drop out of the merged multiproc scrape output."""

    def test_merged_scrape_excludes_dead_worker_series(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

        pid_a = _spawn_liveall_worker(str(tmp_path), value=11.0)
        pid_b = _spawn_liveall_worker(str(tmp_path), value=22.0)
        assert pid_a != pid_b, f"PIDs must differ: a={pid_a}, b={pid_b}"

        # Sanity: both .db files exist in the multiproc dir.
        from glob import glob

        files = sorted(os.path.basename(f) for f in glob(os.path.join(str(tmp_path), "*")))
        assert f"gauge_liveall_{pid_a}.db" in files, f"Worker A's .db should exist: {files}"
        assert f"gauge_liveall_{pid_b}.db" in files, f"Worker B's .db should exist: {files}"

        # Render BEFORE marking dead — both pid-labeled series visible.
        before = _render_merged(str(tmp_path))
        assert f'pid="{pid_a}"' in before, f"A's series should be present initially:\n{before}"
        assert f'pid="{pid_b}"' in before, f"B's series should be present initially:\n{before}"

        # Simulate gunicorn child_exit for worker B — must translate worker.pid → mark_process_dead.
        gconf = _load_gunicorn_conf()
        gconf.child_exit(server=None, worker=_mock_worker(pid_b))

        # Render AFTER — A's series remains, B's is gone.
        after = _render_merged(str(tmp_path))
        assert f'pid="{pid_a}"' in after, f"A's series should remain after B is marked dead:\n{after}"
        assert f'pid="{pid_b}"' not in after, f"B's series should be gone after mark_process_dead:\n{after}"
