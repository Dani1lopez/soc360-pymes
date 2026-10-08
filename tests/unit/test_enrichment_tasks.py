"""Broker-free contracts for bounded vulnerability enrichment tasks."""
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from celery.exceptions import Retry
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.exceptions import VulnerabilityError
from app.core.llm import factory
from app.modules.enrichment.service import EnrichmentRunResult
from app.worker.celery_app import celery_app
from tests.unit.test_config_redis_auth import _REQUIRED


def test_enrichment_settings_defaults_and_languages(monkeypatch):
    from app.modules.enrichment.prompts import SUPPORTED_LANGUAGES

    for field in ("ENRICHMENT_ENABLED", "ENRICHMENT_LANGUAGE", "ENRICHMENT_MAX_CONCURRENCY", "ENRICHMENT_BUDGET_SECONDS"):
        monkeypatch.delenv(field, raising=False)
    config = Settings(_env_file=None, **_REQUIRED)
    assert config.ENRICHMENT_ENABLED is False
    assert config.ENRICHMENT_LANGUAGE == "en"
    assert config.ENRICHMENT_MAX_CONCURRENCY == 3
    assert config.ENRICHMENT_BUDGET_SECONDS == 120
    for language in SUPPORTED_LANGUAGES:
        assert Settings(_env_file=None, ENRICHMENT_LANGUAGE=language, **_REQUIRED).ENRICHMENT_LANGUAGE == language


@pytest.mark.parametrize(("field", "value"), [
    ("ENRICHMENT_LANGUAGE", "unsupported"),
    ("ENRICHMENT_MAX_CONCURRENCY", 0),
    ("ENRICHMENT_BUDGET_SECONDS", 0),
])
def test_invalid_enrichment_settings(field, value):
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **_REQUIRED, **{field: value})


@pytest.fixture
def worker():
    return import_module("app.worker.enrichment_tasks")


def test_retry_countdown(worker):
    assert [worker.retry_countdown(i) for i in range(3)] == [30, 60, 120]


def test_limits_and_loader_registration(worker):
    celery_app.loader.import_default_modules()
    task = celery_app.tasks["enrichment.vulnerability"]
    budget = settings.ENRICHMENT_BUDGET_SECONDS
    assert task.soft_time_limit == budget + 30
    assert task.time_limit == budget + 60
    assert budget < task.soft_time_limit < task.time_limit
    assert task.ignore_result is True
    assert "app.worker.enrichment_tasks" in celery_app.conf.include


def test_disabled_short_circuits(worker, monkeypatch):
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", False)
    run = AsyncMock(side_effect=AssertionError("disabled task accessed dependencies"))
    monkeypatch.setattr(worker, "_enrich", run)
    celery_app.tasks["enrichment.vulnerability"].run(str(uuid4()), str(uuid4()))
    run.assert_not_called()


@pytest.mark.parametrize("retries", [0, 1, 2, 3])
def test_partial_failure_retry(worker, monkeypatch, retries):
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)
    task = celery_app.tasks["enrichment.vulnerability"]
    result = EnrichmentRunResult((), ("summary",), ())
    run = AsyncMock(return_value=result)
    monkeypatch.setattr(worker, "_enrich", run)
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(task, "retry", retry)
    task.push_request(retries=retries)
    try:
        if retries < 3:
            with pytest.raises(Retry):
                task.run("vulnerability", "tenant", ["summary"])
            assert retry.call_args.kwargs["countdown"] == 30 * 2**retries
        else:
            task.run("vulnerability", "tenant", ["summary"])
            retry.assert_not_called()
        run.assert_awaited_once_with("vulnerability", "tenant", ["summary"])
    finally:
        task.pop_request()


@pytest.mark.parametrize("retries", [0, 3])
def test_unexpected_error_retries_then_raises(worker, monkeypatch, retries):
    # A transient DB or provider-construction error must not drop the enrichment.
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)
    task = celery_app.tasks["enrichment.vulnerability"]
    boom = ConnectionError("database unavailable")
    monkeypatch.setattr(worker, "_enrich", AsyncMock(side_effect=boom))
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(task, "retry", retry)
    task.push_request(retries=retries)
    try:
        if retries < 3:
            with pytest.raises(Retry):
                task.run("vulnerability", "tenant")
            assert retry.call_args.kwargs["exc"] is boom
            assert retry.call_args.kwargs["countdown"] == 30
        else:
            with pytest.raises(ConnectionError):
                task.run("vulnerability", "tenant")
            retry.assert_not_called()
    finally:
        task.pop_request()


@pytest.mark.parametrize("result", [None, EnrichmentRunResult(("summary",), (), ())])
def test_terminal_result_does_not_retry(worker, monkeypatch, result):
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(worker, "_enrich", AsyncMock(return_value=result))
    task = celery_app.tasks["enrichment.vulnerability"]
    retry = MagicMock(side_effect=AssertionError("terminal result retried"))
    monkeypatch.setattr(task, "retry", retry)
    task.run(str(uuid4()), str(uuid4()))
    retry.assert_not_called()


async def test_missing_vulnerability_is_not_retried(worker, monkeypatch):
    engine = MagicMock(dispose=AsyncMock())
    session = MagicMock(commit=AsyncMock())
    context = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(worker, "async_sessionmaker", MagicMock(return_value=MagicMock(return_value=context)))
    tenant_context = AsyncMock()
    monkeypatch.setattr(worker, "set_tenant_context", tenant_context)
    monkeypatch.setattr(worker, "enrich_vulnerability", AsyncMock(side_effect=VulnerabilityError("Missing", status_code=404)))
    tenant_id = uuid4()
    assert await worker._enrich(str(uuid4()), str(tenant_id), None, engine_factory=lambda: engine, provider_factory=MagicMock(), model_name=lambda: "test-model") is None
    tenant_context.assert_awaited_once_with(session, tenant_id, False)
    session.commit.assert_not_awaited()
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize("configured", [None, "explicit-model"])
def test_model_name_matches_provider_construction(monkeypatch, configured):
    monkeypatch.setattr(factory, "settings", SimpleNamespace(LLM_PROVIDER="ollama", OLLAMA_MODEL=configured, OLLAMA_URL="http://localhost:11434", LLM_TIMEOUT=30))
    factory._register_providers()
    constructor = MagicMock()
    entry = factory._PROVIDER_REGISTRY["ollama"]
    from dataclasses import replace
    monkeypatch.setitem(factory._PROVIDER_REGISTRY, "ollama", replace(entry, cls=constructor))
    factory._create_provider("ollama")
    assert factory.get_llm_model_name() == constructor.call_args.kwargs["model"]
    assert factory.get_llm_model_name() == (configured or entry.model_default)
