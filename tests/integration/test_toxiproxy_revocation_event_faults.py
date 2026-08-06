"""Serial post-startup Toxiproxy characterization for PR8 primitives.

The shared fixture resets toxics, pools, and disposable Redis state.
"""

import asyncio
from unittest.mock import patch

import pytest
from app.core.config import settings
from app.core.exceptions import RedisOutageError
from app.core.security import revoke_all_user_access_tokens
from app.event_bus import EventBus, EventConsumer
from app.event_bus._helpers import _RETRY_COUNT_KEY
from app.event_schemas import AuthLoginEvent
from tests.integration import test_toxiproxy_scan_lock_faults as toxiproxy

pytestmark = [pytest.mark.integration, pytest.mark.toxiproxy]


async def _close(client) -> None:
    await asyncio.wait_for(client.aclose(), timeout=toxiproxy.CLEANUP_TIMEOUT_SECONDS)


async def _seed_pending(group: str) -> tuple[str, dict]:
    client = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
    try:
        await asyncio.wait_for(
            EventBus(client).publish(
                AuthLoginEvent(
                    event_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    user_id="pr8-user",
                    email_hash="c" * 32,
                )
            ),
            timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS,
        )
        consumer = EventConsumer(client, "auth.login", "pr8-worker", group)
        messages = await asyncio.wait_for(
            consumer.read_new(block=100), timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS
        )
        assert len(messages) == 1
        message = messages[0]
        return message["message_id"], message["data"]
    finally:
        await _close(client)


async def _pending_count(group: str) -> int:
    client = toxiproxy._redis_client(toxiproxy.DIRECT_REDIS_PORT)
    try:
        return len(
            await asyncio.wait_for(
                client.xpending_range("events:auth.login", group, "0", "+", 100),
                timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS,
            )
        )
    finally:
        await _close(client)


async def test_post_startup_drop_bulk_revocation_retains_active_jtis(
    app_via_proxy, toxiproxy_client
) -> None:
    seed = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
    try:
        await seed.sadd("active_jtis:pr8-drop", "jti-drop-a", "jti-drop-b")
    finally:
        await _close(seed)

    async with toxiproxy._connection_drop(toxiproxy_client):
        failing = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
        try:
            with pytest.raises(RedisOutageError):
                await asyncio.wait_for(
                    revoke_all_user_access_tokens("pr8-drop", failing, 60),
                    timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS,
                )
        finally:
            await _close(failing)
        direct = toxiproxy._redis_client(toxiproxy.DIRECT_REDIS_PORT)
        try:
            assert set(await direct.smembers("active_jtis:pr8-drop")) == {
                "jti-drop-a",
                "jti-drop-b",
            }
        finally:
            await _close(direct)


@pytest.mark.parametrize("operation", ["read_pending", "ack"])
async def test_post_startup_drop_classifies_stream_boundary(
    operation: str,
    app_via_proxy,
    toxiproxy_client,
) -> None:
    group = f"pr8-{operation}-group"
    message_id, _ = await _seed_pending(group)
    async with toxiproxy._connection_drop(toxiproxy_client):
        failing = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
        consumer = EventConsumer(failing, "auth.login", "pr8-worker", group)
        try:
            with pytest.raises(RedisOutageError):
                operation_call = (
                    consumer.read_pending()
                    if operation == "read_pending"
                    else consumer.ack(message_id)
                )
                await asyncio.wait_for(
                    operation_call, timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS
                )
        finally:
            await _close(failing)


async def test_post_startup_drop_dlq_failure_retains_pel_until_recovery(
    app_via_proxy, toxiproxy_client
) -> None:
    group = "pr8-dlq-group"
    message_id, data = await _seed_pending(group)
    retry = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
    try:
        await retry.hset(
            f"event_retry:auth.login:{message_id}",
            mapping={"retry_count": settings.EVENT_MAX_RETRIES},
        )
    finally:
        await _close(retry)

    try:
        await asyncio.wait_for(
            toxiproxy_client.add_connection_drop(1.0),
            timeout=toxiproxy.CLEANUP_TIMEOUT_SECONDS,
        )
        failing = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
        try:
            with patch.object(EventBus, "_handle_auth_login", side_effect=RuntimeError):
                with pytest.raises(RedisOutageError):
                    data[_RETRY_COUNT_KEY] = settings.EVENT_MAX_RETRIES
                    await asyncio.wait_for(
                        EventBus._dispatch_event(
                            "auth.login", data, failing, message_id
                        ),
                        timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS,
                    )
        finally:
            await _close(failing)
        assert await _pending_count(group) == 1

        await asyncio.wait_for(
            toxiproxy_client.reset_toxics(), timeout=toxiproxy.CLEANUP_TIMEOUT_SECONDS
        )
        await asyncio.wait_for(
            toxiproxy.close_pool(), timeout=toxiproxy.CLEANUP_TIMEOUT_SECONDS
        )
        healthy = toxiproxy._redis_client(toxiproxy.PROXY_PORT)
        try:
            consumer = EventConsumer(
                healthy, "auth.login", "pr8-recovery-worker", group
            )
            pending = await asyncio.wait_for(
                consumer.read_pending(), timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS
            )
            assert len(pending) == 1
            with patch.object(EventBus, "_handle_auth_login", side_effect=RuntimeError):
                eligible = await asyncio.wait_for(
                    EventBus._dispatch_event(
                        "auth.login", pending[0]["data"], healthy, message_id
                    ),
                    timeout=toxiproxy.REQUEST_TIMEOUT_SECONDS,
                )
            assert eligible is True
            await consumer.ack(pending[0]["message_id"])
            assert await _pending_count(group) == 0
            assert len(await healthy.xrange("events:dlq:auth.login")) == 1
        finally:
            await _close(healthy)
    finally:
        await toxiproxy._reset_proxy_state(toxiproxy_client)
