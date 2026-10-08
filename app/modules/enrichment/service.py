"""Bounded enrichment fan-out with sequential, caller-owned persistence."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import VulnerabilityError
from app.core.llm.providers import LLMProvider, llm_safe_complete
from app.modules.enrichment.prompts import (
    PROMPT_VERSIONS,
    EnrichmentInput,
    build_prompt,
    check_citations,
    functions_for_level,
    input_hash,
)
from app.modules.tenants.models import Tenant
from app.modules.vulnerabilities.enrichment_models import VulnerabilityEnrichment
from app.modules.vulnerabilities.models import Vulnerability

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichmentRunResult:
    succeeded: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]

    @property
    def has_failures(self) -> bool:
        return bool(self.failed)


def due_functions(
    level: str,
    existing_rows_by_function: Mapping[str, VulnerabilityEnrichment],
    *,
    input_hash: str,
    model: str,
    only_functions: Collection[str] | None = None,
) -> tuple[str, ...]:
    """Return scoped functions lacking an identical successful cache entry."""
    due = []
    for function in functions_for_level(level):
        if only_functions is not None and function not in only_functions:
            continue
        row = existing_rows_by_function.get(function)
        if row is not None and (
            row.status == "ok"
            and row.input_hash == input_hash
            and row.prompt_version == PROMPT_VERSIONS[function]
            and row.model == model
        ):
            continue
        due.append(function)
    return tuple(due)


async def enrich_vulnerability(
    session: AsyncSession,
    vulnerability_id: UUID,
    *,
    provider: LLMProvider,
    model: str,
    language: str,
    max_concurrency: int,
    budget_seconds: float,
    only_functions: Collection[str] | None = None,
) -> EnrichmentRunResult:
    """Generate due outputs without sharing the session across concurrent tasks.

    The caller sets tenant context and owns commit/rollback. Budget includes
    semaphore waiting; completed outputs survive cancellation of slower calls.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    if budget_seconds <= 0:
        raise ValueError("budget_seconds must be positive")
    loaded = (await session.execute(
        select(Vulnerability, Tenant.ai_enrichment_level)
        .join(Tenant, Tenant.id == Vulnerability.tenant_id)
        .where(Vulnerability.id == vulnerability_id)
    )).one_or_none()
    if loaded is None:
        raise VulnerabilityError("Vulnerability not found", status_code=404)
    vulnerability, level = loaded
    finding = EnrichmentInput.from_vulnerability(vulnerability)
    digest = input_hash(finding, language)
    existing = {
        row.function: row for row in (await session.scalars(
            select(VulnerabilityEnrichment).where(
                VulnerabilityEnrichment.vulnerability_id == vulnerability_id
            ).execution_options(populate_existing=True)
        )).all()
    }
    targets = tuple(
        function for function in functions_for_level(level)
        if only_functions is None or function in only_functions
    )
    due = due_functions(
        level, existing, input_hash=digest, model=model,
        only_functions=only_functions,
    )
    skipped = tuple(function for function in targets if function not in due)
    # Build before scheduling so invalid prompt arguments fail without partial calls.
    specs = {function: build_prompt(function, finding, language) for function in due}
    semaphore = asyncio.Semaphore(max_concurrency)
    outputs: dict[str, tuple[str, bool]] = {}

    async def complete(function: str) -> None:
        async with semaphore:
            spec = specs[function]
            outputs[function] = await llm_safe_complete(
                provider, spec.user, settings.LLM_MAX_TOKENS,
                settings.LLM_TEMPERATURE, system_prompt=spec.system,
            )

    if due:
        try:
            async with asyncio.timeout(budget_seconds):
                async with asyncio.TaskGroup() as group:
                    for function in due:
                        group.create_task(complete(function))
        except TimeoutError:
            pass

    succeeded: list[str] = []
    failed: list[str] = []
    for function in due:
        content: str | None = None
        error: str | None
        if function not in outputs:
            error = "budget_exceeded"
        else:
            text, provider_failed = outputs[function]
            if provider_failed:
                error = "provider_error"
            elif not text.strip():
                error = "empty_output"
            else:
                error = None
                checked = check_citations(text, finding)
                content = checked.text
                _logger.info(
                    "Enrichment citations removed: function=%s count=%d",
                    function, len(checked.removed),
                )
        status = "ok" if error is None else "failed"
        (succeeded if error is None else failed).append(function)
        stmt = insert(VulnerabilityEnrichment).values(
            vulnerability_id=vulnerability_id,
            tenant_id=vulnerability.tenant_id,
            function=function,
            content=content,
            status=status,
            error=error,
            model=model,
            prompt_version=specs[function].version,
            input_hash=digest,
            attempts=1,
        )
        updates = {
            "status": stmt.excluded.status,
            "error": stmt.excluded.error,
            "model": stmt.excluded.model,
            "prompt_version": stmt.excluded.prompt_version,
            "input_hash": stmt.excluded.input_hash,
            "attempts": VulnerabilityEnrichment.attempts + 1,
            "updated_at": func.now(),
        }
        if error is None:
            updates["content"] = stmt.excluded.content
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["vulnerability_id", "function"], set_=updates,
        ))
    await session.flush()
    return EnrichmentRunResult(tuple(succeeded), tuple(failed), skipped)
