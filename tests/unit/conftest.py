from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    """Override tests/conftest.py prepare_database — no-op for unit tests."""
    pass
