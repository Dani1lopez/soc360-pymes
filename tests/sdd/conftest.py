import pytest


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    """No-op override of the root DB fixture for packaging-only contract tests."""
    yield
