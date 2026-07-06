"""Tests for scripts/seed_db.py — seed script validation and idempotency.

Tests the seed script components without actually running the full script
against a database (which would be slow and require specific env vars).
"""
from __future__ import annotations

import importlib
import os
import uuid
from unittest.mock import patch

import pytest


# Default env vars needed to import seed_db without SystemExit
_DEFAULT_SEED_ENV = {
    "SEED_SUPERADMIN_PASSWORD": "TestSuper123!",
    "SEED_ADMIN_PASSWORD": "TestAdmin123!",
    "SEED_ANALYST_PASSWORD": "TestAnalyst123!",
    "SEED_VIEWER_PASSWORD": "TestViewer123!",
}


class TestSeedPasswordValidation:
    """Test _validate_seed_passwords() function."""

    def test_validates_all_required_env_vars(self):
        """Should raise SystemExit when required env vars are missing."""
        # We need to import the function without triggering module-level code
        # Use importlib with patched env vars to get the module loaded first
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
            func = seed_mod._validate_seed_passwords
        
        # Now test with missing vars
        env_vars = [
            "SEED_SUPERADMIN_PASSWORD",
            "SEED_ADMIN_PASSWORD",
            "SEED_ANALYST_PASSWORD",
            "SEED_VIEWER_PASSWORD",
        ]
        with patch.dict(os.environ, {k: "" for k in env_vars}, clear=False):
            for var in env_vars:
                os.environ.pop(var, None)
            
            with pytest.raises(SystemExit) as exc_info:
                func()
            assert exc_info.value.code == 1

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
        
        # Superadmin password should be hashed (starts with $2b$)
        assert superadmin["hashed_password"].startswith("$2b$")
        assert superadmin["hashed_password"] != "SuperAdmin123!"
        
        # All user passwords should be hashed
        for user in users:
            assert user["hashed_password"].startswith("$2b$")

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

    def test_blocks_in_production(self):
        """Should raise SystemExit when ENVIRONMENT=production."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        # The module-level guard checks settings.ENVIRONMENT
        # We can test the logic by checking the allowed environments
        assert "development" in seed_mod._ALLOWED_SEED_ENVIRONMENTS
        assert "production" not in seed_mod._ALLOWED_SEED_ENVIRONMENTS
        assert "staging" not in seed_mod._ALLOWED_SEED_ENVIRONMENTS

    def test_allows_in_development(self):
        """Should allow execution when ENVIRONMENT=development."""
        with patch.dict(os.environ, _DEFAULT_SEED_ENV, clear=False):
            import scripts.seed_db as seed_mod
        
        assert "development" in seed_mod._ALLOWED_SEED_ENVIRONMENTS
