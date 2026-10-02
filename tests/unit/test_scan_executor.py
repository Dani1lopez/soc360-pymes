import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.scans import executor
from app.modules.scans.nmap.runner import NmapRunError, NmapRunResult

XML = (
    Path("tests/fixtures/nmap/normal.xml")
    .read_bytes()
    .replace(b"unsafe &lt;script&gt; &amp; data", b"VULNERABLE CVSS: 7.5")
)


@pytest.fixture
def setup(monkeypatch):
    session = SimpleNamespace(
        add=Mock(), flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock()
    )
    tenant = uuid.uuid4()
    load = AsyncMock(return_value=("hostname", "example.com"))
    transition = AsyncMock(return_value=True)
    context = AsyncMock()
    events = []

    async def set_context(*args):
        events.append("context")

    async def move(*args, **kwargs):
        assert events[-1] == "context"
        events.append(kwargs["to"])
        return transition.return_value

    context.side_effect = set_context
    transition.side_effect = move
    monkeypatch.setattr(executor, "_load_scan", load)
    monkeypatch.setattr(executor, "transition_scan", transition)
    monkeypatch.setattr(executor, "set_tenant_context", context)
    run = AsyncMock(return_value=NmapRunResult(XML, "", 0))
    resolver = AsyncMock(return_value=["93.184.216.34"])
    return SimpleNamespace(
        session=session,
        tenant=tenant,
        scan=uuid.uuid4(),
        load=load,
        transition=transition,
        context=context,
        run=run,
        resolver=resolver,
    )


async def execute(s):
    return await executor.execute_scan(
        s.session, s.scan, tenant_id=s.tenant, resolver=s.resolver, run=s.run
    )


async def test_success(setup):
    s = setup
    assert await execute(s) == "completed"
    row = s.session.add.call_args.args[0]
    assert row.severity == "high" and row.tenant_id == s.tenant
    assert s.transition.call_args.kwargs == {
        "to": "completed",
        "raw_output": XML.decode(),
        "commit": False,
    }
    s.session.flush.assert_awaited_once()
    s.session.commit.assert_awaited_once()
    assert s.context.await_count == 3


@pytest.mark.parametrize("missing", [False, True])
async def test_skipped(setup, missing):
    s = setup
    if missing:
        s.load.return_value = None
    else:
        s.transition.return_value = False
    assert await execute(s) == "skipped"
    s.run.assert_not_awaited()
    s.session.add.assert_not_called()


@pytest.mark.parametrize(
    "error,reason",
    [
        (NmapRunError("timeout", "private diagnostics"), "timeout"),
        (ValueError("secret"), "internal_error"),
    ],
)
async def test_run_failure(setup, error, reason, caplog):
    s = setup
    s.run.side_effect = error
    assert await execute(s) == "failed"
    assert s.transition.call_args.kwargs == {"to": "failed", "failure_reason": reason}
    s.session.rollback.assert_awaited_once()
    s.session.add.assert_not_called()
    if isinstance(error, NmapRunError):
        assert "private diagnostics" in caplog.text


async def test_target_rejected(setup):
    s = setup
    s.resolver.return_value = ["127.0.0.1"]
    assert await execute(s) == "failed"
    assert s.transition.call_args.kwargs["failure_reason"] == "target_not_global"
    s.run.assert_not_awaited()


@pytest.mark.parametrize(
    "xml,reason",
    [
        (b"bad", "malformed_xml"),
        (
            Path("tests/fixtures/nmap/connect_fallback.xml").read_bytes(),
            "scan_type_mismatch",
        ),
    ],
)
async def test_parse_failure(setup, xml, reason):
    s = setup
    s.run.return_value = NmapRunResult(xml, "", 0)
    assert await execute(s) == "failed"
    assert s.transition.call_args.kwargs["failure_reason"] == reason
    s.session.add.assert_not_called()


async def test_finish_race(setup):
    s = setup

    async def run(*args, **kwargs):
        s.transition.return_value = False
        return NmapRunResult(XML, "", 0)

    s.run.side_effect = run
    assert await execute(s) == "cancelled"
    s.session.rollback.assert_awaited_once()
    s.session.commit.assert_not_awaited()


async def test_cancellation(setup):
    s = setup
    s.run.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await execute(s)
    assert s.transition.call_args.kwargs == {"to": "cancelled"}
    s.session.rollback.assert_awaited_once()


async def test_cancellation_before_claim_leaves_scan_untouched(setup):
    s = setup
    s.load.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await execute(s)
    s.transition.assert_not_awaited()


async def test_cancellation_during_failure_cleanup_still_marks_failed(setup):
    s = setup
    s.run.side_effect = NmapRunError("timeout")
    started, release, done = asyncio.Event(), asyncio.Event(), []

    async def slow(*args, **kwargs):
        if kwargs["to"] == "failed":
            started.set()
            await release.wait()
            done.append(kwargs["failure_reason"])
        return True

    s.transition.side_effect = slow
    task = asyncio.create_task(execute(s))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == ["timeout"]


async def test_dual_family(setup):
    s = setup
    s.resolver.return_value += ["2606:4700:4700::1111"]
    assert await execute(s) == "completed"
    assert s.run.await_count == 2
    assert "-6" in s.run.call_args_list[1].args[0]
    assert (
        s.transition.call_args.kwargs["raw_output"]
        == XML.decode() + "\n" + XML.decode()
    )
