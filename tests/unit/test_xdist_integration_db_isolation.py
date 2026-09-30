"""xdist integration DB isolation (XD-02).

``tests/integration/conftest.py`` overrides ``prepare_database`` and used to
read the raw, unscoped ``DATABASE_URL_MIGRATION``. Under pytest-xdist that
would let every worker drop/migrate the SAME shared database while
``db_session`` points at the worker database. These tests pin the contract:

- under xdist, cleanup, the alembic subprocess and the connectivity check
  receive the WORKER-scoped URLs (never the unscoped shared DB);
- serial runs keep the exact previous behavior (raw env URLs, no
  maintenance-DB bootstrap);
- the destructive-cleanup allowlist is applied to the worker-scoped name;
- nothing here touches a live database: asyncpg and subprocess are mocked.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest import mock

import pytest

import tests.conftest as root_conftest
import tests.integration.conftest as integ

SHARED_MIGRATION_URL = "postgresql+asyncpg://mig:secret@localhost:5434/soc360_test"
SHARED_APP_URL = "postgresql+asyncpg://app:secret@localhost:5434/soc360_test"
WORKER_MIGRATION_URL = "postgresql+asyncpg://mig:secret@localhost:5434/soc360_test_gw1"
WORKER_APP_URL = "postgresql+asyncpg://app:secret@localhost:5434/soc360_test_gw1"


@pytest.fixture
def xdist_worker(monkeypatch):
    """Simulate worker ``gw1``: the root conftest exported worker-scoped env."""
    monkeypatch.setenv("DATABASE_URL_MIGRATION", WORKER_MIGRATION_URL)
    monkeypatch.setenv("DATABASE_URL", WORKER_APP_URL)
    monkeypatch.setattr(root_conftest, "_XDIST_WORKER_ID", "gw1")
    monkeypatch.setattr(root_conftest, "MIGRATION_DATABASE_URL", WORKER_MIGRATION_URL)
    monkeypatch.setattr(root_conftest, "TEST_DATABASE_URL", WORKER_APP_URL)


@pytest.fixture
def serial(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_MIGRATION", SHARED_MIGRATION_URL)
    monkeypatch.setenv("DATABASE_URL", SHARED_APP_URL)
    monkeypatch.setattr(root_conftest, "_XDIST_WORKER_ID", "")
    monkeypatch.setattr(root_conftest, "MIGRATION_DATABASE_URL", SHARED_MIGRATION_URL)
    monkeypatch.setattr(root_conftest, "TEST_DATABASE_URL", SHARED_APP_URL)


def _fake_asyncpg(monkeypatch):
    """Patch asyncpg.connect; return the mock so calls can be inspected."""
    import asyncpg

    conn = mock.AsyncMock()
    connect = mock.AsyncMock(return_value=conn)
    monkeypatch.setattr(asyncpg, "connect", connect)
    return connect


class TestScopedUrls:
    def test_xdist_migration_url_is_worker_scoped(self, xdist_worker):
        assert integ._migration_database_url() == WORKER_MIGRATION_URL

    def test_xdist_app_url_is_worker_scoped(self, xdist_worker):
        assert integ._app_database_url() == WORKER_APP_URL

    def test_serial_urls_pass_through_raw_env(self, serial):
        assert integ._migration_database_url() == SHARED_MIGRATION_URL
        assert integ._app_database_url() == SHARED_APP_URL


class TestEnvExportedBeforeAppImport:
    """The app engine/settings read env at import, so it must be scoped first."""

    def test_worker_scoping_is_idempotent(self):
        once = root_conftest._worker_scoped_db_url(SHARED_APP_URL, "gw1")
        assert once == WORKER_APP_URL
        assert root_conftest._worker_scoped_db_url(once, "gw1") == WORKER_APP_URL

    def test_root_conftest_exports_scoped_env_before_app_import(self):
        source = inspect.getsource(root_conftest)
        export = source.index('os.environ["DATABASE_URL"] = TEST_DATABASE_URL')
        app_import = source.index("from app.core.redis import")
        assert export < app_import

    @pytest.mark.skipif(
        not root_conftest._XDIST_WORKER_ID, reason="only meaningful under xdist"
    )
    def test_settings_and_app_engine_use_worker_database(self):
        from app.core.config import settings
        from app.core.database import engine

        worker = root_conftest._XDIST_WORKER_ID
        assert settings.DATABASE_URL == root_conftest.TEST_DATABASE_URL
        assert settings.DATABASE_URL_MIGRATION == root_conftest.MIGRATION_DATABASE_URL
        assert engine.url.database.endswith(f"_{worker}")


class TestCleanDatabase:
    def test_xdist_cleanup_connects_only_to_worker_db(self, xdist_worker, monkeypatch):
        connect = _fake_asyncpg(monkeypatch)
        integ._clean_database()
        databases = [c.kwargs["database"] for c in connect.await_args_list]
        assert databases == ["soc360_test_gw1"]

    def test_serial_cleanup_connects_to_unscoped_db(self, serial, monkeypatch):
        connect = _fake_asyncpg(monkeypatch)
        integ._clean_database()
        databases = [c.kwargs["database"] for c in connect.await_args_list]
        assert databases == ["soc360_test"]

    def test_cleanup_refuses_unscoped_db_under_xdist(self, xdist_worker, monkeypatch):
        connect = _fake_asyncpg(monkeypatch)
        # Unscoped URL leaked back into the env: refuse.
        monkeypatch.setenv("DATABASE_URL_MIGRATION", SHARED_MIGRATION_URL)
        with pytest.raises(RuntimeError, match="unscoped"):
            integ._clean_database()
        connect.assert_not_awaited()

    def test_allowlist_rejects_non_test_worker_db(self, xdist_worker, monkeypatch):
        connect = _fake_asyncpg(monkeypatch)
        monkeypatch.setenv(
            "DATABASE_URL_MIGRATION",
            "postgresql+asyncpg://mig:secret@localhost:5434/prod_gw1",
        )
        with pytest.raises(RuntimeError, match="disposable test database") as exc:
            integ._clean_database()
        assert "secret" not in str(exc.value)
        connect.assert_not_awaited()

    def test_allowlist_accepts_worker_scoped_test_name(self):
        assert integ._is_safe_database_name("soc360_test_gw1")


class TestAlembicUpgrade:
    def _run(self, monkeypatch):
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(integ.subprocess, "run", run)
        integ._run_alembic_upgrade()
        return run.call_args.kwargs["env"]

    def test_xdist_subprocess_receives_worker_migration_url(self, xdist_worker, monkeypatch):
        env = self._run(monkeypatch)
        assert env["DATABASE_URL_MIGRATION"] == WORKER_MIGRATION_URL

    def test_serial_subprocess_receives_raw_env_url(self, serial, monkeypatch):
        env = self._run(monkeypatch)
        assert env["DATABASE_URL_MIGRATION"] == SHARED_MIGRATION_URL


class TestPrepareDatabaseFlow:
    """Drive the real ``prepare_database`` generator with mocked I/O."""

    def _drive(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            root_conftest,
            "_bootstrap_worker_database",
            mock.AsyncMock(side_effect=lambda: calls.append("bootstrap")),
        )
        monkeypatch.setattr(integ, "_clean_database", lambda: calls.append("clean"))
        monkeypatch.setattr(integ, "_run_alembic_upgrade", lambda **kw: calls.append("upgrade"))
        _fake_asyncpg(monkeypatch)
        gen = integ.prepare_database.__wrapped__()
        next(gen)
        return calls

    def test_xdist_bootstraps_worker_db_before_clean_and_migrate(
        self, xdist_worker, monkeypatch
    ):
        assert self._drive(monkeypatch) == ["bootstrap", "clean", "upgrade"]

    def test_serial_never_bootstraps(self, serial, monkeypatch):
        assert self._drive(monkeypatch) == ["clean", "upgrade"]

    def test_xdist_connectivity_check_uses_worker_app_db(self, xdist_worker, monkeypatch):
        connect_holder = {}
        monkeypatch.setattr(root_conftest, "_bootstrap_worker_database", mock.AsyncMock())
        monkeypatch.setattr(integ, "_clean_database", lambda: None)
        monkeypatch.setattr(integ, "_run_alembic_upgrade", lambda **kw: None)
        connect_holder["m"] = _fake_asyncpg(monkeypatch)
        next(integ.prepare_database.__wrapped__())
        databases = [c.kwargs["database"] for c in connect_holder["m"].await_args_list]
        assert databases == ["soc360_test_gw1"]


class TestBootstrapHelper:
    def test_bootstrap_creates_db_and_role_under_lock(self, xdist_worker, monkeypatch):
        order: list[str] = []
        lock_conn = mock.AsyncMock()
        monkeypatch.setattr(
            root_conftest, "_maintenance_connection", mock.AsyncMock(return_value=lock_conn)
        )
        monkeypatch.setattr(
            root_conftest,
            "_acquire_bootstrap_lock",
            mock.AsyncMock(side_effect=lambda c: order.append("lock")),
        )
        ensure_db = mock.AsyncMock(side_effect=lambda c, n: order.append(f"db:{n}"))
        monkeypatch.setattr(root_conftest, "_ensure_database_exists", ensure_db)
        monkeypatch.setattr(
            root_conftest,
            "_ensure_app_role",
            mock.AsyncMock(side_effect=lambda: order.append("role")),
        )
        asyncio.run(root_conftest._bootstrap_worker_database())
        assert order == ["lock", "db:soc360_test_gw1", "role"]
        lock_conn.close.assert_awaited()
