"""Bounded, retryable enrichment in a fresh worker event loop."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from uuid import UUID

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings
from app.core.database import set_tenant_context
from app.core.exceptions import VulnerabilityError
from app.core.llm.factory import get_llm_model_name, get_llm_provider
from app.core.llm.providers import LLMProvider
from app.modules.enrichment.service import EnrichmentRunResult, enrich_vulnerability
from app.worker.celery_app import celery_app
from app.worker.tasks import build_task_engine

logger = logging.getLogger(__name__)


def retry_countdown(retries: int) -> int:
    return 30 * 2**retries


async def _enrich(
    vulnerability_id: str,
    tenant_id: str,
    only_functions: list[str] | None,
    *,
    engine_factory: Callable[[], AsyncEngine] = build_task_engine,
    provider_factory: Callable[[], LLMProvider] = get_llm_provider,
    model_name: Callable[[], str] = get_llm_model_name,
) -> EnrichmentRunResult | None:
    engine = engine_factory()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await set_tenant_context(session, UUID(tenant_id), False)
            try:
                result = await enrich_vulnerability(
                    session, UUID(vulnerability_id), provider=provider_factory(),
                    model=model_name(), language=settings.ENRICHMENT_LANGUAGE,
                    max_concurrency=settings.ENRICHMENT_MAX_CONCURRENCY,
                    budget_seconds=settings.ENRICHMENT_BUDGET_SECONDS,
                    only_functions=only_functions,
                )
            except VulnerabilityError as exc:
                if exc.status_code != 404:
                    raise
                logger.info("Vulnerability missing; enrichment ignored")
                return None
            await session.commit()
            return result
    finally:
        await engine.dispose()


@celery_app.task(
    name="enrichment.vulnerability", bind=True, ignore_result=True,
    max_retries=3,
    soft_time_limit=settings.ENRICHMENT_BUDGET_SECONDS + 30,
    time_limit=settings.ENRICHMENT_BUDGET_SECONDS + 60,
)
def enrich(
    self: Task,
    vulnerability_id: str,
    tenant_id: str,
    only_functions: list[str] | None = None,
) -> None:
    if not settings.ENRICHMENT_ENABLED:
        return
    result = asyncio.run(_enrich(vulnerability_id, tenant_id, only_functions))
    if result is not None and result.has_failures and self.request.retries < 3:
        raise self.retry(countdown=retry_countdown(self.request.retries))
