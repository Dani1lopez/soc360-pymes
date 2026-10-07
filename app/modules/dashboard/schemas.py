"""Public dashboard aggregate schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SeverityCounts(BaseModel):
    """Open findings by severity, including zero counts."""

    model_config = ConfigDict(extra="forbid")

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class CoverageMetric(BaseModel):
    """Recent scan coverage of active assets."""

    model_config = ConfigDict(extra="forbid")

    covered: int
    total: int
    ratio: float | None = Field(
        ge=0,
        le=1,
        description="0..1 fraction rounded to 4 decimals; None when total is 0 (no data, not 0 %).",
    )
    since: datetime


class TrendDay(BaseModel):
    """Findings opened and closed on one UTC calendar day."""

    model_config = ConfigDict(extra="forbid")

    day: date
    opened: int
    closed: int


class ScanSuccessMetric(BaseModel):
    """Completed and failed scans within the rolling window."""

    model_config = ConfigDict(extra="forbid")

    completed: int
    failed: int
    ratio: float | None = Field(
        ge=0,
        le=1,
        description="0..1 fraction rounded to 4 decimals; None when completed + failed is 0 (no data, not 0 %).",
    )
    since: datetime


class DashboardSummary(BaseModel):
    """Tenant-scoped dashboard metrics at the database clock time."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    generated_at: datetime
    assets_monitored: int
    open_by_severity: SeverityCounts
    coverage_24h: CoverageMetric
    trend_30d: list[TrendDay]
    scan_success_30d: ScanSuccessMetric
