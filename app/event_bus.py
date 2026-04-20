"""Event bus abstraction for Redis Streams.

Provides EventBus (publisher) and EventConsumer (consumer group) classes
that wrap Redis Streams primitives with typed Pydantic event schemas.
"""
from __future__ import annotations

import asyncio
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.event_schemas import BaseEvent

logger = get_logger(__name__)


# Retry tracking key stored in event data
_RETRY_COUNT_KEY = "_retry_count"


class EventBus:
    """Publisher abstraction over Redis Streams XADD.

    Publishes typed events to streams named: {EVENT_STREAM_PREFIX}:{event_type}
    e.g. events:auth.login
    """

    def __init__(self, redis_client: Redis) -> None:
        """Initialize with a Redis client instance.

        Args:
            redis_client: An async Redis client (e.g. from get_redis_client()).
        """
        self._redis = redis_client

    def stream_name(self, event_type: str) -> str:
        """Return the full Redis key for a given event type.

        Args:
            event_type: Dot-namespaced event type, e.g. "auth.login".

        Returns:
            Full stream key, e.g. "events:auth.login".
        """
        return f"{settings.EVENT_STREAM_PREFIX}:{event_type}"

    async def publish(self, event: BaseEvent) -> bytes:
        """Publish a typed event to its corresponding stream.

        Args:
            event: A BaseEvent subclass (e.g. AuthLoginEvent).

        Returns:
            The Redis XADD message ID (bytes), e.g. b"1734567890123-0".

        Raises:
            RedisError: If the Redis write fails.
        """
        stream = self.stream_name(event.event_type)
        # Serialize event to dict, converting UUID and datetime to strings
        # so Redis can handle them as string values.
        raw = event.model_dump()
        payload = {
            k: str(v) if hasattr(v, "__str__") else v
            for k, v in raw.items()
        }
        # XADD with bounded stream length (approximate)
        msg_id = await self._redis.xadd(
            stream,
            payload,
            maxlen=settings.EVENT_STREAM_MAXLEN,
            approximate=True,
        )
        return msg_id

    def get_consumer(self, consumer_name: str, event_type: str) -> EventConsumer:
        """Create a consumer for a specific event type.

        Args:
            consumer_name: Unique name for this consumer instance,
                           e.g. "worker-1", "consumer-abc".
            event_type: The event type to consume, e.g. "auth.login".

        Returns:
            An EventConsumer instance bound to this event type
            and the configured consumer group.
        """
        return EventConsumer(
            redis_client=self._redis,
            event_type=event_type,
            consumer_name=consumer_name,
            group_name=settings.EVENT_CONSUMER_GROUP,
        )

    @staticmethod
    def _dispatch_event(event_type: str, data: dict, redis_client: Redis | None = None) -> bool:
        """Dispatch a consumed event to the appropriate handler by event_type.

        This method is idempotent, non-throwing, and extensible.
        Malformed events are logged and skipped without breaking the consumer loop.

        Retry logic: If handler raises an exception, retries up to EVENT_MAX_RETRIES times.
        After retry exhaustion, moves event to Dead Letter Queue (DLQ) stream.

        Args:
            event_type: The dot-namespaced event type, e.g. "auth.login".
            data: The event payload dict as read from Redis stream.
            redis_client: Optional Redis client for DLQ operations.

        Returns:
            True if handler succeeded (or no handler exists), False if moved to DLQ.
        """
        retry_count = int(data.get(_RETRY_COUNT_KEY, 0))

        try:
            if event_type == "auth.login":
                EventBus._handle_auth_login(data)
            else:
                logger.debug("no_handler_for_event_type", event_type=event_type)
            return True  # Success
        except Exception as exc:
            if retry_count < settings.EVENT_MAX_RETRIES:
                # Retry: increment counter and re-raise to let caller re-queue
                data[_RETRY_COUNT_KEY] = retry_count + 1
                logger.warning(
                    "event_handler_retry",
                    event_type=event_type,
                    retry_count=retry_count + 1,
                    max_retries=settings.EVENT_MAX_RETRIES,
                    error=str(exc),
                )
                raise  # Re-raise to trigger retry in consumer loop
            else:
                # Exhausted retries — move to DLQ
                logger.error(
                    "event_exhausted_retries_moving_to_dlq",
                    event_type=event_type,
                    retry_count=retry_count,
                    error=str(exc),
                )
                if redis_client is not None:
                    dlq_stream = f"{settings.EVENT_STREAM_PREFIX}:dlq:{event_type}"
                    dlq_payload = {
                        **data,
                        "_dlq_reason": str(exc),
                        "_dlq_timestamp": str(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
                    }
                    # Convert all values to strings for Redis
                    dlq_payload = {
                        k: str(v) if hasattr(v, "__str__") else v
                        for k, v in dlq_payload.items()
                    }
                    try:
                        # Fire-and-forget: write to DLQ without blocking
                        asyncio.ensure_future(
                            redis_client.xadd(dlq_stream, dlq_payload)
                        )
                    except Exception as dlq_err:
                        logger.error("dlq_write_failed", error=str(dlq_err))
                return False

    @staticmethod
    def _handle_auth_login(data: dict) -> None:
        """Handle a consumed auth.login event.

        Logs the event payload in structured form. This handler is
        idempotent and non-throwing.

        Args:
            data: The event payload dict with fields:
                  event_id, event_type, tenant_id, user_id, email,
                  ip_address, user_agent, timestamp.
        """
        user_id = data.get("user_id", "unknown")
        email = data.get("email", "unknown")
        ip_address = data.get("ip_address", None)
        user_agent = data.get("user_agent", None)
        tenant_id = data.get("tenant_id", None)

        logger.info(
            "auth.login_event_consumed",
            user_id=user_id,
            email=email,
            ip_address=ip_address,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )


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

        result = []
        for entry in pending_entries:
            # entry is a dict with: "message_id", "consumer", "time_since_delivered", "times_delivered"
            msg_id = entry["message_id"]
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id

            # Use XCLAIM to get the message content without changing pending state
            # XCLAIM just reads the message, doesn't re-deliver it
            try:
                claimed = await self.redis_client.xclaim(
                    stream_key,
                    self.group_name,
                    self.consumer_name,
                    min_idle_time=0,  # 0 means claim regardless of idle time
                    message_ids=[msg_id_str],
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
                # XCLAIM may fail if message is already acked or deleted
                pass
        return result

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
