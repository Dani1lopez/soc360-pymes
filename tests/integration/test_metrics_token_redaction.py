"""Spec #6: 100-concurrent scrape smoke + no credential leak.

Integration test that hits ``/metrics`` 100 times concurrently with a valid
token and asserts:

1. All 100 requests return 200 with ``text/plain; version=0.0.4``.
2. No ``METRICS_TOKEN`` substring in ``caplog`` or response bodies.
3. No metric values that would expose the token.

Run with ``--noconftest`` to skip the integration DB conftest (the test
exercises only Prometheus multiprocess + ``app.main`` — no PostgreSQL/Redis
required, since the ``/metrics`` route is read-only and the auth token is
held in module-level settings).

The module-level env-var priming is required because the file is run with
``--noconftest`` (which skips ``tests/conftest.py`` and its
env-var priming block). Without these, the
``from app.main import create_app`` import below would fail because
``app.core.config.settings = Settings()`` runs at module load.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

# Env-var priming (must precede the app.main import below).
os.environ.setdefault("ENVIRONMENT", "development")

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from tests/.env (dependency-free).

    This module is also run with ``--noconftest``, so it cannot rely on
    ``tests/conftest.py`` priming the environment. Blank lines and ``#``
    comments are ignored; surrounding quotes are stripped; real environment
    variables always win via ``os.environ.setdefault``.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_env_file(_ENV_FILE)
os.environ.setdefault("POSTGRES_USER", "soc360_app")
os.environ.setdefault("POSTGRES_DB", "soc360_test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "15")
os.environ.setdefault("REDIS_PASSWORD", "soc360_redis_dev_password")

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core import metrics_auth
from app.core.config import settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _install_token(monkeypatch: pytest.MonkeyPatch):
    """Install a known token and clear the encoded-bytes cache.

    Restores the singleton ``settings.METRICS_TOKEN`` on teardown via
    ``monkeypatch`` and re-clears the caches so the next test starts clean.
    """
    monkeypatch.setattr(settings, "METRICS_TOKEN", SecretStr("test-token-correct"))
    monkeypatch.setattr(settings, "METRICS_TOKEN_PREVIOUS", None)
    metrics_auth._current_bytes.cache_clear()
    metrics_auth._previous_bytes.cache_clear()
    yield
    metrics_auth._current_bytes.cache_clear()
    metrics_auth._previous_bytes.cache_clear()


@pytest.mark.asyncio
async def test_100_concurrent_no_credential_leak(
    caplog: pytest.LogCaptureFixture,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec #6: 100 concurrent ``/metrics`` requests with valid token, no leak."""
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    app = create_app()
    token = "test-token-correct"

    async def _hit(client: AsyncClient) -> int:
        response = await client.get("/metrics", headers={"x-metrics-token": token})
        return response.status_code

    with caplog.at_level("DEBUG"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            statuses = await asyncio.gather(*[_hit(client) for _ in range(100)])

    assert all(s == 200 for s in statuses), f"Expected all 200, got {set(statuses)}"
    # No token material in logs.
    full_log = caplog.text
    assert token not in full_log, f"Token leaked in logs: {full_log!r}"


@pytest.mark.asyncio
async def test_100_concurrent_unauthorized_no_token_leak(
    caplog: pytest.LogCaptureFixture,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec #6 (negative): 100 concurrent ``/metrics`` requests with no token, no 500, no leak."""
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    app = create_app()

    async def _hit(client: AsyncClient) -> int:
        response = await client.get("/metrics")
        return response.status_code

    with caplog.at_level("DEBUG"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            statuses = await asyncio.gather(*[_hit(client) for _ in range(100)])

    assert all(s == 401 for s in statuses), f"Expected all 401, got {set(statuses)}"
    full_log = caplog.text
    assert "test-token-correct" not in full_log, f"Token leaked in logs: {full_log!r}"
