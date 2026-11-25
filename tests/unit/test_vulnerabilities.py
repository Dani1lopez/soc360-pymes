"""Unit tests for the Vulnerabilities domain (F2 Slice 3).

Happy path per service function, plus the event schema shape. Proportionate
in scope per the active freeze: no exhaustive edge-case suite (see
``tests/api/test_scans.py`` for what NOT to copy).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.event_schemas import (
    BaseEvent,
    VulnerabilityCreatedEvent,
    VulnerabilityDeletedEvent,
    VulnerabilityUpdatedEvent,
)
from app.modules.vulnerabilities import service
from app.modules.vulnerabilities.models import Vulnerability
from app.modules.vulnerabilities.schemas import VulnerabilityCreate, VulnerabilityUpdate


class TestVulnerabilityEventSchemas:
    """The three Vulnerabilities CRUD events, on the shared BaseEvent envelope."""

    @staticmethod
    def _envelope() -> dict[str, object]:
        return {"event_id": uuid.uuid4(), "tenant_id": uuid.uuid4()}

    def test_vulnerability_events_inherit_the_base_envelope(self) -> None:
        for event_cls in (
            VulnerabilityCreatedEvent,
            VulnerabilityUpdatedEvent,
            VulnerabilityDeletedEvent,
        ):
            assert issubclass(event_cls, BaseEvent)

    def test_vulnerability_created_event_carries_the_finding_payload(self) -> None:
        event = VulnerabilityCreatedEvent(
            **self._envelope(),
            vulnerability_id=uuid.uuid4(),
            scan_id=uuid.uuid4(),
            title="SQL injection",
            severity="high",
            status="open",
            cve_id="CVE-2024-0001",
            cvss_score=8.5,
            created_at=datetime.now(UTC),
        )

        assert event.event_type == "vulnerability.created"
        assert event.severity == "high"
        assert event.status == "open"

    def test_vulnerability_updated_event_carries_changed_fields(self) -> None:
        event = VulnerabilityUpdatedEvent(
            **self._envelope(),
            vulnerability_id=uuid.uuid4(),
            changed_fields=["status", "description"],
        )

        assert event.event_type == "vulnerability.updated"
        assert event.changed_fields == ["status", "description"]

    def test_vulnerability_deleted_event_carries_the_id(self) -> None:
        vuln_id = uuid.uuid4()
        event = VulnerabilityDeletedEvent(**self._envelope(), vulnerability_id=vuln_id)

        assert event.event_type == "vulnerability.deleted"
        assert event.vulnerability_id == vuln_id


def _make_db(scalar_result: object) -> AsyncMock:
    """A minimal AsyncSession double whose execute() returns a canned scalar."""
    db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    execute_result.scalar_one = MagicMock(return_value=1)
    execute_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[scalar_result] if scalar_result else []))
    )
    db.execute = AsyncMock(return_value=execute_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
class TestCreateVulnerability:
    async def test_creates_and_publishes_created_event(self) -> None:
        tenant_id = uuid.uuid4()
        scan_id = uuid.uuid4()
        data = VulnerabilityCreate(
            tenant_id=tenant_id,
            scan_id=scan_id,
            title="Open port",
            severity="medium",
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        event_bus = AsyncMock()

        def _fake_add(instance: Vulnerability) -> None:
            instance.id = uuid.uuid4()
            instance.created_at = datetime.now(UTC)
            instance.updated_at = datetime.now(UTC)

        db.add.side_effect = _fake_add

        vulnerability = await service.create_vulnerability(
            data=data, tenant_id=tenant_id, db=db, event_bus=event_bus
        )

        assert vulnerability.status == "open"
        assert vulnerability.tenant_id == tenant_id
        assert vulnerability.scan_id == scan_id
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()
        event_bus.publish.assert_awaited_once()
        published_event = event_bus.publish.call_args.args[0]
        assert published_event.event_type == "vulnerability.created"


@pytest.mark.asyncio
class TestGetVulnerability:
    async def test_returns_the_vulnerability_when_found(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(), scan_id=uuid.uuid4(), title="x", severity="low"
        )
        db = _make_db(vuln)

        result = await service.get_vulnerability(vuln.id, vuln.tenant_id, db)

        assert result is vuln

    async def test_returns_none_when_missing(self) -> None:
        db = _make_db(None)

        result = await service.get_vulnerability(uuid.uuid4(), uuid.uuid4(), db)

        assert result is None


@pytest.mark.asyncio
class TestListVulnerabilities:
    async def test_returns_items_and_total(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(), scan_id=uuid.uuid4(), title="x", severity="low"
        )
        db = _make_db(vuln)

        items, total = await service.list_vulnerabilities(
            tenant_id=vuln.tenant_id, db=db, limit=50, offset=0
        )

        assert list(items) == [vuln]
        assert total == 1


@pytest.mark.asyncio
class TestUpdateVulnerability:
    async def test_updates_status_and_publishes_event(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            scan_id=uuid.uuid4(),
            title="x",
            severity="low",
            status="open",
        )
        db = _make_db(vuln)
        event_bus = AsyncMock()

        result = await service.update_vulnerability(
            vulnerability_id=vuln.id,
            tenant_id=vuln.tenant_id,
            data=VulnerabilityUpdate(status="fixed"),
            db=db,
            event_bus=event_bus,
        )

        assert result is not None
        assert result.status == "fixed"
        event_bus.publish.assert_awaited_once()
        published_event = event_bus.publish.call_args.args[0]
        assert published_event.changed_fields == ["status"]

    async def test_returns_none_when_missing(self) -> None:
        db = _make_db(None)
        event_bus = AsyncMock()

        result = await service.update_vulnerability(
            vulnerability_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            data=VulnerabilityUpdate(status="fixed"),
            db=db,
            event_bus=event_bus,
        )

        assert result is None
        event_bus.publish.assert_not_awaited()

    async def test_no_change_publishes_nothing(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            scan_id=uuid.uuid4(),
            title="x",
            severity="low",
            status="open",
        )
        db = _make_db(vuln)
        event_bus = AsyncMock()

        result = await service.update_vulnerability(
            vulnerability_id=vuln.id,
            tenant_id=vuln.tenant_id,
            data=VulnerabilityUpdate(status="open"),
            db=db,
            event_bus=event_bus,
        )

        assert result is vuln
        event_bus.publish.assert_not_awaited()

    async def test_cvss_rounding_to_persisted_value_publishes_no_second_event(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            scan_id=uuid.uuid4(),
            title="x",
            severity="low",
            cvss_score=Decimal("8.3"),
        )
        db = _make_db(vuln)
        event_bus = AsyncMock()

        await service.update_vulnerability(
            vulnerability_id=vuln.id,
            tenant_id=vuln.tenant_id,
            data=VulnerabilityUpdate(cvss_score=8.45),
            db=db,
            event_bus=event_bus,
        )
        assert vuln.cvss_score == Decimal("8.5")
        assert event_bus.publish.call_args.args[0].changed_fields == ["cvss_score"]

        await service.update_vulnerability(
            vulnerability_id=vuln.id,
            tenant_id=vuln.tenant_id,
            data=VulnerabilityUpdate(cvss_score=8.46),
            db=db,
            event_bus=event_bus,
        )
        assert vuln.cvss_score == Decimal("8.5")
        event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
class TestDeleteVulnerability:
    async def test_deletes_and_publishes_event(self) -> None:
        vuln = Vulnerability(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(), scan_id=uuid.uuid4(), title="x", severity="low"
        )
        db = _make_db(vuln)
        event_bus = AsyncMock()

        result = await service.delete_vulnerability(
            vulnerability_id=vuln.id, tenant_id=vuln.tenant_id, db=db, event_bus=event_bus
        )

        assert result is True
        db.delete.assert_awaited_once_with(vuln)
        event_bus.publish.assert_awaited_once()

    async def test_returns_false_when_missing(self) -> None:
        db = _make_db(None)
        event_bus = AsyncMock()

        result = await service.delete_vulnerability(
            vulnerability_id=uuid.uuid4(), tenant_id=uuid.uuid4(), db=db, event_bus=event_bus
        )

        assert result is False
        event_bus.publish.assert_not_awaited()
