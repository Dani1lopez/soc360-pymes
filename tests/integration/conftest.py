"""Override session-scoped DB fixture for integration tests.

These integration tests use fakeredis (not real Redis) and mocks (not real DB),
so the autouse prepare_database from tests/conftest.py must be a no-op here.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    # No-op: integration tests use mocks, no PostgreSQL needed
    yield
