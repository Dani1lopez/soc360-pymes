"""Report service: module-level async functions implementing the Reports CRUD.

Follows the same shape as ``app.modules.vulnerabilities.service``: standalone
``async def`` functions that take ``AsyncSession`` and ``EventBus`` explicitly,
with no class holding mutable state.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fpdf import FPDF
from fpdf.enums import TableCellFillMode
from fpdf.fonts import FontFace
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.event_bus import EventBus
from app.event_schemas import ReportCreatedEvent, ReportDeletedEvent, ReportUpdatedEvent
from app.modules.assets.models import Asset
from app.modules.reports.models import Report
from app.modules.reports.schemas import (
    ReportCreate,
    ReportStatus,
    ReportType,
    ReportUpdate,
)
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability

__all__ = [
    "REPORT_EVENTS_STREAM",
    "ReportAssetNotFoundError",
    "ReportDownloadFormat",
    "ReportExport",
    "build_report_export",
    "create_report",
    "delete_report",
    "get_report",
    "list_reports",
    "render_report_export",
    "sanitize_download_filename",
    "update_report",
]

ReportDownloadFormat = Literal["md", "json", "pdf"]

_SEVERITY_ORDER: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
_SEVERITY_RANK: dict[str, int] = {
    sev: idx for idx, sev in enumerate(_SEVERITY_ORDER)
}
_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class ReportExport:
    """Rendered report artifact ready to send as an HTTP attachment."""

    content: str | bytes
    media_type: str
    filename: str

REPORT_EVENTS_STREAM: Literal["report.events"] = "report.events"

# The composite FK guarding the report/asset relationship; its flush-time
# violation is the deleted-asset race.
_ASSET_FK_CONSTRAINT = "fk_reports_asset_tenant"

# Public PATCH fields, in the fixed order ``changed_fields`` reports them.
_UPDATABLE_FIELDS = ("name", "status", "summary", "report_metadata", "generated_at")


class ReportAssetNotFoundError(Exception):
    """Raised when the report's asset disappeared between resolution and INSERT.

    The router maps this to HTTP 404 with the same ``report asset not found``
    detail as the pre-INSERT path, so the two 404s are indistinguishable to
    the caller.
    """

    def __init__(self, message: str = "report asset not found") -> None:
        super().__init__(message)


def _add_tenant_predicate(stmt: Any, tenant_id: uuid.UUID | None) -> Any:
    """Apply the tenant predicate unless ``tenant_id`` is None.

    ``None`` is reserved for the deliberately global superadmin path. For any
    other caller it would silently widen the query, so the router must only
    pass None for a superadmin.
    """
    if tenant_id is not None:
        return stmt.where(Report.tenant_id == tenant_id)
    return stmt


def _violates_constraint(exc: IntegrityError, constraint_name: str) -> bool:
    """Detect a named-constraint violation across drivers.

    Inspects the driver's constraint name first (asyncpg exposes it on the
    exception, psycopg on ``diag``) and falls back to the driver message.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False

    name = getattr(orig, "constraint_name", None)
    if not name:
        diag = getattr(orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
    if name and constraint_name in str(name):
        return True

    return constraint_name in str(orig)


def _is_asset_fk_violation(exc: IntegrityError) -> bool:
    """Detect an fk_reports_asset_tenant violation across drivers."""
    return _violates_constraint(exc, _ASSET_FK_CONSTRAINT)


async def create_report(
    data: ReportCreate,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Report:
    """Create a new report; persist then publish ``report.created``.

    Ordering guarantee: INSERT + flush (the asset FK fires here) -> commit ->
    publish, so a failed commit publishes nothing and a Redis failure after
    commit cannot roll back the persisted row. Tenant-scoping rule: the row
    always carries the caller's ``tenant_id`` (creation is never global), and
    the lifecycle is forced server-side to ``"pending"`` with no
    ``generated_at``, whatever the client sent.
    """
    report = Report(
        tenant_id=tenant_id,
        asset_id=data.asset_id,
        name=data.name,
        report_type=data.report_type,
        status="pending",
        summary=data.summary,
        report_metadata=data.report_metadata,
        generated_at=None,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_asset_fk_violation(exc):
            raise ReportAssetNotFoundError("report asset not found") from exc
        raise

    await db.commit()

    # Capture-after-flush / publish-after-commit: the snapshot is read from
    # the flushed row and only sent once commit succeeded.
    event = ReportCreatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        report_id=report.id,
        asset_id=report.asset_id,
        name=report.name,
        report_type=report.report_type,
        status=report.status,
        created_at=report.created_at,
    )
    await event_bus.publish(event, stream=REPORT_EVENTS_STREAM)
    return report


async def get_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> Report | None:
    """Return the report or None.

    Ordering guarantee: a single SELECT, no flush, no commit, no events.
    Tenant-scoping rule: when ``tenant_id`` is not None the predicate
    ``Report.tenant_id == tenant_id`` is added explicitly (the database RLS
    policy is a second layer, not a substitute); ``None`` is the deliberately
    global superadmin path and adds no predicate.
    """
    stmt = _add_tenant_predicate(
        select(Report).where(Report.id == report_id), tenant_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_reports(
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    asset_id: uuid.UUID | None = None,
    report_type: ReportType | None = None,
    status: ReportStatus | None = None,
) -> tuple[Sequence[Report], int]:
    """Return ``(items, total)`` ordered by ``created_at DESC, id DESC``.

    Ordering guarantee: the count query runs first, then the items query with
    a deterministic ``created_at DESC, id DESC`` order plus offset/limit.
    Tenant-scoping rule: ``Report.tenant_id == tenant_id`` is added to both
    queries when ``tenant_id`` is not None; ``None`` is the superadmin path.
    Every optional filter is applied to BOTH the count and the items query,
    so the page metadata can never disagree with the items it describes.
    """
    filters = []
    if asset_id is not None:
        filters.append(Report.asset_id == asset_id)
    if report_type is not None:
        filters.append(Report.report_type == report_type)
    if status is not None:
        filters.append(Report.status == status)

    base_stmt = _add_tenant_predicate(select(Report), tenant_id).where(*filters)
    count_stmt = _add_tenant_predicate(
        select(func.count()).select_from(Report),
        tenant_id,
    ).where(*filters)

    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = (
        base_stmt.order_by(Report.created_at.desc(), Report.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(items_stmt)).scalars().all()
    return items, int(total or 0)


async def update_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    data: ReportUpdate,
    db: AsyncSession,
    event_bus: EventBus,
) -> Report | None:
    """Apply a partial update; return the updated report or None.

    Ordering guarantee: flush, commit, and only after a successful commit is
    ``report.updated`` published. Tenant-scoping rule: the row is fetched
    through the explicit ``Report.tenant_id == tenant_id`` predicate unless
    ``tenant_id`` is None (superadmin path); an invisible report yields
    ``None`` and publishes nothing.

    ``changed_fields`` lists only public fields whose value actually changed,
    in the fixed order ``name``, ``status``, ``summary``, ``report_metadata``,
    ``generated_at``. When it is empty the flush and commit still run, but
    nothing is published.
    """
    stmt = _add_tenant_predicate(
        select(Report).where(Report.id == report_id), tenant_id
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if report is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    changed_fields: list[str] = []
    for field in _UPDATABLE_FIELDS:
        if field in update_data and update_data[field] != getattr(report, field):
            setattr(report, field, update_data[field])
            changed_fields.append(field)

    await db.flush()
    await db.commit()

    # Nothing public changed: no event.
    if not changed_fields:
        return report

    event = ReportUpdatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=report.tenant_id,
        report_id=report.id,
        changed_fields=changed_fields,
    )
    await event_bus.publish(event, stream=REPORT_EVENTS_STREAM)
    return report


async def delete_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    event_bus: EventBus,
) -> bool:
    """Delete the report (tenant-scoped); return True on success, False on miss.

    Ordering guarantee: ``db.delete`` then ``commit``, and only after commit
    succeeds is ``report.deleted`` published with the id and tenant captured
    BEFORE the delete. Tenant-scoping rule: the visibility SELECT carries the
    explicit ``Report.tenant_id == tenant_id`` predicate unless ``tenant_id``
    is None (superadmin path); an invisible report yields False and
    publishes nothing.
    """
    stmt = _add_tenant_predicate(
        select(Report).where(Report.id == report_id), tenant_id
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if report is None:
        return False

    captured_id = report.id
    captured_tenant = report.tenant_id

    await db.delete(report)
    await db.commit()

    event = ReportDeletedEvent(
        event_id=uuid.uuid4(),
        tenant_id=captured_tenant,
        report_id=captured_id,
    )
    await event_bus.publish(event, stream=REPORT_EVENTS_STREAM)
    return True


def sanitize_download_filename(
    name: str, report_id: uuid.UUID, fmt: ReportDownloadFormat
) -> str:
    """Return a header-safe attachment filename derived from ``name``."""
    slug = _FILENAME_UNSAFE_RE.sub("-", name).strip("-_")[:64]
    if not slug:
        slug = str(report_id)[:8]
    return f"report-{slug}.{fmt}"


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _escape_md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _pdf_text(value: str) -> str:
    """Keep text within Latin-1 for PDF core fonts without raising on Unicode."""
    return value.encode("latin-1", "replace").decode("latin-1")


_NAVY = (15, 23, 42)
_SLATE = (30, 41, 59)
_ACCENT = (56, 189, 248)
_MUTED = (100, 116, 139)
_BORDER = (203, 213, 225)
_SURFACE = (248, 250, 252)
_WHITE = (255, 255, 255)

_SEVERITY_COLORS: dict[str, tuple[int, int, int]] = {
    "critical": (185, 28, 28),
    "high": (194, 65, 12),
    "medium": (180, 83, 9),
    "low": (29, 78, 216),
    "info": (71, 85, 105),
}

_SEVERITY_LABELS: dict[str, str] = {
    "critical": "Critica",
    "high": "Alta",
    "medium": "Media",
    "low": "Baja",
    "info": "Info",
}

_REPORT_TYPE_LABELS: dict[str, str] = {
    "vulnerability": "Vulnerabilidades",
    "executive": "Ejecutivo",
    "technical": "Tecnico",
    "compliance": "Cumplimiento",
}

_REPORT_STATUS_LABELS: dict[str, str] = {
    "pending": "Pendiente",
    "generating": "Generando",
    "completed": "Completado",
    "failed": "Fallido",
}


class _CorporateReportPDF(FPDF):
    """Branded SOC360 PyMEs PDF layout with header and page numbers."""

    def __init__(self, report_type_label: str) -> None:
        super().__init__()
        self._report_type_label = report_type_label
        self.alias_nb_pages()
        self.set_margins(15, 26, 15)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        self.set_fill_color(*_NAVY)
        self.rect(0, 0, self.w, 18, style="F")
        self.set_fill_color(*_ACCENT)
        self.rect(0, 18, self.w, 1.2, style="F")
        self.set_xy(15, 5)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*_WHITE)
        self.cell(90, 8, "SOC360 PyMEs", border=0)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(203, 213, 225)
        self.cell(
            self.w - 30 - 90,
            8,
            _pdf_text(f"Informe de seguridad  |  {self._report_type_label}"),
            border=0,
            align="R",
        )
        self.set_y(24)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*_BORDER)
        self.line(15, self.get_y(), self.w - 15, self.get_y())
        self.ln(2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_MUTED)
        self.cell(
            (self.w - 30) / 2,
            6,
            "SOC360 PyMEs  -  Documento generado automaticamente",
            border=0,
        )
        self.cell(
            (self.w - 30) / 2,
            6,
            f"Pagina {self.page_no()} / {{nb}}",
            border=0,
            align="R",
        )


def _pdf_section_heading(pdf: FPDF, title: str) -> None:
    pdf.ln(5)
    y = pdf.get_y()
    pdf.set_fill_color(*_ACCENT)
    pdf.rect(15, y + 1, 2.5, 6, style="F")
    pdf.set_x(20)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 8, _pdf_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _format_pdf_timestamp(value: str | None) -> str:
    if not value:
        return "N/A"
    return value.replace("T", " ")[:19] + " UTC"


def _render_pdf(payload: dict[str, Any]) -> bytes:
    """Render the public report payload as a structured corporate PDF."""
    report = payload["report"]
    asset = payload["asset"]
    counts = payload["summary_counts"]
    scans = payload["scans"]
    vulns = payload["vulnerabilities"]

    type_label = _REPORT_TYPE_LABELS.get(report["report_type"], report["report_type"])
    status_label = _REPORT_STATUS_LABELS.get(report["status"], report["status"])

    pdf = _CorporateReportPDF(type_label)
    pdf.add_page()
    content_width = pdf.w - 30

    # Title block
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*_NAVY)
    pdf.multi_cell(0, 9, _pdf_text(report["name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Metadata card
    asset_label = (
        f"{asset['value']} ({asset['asset_type']})" if asset is not None else "N/A"
    )
    meta_rows = [
        ("Activo", asset_label, "Tipo de informe", type_label),
        ("Estado", status_label, "ID de informe", str(report["id"])[:8] + "..."),
        (
            "Generado",
            _format_pdf_timestamp(report["generated_at"]),
            "Creado",
            _format_pdf_timestamp(report["created_at"]),
        ),
    ]
    box_y = pdf.get_y()
    row_h = 7
    box_h = len(meta_rows) * row_h + 6
    pdf.set_fill_color(*_SURFACE)
    pdf.set_draw_color(*_BORDER)
    pdf.rect(15, box_y, content_width, box_h, style="DF")
    pdf.set_xy(18, box_y + 3)
    col_label = 30
    col_val = (content_width - 6) / 2 - col_label
    for left_k, left_v, right_k, right_v in meta_rows:
        pdf.set_x(18)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_label, row_h, _pdf_text(f"{left_k}:"), border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(col_val, row_h, _pdf_text(left_v[:36]), border=0)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_label, row_h, _pdf_text(f"{right_k}:"), border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_NAVY)
        pdf.cell(col_val, row_h, _pdf_text(right_v[:36]), border=0, new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(box_y + box_h + 2)

    # Executive summary
    if report["summary"]:
        _pdf_section_heading(pdf, "Resumen ejecutivo")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_SLATE)
        pdf.multi_cell(
            0, 5.5, _pdf_text(str(report["summary"])), new_x="LMARGIN", new_y="NEXT"
        )

    # KPI severity cards
    _pdf_section_heading(pdf, "Indicadores de riesgo")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(*_SLATE)
    pdf.multi_cell(
        0,
        5.5,
        _pdf_text(
            f"Escaneos analizados: {counts['total_scans']}   |   "
            f"Vulnerabilidades totales: {counts['total_vulnerabilities']}   |   "
            f"Abiertas: {counts['open_vulnerabilities']}"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    by_sev = counts["by_severity"]
    gap = 3
    card_w = (content_width - gap * (len(_SEVERITY_ORDER) - 1)) / len(_SEVERITY_ORDER)
    card_h = 18
    cards_y = pdf.get_y()
    for idx, sev in enumerate(_SEVERITY_ORDER):
        x = 15 + idx * (card_w + gap)
        color = _SEVERITY_COLORS[sev]
        pdf.set_fill_color(*_SURFACE)
        pdf.set_draw_color(*_BORDER)
        pdf.rect(x, cards_y, card_w, card_h, style="DF")
        pdf.set_fill_color(*color)
        pdf.rect(x, cards_y, card_w, 2.2, style="F")
        pdf.set_xy(x, cards_y + 4)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*color)
        pdf.cell(card_w, 6, str(by_sev[sev]), align="C")
        pdf.set_xy(x, cards_y + 11)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(card_w, 5, _SEVERITY_LABELS[sev], align="C")
    pdf.set_y(cards_y + card_h + 2)

    # Shared table styling
    header_style = FontFace(emphasis="BOLD", color=_WHITE, fill_color=_SLATE, size_pt=9)
    pdf.set_draw_color(*_BORDER)

    # Scans table
    _pdf_section_heading(pdf, "Escaneos realizados")
    if scans:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_NAVY)
        with pdf.table(
            col_widths=(44, 18, 16, 22),
            headings_style=header_style,
            cell_fill_color=_SURFACE,
            cell_fill_mode=TableCellFillMode.ROWS,
            line_height=6,
            padding=2,
        ) as table:
            head = table.row()
            for col in ("Nombre", "Tipo", "Estado", "Completado"):
                head.cell(col)
            for scan in scans:
                row = table.row()
                row.cell(_pdf_text(scan["name"]))
                row.cell(_pdf_text(scan["scan_type"]))
                row.cell(_pdf_text(scan["status"]))
                row.cell(_pdf_text(_format_pdf_timestamp(scan["completed_at"])))
    else:
        pdf.set_font("Helvetica", "I", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(
            0, 6, "No hay escaneos registrados para este activo.", new_x="LMARGIN", new_y="NEXT"
        )

    # Vulnerabilities table
    _pdf_section_heading(pdf, "Detalle de vulnerabilidades")
    if vulns:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_NAVY)
        with pdf.table(
            col_widths=(44, 14, 14, 18, 10),
            headings_style=header_style,
            cell_fill_color=_SURFACE,
            cell_fill_mode=TableCellFillMode.ROWS,
            line_height=6,
            padding=2,
        ) as table:
            head = table.row()
            for col in ("Titulo", "Severidad", "Estado", "CVE", "CVSS"):
                head.cell(col)
            for vuln in vulns:
                sev = vuln["severity"]
                sev_style = FontFace(
                    emphasis="BOLD",
                    color=_SEVERITY_COLORS.get(sev, _NAVY),
                    size_pt=8.5,
                )
                cvss = (
                    f"{vuln['cvss_score']:.1f}"
                    if vuln["cvss_score"] is not None
                    else "-"
                )
                row = table.row()
                row.cell(_pdf_text(vuln["title"]))
                row.cell(_SEVERITY_LABELS.get(sev, sev).upper(), style=sev_style)
                row.cell(_pdf_text(vuln["status"]))
                row.cell(_pdf_text(vuln["cve_id"] or "-"))
                row.cell(cvss)
    else:
        pdf.set_font("Helvetica", "I", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(
            0,
            6,
            "No hay vulnerabilidades registradas para este activo.",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    return bytes(pdf.output())


def _sorted_vulnerabilities(
    vulnerabilities: Sequence[Vulnerability],
) -> list[Vulnerability]:
    return sorted(
        vulnerabilities,
        key=lambda vuln: (
            _SEVERITY_RANK.get(vuln.severity, len(_SEVERITY_ORDER)),
            -(vuln.created_at.timestamp()) if vuln.created_at is not None else 0.0,
        ),
    )


def render_report_export(
    report: Report,
    asset: Asset | None,
    scans: Sequence[Scan],
    vulnerabilities: Sequence[Vulnerability],
    fmt: ReportDownloadFormat,
) -> ReportExport:
    """Render a downloadable report from an explicit public-field whitelist.

    Internal columns such as ``Scan.raw_output``, ``Scan.config``, and
    ``*_metadata`` JSON blobs are deliberately excluded so every reader role
    receives only the public data it can already view via read endpoints.
    """
    ordered_vulns = _sorted_vulnerabilities(vulnerabilities)
    by_severity = {sev: 0 for sev in _SEVERITY_ORDER}
    open_count = 0
    for vuln in ordered_vulns:
        if vuln.severity in by_severity:
            by_severity[vuln.severity] += 1
        if vuln.status == "open":
            open_count += 1

    payload: dict[str, Any] = {
        "report": {
            "id": str(report.id),
            "name": report.name,
            "report_type": report.report_type,
            "status": report.status,
            "summary": report.summary,
            "generated_at": _iso_or_none(report.generated_at),
            "created_at": _iso_or_none(report.created_at),
            "updated_at": _iso_or_none(report.updated_at),
        },
        "asset": (
            {
                "id": str(asset.id),
                "value": asset.value,
                "asset_type": asset.asset_type,
                "status": asset.status,
            }
            if asset is not None
            else None
        ),
        "summary_counts": {
            "total_scans": len(scans),
            "total_vulnerabilities": len(ordered_vulns),
            "open_vulnerabilities": open_count,
            "by_severity": by_severity,
        },
        "scans": [
            {
                "id": str(scan.id),
                "name": scan.name,
                "scan_type": scan.scan_type,
                "status": scan.status,
                "started_at": _iso_or_none(scan.started_at),
                "completed_at": _iso_or_none(scan.completed_at),
                "created_at": _iso_or_none(scan.created_at),
            }
            for scan in scans
        ],
        "vulnerabilities": [
            {
                "id": str(vuln.id),
                "scan_id": str(vuln.scan_id),
                "title": vuln.title,
                "severity": vuln.severity,
                "status": vuln.status,
                "cve_id": vuln.cve_id,
                "cvss_score": (
                    float(vuln.cvss_score) if vuln.cvss_score is not None else None
                ),
                "description": vuln.description,
                "created_at": _iso_or_none(vuln.created_at),
            }
            for vuln in ordered_vulns
        ],
    }

    filename = sanitize_download_filename(report.name, report.id, fmt)
    if fmt == "json":
        return ReportExport(
            content=json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            media_type="application/json",
            filename=filename,
        )
    if fmt == "pdf":
        return ReportExport(
            content=_render_pdf(payload),
            media_type="application/pdf",
            filename=filename,
        )

    lines: list[str] = [
        f"# {report.name}",
        "",
        f"- **Report ID:** {report.id}",
        f"- **Type:** {report.report_type}",
        f"- **Status:** {report.status}",
        f"- **Asset:** {asset.value} ({asset.asset_type})"
        if asset is not None
        else f"- **Asset ID:** {report.asset_id}",
        f"- **Generated At:** {_iso_or_none(report.generated_at) or 'N/A'}",
        f"- **Created At:** {_iso_or_none(report.created_at) or 'N/A'}",
    ]
    if report.summary:
        lines.extend(["", "## Summary", "", report.summary])

    lines.extend(
        [
            "",
            "## Overview",
            "",
            f"- **Scans:** {len(scans)}",
            f"- **Vulnerabilities:** {len(ordered_vulns)} (open: {open_count})",
            "- **By severity:** "
            + ", ".join(f"{sev}={by_severity[sev]}" for sev in _SEVERITY_ORDER),
        ]
    )

    lines.extend(["", "## Scans", ""])
    if scans:
        lines.append("| Name | Type | Status | Completed At |")
        lines.append("| --- | --- | --- | --- |")
        for scan in scans:
            lines.append(
                f"| {_escape_md_cell(scan.name)} | {scan.scan_type} | "
                f"{scan.status} | {_iso_or_none(scan.completed_at) or 'N/A'} |"
            )
    else:
        lines.append("No scans recorded for this asset.")

    lines.extend(["", "## Vulnerabilities", ""])
    if ordered_vulns:
        lines.append("| Title | Severity | Status | CVE | CVSS |")
        lines.append("| --- | --- | --- | --- | --- |")
        for vuln in ordered_vulns:
            cvss = f"{float(vuln.cvss_score):.1f}" if vuln.cvss_score is not None else "-"
            lines.append(
                f"| {_escape_md_cell(vuln.title)} | {vuln.severity} | "
                f"{vuln.status} | {vuln.cve_id or '-'} | {cvss} |"
            )
    else:
        lines.append("No vulnerabilities recorded for this asset.")

    return ReportExport(
        content="\n".join(lines) + "\n",
        media_type="text/markdown; charset=utf-8",
        filename=filename,
    )


async def build_report_export(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    *,
    fmt: ReportDownloadFormat = "md",
) -> ReportExport | None:
    """Load a visible report and its asset/scans/vulnerabilities, then render."""
    report = await get_report(report_id=report_id, tenant_id=tenant_id, db=db)
    if report is None:
        return None

    asset_stmt = select(Asset).where(
        Asset.id == report.asset_id,
        Asset.tenant_id == report.tenant_id,
    )
    asset = (await db.execute(asset_stmt)).scalar_one_or_none()

    scans_stmt = (
        select(Scan)
        .where(
            Scan.asset_id == report.asset_id,
            Scan.tenant_id == report.tenant_id,
        )
        .order_by(Scan.created_at.desc(), Scan.id.desc())
    )
    scans = (await db.execute(scans_stmt)).scalars().all()

    vulnerabilities: Sequence[Vulnerability] = ()
    if scans:
        scan_ids = [scan.id for scan in scans]
        vulns_stmt = (
            select(Vulnerability)
            .where(
                Vulnerability.scan_id.in_(scan_ids),
                Vulnerability.tenant_id == report.tenant_id,
            )
            .order_by(Vulnerability.created_at.desc(), Vulnerability.id.desc())
        )
        vulnerabilities = (await db.execute(vulns_stmt)).scalars().all()

    return render_report_export(
        report=report,
        asset=asset,
        scans=scans,
        vulnerabilities=vulnerabilities,
        fmt=fmt,
    )
