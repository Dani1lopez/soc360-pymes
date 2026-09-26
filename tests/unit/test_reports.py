"""Unit tests for the Reports domain (F2 Slice 4).

Happy path per service function, plus the event schema shape. Proportionate
in scope per the active freeze: no exhaustive edge-case suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.event_schemas import (
    BaseEvent,
    ReportCreatedEvent,
    ReportDeletedEvent,
    ReportUpdatedEvent,
)
from app.modules.reports import service
from app.modules.reports.models import Report
from app.modules.reports.schemas import ReportCreate, ReportUpdate


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
