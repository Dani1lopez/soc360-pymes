# LLM Abstraction — Developer Notes

## Overview

The LLM abstraction layer (`app/core/llm.py`) provides a pluggable async interface for multiple LLM providers. The public interface is the `@runtime_checkable` `LLMProvider` protocol.

## Provider Selection

Providers are selected via the `LLM_PROVIDER` environment variable. Supported providers:

| Provider | Class | Notes |
|----------|-------|-------|
| `groq` | `OpenAICompatProvider` | Default in development |
| `ollama` | `OpenAICompatProvider` | Local; no API key required |
| `openai` | `OpenAICompatProvider` | Uses `OPENAI_API_KEY` |
| `anthropic` | `AnthropicProvider` | Uses `ANTHROPIC_API_KEY` |
| `gemini` | `GeminiProvider` | Uses `GEMINI_API_KEY` |
| `mistral` | `OpenAICompatProvider` | Uses `MISTRAL_API_KEY` |
| `cohere` | `OpenAICompatProvider` | Uses `COHERE_API_KEY` |
| `together` | `OpenAICompatProvider` | Uses `TOGETHER_API_KEY` |
| `huggingface` | `OpenAICompatProvider` | Uses `HUGGINGFACE_API_KEY` |

Factory: `_create_provider(name)` → raises `LLMResponseError` on unknown provider (safe — no key in message).

Singleton: `get_llm_provider()` caches one instance per provider name per process.

## Mock Provider

`MockLLMProvider` is a deterministic test double. It:
- Conforms to `LLMProvider` protocol at runtime
- Makes **zero** network calls
- Accepts `response_text` and optional `delay_seconds`

```python
from app.core.llm import MockLLMProvider

# In tests:
mock = MockLLMProvider(response_text='{"vuln_type": "xss", ...}')
result = await mock.complete(prompt="...", max_tokens=500, temperature=0.0)
```

For FastAPI dependency override:
```python
app.dependency_overrides[get_llm_provider] = lambda: mock_provider
```

## Contract Boundary

### Provider → Downstream

`LLMProvider.complete()` returns **raw text** (a `str`). The downstream AI Analysis node is responsible for:
- Parsing JSON if the provider returned JSON-formatted text
- Handling plain text / empty responses gracefully

### EnrichedFinding & Fallback

`EnrichedFinding` (`app/core/contracts.py`) is the output type. On LLM failure:

```python
fallback = finding.to_fallback()
# ai_enriched=False, needs_ai_retry=True
```

The `needs_ai_retry=True` flag signals that the finding should be re-processed by the LLM later.

## Error Safety

No API keys or secrets appear in error messages. All `LLMError` subclasses sanitize their `detail` field before surfacing.

## Adding a New Provider

1. Create a new class implementing `LLMProvider.complete(prompt, max_tokens, temperature) -> str`
2. Register it in `_PROVIDER_CLASSES` dict in `llm.py`
3. Add provider config in `_create_provider()`
4. Add `model` validator in `config.py` if needed
5. Add tests (see `tests/unit/test_llm_*.py`)
