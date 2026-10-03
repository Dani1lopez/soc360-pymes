"""Bounded broker retry and off-loop publishing."""

import threading
from uuid import uuid4

import pytest

from app.modules.scans.dispatch import CeleryScanDispatcher
from app.worker.tasks import run_scan


async def test_celery_dispatch(monkeypatch):
    calls = []
    main_thread = threading.get_ident()

    def publish(**kwargs):
        assert threading.get_ident() != main_thread
        calls.append(kwargs)

    monkeypatch.setattr(run_scan, "apply_async", publish)
    scan_id, tenant_id = uuid4(), uuid4()
    await CeleryScanDispatcher().dispatch(scan_id, tenant_id)
    assert calls == [
        {
            "args": [str(scan_id), str(tenant_id)],
            "retry": True,
            "retry_policy": {
                "max_retries": 2,
                "interval_start": 0,
                "interval_step": 0.5,
                "interval_max": 1,
            },
        }
    ]


async def test_dispatch_failure_propagates(monkeypatch):
    def publish(**kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(run_scan, "apply_async", publish)
    with pytest.raises(RuntimeError, match="unavailable"):
        await CeleryScanDispatcher().dispatch(uuid4(), uuid4())
