"""Unit tests for the Reports domain (F2 Slice 4).

Happy path per service function, plus the event schema shape. Proportionate
in scope per the active freeze: no exhaustive edge-case suite.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.event_schemas import (
    BaseEvent,
    ReportCreatedEvent,
    ReportDeletedEvent,
    ReportUpdatedEvent,
)
from app.modules.assets.models import Asset
from app.modules.reports import service
from app.modules.reports.models import Report
from app.modules.reports.schemas import ReportCreate, ReportUpdate
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability


class TestReportEventSchemas:
    """The three Reports CRUD events, on the shared BaseEvent envelope."""

    @staticmethod
    def _envelope() -> dict[str, object]:
        return {"event_id": uuid.uuid4(), "tenant_id": uuid.uuid4()}

    def test_report_events_inherit_the_base_envelope(self) -> None:
        for event_cls in (ReportCreatedEvent, ReportUpdatedEvent, ReportDeletedEvent):
            assert issubclass(event_cls, BaseEvent)

    def test_report_created_event_carries_the_report_payload(self) -> None:
        event = ReportCreatedEvent(
            **self._envelope(),
            report_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            name="Q3 executive",
            report_type="executive",
            status="pending",
            created_at=datetime.now(UTC),
        )

        assert event.event_type == "report.created"
        assert event.report_type == "executive"
        assert event.status == "pending"

    def test_report_updated_event_carries_changed_fields(self) -> None:
        event = ReportUpdatedEvent(
            **self._envelope(),
            report_id=uuid.uuid4(),
            changed_fields=["status", "generated_at"],
        )

        assert event.event_type == "report.updated"
        assert event.changed_fields == ["status", "generated_at"]

    def test_report_deleted_event_carries_the_id(self) -> None:
        report_id = uuid.uuid4()
        event = ReportDeletedEvent(**self._envelope(), report_id=report_id)

        assert event.event_type == "report.deleted"
        assert event.report_id == report_id


class TestReportUpdateSchema:
    def test_explicit_null_status_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReportUpdate(status=None)


def _make_report(**overrides: object) -> Report:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "asset_id": uuid.uuid4(),
        "name": "r",
        "report_type": "vulnerability",
        "status": "pending",
    }
    fields.update(overrides)
    return Report(**fields)


def _make_db(scalar_result: object) -> AsyncMock:
    """A minimal AsyncSession double whose execute() returns a canned scalar."""
    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    execute_result.scalar_one = MagicMock(return_value=1)
    execute_result.scalars = MagicMock(
        return_value=MagicMock(
            all=MagicMock(return_value=[scalar_result] if scalar_result else [])
        )
    )
    db.execute = AsyncMock(return_value=execute_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
class TestCreateReport:
    async def test_creates_pending_report_and_publishes_created_event(self) -> None:
        tenant_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        data = ReportCreate(
            tenant_id=tenant_id,
            asset_id=asset_id,
            name="Monthly vulns",
            report_type="vulnerability",
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        event_bus = AsyncMock()

        def _fake_add(instance: Report) -> None:
            instance.id = uuid.uuid4()
            instance.created_at = datetime.now(UTC)
            instance.updated_at = datetime.now(UTC)

        db.add.side_effect = _fake_add

        report = await service.create_report(
            data=data, tenant_id=tenant_id, db=db, event_bus=event_bus
        )

        assert report.status == "pending"
        assert report.generated_at is None
        assert report.tenant_id == tenant_id
        assert report.asset_id == asset_id
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()
        event_bus.publish.assert_awaited_once()
        published_event = event_bus.publish.call_args.args[0]
        assert published_event.event_type == "report.created"


@pytest.mark.asyncio
class TestGetReport:
    async def test_returns_the_report_when_found(self) -> None:
        report = _make_report()
        db = _make_db(report)

        result = await service.get_report(report.id, report.tenant_id, db)

        assert result is report

    async def test_returns_none_when_missing(self) -> None:
        db = _make_db(None)

        result = await service.get_report(uuid.uuid4(), uuid.uuid4(), db)

        assert result is None


@pytest.mark.asyncio
class TestListReports:
    async def test_returns_items_and_total(self) -> None:
        report = _make_report()
        db = _make_db(report)

        items, total = await service.list_reports(
            tenant_id=report.tenant_id,
            db=db,
            limit=50,
            offset=0,
            report_type="vulnerability",
            status="pending",
        )

        assert list(items) == [report]
        assert total == 1


@pytest.mark.asyncio
class TestUpdateReport:
    async def test_updates_status_and_generated_at_and_publishes_event(self) -> None:
        report = _make_report()
        db = _make_db(report)
        event_bus = AsyncMock()
        generated_at = datetime.now(UTC)

        result = await service.update_report(
            report_id=report.id,
            tenant_id=report.tenant_id,
            data=ReportUpdate(status="completed", generated_at=generated_at),
            db=db,
            event_bus=event_bus,
        )

        assert result is not None
        assert result.status == "completed"
        assert result.generated_at == generated_at
        event_bus.publish.assert_awaited_once()
        published_event = event_bus.publish.call_args.args[0]
        assert published_event.changed_fields == ["status", "generated_at"]

    async def test_returns_none_when_missing(self) -> None:
        db = _make_db(None)
        event_bus = AsyncMock()

        result = await service.update_report(
            report_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            data=ReportUpdate(status="completed"),
            db=db,
            event_bus=event_bus,
        )

        assert result is None
        event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
class TestDeleteReport:
    async def test_deletes_and_publishes_event(self) -> None:
        report = _make_report()
        db = _make_db(report)
        event_bus = AsyncMock()

        result = await service.delete_report(
            report_id=report.id, tenant_id=report.tenant_id, db=db, event_bus=event_bus
        )

        assert result is True
        db.delete.assert_awaited_once_with(report)
        event_bus.publish.assert_awaited_once()

    async def test_returns_false_when_missing(self) -> None:
        db = _make_db(None)
        event_bus = AsyncMock()

        result = await service.delete_report(
            report_id=uuid.uuid4(), tenant_id=uuid.uuid4(), db=db, event_bus=event_bus
        )

        assert result is False
        event_bus.publish.assert_not_awaited()


class TestReportExport:
    def test_sanitize_download_filename_strips_header_injection_and_falls_back(
        self,
    ) -> None:
        report_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

        safe = service.sanitize_download_filename(
            'Q3 "Exec"\r\nX-Injected: 1/../../secret', report_id, "md"
        )
        assert "\r" not in safe
        assert "\n" not in safe
        assert '"' not in safe
        assert "/" not in safe
        assert safe.startswith("report-")
        assert safe.endswith(".md")

        fallback = service.sanitize_download_filename("!!! ///", report_id, "json")
        assert fallback == "report-12345678.json"

    def test_render_report_export_whitelists_public_fields_in_md_and_json(
        self,
    ) -> None:
        now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
        tenant_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        scan_id = uuid.uuid4()

        report = _make_report(
            tenant_id=tenant_id,
            asset_id=asset_id,
            name="Executive Q4",
            report_type="executive",
            status="completed",
            summary="Key risks found on perimeter.",
            report_metadata={"internal_only": "SECRET_REPORT_META"},
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        asset = Asset(
            id=asset_id,
            tenant_id=tenant_id,
            value="api.acme.example",
            asset_type="domain",
            status="active",
            asset_metadata={"internal_only": "SECRET_ASSET_META"},
        )
        scan = Scan(
            id=scan_id,
            tenant_id=tenant_id,
            asset_id=asset_id,
            name="Perimeter scan",
            scan_type="vulnerability",
            status="completed",
            config={"secret_flag": "SECRET_SCAN_CONFIG"},
            raw_output="<nmaprun>SECRET_RAW_XML</nmaprun>",
            completed_at=now,
            created_at=now,
        )
        vuln_low = Vulnerability(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scan_id=scan_id,
            title="Minor banner leak",
            severity="low",
            status="fixed",
            cve_id=None,
            cvss_score=None,
            vulnerability_metadata={"internal_only": "SECRET_VULN_META"},
            created_at=now,
        )
        vuln_crit = Vulnerability(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scan_id=scan_id,
            title="OpenSSH RCE | critical",
            severity="critical",
            status="open",
            cve_id="CVE-2026-0001",
            cvss_score=Decimal("9.8"),
            description="Remote code execution.",
            vulnerability_metadata={"internal_only": "SECRET_VULN_META"},
            created_at=now,
        )

        md_export = service.render_report_export(
            report, asset, [scan], [vuln_low, vuln_crit], "md"
        )
        assert md_export.media_type == "text/markdown; charset=utf-8"
        assert md_export.filename == "report-Executive-Q4.md"
        assert "# Executive Q4" in md_export.content
        assert "api.acme.example (domain)" in md_export.content
        assert "Key risks found on perimeter." in md_export.content
        assert "OpenSSH RCE \\| critical" in md_export.content
        assert "CVE-2026-0001" in md_export.content
        assert "9.8" in md_export.content
        for secret in (
            "SECRET_RAW_XML",
            "SECRET_SCAN_CONFIG",
            "SECRET_REPORT_META",
            "SECRET_ASSET_META",
            "SECRET_VULN_META",
        ):
            assert secret not in md_export.content

        json_export = service.render_report_export(
            report, asset, [scan], [vuln_low, vuln_crit], "json"
        )
        assert json_export.media_type == "application/json"
        assert json_export.filename == "report-Executive-Q4.json"
        parsed = json.loads(json_export.content)
        assert parsed["report"]["name"] == "Executive Q4"
        assert parsed["asset"]["value"] == "api.acme.example"
        assert parsed["summary_counts"] == {
            "total_scans": 1,
            "total_vulnerabilities": 2,
            "open_vulnerabilities": 1,
            "by_severity": {
                "critical": 1,
                "high": 0,
                "medium": 0,
                "low": 1,
                "info": 0,
            },
        }
        assert [v["severity"] for v in parsed["vulnerabilities"]] == [
            "critical",
            "low",
        ]
        assert parsed["vulnerabilities"][0]["cvss_score"] == 9.8
        assert "raw_output" not in parsed["scans"][0]
        assert "config" not in parsed["scans"][0]
        assert "report_metadata" not in parsed["report"]
        assert "asset_metadata" not in parsed["asset"]
        assert "vulnerability_metadata" not in parsed["vulnerabilities"][0]

        report_unicode = _make_report(
            tenant_id=tenant_id,
            asset_id=asset_id,
            name="Informe Español 🔒",
            report_type="executive",
            status="completed",
            summary="Resumen con ñ, tildes y emoji 🔒",
            report_metadata={"internal_only": "SECRET_REPORT_META"},
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        pdf_export = service.render_report_export(
            report_unicode, asset, [scan], [vuln_low, vuln_crit], "pdf"
        )
        assert pdf_export.media_type == "application/pdf"
        assert pdf_export.filename.endswith(".pdf")
        assert isinstance(pdf_export.content, bytes)
        assert pdf_export.content.startswith(b"%PDF-")
        for secret in (
            b"SECRET_RAW_XML",
            b"SECRET_SCAN_CONFIG",
            b"SECRET_REPORT_META",
            b"SECRET_ASSET_META",
            b"SECRET_VULN_META",
        ):
            assert secret not in pdf_export.content
