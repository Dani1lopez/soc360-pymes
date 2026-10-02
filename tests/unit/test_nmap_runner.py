import asyncio
import json
import os
import signal
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.scans.nmap.runner import NmapRunError, _cleanup, run_nmap


async def test_cleanup_bounds_post_kill_wait(caplog: pytest.LogCaptureFixture) -> None:
    process = Mock()
    process.pid = 12345
    process.stdout = asyncio.StreamReader()
    process.stderr = asyncio.StreamReader()

    async def never_exits() -> int:
        await asyncio.Event().wait()
        return 0

    process.wait = AsyncMock(side_effect=never_exits)
    before = set(asyncio.all_tasks())
    await asyncio.wait_for(_cleanup(process, grace_period=0.01), timeout=0.2)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert set(asyncio.all_tasks()) == before
    assert any(
        record.name == "app.modules.scans.nmap.runner"
        and record.levelname == "WARNING"
        and "12345" in record.getMessage()
        for record in caplog.records
    )


def child(script: str) -> list[str]:
    return [sys.executable, "-c", script]


async def test_success_and_bounded_stderr() -> None:
    result = await run_nmap(
        child("import os; os.write(2, b'x'*100000 + b'\\xfftail'); os.write(1, b'ok')"),
        timeout=2,
        max_output_bytes=2,
    )
    assert result.stdout == b"ok"
    assert result.returncode == 0
    assert result.stderr_tail == "x" * 4091 + "\ufffdtail"


async def test_nonzero_exit_keeps_diagnostics() -> None:
    with pytest.raises(NmapRunError) as caught:
        await run_nmap(
            child(
                "import os, sys; os.write(2, b'x'*10000 + b'diagnostic'); sys.exit(3)"
            ),
            timeout=2,
            max_output_bytes=100,
        )
    assert caught.value.reason == "nonzero_exit"
    assert str(caught.value) == "nonzero_exit"
    assert caught.value.detail is not None
    assert caught.value.detail.endswith("diagnostic")
    assert len(caught.value.detail.encode()) <= 4096


def test_error_detail_defaults_to_none() -> None:
    assert NmapRunError("timeout").detail is None


async def test_child_gets_minimal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOC360_TEST_SECRET", "do-not-leak")
    result = await run_nmap(
        child("import json, os; print(json.dumps(sorted(os.environ)))"),
        timeout=2,
        max_output_bytes=4096,
    )
    names = set(json.loads(result.stdout))
    assert "SOC360_TEST_SECRET" not in names
    assert names <= {"PATH", "LC_ALL", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}


@pytest.mark.parametrize(
    ("script", "timeout", "cap", "reason"),
    [
        ("import sys; print('partial'); sys.exit(3)", 2, 100, "nonzero_exit"),
        ("import time; time.sleep(30)", 0.15, 100, "timeout"),
        ("import os; os.write(1, b'x'*101)", 2, 100, "output_too_large"),
    ],
)
async def test_failures(script: str, timeout: float, cap: int, reason: str) -> None:
    with pytest.raises(NmapRunError) as caught:
        await run_nmap(
            child(script), timeout=timeout, max_output_bytes=cap, grace_period=0.05
        )
    assert caught.value.reason == reason
    assert len(caught.value.reason) <= 64


async def test_missing_binary_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(NmapRunError, match="nmap_not_found"):
        await run_nmap(
            ["/nonexistent/nmap-test-binary"], timeout=1, max_output_bytes=10
        )
    spawn.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [{"timeout": 0}, {"max_output_bytes": 0}, {"grace_period": -1}],
)
async def test_invalid_parameters(kwargs: dict[str, float]) -> None:
    params = {"timeout": 1, "max_output_bytes": 10, "grace_period": 1} | kwargs
    with pytest.raises(ValueError):
        await run_nmap(child("pass"), **params)


async def test_empty_argv() -> None:
    with pytest.raises(ValueError):
        await run_nmap([], timeout=1, max_output_bytes=10)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")
@pytest.mark.parametrize("cancel", [False, True])
async def test_cleanup_ignoring_sigterm(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    spawn = asyncio.create_subprocess_exec
    processes = []
    ready = asyncio.Event()

    async def capture(*args, **kwargs):
        assert args[0] == sys.executable
        assert set(kwargs.pop("env")) == {"PATH", "LC_ALL"}
        assert kwargs == {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        process = await spawn(*args, **kwargs, env={"PATH": os.defpath})
        processes.append(process)
        assert process.stdout is not None
        assert await process.stdout.readexactly(5) == b"ready"
        ready.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    task = asyncio.create_task(
        run_nmap(
            child(
                "import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); os.write(1, b'ready'); time.sleep(30)"
            ),
            timeout=0.2,
            max_output_bytes=100,
            grace_period=0.05,
        )
    )
    await asyncio.wait_for(ready.wait(), 1)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(NmapRunError, match="timeout"):
            await task
    assert processes[0].returncode == -signal.SIGKILL
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)
