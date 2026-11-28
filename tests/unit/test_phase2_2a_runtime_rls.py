"""Unit tests for Phase 2 unit 2A runtime, LLM client lifecycle, and RLS fixes."""

from __future__ import annotations

import inspect
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import yaml

from app.core.llm import _llm_singletons, get_llm_provider
from app.core.llm.factory import create_llm_provider
from app.core.outage import _FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK
from app.dependencies import lock_deps
from app.dependencies.auth import require_superadmin
from app.dependencies.db_deps import get_db_with_tenant
from app.modules.tenants import router as tenants_router
from app.modules.tenants import schemas as tenant_schemas
from app.worker import enrichment_tasks

_ROOT = Path(__file__).resolve().parents[2]


def test_compose_only_migrate_receives_migration_owner_dsn() -> None:
    data = yaml.safe_load(
        (_ROOT / "docker-compose.app.yml").read_text(encoding="utf-8")
    )
    services = data["services"]

    assert (
        services["migrate"]["environment"]["DATABASE_URL_MIGRATION"]
        == "${STACK_DB_MIGRATION_DSN}"
    )
    for service_name in ("api", "worker", "beat", "maintenance", "enrichment"):
        env = services[service_name]["environment"]
        assert env.get("DATABASE_URL_MIGRATION") == ""


@pytest.mark.asyncio
async def test_create_llm_provider_is_fresh_and_get_llm_provider_is_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_singletons.clear()
    monkeypatch.setattr("app.core.llm.settings.LLM_PROVIDER", "openai")
    monkeypatch.setattr("app.core.llm.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("app.core.llm.settings.OPENAI_MODEL", "test-model")

    p1 = create_llm_provider()
    p2 = create_llm_provider()
    g1 = get_llm_provider()
    g2 = get_llm_provider()
    try:
        assert p1 is not p2
        assert g1 is g2
        assert g1 is not p1
        assert g1 is not p2

        await p1.close()
        assert p1._client.is_closed is True
        assert p2._client.is_closed is False
    finally:
        await p2.close()
        await p1.close()
        await g1.close()
        _llm_singletons.clear()


def test_settings_loads_without_database_url_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.delenv("DATABASE_URL_MIGRATION", raising=False)
    s = Settings(
        _env_file=None,
        SECRET_KEY="".join(chr(ord("a") + (i % 26)) for i in range(130)),
        LLM_PROVIDER="ollama",
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="test",
    )
    assert s.DATABASE_URL_MIGRATION == ""


def test_alembic_env_rejects_empty_migration_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.DATABASE_URL_MIGRATION", "")
    fake_context = MagicMock()
    fake_context.config.config_file_name = None
    monkeypatch.setattr("alembic.context", fake_context)

    with pytest.raises(RuntimeError, match="DATABASE_URL_MIGRATION"):
        runpy.run_path(str(_ROOT / "migrations" / "env.py"))


class _ClosableProvider:
    def __init__(self, close_error: Exception | None = None) -> None:
        self.closed = False
        self._close_error = close_error

    async def complete(self, *args: object, **kwargs: object) -> str:
        return "ok"

    async def close(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class _FakeSession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    async def commit(self) -> None:
        return None


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _patch_enrichment(
    monkeypatch: pytest.MonkeyPatch, enrich_side_effect: Exception
) -> None:
    monkeypatch.setattr(
        enrichment_tasks,
        "async_sessionmaker",
        lambda *a, **kw: lambda: _FakeSession(),
    )
    monkeypatch.setattr(enrichment_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(
        enrichment_tasks,
        "enrich_vulnerability",
        AsyncMock(side_effect=enrich_side_effect),
    )


def test_enrichment_task_defaults_to_fresh_provider_factory() -> None:
    sig = inspect.signature(enrichment_tasks._enrich)
    assert sig.parameters["provider_factory"].default is create_llm_provider


@pytest.mark.asyncio
async def test_enrichment_closes_provider_and_disposes_engine_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_enrichment(monkeypatch, RuntimeError("boom"))
    engine = _FakeEngine()
    provider = _ClosableProvider()

    with pytest.raises(RuntimeError, match="boom"):
        await enrichment_tasks._enrich(
            str(uuid4()),
            str(uuid4()),
            None,
            engine_factory=lambda: engine,
            provider_factory=lambda: provider,
            model_name=lambda: "test-model",
        )

    assert provider.closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_enrichment_disposes_engine_when_provider_factory_fails() -> None:
    engine = _FakeEngine()

    def _boom() -> _ClosableProvider:
        raise RuntimeError("factory boom")

    with pytest.raises(RuntimeError, match="factory boom"):
        await enrichment_tasks._enrich(
            str(uuid4()),
            str(uuid4()),
            None,
            engine_factory=lambda: engine,
            provider_factory=_boom,
            model_name=lambda: "test-model",
        )

    assert engine.disposed is True


@pytest.mark.asyncio
async def test_enrichment_disposes_engine_when_provider_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_enrichment(monkeypatch, RuntimeError("boom"))
    engine = _FakeEngine()
    provider = _ClosableProvider(close_error=RuntimeError("close boom"))

    with pytest.raises(RuntimeError, match="close boom"):
        await enrichment_tasks._enrich(
            str(uuid4()),
            str(uuid4()),
            None,
            engine_factory=lambda: engine,
            provider_factory=lambda: provider,
            model_name=lambda: "test-model",
        )

    assert provider.closed is True
    assert engine.disposed is True


def test_tenant_admin_routes_use_rls_session_and_superadmin_first() -> None:
    for fn in (
        tenants_router.create_tenant,
        tenants_router.list_tenants,
        tenants_router.update_tenant,
    ):
        assert fn.__annotations__["db"] == "DBWithTenantDep"
    assert (
        tenants_router.deactivate_tenant.__annotations__["db"]
        == "TenantDeactivationDBDep"
    )

    params = inspect.signature(lock_deps.get_tenant_deactivation_db).parameters
    names = list(params)
    assert params["_current_user"].default.dependency is require_superadmin
    assert params["db"].default.dependency is get_db_with_tenant
    assert names.index("_current_user") < names.index("db")
    assert names.index("_current_user") < names.index("redis")


class _LockSpy:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.kwargs: dict[str, object] | None = None

    def __call__(self, **kwargs: object) -> _LockSpy:
        self.kwargs = kwargs
        return self

    async def __aenter__(self) -> None:
        self.events.append("lock_enter")

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.events.append("lock_exit")
        return False


@pytest.mark.asyncio
async def test_update_tenant_without_deactivation_takes_no_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    lock = _LockSpy(events)
    tenant = SimpleNamespace()
    service_update = AsyncMock(return_value=tenant)
    monkeypatch.setattr(tenants_router, "acquire_dist_lock", lock)
    monkeypatch.setattr(tenants_router.service, "update_tenant", service_update)
    monkeypatch.setattr(
        tenants_router.schemas.TenantResponse,
        "model_validate",
        classmethod(lambda cls, obj: obj),
    )

    result = await tenants_router.update_tenant(
        uuid4(),
        tenant_schemas.TenantUpdate(name="Renamed"),
        db=MagicMock(),
        redis=MagicMock(),
        current_user=MagicMock(),
    )

    assert result is tenant
    assert lock.kwargs is None
    assert events == []
    service_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_tenant_deactivation_commits_inside_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    lock = _LockSpy(events)
    db = MagicMock()
    db.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    db.rollback = AsyncMock(side_effect=lambda: events.append("rollback"))
    tenant = SimpleNamespace()
    monkeypatch.setattr(tenants_router, "acquire_dist_lock", lock)
    monkeypatch.setattr(
        tenants_router.service, "update_tenant", AsyncMock(return_value=tenant)
    )
    monkeypatch.setattr(
        tenants_router.schemas.TenantResponse,
        "model_validate",
        classmethod(lambda cls, obj: obj),
    )

    await tenants_router.update_tenant(
        uuid4(),
        tenant_schemas.TenantUpdate(is_active=False),
        db=db,
        redis=MagicMock(),
        current_user=MagicMock(),
    )

    assert lock.kwargs is not None
    assert lock.kwargs["flow_id"] == _FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK
    assert events == ["lock_enter", "commit", "lock_exit"]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_tenant_deactivation_rolls_back_inside_lock_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    lock = _LockSpy(events)
    db = MagicMock()
    db.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    db.rollback = AsyncMock(side_effect=lambda: events.append("rollback"))
    monkeypatch.setattr(tenants_router, "acquire_dist_lock", lock)
    monkeypatch.setattr(
        tenants_router.service,
        "update_tenant",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        await tenants_router.update_tenant(
            uuid4(),
            tenant_schemas.TenantUpdate(is_active=False),
            db=db,
            redis=MagicMock(),
            current_user=MagicMock(),
        )

    assert events == ["lock_enter", "rollback", "lock_exit"]
    db.commit.assert_not_awaited()
