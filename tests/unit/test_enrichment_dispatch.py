"""Best-effort enrichment publishing never leaks broker failures."""
from importlib import import_module
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.worker.celery_app import celery_app


@pytest.mark.parametrize("outcome", ["success", "error", "timeout", "disabled"])
async def test_enqueue_enrichment(monkeypatch, outcome):
    dispatch = import_module("app.modules.enrichment.dispatch")
    import_module("app.worker.enrichment_tasks")
    publish = MagicMock(side_effect=RuntimeError("broker unavailable") if outcome == "error" else None)
    monkeypatch.setattr(celery_app.tasks["enrichment.vulnerability"], "apply_async", publish)
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", outcome != "disabled")
    if outcome == "timeout":
        async def timeout(awaitable, *, timeout):
            assert timeout == 3
            awaitable.close()
            raise TimeoutError
        monkeypatch.setattr(dispatch.asyncio, "wait_for", timeout)
    result = await dispatch.enqueue_enrichment("vulnerability", "tenant", ["summary"])
    assert result is (outcome == "success")
    if outcome in {"disabled", "timeout"}:
        publish.assert_not_called()
    else:
        publish.assert_called_once()
        assert publish.call_args.kwargs["args"] == ["vulnerability", "tenant", ["summary"]]
        assert publish.call_args.kwargs["queue"] == "enrichment"
        assert publish.call_args.kwargs["retry_policy"]["max_retries"] == 2
