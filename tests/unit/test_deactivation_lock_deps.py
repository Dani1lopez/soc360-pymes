from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import RedisUnreachableError, TemporaryUnavailableError


class RecordingSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class RecordingLock:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> "RecordingLock":
        self.events.append("lock_enter")
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        self.events.append("lock_exit")
        return False


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4())


def test_deactivation_db_aliases_bind_specialized_dependencies() -> None:
    from typing import get_args

    from app.dependencies import TenantDeactivationDBDep, UserDeactivationDBDep
    from app.dependencies import lock_deps

    user_dependency = get_args(UserDeactivationDBDep)[1]
    tenant_dependency = get_args(TenantDeactivationDBDep)[1]

    assert user_dependency.dependency is lock_deps.get_user_deactivation_db
    assert tenant_dependency.dependency is lock_deps.get_tenant_deactivation_db


def test_deactivation_routers_use_specialized_db_aliases() -> None:
    from app.modules.tenants import router as tenants_router
    from app.modules.users import router as users_router

    assert users_router.deactivate_user.__annotations__["db"] == (
        "UserDeactivationDBDep"
    )
    assert tenants_router.deactivate_tenant.__annotations__["db"] == (
        "TenantDeactivationDBDep"
    )


@pytest.mark.asyncio
async def test_user_deactivation_commits_before_lock_exit(monkeypatch) -> None:
    from app.dependencies import lock_deps

    events: list[str] = []
    db = RecordingSession(events)
    target = _user()
    lock = RecordingLock(events)
    captured: dict[str, object] = {}

    def acquire(**kwargs):
        captured.update(kwargs)
        return lock

    monkeypatch.setattr(lock_deps, "acquire_dist_lock", acquire)
    generator = lock_deps.get_user_deactivation_db(
        db=db,
        target=target,
        redis=object(),
    )

    assert await generator.__anext__() is db
    with pytest.raises(StopAsyncIteration):
        await generator.asend(None)

    assert events == ["lock_enter", "commit", "lock_exit"]
    assert captured["tenant_id"] == str(target.tenant_id)
    assert captured["asset_id"] == f"user:{target.id}"


@pytest.mark.asyncio
async def test_user_deactivation_rolls_back_before_lock_exit(monkeypatch) -> None:
    from app.dependencies import lock_deps

    events: list[str] = []
    db = RecordingSession(events)
    lock = RecordingLock(events)
    monkeypatch.setattr(lock_deps, "acquire_dist_lock", lambda **_kwargs: lock)
    generator = lock_deps.get_user_deactivation_db(
        db=db,
        target=_user(),
        redis=object(),
    )
    await generator.__anext__()

    error = RuntimeError("mutation failed")
    with pytest.raises(RuntimeError, match="mutation failed"):
        await generator.athrow(error)

    assert events == ["lock_enter", "rollback", "lock_exit"]


@pytest.mark.asyncio
async def test_tenant_deactivation_commits_before_lock_exit(monkeypatch) -> None:
    from app.dependencies import lock_deps

    events: list[str] = []
    db = RecordingSession(events)
    tenant_id = uuid4()
    lock = RecordingLock(events)
    captured: dict[str, object] = {}

    def acquire(**kwargs):
        captured.update(kwargs)
        return lock

    monkeypatch.setattr(lock_deps, "acquire_dist_lock", acquire)
    generator = lock_deps.get_tenant_deactivation_db(
        db=db,
        tenant_id=tenant_id,
        redis=object(),
    )

    assert await generator.__anext__() is db
    with pytest.raises(StopAsyncIteration):
        await generator.asend(None)

    assert events == ["lock_enter", "commit", "lock_exit"]
    assert captured["tenant_id"] == str(tenant_id)
    assert captured["asset_id"] == f"tenant:{tenant_id}"


@pytest.mark.asyncio
async def test_tenant_deactivation_rolls_back_before_lock_exit(monkeypatch) -> None:
    from app.dependencies import lock_deps

    events: list[str] = []
    db = RecordingSession(events)
    lock = RecordingLock(events)
    monkeypatch.setattr(lock_deps, "acquire_dist_lock", lambda **_kwargs: lock)
    generator = lock_deps.get_tenant_deactivation_db(
        db=db,
        tenant_id=uuid4(),
        redis=object(),
    )
    await generator.__anext__()

    error = RuntimeError("mutation failed")
    with pytest.raises(RuntimeError, match="mutation failed"):
        await generator.athrow(error)

    assert events == ["lock_enter", "rollback", "lock_exit"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dependency_name, dependency_kwargs",
    [
        ("get_user_deactivation_db", {"target": _user()}),
        ("get_tenant_deactivation_db", {"tenant_id": uuid4()}),
    ],
)
@pytest.mark.parametrize(
    "lock_error",
    [
        TemporaryUnavailableError("contention"),
        RedisUnreachableError("redis outage"),
    ],
)
async def test_acquire_failure_precedes_transaction_actions(
    monkeypatch,
    dependency_name: str,
    dependency_kwargs: dict[str, object],
    lock_error: Exception,
) -> None:
    from app.dependencies import lock_deps

    events: list[str] = []
    db = RecordingSession(events)

    def acquire(**_kwargs):
        raise lock_error

    monkeypatch.setattr(lock_deps, "acquire_dist_lock", acquire)
    dependency = getattr(lock_deps, dependency_name)
    generator = dependency(db=db, redis=object(), **dependency_kwargs)

    with pytest.raises(type(lock_error)) as exc_info:
        await generator.__anext__()

    assert exc_info.value is lock_error
    assert events == []
