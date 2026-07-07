"""LLM test doubles — mock providers for unit tests."""
from __future__ import annotations

import asyncio


class MockLLMProvider:
    """Async test double for LLM providers.

    Returns a pre-configured response after an optional delay.
    No network calls are made. Satisfies the LLMProvider protocol
    at runtime so it can be substituted for any concrete provider.
    """

    def __init__(
        self,
        response_text: str = "mock response",
        delay_seconds: float = 0.0,
    ) -> None:
        self._response_text = response_text
        self._delay_seconds = delay_seconds

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Return the configured response text after the configured delay."""
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
        return self._response_text
