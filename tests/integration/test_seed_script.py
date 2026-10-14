"""Tests for scripts/seed_db.py — seed script validation and idempotency.

Tests the seed script components without actually running the full script
against a database (which would be slow and require specific env vars).
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]


class TestSeedScriptRunsAsItsOwnEntryPoint:
    """The script must work when it is the only entry point.

    Every other test in this file imports the module inside the pytest process,
    where earlier imports have already populated SQLAlchemy's mapper registry. A
    missing model import therefore stayed invisible: it only broke when the
    script ran on its own, which is exactly what the container does.

    ``configure_mappers()`` is the step that resolves those string relationship
    names, and it needs no database connection.
    """

    def test_mappers_configure_in_a_fresh_interpreter(self) -> None:
        env = dict(os.environ)
        env.update(_DEFAULT_SEED_ENV)
        env["ENVIRONMENT"] = "development"

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import scripts.seed_db; "
                "from sqlalchemy.orm import configure_mappers; "
                "configure_mappers(); "
                "print('mappers configured')",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        assert "mappers configured" in result.stdout


# Default env vars needed to import seed_db without SystemExit
_DEFAULT_SEED_ENV = {
    "SEED_SUPERADMIN_PASSWORD": "TestSuper123!",
    "SEED_ADMIN_PASSWORD": "TestAdmin123!",
    "SEED_ANALYST_PASSWORD": "TestAnalyst123!",
    "SEED_VIEWER_PASSWORD": "TestViewer123!",
}


class TestSeedPasswordValidation:
    """Test _validate_seed_passwords() function."""

    @pytest.mark.parametrize("missing_var", sorted(_DEFAULT_SEED_ENV))
    @pytest.mark.parametrize("value", [None, ""])
    def test_rejects_a_single_missing_or_empty_variable(self, missing_var, value, capsys):
        """Each variable is required on its own, and an empty value counts as missing."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
            func = seed_mod._validate_seed_passwords

        env = dict(_DEFAULT_SEED_ENV)
        with patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop(missing_var)
            else:
                os.environ[missing_var] = value
            with pytest.raises(SystemExit) as exc_info:
                func()

        assert exc_info.value.code == 1
        assert missing_var in capsys.readouterr().out

    def test_passes_when_all_env_vars_set(self):
        """Should not raise when all required env vars are set."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
            func = seed_mod._validate_seed_passwords
        
        # Should not raise with all vars set
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            func()


class TestSeedDataBuilder:
    """Test _build_seed_data() function."""

    def test_returns_tenant_superadmin_and_users(self):
        """Should return tenant, superadmin, and list of tenant users."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
            tenant, superadmin, users = seed_mod._build_seed_data()
        
        # Tenant
        assert tenant["slug"] == "acme-corp"
        assert tenant["is_active"] is True
        
        # Superadmin
        assert superadmin["email"] == "superadmin@soc360.local"
        assert superadmin["role"] == "superadmin"
        assert superadmin["is_superadmin"] is True
        assert superadmin["tenant_id"] is None
        
        # Tenant users
        assert len(users) == 3
        roles = {u["role"] for u in users}
        assert roles == {"admin", "analyst", "viewer"}

    def test_passwords_are_hashed(self):
        """Passwords should be bcrypt hashed, not plaintext."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
            tenant, superadmin, users = seed_mod._build_seed_data()
        
        configured = set(_DEFAULT_SEED_ENV.values())
        for user in [superadmin, *users]:
            assert user["hashed_password"].startswith("$2b$")
            assert user["hashed_password"] not in configured

    def test_uuids_are_deterministic(self):
        """Seed UUIDs should be fixed for test reproducibility."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        # Should be valid UUIDs
        assert isinstance(seed_mod.SEED_TENANT_ID, uuid.UUID)
        assert isinstance(seed_mod.SEED_SUPERADMIN_ID, uuid.UUID)
        assert isinstance(seed_mod.SEED_ADMIN_ID, uuid.UUID)
        assert isinstance(seed_mod.SEED_ANALYST_ID, uuid.UUID)
        assert isinstance(seed_mod.SEED_VIEWER_ID, uuid.UUID)
        
        # Should be deterministic (same value every run)
        assert str(seed_mod.SEED_TENANT_ID) == "00000000-0000-0000-0000-000000000001"
        assert str(seed_mod.SEED_SUPERADMIN_ID) == "00000000-0000-0000-0000-000000000010"

    def test_seeded_users_have_distinct_ids(self):
        """A shared primary key would silently drop one seeded user."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod

        ids = [
            seed_mod.SEED_SUPERADMIN_ID,
            seed_mod.SEED_ADMIN_ID,
            seed_mod.SEED_ANALYST_ID,
            seed_mod.SEED_VIEWER_ID,
        ]
        assert len(set(ids)) == len(ids)


class TestSeedStats:
    """Test SeedStats dataclass."""

    def test_initial_state(self):
        """Should start with zero counts."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        stats = seed_mod.SeedStats()
        assert stats.created == 0
        assert stats.skipped == 0
        assert stats.errors == 0
        assert stats.details == []

    def test_record_created(self):
        """Should increment created count and add detail."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        stats = seed_mod.SeedStats()
        stats.record_created("Tenant 'acme'")
        
        assert stats.created == 1
        assert stats.skipped == 0
        assert stats.errors == 0
        assert len(stats.details) == 1
        assert "acme" in stats.details[0]

    def test_record_skipped(self):
        """Should increment skipped count."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        stats = seed_mod.SeedStats()
        stats.record_skipped("User 'admin@test.com'")
        
        assert stats.created == 0
        assert stats.skipped == 1
        assert len(stats.details) == 1

    def test_record_error(self):
        """Should increment error count and include reason."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        stats = seed_mod.SeedStats()
        stats.record_error("User 'bad@test.com'", "duplicate key")
        
        assert stats.created == 0
        assert stats.skipped == 0
        assert stats.errors == 1
        assert "duplicate key" in stats.details[0]


class TestEnvironmentGuard:
    """Test that seed script blocks execution outside development."""

    @staticmethod
    def _reload_with_environment(environment: str) -> None:
        import scripts.seed_db as seed_mod
        from app.core.config import settings

        with (
            patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False),
            patch.object(settings, "ENVIRONMENT", environment),
        ):
            importlib.reload(seed_mod)

    @pytest.mark.parametrize("environment", ["production", "staging"])
    def test_blocks_outside_development(self, environment):
        """Importing the script must exit when ENVIRONMENT is not development."""
        try:
            with pytest.raises(SystemExit) as exc_info:
                self._reload_with_environment(environment)
            assert exc_info.value.code == 1
        finally:
            self._reload_with_environment("development")

    def test_allows_in_development(self):
        """Importing the script succeeds when ENVIRONMENT=development."""
        self._reload_with_environment("development")
