from __future__ import annotations

import pytest

from tests.integration.conftest import _clean_database, _is_safe_database_name


class TestDatabaseCleanupGuard:
    """Unit tests for the disposable-database guard used by integration tests."""

    @pytest.mark.parametrize(
        "dbname",
        [
            "soc360_test",
            "test_soc360",
            "test_db",
            "TEST",
            "my_test_db",
            "test",
            "  TEST  ",
        ],
    )
    def test_name_is_safe_when_it_contains_a_clear_test_token(self, dbname: str) -> None:
        assert _is_safe_database_name(dbname) is True

    @pytest.mark.parametrize(
        "dbname",
        [
            "postgres",
            "template0",
            "template1",
            "soc360",
            "soc360_prod",
            "app_database",
            "production",
            "prod",
            "",
            "   ",
            "contest",
            "mytestdb",
            "testme",
        ],
    )
    def test_name_is_unsafe_without_a_clear_test_token(self, dbname: str) -> None:
        assert _is_safe_database_name(dbname) is False

    @pytest.mark.parametrize("dbname", [None, 123, []])
    def test_non_string_database_names_are_unsafe(self, dbname: object) -> None:
        assert _is_safe_database_name(dbname) is False  # type: ignore[arg-type]

    def test_clean_database_refuses_unsafe_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_clean_database() must bail out before connecting when the DB name is not test-only."""
        monkeypatch.setenv(
            "DATABASE_URL_MIGRATION",
            "postgresql+asyncpg://user:pass@localhost:5432/postgres",
        )
        with pytest.raises(RuntimeError, match="does not look like a disposable test database"):
            _clean_database()
