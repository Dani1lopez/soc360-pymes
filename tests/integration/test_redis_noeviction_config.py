"""Static contract tests for the shared Redis safety configuration."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _redis_service_block() -> str:
    compose = (ROOT / "docker-compose.yml").read_text()
    return compose.split("\n  redis:\n", 1)[1].split("\n  toxiproxy:", 1)[0]


def test_shared_redis_uses_noeviction_and_external_limits() -> None:
    block = _redis_service_block()

    assert "--maxmemory-policy noeviction" in block
    assert not any(
        policy in block for policy in ("allkeys-lru", "volatile-lru", "volatile-ttl")
    )
    assert "--maxmemory ${REDIS_MAXMEMORY:?REDIS_MAXMEMORY must be set}" in block
    assert "mem_limit: ${REDIS_CONTAINER_MEMORY_LIMIT:?REDIS_CONTAINER_MEMORY_LIMIT must be set}" in block
    maxmemory_value = block.split("--maxmemory ", 1)[1].splitlines()[0].strip()
    container_limit_value = block.split("mem_limit: ", 1)[1].splitlines()[0].strip()
    assert maxmemory_value.startswith("${REDIS_MAXMEMORY:")
    assert container_limit_value.startswith("${REDIS_CONTAINER_MEMORY_LIMIT:")
    assert maxmemory_value != container_limit_value
    assert "--maxmemory [0-9]" not in block


def test_compose_documents_environment_owned_memory_values() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    env_example = (ROOT / ".env.example").read_text()

    assert "environment-owned" in compose
    assert "must be measured per environment" in compose
    assert "test values are never production sizing" in compose
    assert "REDIS_MAXMEMORY" in env_example
    assert "REDIS_CONTAINER_MEMORY_LIMIT" in env_example
    assert "development-representative" in env_example
    assert "NOT production sizing" in env_example


def test_pressure_compose_is_not_part_of_shared_service() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "redis-pressure" not in compose
