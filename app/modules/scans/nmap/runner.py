"""Execute prebuilt argv without a shell, retaining only bounded output.

The subprocess gets a minimal environment so application secrets (database
URLs, signing keys) are never visible to Nmap or its NSE scripts. This layer
does not parse the output.
"""

import asyncio
import logging
import math
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass


logger = logging.getLogger(__name__)


class NmapRunError(Exception):
    """A bounded failure code suitable for scans.failure_reason."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class NmapRunResult:
    stdout: bytes
    stderr_tail: str
    returncode: int


def _minimal_env() -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}


async def _stdout(stream: asyncio.StreamReader, cap: int) -> bytes:
    output = bytearray()
    while chunk := await stream.read(min(65536, cap - len(output) + 1)):
        if len(output) + len(chunk) > cap:
            raise NmapRunError("output_too_large")
        output.extend(chunk)
    return bytes(output)


async def _stderr(stream: asyncio.StreamReader) -> str:
    tail = b""
    while chunk := await stream.read(65536):
        tail = (tail + chunk)[-4096:]
    return tail.decode(errors="replace")


async def _discard(stream: asyncio.StreamReader) -> None:
    while await stream.read(65536):
        pass


async def _cleanup(process: asyncio.subprocess.Process, grace_period: float) -> None:
    # Drain both pipes even after a reader failed, so wait() cannot deadlock on
    # the transport's paused pipe buffers.
    assert process.stdout is not None and process.stderr is not None
    drains = [
        asyncio.create_task(_discard(process.stdout)),
        asyncio.create_task(_discard(process.stderr)),
    ]
    try:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), grace_period)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), grace_period)
            except TimeoutError:
                logger.warning(
                    "Nmap process pid=%s did not exit after kill", process.pid
                )
    finally:
        for task in drains:
            task.cancel()
        await asyncio.gather(*drains, return_exceptions=True)


async def run_nmap(
    argv: Sequence[str],
    *,
    timeout: float,
    max_output_bytes: int,
    grace_period: float = 5.0,
) -> NmapRunResult:
    """Run one binary, discard partial results on any failure or cancellation."""
    if (
        not argv
        or not math.isfinite(timeout)
        or timeout <= 0
        or max_output_bytes <= 0
        or not math.isfinite(grace_period)
        or grace_period <= 0
    ):
        raise ValueError("argv and positive finite resource limits are required")
    resolved = shutil.which(argv[0])
    if resolved is None:
        raise NmapRunError("nmap_not_found")
    process = None
    readers: list[asyncio.Task[bytes] | asyncio.Task[str]] = []
    try:
        async with asyncio.timeout(timeout):
            try:
                process = await asyncio.create_subprocess_exec(
                    resolved,
                    *argv[1:],
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_minimal_env(),
                )
            except FileNotFoundError as exc:
                raise NmapRunError("nmap_not_found") from exc
            assert process.stdout is not None and process.stderr is not None
            stdout_task = asyncio.create_task(_stdout(process.stdout, max_output_bytes))
            stderr_task = asyncio.create_task(_stderr(process.stderr))
            readers = [stdout_task, stderr_task]
            await asyncio.gather(*readers)
            returncode = await process.wait()
            if returncode != 0:
                raise NmapRunError("nonzero_exit", detail=stderr_task.result())
            return NmapRunResult(stdout_task.result(), stderr_task.result(), returncode)
    except BaseException as exc:
        for task in readers:
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        if process is not None:
            # Shield cleanup from further cancellation, and wait for it before
            # propagating the caller's cancellation.
            cleanup = asyncio.create_task(_cleanup(process, grace_period))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
        if isinstance(exc, TimeoutError):
            raise NmapRunError("timeout") from exc
        raise
