"""Worker task lifecycle without a database or broker."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.pool import NullPool

from app.worker import tasks
from app.worker.celery_app import celery_app


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
    return engine, factory, session


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled", "skipped"])
def test_run_scan_parses_ids_and_returns_outcome(monkeypatch, task_engine, outcome):
    engine, factory, session = task_engine
    scan_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    execute = AsyncMock(return_value=outcome)
    monkeypatch.setattr(tasks, "execute_scan", execute)

    assert tasks.run_scan.run(str(scan_id), str(tenant_id)) == outcome
    execute.assert_awaited_once_with(session, scan_id, tenant_id=tenant_id)
    factory.assert_called_once_with()
    engine.dispose.assert_awaited_once_with()


def test_engine_disposed_on_execution_error(monkeypatch, task_engine):
    engine, _, _ = task_engine
    monkeypatch.setattr(
        tasks, "execute_scan", AsyncMock(side_effect=RuntimeError("scan failed"))
    )
    with pytest.raises(RuntimeError, match="scan failed"):
        tasks.run_scan.run(str(uuid.uuid4()), str(uuid.uuid4()))
    engine.dispose.assert_awaited_once_with()


@pytest.mark.parametrize("invalid", ["not-a-uuid", None, 123, ["x"]])
@pytest.mark.parametrize("position", [0, 1])
def test_invalid_ids_skip_without_engine(task_engine, invalid, position):
    _, factory, _ = task_engine
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    ids[position] = invalid
    assert tasks.run_scan.run(*ids) == "skipped"
    factory.assert_not_called()


def test_task_engine_uses_null_pool():
    engine = tasks.build_task_engine()
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        asyncio.run(engine.dispose())


def test_task_registered_through_loader():
    celery_app.loader.import_default_modules()
    assert "scans.run_scan" in celery_app.tasks
