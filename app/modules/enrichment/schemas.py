"""Public enrichment response whitelists."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EnrichmentItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    function: str
    status: Literal["ok", "failed", "pending", "missing"]
    content: str | None = None
    error: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    attempts: int = 0
    updated_at: datetime | None = None


class VulnerabilityEnrichmentRead(BaseModel):
    vulnerability_id: UUID
    level: str
    items: list[EnrichmentItemRead]


class EnrichmentQueued(BaseModel):
    queued: int


class ScanEnrichmentQueued(EnrichmentQueued):
    total: int
