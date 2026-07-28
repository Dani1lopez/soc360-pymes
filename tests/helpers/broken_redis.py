"""Deterministic AsyncWaiter injectors for outage testing.

PR2 #260: these helpers let tests control Redis deadlines without sleeping
or touching a real Redis instance.  Every waiter propagates
``asyncio.CancelledError`` unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, TypeVar

T = TypeVar("T")


class DeterministicWaiter:
    """AsyncWaiter that completes or times out instantly — no real clock.

    Usage in tests::

        waiter = DeterministicWaiter()
        # Normal path — resolves the awaitable:
        result = await waiter.wait(some_coro(), timeout=5.0)

        waiter = DeterministicWaiter(should_timeout=True)
        # Timeout path — raises TimeoutError without sleeping:
        with pytest.raises(asyncio.TimeoutError):
            await waiter.wait(some_coro(), timeout=1.0)
    """

    def __init__(self, *, should_timeout: bool = False) -> None:
        self._should_timeout = should_timeout
        self._calls: list[tuple[Any, float]] = []

    async def wait(self, awaitable: Awaitable[T], *, timeout: float) -> T:
        self._calls.append((awaitable, timeout))
        if self._should_timeout:
            raise asyncio.TimeoutError()
        return await awaitable


class CancellationWaiter:
    """AsyncWaiter that raises ``asyncio.CancelledError`` immediately.

    Proves that every call site propagates cancellation unchanged
    (spec rev 9 §Cancellation).
    """

    async def wait(self, awaitable: Awaitable[Any], *, timeout: float) -> Any:
        raise asyncio.CancelledError()
