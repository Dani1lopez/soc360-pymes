"""Worker task lifecycle without a database or broker."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.pool import NullPool

from app.worker import tasks
from app.worker.celery_app import celery_app
from app.worker.tasks import _wait_for_cancel as real_watcher


@pytest.fixture
def task_engine(monkeypatch):
    engine = MagicMock()
    engine.dispose = AsyncMock()
    factory = MagicMock(return_value=engine)
    session = MagicMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    maker = MagicMock(return_value=context)
    monkeypatch.setattr(tasks, "build_task_engine", factory)
    monkeypatch.setattr(tasks, "async_sessionmaker", MagicMock(return_value=maker))

    async def idle_watcher(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(tasks, "_wait_for_cancel", idle_watcher, raising=False)
    monkeypatch.setattr(
        tasks,
        "claim_next_scan",
        AsyncMock(return_value=(uuid.uuid4(), uuid.uuid4())),
        raising=False,
    )
    return engine, factory, session


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled", "skipped"])
def test_wake_returns_outcome(monkeypatch, task_engine, outcome):
    engine, factory, session = task_engine
    scan_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    execute = AsyncMock(return_value=outcome)
    monkeypatch.setattr(tasks, "execute_scan", execute)

    tasks.claim_next_scan.return_value = (scan_id, tenant_id)
    assert tasks.wake.run() == outcome
    execute.assert_awaited_once_with(
        session, scan_id, tenant_id=tenant_id, claimed=True
    )
    tasks.claim_next_scan.assert_awaited_once_with(session)
    factory.assert_called_once_with()
    engine.dispose.assert_awaited_once_with()


def test_engine_disposed_on_execution_error(monkeypatch, task_engine):
    engine, _, _ = task_engine
    monkeypatch.setattr(
        tasks, "execute_scan", AsyncMock(side_effect=RuntimeError("scan failed"))
    )
    with pytest.raises(RuntimeError, match="scan failed"):
        tasks.wake.run()
    engine.dispose.assert_awaited_once_with()


def test_idle_disposes_engine_without_execution(monkeypatch, task_engine):
    engine, factory, session = task_engine
    tasks.claim_next_scan.return_value = None
    execute = AsyncMock()
    monkeypatch.setattr(tasks, "execute_scan", execute)
    assert tasks.wake.run() == "idle"
    tasks.claim_next_scan.assert_awaited_once_with(session)
    execute.assert_not_awaited()
    factory.assert_called_once_with()
    engine.dispose.assert_awaited_once_with()


async def test_live_cancel(monkeypatch, task_engine):
    cancelled = asyncio.Event()
    started = asyncio.Event()

    async def execute(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def watcher(*args, **kwargs):
        await started.wait()

    monkeypatch.setattr(tasks, "_wait_for_cancel", watcher)
    result = await asyncio.wait_for(tasks._wake(execute=execute), 1)
    assert result == "cancelled"
    assert cancelled.is_set()
    task_engine[0].dispose.assert_awaited_once()


async def test_executor_finishes_cleans_watcher(monkeypatch, task_engine):
    watching = asyncio.Event()
    stopped = asyncio.Event()

    async def watcher(*args, **kwargs):
        watching.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def execute(*args, **kwargs):
        await watching.wait()
        return "completed"

    monkeypatch.setattr(tasks, "_wait_for_cancel", watcher)
    assert await asyncio.wait_for(tasks._wake(execute=execute), 1) == "completed"
    assert stopped.is_set()


async def test_poll_error_retries(monkeypatch, task_engine, caplog):
    session = task_engine[2]
    session.scalar = AsyncMock(
        side_effect=[RuntimeError("private detail"), "running", "cancelled"]
    )
    context = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(
        tasks,
        "async_sessionmaker",
        MagicMock(return_value=MagicMock(return_value=context)),
    )
    monkeypatch.setattr(tasks, "set_tenant_context", AsyncMock())
    await asyncio.wait_for(
        real_watcher(task_engine[0], uuid.uuid4(), uuid.uuid4(), interval=0), 1
    )
    assert session.scalar.await_count == 3
    assert "cancel" in caplog.text.lower()
    assert "private detail" not in caplog.text


def test_task_engine_uses_null_pool():
    engine = tasks.build_task_engine()
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.parametrize("fails", [False, True])
async def test_reap_disposes_engine(monkeypatch, task_engine, fails):
    engine, factory, session = task_engine
    reaper = AsyncMock(
        side_effect=RuntimeError("lost") if fails else None, return_value=2
    )
    monkeypatch.setattr(tasks, "reap_stale_scans", reaper, raising=False)
    if fails:
        with pytest.raises(RuntimeError, match="lost"):
            await tasks._reap(engine_factory=factory)
    else:
        assert await tasks._reap(engine_factory=factory) == 2
    reaper.assert_awaited_once_with(
        session, older_than_seconds=tasks.STALE_SCAN_SECONDS
    )
    engine.dispose.assert_awaited_once_with()


def test_task_registered_through_loader():
    celery_app.loader.import_default_modules()
    assert "scans.wake" in celery_app.tasks
