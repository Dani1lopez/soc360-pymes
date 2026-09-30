"""xdist serial/parallel partition (XD-03).

Tests that create or drop a FIXED-NAME database, or run alembic against the
shared unscoped database, cannot run on concurrent xdist workers. They carry
the ``serial_only`` marker and are split out of the parallel run:

- parallel run:  ``pytest -n 2 -m "not serial_only"``
- serial run:    ``pytest -m serial_only``

These tests pin the partition invariant by collecting the real suite in a
subprocess (collection only, no database access):

- the marker is registered, so ``--strict-markers`` cannot reject it;
- the two selections are disjoint and together equal the full collection,
  so no test is silently dropped from both runs or executed twice;
- the known fixed-name migration tests really are in the serial selection.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Node-id prefixes that MUST be serial-only (fixed-name DB / shared-DB alembic).
EXPECTED_SERIAL_PREFIXES = (
    "tests/unit/test_assets.py::TestUpgradePrecondition::",
    "tests/unit/test_assets.py::TestDowngradePrecondition::",
    "tests/sdd/test_migration_chain_indexes.py::TestIndexExistence::",
)
# A pure-SQL-text test in the same module must stay in the parallel run.
EXPECTED_PARALLEL_PREFIX = "tests/unit/test_assets.py::TestMigrationShape::"


def _collect(*extra: str) -> set[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_XDIST_WORKER"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert result.returncode in (0, 5), (
        f"collection failed ({extra}):\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    return {line for line in result.stdout.splitlines() if "::" in line}


@pytest.fixture(scope="module")
def selections() -> tuple[set[str], set[str], set[str]]:
    full = _collect()
    parallel = _collect("-m", "not serial_only")
    serial = _collect("-m", "serial_only")
    return full, parallel, serial


def test_serial_only_marker_is_registered() -> None:
    ini = (ROOT / "pytest.ini").read_text()
    assert "serial_only:" in ini


def test_selections_are_disjoint_and_exhaustive(selections) -> None:
    full, parallel, serial = selections
    assert full, "full collection is empty"
    assert parallel & serial == set(), "tests selected by BOTH runs"
    assert parallel | serial == full, "tests selected by NEITHER run"


def test_known_fixed_name_migration_tests_are_serial_only(selections) -> None:
    _, parallel, serial = selections
    for prefix in EXPECTED_SERIAL_PREFIXES:
        in_serial = {n for n in serial if n.startswith(prefix)}
        assert in_serial, f"no serial-only tests under {prefix}"
        assert not {n for n in parallel if n.startswith(prefix)}, prefix


def test_pure_sql_shape_tests_stay_parallel(selections) -> None:
    _, parallel, serial = selections
    assert {n for n in parallel if n.startswith(EXPECTED_PARALLEL_PREFIX)}
    assert not {n for n in serial if n.startswith(EXPECTED_PARALLEL_PREFIX)}
