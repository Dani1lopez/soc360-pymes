"""Bounded broker retry and off-loop publishing."""

import threading
import time
from uuid import uuid4

import pytest

from app.modules.scans import dispatch
from app.modules.scans.dispatch import CeleryScanDispatcher
from app.worker import tasks


async def test_celery_dispatch(monkeypatch):
    calls = []
    main_thread = threading.get_ident()

    def publish(**kwargs):
        assert threading.get_ident() != main_thread
        calls.append(kwargs)

    monkeypatch.setattr(tasks.wake, "apply_async", publish)
    scan_id, tenant_id = uuid4(), uuid4()
    await CeleryScanDispatcher().dispatch(scan_id, tenant_id)
    assert calls == [
        {
            "args": [],
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

    monkeypatch.setattr(tasks.wake, "apply_async", publish)
    with pytest.raises(RuntimeError, match="unavailable"):
        await CeleryScanDispatcher().dispatch(uuid4(), uuid4())


async def test_hung_publish_has_request_deadline(monkeypatch):
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    def publish(**kwargs):
        started.set()
        try:
            release.wait(timeout=2)
        finally:
            finished.set()

    monkeypatch.setattr(dispatch, "PUBLISH_TIMEOUT_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(tasks.wake, "apply_async", publish)
    before = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            await CeleryScanDispatcher().dispatch(uuid4(), uuid4())
        assert started.is_set()
        assert 0.15 <= time.monotonic() - before < 1
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(timeout=3)
