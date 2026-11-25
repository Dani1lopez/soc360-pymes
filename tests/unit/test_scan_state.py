"""Unit tests for the scan state machine — F2 slice 5, PR 5a.

DB-free by design: the transition map and the ValueError guards are pure
logic, and the shape of the single conditional UPDATE is asserted by
compiling the statement the fake session captured. Real atomicity (races,
terminal rows, timestamp persistence) is covered by
``tests/integration/test_scan_state_transitions.py``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.modules.scans.state import (
    SCAN_TRANSITIONS,
    TERMINAL_STATUSES,
    cancel_scan,
    transition_scan,
)


class _RecordingSession:
    """AsyncSession stand-in that captures executed statements and commits."""

    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.statements: list = []
        self.commit_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=self.rowcount)

    async def commit(self) -> None:
        self.commit_count += 1


def _as_session(fake: _RecordingSession) -> AsyncSession:
    """Type the fake as the AsyncSession the state helpers expect."""
    return cast(AsyncSession, fake)


def _compile(statement) -> tuple[str, dict]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


def _in_source_lists(params: dict) -> list:
    """Return every list-valued bind param — the expanded ``status IN (...)``.

    Only the ``IN`` sources are lists; every other bind is a scalar
    (uuid/datetime/str/None), so this picks the allowed-source set without
    depending on SQLAlchemy's auto-generated parameter names. Inner lists are
    sorted because they come from a frozenset with no defined order.
    """
    return [
        sorted(value) for value in params.values() if isinstance(value, (list, tuple))
    ]


# ---------------------------------------------------------------------------
# Transition map
# ---------------------------------------------------------------------------


class TestTransitionMap:
    def test_pending_edges(self) -> None:
        assert SCAN_TRANSITIONS["pending"] == {"running", "cancelled", "failed"}

    def test_running_edges(self) -> None:
        assert SCAN_TRANSITIONS["running"] == {"completed", "failed", "cancelled"}

    def test_terminal_states_have_no_outgoing_edges(self) -> None:
        for status in ("completed", "failed", "cancelled"):
            assert status in TERMINAL_STATUSES
            assert SCAN_TRANSITIONS[status] == set()

    def test_invalid_edges_are_absent(self) -> None:
        # A pending scan cannot complete without running first.
        assert "completed" not in SCAN_TRANSITIONS["pending"]
        # No state ever re-enters pending, and a running scan cannot be
        # claimed a second time.
        assert "pending" not in SCAN_TRANSITIONS["running"]
        for terminal in TERMINAL_STATUSES:
            assert "pending" not in SCAN_TRANSITIONS[terminal]
            assert "running" not in SCAN_TRANSITIONS[terminal]

    def test_every_status_is_covered_exactly_once(self) -> None:
        assert set(SCAN_TRANSITIONS) == {
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
        }


# ---------------------------------------------------------------------------
# ValueError guards — must fire before any statement reaches the DB
# ---------------------------------------------------------------------------


class TestValueErrorGuards:
    async def test_reason_length_bound(self) -> None:
        session = _RecordingSession()
        with pytest.raises(ValueError, match="64"):
            await transition_scan(
                _as_session(session), uuid.uuid4(), to="failed", failure_reason="x" * 65
            )
        assert session.statements == []
        assert session.commit_count == 0

    @pytest.mark.parametrize("target", ["pending", "running", "cancelled"])
    async def test_raw_output_forbidden(self, target: str) -> None:
        session = _RecordingSession()
        with pytest.raises(ValueError):
            await transition_scan(
                _as_session(session), uuid.uuid4(), to=target, raw_output="xml"
            )
        assert session.statements == []
        assert session.commit_count == 0

    async def test_unknown_target_raises_before_touching_db(self) -> None:
        session = _RecordingSession()
        with pytest.raises(ValueError, match="unknown scan status"):
            await transition_scan(_as_session(session), uuid.uuid4(), to="archived")
        assert session.statements == []
        assert session.commit_count == 0

    async def test_unreachable_target_raises_before_touching_db(self) -> None:
        # ``pending`` is a valid status but only an initial state: nothing may
        # ever transition into it, so it is rejected like an invalid target.
        session = _RecordingSession()
        with pytest.raises(ValueError, match="cannot be reached"):
            await transition_scan(_as_session(session), uuid.uuid4(), to="pending")
        assert session.statements == []
        assert session.commit_count == 0

    async def test_failed_requires_failure_reason(self) -> None:
        session = _RecordingSession()
        with pytest.raises(ValueError, match="failure_reason is required"):
            await transition_scan(_as_session(session), uuid.uuid4(), to="failed")
        assert session.statements == []

    async def test_failed_rejects_empty_failure_reason(self) -> None:
        session = _RecordingSession()
        with pytest.raises(ValueError, match="failure_reason is required"):
            await transition_scan(
                _as_session(session), uuid.uuid4(), to="failed", failure_reason=""
            )
        assert session.statements == []

    @pytest.mark.parametrize("target", ["running", "completed", "cancelled"])
    async def test_failure_reason_forbidden_for_non_failed_targets(
        self, target: str
    ) -> None:
        session = _RecordingSession()
        with pytest.raises(ValueError, match="failure_reason is only allowed"):
            await transition_scan(
                _as_session(session), uuid.uuid4(), to=target, failure_reason="timeout"
            )
        assert session.statements == []


# ---------------------------------------------------------------------------
# The one conditional UPDATE
# ---------------------------------------------------------------------------


class TestSingleConditionalUpdate:
    @pytest.mark.parametrize("rowcount", [0, 1])
    @pytest.mark.parametrize("target", ["completed", "failed"])
    async def test_caller_owned_completion(self, rowcount: int, target: str) -> None:
        session = _RecordingSession(rowcount=rowcount)
        result = await transition_scan(
            _as_session(session),
            uuid.uuid4(),
            to=target,
            failure_reason="x" * 64 if target == "failed" else None,
            raw_output="",
            commit=False,
        )
        assert result is (rowcount == 1)
        assert session.commit_count == 0
        _, params = _compile(session.statements[0])
        assert params["raw_output"] == ""

    async def test_exactly_one_update_statement_and_no_read(self) -> None:
        session = _RecordingSession(rowcount=1)
        result = await transition_scan(_as_session(session), uuid.uuid4(), to="running")
        assert result is True
        assert len(session.statements) == 1
        assert isinstance(session.statements[0], Update)
        assert session.commit_count == 1

    async def test_running_targets_only_pending_and_sets_started_at(self) -> None:
        session = _RecordingSession()
        await transition_scan(_as_session(session), uuid.uuid4(), to="running")
        sql, params = _compile(session.statements[0])
        assert "scans.id =" in sql
        assert "scans.status IN" in sql
        assert _in_source_lists(params) == [["pending"]]
        assert "started_at" in sql
        assert "completed_at" not in sql
        assert "failure_reason" not in sql

    async def test_completed_targets_running_and_sets_completed_at(self) -> None:
        session = _RecordingSession()
        await transition_scan(_as_session(session), uuid.uuid4(), to="completed")
        sql, params = _compile(session.statements[0])
        assert _in_source_lists(params) == [["running"]]
        assert "completed_at" in sql
        assert "started_at" not in sql
        assert "failure_reason" not in sql

    async def test_failed_targets_pending_and_running_and_stores_reason(self) -> None:
        session = _RecordingSession()
        await transition_scan(
            _as_session(session), uuid.uuid4(), to="failed", failure_reason="timeout"
        )
        sql, params = _compile(session.statements[0])
        assert _in_source_lists(params) == [["pending", "running"]]
        assert "completed_at" in sql
        assert "failure_reason" in sql
        assert "started_at" not in sql
        assert params["failure_reason"] == "timeout"

    async def test_zero_rows_returns_false_and_still_commits(self) -> None:
        session = _RecordingSession(rowcount=0)
        result = await transition_scan(_as_session(session), uuid.uuid4(), to="running")
        assert result is False
        # Commit runs unconditionally so the conditional UPDATE's transaction
        # is closed deterministically even when the race was lost.
        assert session.commit_count == 1


# ---------------------------------------------------------------------------
# cancel_scan helper
# ---------------------------------------------------------------------------


class TestCancelScan:
    async def test_cancel_targets_pending_and_running(self) -> None:
        session = _RecordingSession(rowcount=1)
        assert await cancel_scan(_as_session(session), uuid.uuid4()) is True
        assert len(session.statements) == 1
        assert isinstance(session.statements[0], Update)
        sql, params = _compile(session.statements[0])
        assert params["status"] == "cancelled"
        assert _in_source_lists(params) == [["pending", "running"]]
        assert "completed_at" in sql
        assert "failure_reason" not in sql

    async def test_cancel_returns_false_when_race_lost(self) -> None:
        session = _RecordingSession(rowcount=0)
        assert await cancel_scan(_as_session(session), uuid.uuid4()) is False
        assert session.commit_count == 1
