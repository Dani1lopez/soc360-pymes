"""Unit tests for F5 enrichment in-flight Redis deduplication."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.modules.enrichment import queries
from app.modules.enrichment.dispatch import (
    acquire_enrichment_slot,
    enrichment_dedup_ttl_seconds,
    enrichment_inflight_key,
    release_enrichment_slot,
)
from app.modules.enrichment.router import request_enrichment, request_scan_enrichment


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = (value, ex)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


class _BrokenRedis:
    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def delete(self, *args, **kwargs):
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_acquire_and_release_slot_enforce_nx_and_ttl() -> None:
    redis = _FakeRedis()
    tenant_id = str(uuid4())
    vuln_id = str(uuid4())
    key = enrichment_inflight_key(tenant_id, vuln_id)

    assert await acquire_enrichment_slot(redis, tenant_id, vuln_id) is True
    assert redis.store[key] == ("1", enrichment_dedup_ttl_seconds())
    assert enrichment_dedup_ttl_seconds() == settings.ENRICHMENT_BUDGET_SECONDS + 30
    assert await acquire_enrichment_slot(redis, tenant_id, vuln_id) is False

    await release_enrichment_slot(redis, tenant_id, vuln_id)
    assert key not in redis.store
    assert await acquire_enrichment_slot(redis, tenant_id, vuln_id) is True


@pytest.mark.asyncio
async def test_redis_errors_fail_open_without_raising() -> None:
    redis = _BrokenRedis()
    assert await acquire_enrichment_slot(redis, "t1", "v1") is True
    await release_enrichment_slot(redis, "t1", "v1")


@pytest.mark.asyncio
async def test_scan_enrichment_deduplicates_repeated_requests(monkeypatch) -> None:
    tenant_id = uuid4()
    scan_id = uuid4()
    vulns = [
        SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
        SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
    ]
    user = SimpleNamespace(tenant_id=tenant_id, is_superadmin=False)
    scan = SimpleNamespace(id=scan_id, tenant_id=tenant_id)
    redis = _FakeRedis()
    calls: list[tuple[str, str]] = []

    async def fake_visible_scan(db, sid, tid):
        return scan

    async def fake_tenant_level(db, tid):
        return "basic"

    async def fake_scan_pending(db, s, funcs):
        return vulns, len(vulns)

    async def fake_enqueuer(vid: str, tid: str) -> bool:
        calls.append((vid, tid))
        return True

    monkeypatch.setattr(queries, "visible_scan", fake_visible_scan)
    monkeypatch.setattr(queries, "tenant_level", fake_tenant_level)
    monkeypatch.setattr(queries, "scan_pending", fake_scan_pending)
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)

    first = await request_scan_enrichment(
        scan_id=scan_id,
        db=object(),
        enqueuer=fake_enqueuer,
        redis=redis,
        current_user=user,
    )
    second = await request_scan_enrichment(
        scan_id=scan_id,
        db=object(),
        enqueuer=fake_enqueuer,
        redis=redis,
        current_user=user,
    )

    assert first.queued == 2
    assert first.total == 2
    assert second.queued == 0
    assert second.total == 2
    assert calls == [(str(v.id), str(tenant_id)) for v in vulns]


@pytest.mark.asyncio
async def test_scan_enrichment_releases_only_failed_slot_on_503(monkeypatch) -> None:
    tenant_id = uuid4()
    scan_id = uuid4()
    v1 = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    v2 = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    user = SimpleNamespace(tenant_id=tenant_id, is_superadmin=False)
    scan = SimpleNamespace(id=scan_id, tenant_id=tenant_id)
    redis = _FakeRedis()
    calls: list[str] = []
    fail_second = True

    async def fake_visible_scan(db, sid, tid):
        return scan

    async def fake_tenant_level(db, tid):
        return "basic"

    async def fake_scan_pending(db, s, funcs):
        return [v1, v2], 2

    async def fake_enqueuer(vid: str, tid: str) -> bool:
        calls.append(vid)
        if fail_second and vid == str(v2.id):
            return False
        return True

    monkeypatch.setattr(queries, "visible_scan", fake_visible_scan)
    monkeypatch.setattr(queries, "tenant_level", fake_tenant_level)
    monkeypatch.setattr(queries, "scan_pending", fake_scan_pending)
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)

    with pytest.raises(HTTPException) as exc_info:
        await request_scan_enrichment(
            scan_id=scan_id,
            db=object(),
            enqueuer=fake_enqueuer,
            redis=redis,
            current_user=user,
        )
    assert exc_info.value.status_code == 503
    assert enrichment_inflight_key(str(tenant_id), str(v1.id)) in redis.store
    assert enrichment_inflight_key(str(tenant_id), str(v2.id)) not in redis.store

    fail_second = False
    retry = await request_scan_enrichment(
        scan_id=scan_id,
        db=object(),
        enqueuer=fake_enqueuer,
        redis=redis,
        current_user=user,
    )
    assert retry.queued == 1
    assert retry.total == 2
    assert calls == [str(v1.id), str(v2.id), str(v2.id)]


@pytest.mark.asyncio
async def test_single_vulnerability_enrichment_dedup_and_release(monkeypatch) -> None:
    tenant_id = uuid4()
    vuln_id = uuid4()
    vuln = SimpleNamespace(id=vuln_id, tenant_id=tenant_id)
    user = SimpleNamespace(tenant_id=tenant_id, is_superadmin=False)
    redis = _FakeRedis()
    should_succeed = False
    calls: list[str] = []

    async def fake_visible_vuln(db, vid, tid):
        return vuln

    async def fake_enqueuer(vid: str, tid: str) -> bool:
        calls.append(vid)
        return should_succeed

    monkeypatch.setattr(queries, "visible_vulnerability", fake_visible_vuln)
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)

    with pytest.raises(HTTPException) as exc_info:
        await request_enrichment(
            vulnerability_id=vuln_id,
            db=object(),
            enqueuer=fake_enqueuer,
            redis=redis,
            current_user=user,
        )
    assert exc_info.value.status_code == 503
    assert enrichment_inflight_key(str(tenant_id), str(vuln_id)) not in redis.store

    should_succeed = True
    first = await request_enrichment(
        vulnerability_id=vuln_id,
        db=object(),
        enqueuer=fake_enqueuer,
        redis=redis,
        current_user=user,
    )
    second = await request_enrichment(
        vulnerability_id=vuln_id,
        db=object(),
        enqueuer=fake_enqueuer,
        redis=redis,
        current_user=user,
    )
    assert first.queued == 1
    assert second.queued == 0
    assert calls == [str(vuln_id), str(vuln_id)]
