# Code Review Rules

## Python
- Use `from __future__ import annotations` first in every `.py` file.
- Prefer explicit types and async-safe code.
- Preserve existing project conventions and test patterns.

## Tests
- Keep unit tests isolated and deterministic.
- Prefer focused assertions over no-op placeholders.

## Logging
- Never log secrets, API keys, or raw sensitive payloads.
- Use the shared project logging conventions when available.
