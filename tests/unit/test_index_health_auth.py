from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main
from app.core import metrics_auth


def test_index_health_rejects_previous_only_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(main.settings, "METRICS_TOKEN", None)
            patch.setattr(
                main.settings, "METRICS_TOKEN_PREVIOUS", SecretStr("previous")
            )
            patch.setattr(main, "engine", engine)
            response = TestClient(main.create_app()).get(
                "/health/db/indexes", headers={"x-metrics-token": "previous"}
            )
            assert (response.status_code, response.json()) == (
                401,
                {"detail": "unauthorized"},
            )
            engine.execution_options.assert_not_called()
    finally:
        metrics_auth._current_bytes.cache_clear()
        metrics_auth._previous_bytes.cache_clear()
