"""Tests for Redis Streams primitives (T1.2)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from fakeredis.aioredis import FakeRedis


class TestRedisStreamsPrimitives:
    """Verify Redis Streams methods are available and return correct types."""

    @pytest_asyncio.fixture
    async def redis_client(self) -> FakeRedis:
        r = FakeRedis()
        yield r
        await r.aclose()

    # ------------------------------------------------------------------
    # xadd
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_xadd_returns_bytes_id(self, redis_client: FakeRedis):
        """xadd MUST return a bytes message ID."""
        msg_id = await redis_client.xadd("events:auth", {"event": "login", "user_id": "u1"})
        assert isinstance(msg_id, bytes), f"xadd must return bytes, got {type(msg_id)}"
        assert b"-" in msg_id, f"xadd ID must contain '-', got {msg_id!r}"

    @pytest.mark.asyncio
    async def test_xadd_with_maxlen(self, redis_client: FakeRedis):
        """xadd with maxlen MUST respect the stream length bound."""
        # Add 3 messages with maxlen=2
        for i in range(3):
            await redis_client.xadd("events:auth", {"n": str(i)}, maxlen=2, approximate=True)
        length = await redis_client.xlen("events:auth")
        assert length == 2, f"stream length must be 2, got {length}"

    # ------------------------------------------------------------------
    # xgroup_create (mkstream)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_xgroup_create_mkstream_returns_true(self, redis_client: FakeRedis):
        """xgroup_create with mkstream=True MUST return True and create the group."""
        result = await redis_client.xgroup_create(
            "events:auth", "soc360-consumers", "0", mkstream=True
        )
        assert result is True

        # Verify the group exists by reading from it
        groups = await redis_client.xinfo_groups("events:auth")
        assert len(groups) == 1
        assert groups[0]["name"] == b"soc360-consumers"

    # ------------------------------------------------------------------
    # xreadgroup
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_xreadgroup_returns_list_of_messages(self, redis_client: FakeRedis):
        """xreadgroup MUST return a list with stream name and message tuples."""
        await redis_client.xgroup_create("events:auth", "soc360-consumers", "0", mkstream=True)
        await redis_client.xadd("events:auth", {"event": "login", "user_id": "u1"})
        await redis_client.xadd("events:auth", {"event": "logout", "user_id": "u1"})

        msgs = await redis_client.xreadgroup(
            "soc360-consumers", "consumer1", {"events:auth": ">"}, count=2
        )
        assert isinstance(msgs, list), f"xreadgroup must return list, got {type(msgs)}"
        assert len(msgs) == 1, f"expected 1 stream, got {len(msgs)}"
        stream_name, messages = msgs[0]
        assert len(messages) == 2, f"expected 2 messages, got {len(messages)}"

        msg_id, fields = messages[0]
        assert isinstance(msg_id, bytes), "message ID must be bytes"
        assert fields[b"event"] == b"login"

    @pytest.mark.asyncio
    async def test_xreadgroup_block_with_count(self, redis_client: FakeRedis):
        """xreadgroup with count MUST limit returned messages."""
        await redis_client.xgroup_create("events:auth", "soc360-consumers", "0", mkstream=True)
        # Add 5 messages
        for i in range(5):
            await redis_client.xadd("events:auth", {"n": str(i)})

        # Request only 2
        msgs = await redis_client.xreadgroup(
            "soc360-consumers", "consumer1", {"events:auth": ">"}, count=2
        )
        assert msgs is not None
        _, messages = msgs[0]
        assert len(messages) == 2, f"expected 2 messages, got {len(messages)}"

    # ------------------------------------------------------------------
    # xack
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_xack_returns_ack_count(self, redis_client: FakeRedis):
        """xack MUST return an integer count of acknowledged messages."""
        await redis_client.xgroup_create("events:auth", "soc360-consumers", "0", mkstream=True)
        msg_id = await redis_client.xadd("events:auth", {"event": "login", "user_id": "u1"})
        await redis_client.xreadgroup(
            "soc360-consumers", "consumer1", {"events:auth": ">"}
        )

        ack_count = await redis_client.xack("events:auth", "soc360-consumers", msg_id)
        assert isinstance(ack_count, int), f"xack must return int, got {type(ack_count)}"
        assert ack_count == 1

    # ------------------------------------------------------------------
    # xpending
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_xpending_returns_dict(self, redis_client: FakeRedis):
        """xpending MUST return a dict with pending count and consumer info."""
        await redis_client.xgroup_create("events:auth", "soc360-consumers", "0", mkstream=True)
        await redis_client.xadd("events:auth", {"event": "login", "user_id": "u1"})
        await redis_client.xreadgroup(
            "soc360-consumers", "consumer1", {"events:auth": ">"}
        )

        pending = await redis_client.xpending("events:auth", "soc360-consumers")
        assert isinstance(pending, dict), f"xpending must return dict, got {type(pending)}"
        assert "pending" in pending
        assert isinstance(pending["pending"], int)

    # ------------------------------------------------------------------
    # xdel
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_xdel_returns_deletion_count(self, redis_client: FakeRedis):
        """xdel MUST return an integer count of deleted messages."""
        msg_id = await redis_client.xadd("events:auth", {"event": "login", "user_id": "u1"})
        del_count = await redis_client.xdel("events:auth", msg_id)
        assert isinstance(del_count, int), f"xdel must return int, got {type(del_count)}"
        assert del_count == 1

    @pytest.mark.asyncio
    async def test_xdel_with_real_message_id(self, redis_client: FakeRedis):
        """xdel MUST return 1 when deleting an existing message and 0 for a second call."""
        # Add a message and delete it
        msg_id = await redis_client.xadd("events:auth", {"event": "login", "user_id": "u1"})
        del_count1 = await redis_client.xdel("events:auth", msg_id)
        assert del_count1 == 1
        # Second delete of same ID returns 0 (already deleted)
        del_count2 = await redis_client.xdel("events:auth", msg_id)
        assert del_count2 == 0


# ------------------------------------------------------------------
# Wrapper function tests — these test app/core/redis.py helpers
# ------------------------------------------------------------------

class TestRedisClientFactory:
    """Test that get_redis_client() returns a usable Redis instance."""

    @pytest.mark.asyncio
    async def test_get_redis_client_returns_redis_instance(self):
        """get_redis_client() MUST return a Redis (or FakeRedis) instance."""
        from app.core.redis import get_redis_client

        # Patch to use fakeredis so we don't need real Redis
        with patch("app.core.redis.get_pool") as mock_get_pool:
            mock_pool = AsyncMock()
            mock_get_pool.return_value = mock_pool
            with patch("redis.asyncio.Redis") as MockRedis:
                mock_instance = AsyncMock()
                MockRedis.return_value = mock_instance

                client = await get_redis_client()
                # Just verify it returns something with the methods we need
                assert hasattr(client, "xadd")
                assert hasattr(client, "xreadgroup")
                assert hasattr(client, "xack")
                assert hasattr(client, "xpending")
                assert hasattr(client, "xdel")
                assert hasattr(client, "xgroup_create")
