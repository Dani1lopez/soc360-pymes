"""EventConsumer — consumer group abstraction over Redis Streams."""
from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EventConsumer:
    """Consumer abstraction over Redis Streams consumer groups.

    Reads pending messages, acknowledges them, or deletes them from the stream.
    """

    def __init__(
        self,
        redis_client: Redis,
        event_type: str,
        consumer_name: str,
        group_name: str,
    ) -> None:
        """Initialize a consumer.

        Args:
            redis_client: An async Redis client.
            event_type: Event type this consumer processes, e.g. "auth.login".
            consumer_name: Unique identifier for this consumer within the group.
            group_name: Consumer group name, e.g. "soc360-consumers".
        """
        self.redis_client = redis_client
        self.event_type = event_type
        self.consumer_name = consumer_name
        self.group_name = group_name

    def _stream_key(self) -> str:
        """Return the full stream key for this consumer's event type."""
        return f"{settings.EVENT_STREAM_PREFIX}:{self.event_type}"

    async def _ensure_group_exists(self) -> None:
        """Create the consumer group with MKSTREAM if it doesn't exist.

        This is safe to call on every read; Redis returns True if the group
        was created, raises ResponseError if it already exists.
        """
        try:
            await self.redis_client.xgroup_create(
                self._stream_key(),
                self.group_name,
                "0",  # start reading from the beginning (or use "$" for new only)
                mkstream=True,
            )
        except Exception:
            # Group already exists — safe to ignore
            pass

    async def read_pending(self) -> list[dict]:
        """Read pending messages for this consumer in this group.

        Pending messages are those that have been delivered but not yet acknowledged.

        Also monitors consumer lag: if pending count exceeds EVENT_PENDING_LAG_THRESHOLD,
        logs a warning for operational visibility.

        Returns:
            List of dicts, each containing:
              - "message_id": bytes
              - "data": dict with event fields
            Returns an empty list if no pending messages exist.
        """
        await self._ensure_group_exists()
        stream_key = self._stream_key()

        # Get detailed pending entries: XPENDING stream group [start end count consumer]
        # Use "0" + "+" to get all pending entries
        # Signature: xpending_range(stream, group, min_id, max_id, count)
        pending_entries = await self.redis_client.xpending_range(
            stream_key,
            self.group_name,
            "0",
            "+",
            100,
        )

        # Consumer lag monitoring: warn if pending entries exceed threshold
        pending_count = len(pending_entries)
        if pending_count > settings.EVENT_PENDING_LAG_THRESHOLD:
            logger.warning(
                "consumer_lag_exceeded_threshold",
                event_type=self.event_type,
                consumer_name=self.consumer_name,
                pending_count=pending_count,
                lag_threshold=settings.EVENT_PENDING_LAG_THRESHOLD,
            )

        if not pending_entries:
            return []

        # Batch XCLAIM: claim all pending messages in a single round-trip
        # instead of O(n) individual XCLAIM calls (issue #100).
        # This reduces Redis round-trips from N to 1 for N pending messages.
        msg_ids = []
        for entry in pending_entries:
            msg_id = entry["message_id"]
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            msg_ids.append(msg_id_str)

        result = []
        try:
            # Single XCLAIM call with all message_ids (batch operation)
            claimed = await self.redis_client.xclaim(
                stream_key,
                self.group_name,
                self.consumer_name,
                min_idle_time=0,  # 0 means claim regardless of idle time
                message_ids=msg_ids,
            )
            if claimed:
                for cid, fields in claimed:
                    str_fields = {
                        k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                        for k, v in fields.items()
                    }
                    result.append({
                        "message_id": cid if isinstance(cid, bytes) else cid.encode(),
                        "data": str_fields,
                    })
        except Exception:
            # XCLAIM may fail if messages are already acked or deleted.
            # Log for observability but don't crash — the consumer loop
            # will retry on the next iteration.
            logger.warning(
                "batch_xclaim_failed",
                event_type=self.event_type,
                consumer_name=self.consumer_name,
                message_count=len(msg_ids),
            )
        return result

    async def read_new(self, block: int = 5000) -> list[dict]:
        """Read new (undelivered) messages using XREADGROUP with blocking.

        Uses XREADGROUP with '>' to read only new messages (never delivered
        before to any consumer in the group). Blocks for up to `block`
        milliseconds waiting for new messages, replacing the old busy-poll
        pattern (issue #133).

        Args:
            block: Maximum milliseconds to block waiting for messages.
                   Defaults to 5000 (5 seconds).

        Returns:
            List of dicts, each containing:
              - "message_id": bytes
              - "data": dict with event fields
            Returns an empty list if no messages available within the timeout.
        """
        await self._ensure_group_exists()
        stream_key = self._stream_key()

        result = await self.redis_client.xreadgroup(
            self.group_name,
            self.consumer_name,
            {stream_key: ">"},
            count=10,
            block=block,
        )

        if not result:
            return []

        messages: list[dict] = []
        for _stream_name, stream_messages in result:
            for msg_id, fields in stream_messages:
                str_fields = {
                    k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in fields.items()
                }
                messages.append({
                    "message_id": msg_id if isinstance(msg_id, bytes) else msg_id.encode(),
                    "data": str_fields,
                })
        return messages

    async def reconnect_and_resume(self) -> list[dict]:
        """Reconnect to Redis and resume from last acknowledged position.

        This handles temporary Redis connection drops by:
        1. Re-calling _ensure_group_exists() to re-establish consumer group
        2. Reading pending entries that may have been missed during disconnect

        Returns:
            List of pending messages that were unacknowledged during disconnect.
        """
        logger.info(
            "consumer_reconnecting",
            event_type=self.event_type,
            consumer_name=self.consumer_name,
        )
        # Re-establish the consumer group (idempotent)
        await self._ensure_group_exists()
        # Read any pending messages that need processing
        pending = await self.read_pending()
        logger.info(
            "consumer_resumed",
            event_type=self.event_type,
            consumer_name=self.consumer_name,
            pending_count=len(pending),
        )
        return pending

    async def ack(self, message_id: str | bytes) -> None:
        """Acknowledge a message, removing it from the pending list.

        Args:
            message_id: The message ID to acknowledge (as returned by read_pending).
        """
        stream_key = self._stream_key()
        if isinstance(message_id, str):
            message_id = message_id.encode()
        await self.redis_client.xack(stream_key, self.group_name, message_id)

    async def delete(self, message_id: str | bytes) -> None:
        """Delete a message from the stream entirely.

        Args:
            message_id: The message ID to delete.
        """
        stream_key = self._stream_key()
        if isinstance(message_id, str):
            message_id = message_id.encode()
        await self.redis_client.xdel(stream_key, message_id)
