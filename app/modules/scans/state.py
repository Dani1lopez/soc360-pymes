"""Scan state machine: the explicit transition map and the atomic UPDATE.

Every status change of a ``Scan`` row goes through this module (F2 slice 5,
decisions 5-6). Two rules define it:

1. The transition map is the single source of truth for which edges exist:
   ``pending → {running, cancelled, failed}``,
   ``running → {completed, failed, cancelled}``, and
   ``completed``/``failed``/``cancelled`` are terminal (no outgoing edges).
   A terminal row can therefore never be revived — rescan means a new
   ``Scan`` row, never a reuse of a terminal one.
2. A transition is ONE conditional ``UPDATE``:
   ``SET status = :to WHERE id = :id AND status IN (:allowed_from)``.
   There is no read-then-write: the rowcount decides the outcome, so two
   concurrent claims of the same ``pending`` scan can never both win — the
   loser gets ``False`` (the caller turns that into a 409 or discards its
   results), and a transition from a terminal state simply matches zero rows.

``failure_reason`` is required when the target is ``failed`` and forbidden
otherwise; both violations raise ``ValueError`` before any statement reaches
the database, as does an unknown target status — and a known status no
transition can ever reach (``pending``).

Commit handling follows ``app.modules.scans.service``: each public function
defaults to ``await session.commit()`` — even when zero rows matched — so the
conditional UPDATE's transaction is closed deterministically in every outcome.
With ``transition_scan(commit=False)``, the caller owns the transaction and
must commit or roll back (including on a zero-row update), allowing findings
and completion to be persisted atomically. ``raw_output`` is allowed only
for completed/failed outcomes; failure reasons are bounded to 64 characters.
With the savepoint ``db_session`` fixture a commit only releases the
savepoint; the outer test transaction still rolls everything back.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scans.models import Scan

__all__ = [
    "SCAN_TRANSITIONS",
    "TERMINAL_STATUSES",
    "cancel_scan",
    "transition_scan",
]

# Allowed outgoing edges per status. Terminal statuses are present as keys
# with an empty set on purpose: they are VALID targets (and valid sources to
# look up), they just never originate a transition.
SCAN_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# Reverse index of SCAN_TRANSITIONS: which statuses may sit in the WHERE clause
# when the target is ``to``. Derived, never hand-maintained, so the map stays
# the single source of truth. ``pending`` ends up with no sources (it is only
# an initial state), which transition_scan rejects up front instead of
# executing an UPDATE that can never match.
_ALLOWED_FROM: dict[str, frozenset[str]] = {
    target: frozenset(
        source for source, targets in SCAN_TRANSITIONS.items() if target in targets
    )
    for target in SCAN_TRANSITIONS
}


async def transition_scan(
    session: AsyncSession,
    scan_id: uuid.UUID,
    *,
    to: str,
    failure_reason: str | None = None,
    raw_output: str | None = None,
    commit: bool = True,
) -> bool:
    """Atomically move scan ``scan_id`` to status ``to``; True iff 1 row updated.

    Raises ``ValueError`` — before touching the database — when ``to`` is not
    a known status, when no status may ever transition to ``to`` (``pending``
    is only an initial state), when ``failure_reason`` is missing for
    ``to="failed"``, when it is supplied for any other target or exceeds
    64 characters, or when ``raw_output`` is supplied outside completed/failed.
    With ``commit=False``, the caller owns commit/rollback of the UPDATE.

    Transitioning to ``running`` also requires non-NULL ``dispatched_at``;
    an undispatched pending scan is left unchanged and returns False.
    Other transitions do not require dispatch.

    The statement is one conditional UPDATE with ``synchronize_session=False``:
    the identity map is deliberately left alone so callers must re-read the
    row from the database instead of trusting a possibly stale ORM object.
    """
    if to not in SCAN_TRANSITIONS:
        raise ValueError(f"unknown scan status {to!r}")
    if not _ALLOWED_FROM[to]:
        raise ValueError(f"scan status {to!r} cannot be reached by any transition")
    if to == "failed" and not failure_reason:
        raise ValueError("failure_reason is required when transitioning to 'failed'")
    if to != "failed" and failure_reason is not None:
        raise ValueError(
            "failure_reason is only allowed when transitioning to 'failed'"
        )

    if failure_reason is not None and len(failure_reason) > 64:
        raise ValueError("failure_reason must not exceed 64 characters")
    if raw_output is not None and to not in ("completed", "failed"):
        raise ValueError("raw_output is only allowed for completed or failed scans")

    values: dict[str, object] = {"status": to}
    if raw_output is not None:
        values["raw_output"] = raw_output
    if to == "running":
        values["started_at"] = datetime.now(timezone.utc)
    elif to in TERMINAL_STATUSES:
        values["completed_at"] = datetime.now(timezone.utc)
    if to == "failed":
        values["failure_reason"] = failure_reason

    stmt = (
        update(Scan)
        .where(Scan.id == scan_id, Scan.status.in_(_ALLOWED_FROM[to]))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if to == "running":
        stmt = stmt.where(Scan.dispatched_at.isnot(None))
    result = await session.execute(stmt)
    if commit:
        await session.commit()
    return result.rowcount == 1


async def cancel_scan(session: AsyncSession, scan_id: uuid.UUID) -> bool:
    """Move a ``pending`` or ``running`` scan to ``cancelled``; False if too late.

    The HTTP cancel endpoint uses the same transition via the scan service;
    the worker watches persisted cancellation to stop a live executor.
    """
    return await transition_scan(session, scan_id, to="cancelled")
