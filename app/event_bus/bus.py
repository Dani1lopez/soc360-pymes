"""EventBus (publisher) class.

Wraps Redis Streams primitives with typed Pydantic event schemas.
"""
from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.event_bus._helpers import (
    _INFLIGHT_DLQ,
    _RETRY_COUNT_KEY,
    _RETRY_HASH_FIELD,
    _retry_key,
    drain_dlq_tasks,
)
from app.event_bus.consumer import EventConsumer
from app.event_schemas import BaseEvent

logger = get_logger(__name__)


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
    async def _dispatch_event(
        event_type: str,
        data: dict,
        redis_client: Redis | None = None,
        message_id: str | None = None,
    ) -> bool:
        """Dispatch a consumed event to the appropriate handler by event_type.

        This method is idempotent, non-throwing, and extensible.
        Malformed events are logged and skipped without breaking the consumer loop.

        Retry logic: If handler raises an exception, retries up to EVENT_MAX_RETRIES times.
        After retry exhaustion, moves event to Dead Letter Queue (DLQ) stream.

        Issue #127: the retry count is persisted to a Redis hash keyed by
        `event_retry:{event_type}:{message_id}` so it survives consumer
        restarts, fail-overs, and rebalances. If `message_id` is not provided
        (e.g. unit tests), the function falls back to the in-memory data dict
        for backward compatibility.

        Args:
            event_type: The dot-namespaced event type, e.g. "auth.login".
            data: The event payload dict as read from Redis stream.
            redis_client: Optional Redis client for DLQ operations and the
                persistent retry counter.
            message_id: Optional Redis stream message id (e.g. "1234-0").
                When provided with a redis_client, the retry count is read
                from and written to a persistent Redis hash instead of the
                local data dict.

        Returns:
            True if handler succeeded (or no handler exists), False if moved to DLQ.
        """
        # Resolve the source of truth for the retry count. When we have a
        # message_id and a redis_client, read the persisted counter so it
        # survives consumer restarts. Otherwise fall back to the in-memory
        # data dict (backward compat for tests that don't provide message_id).
        use_persistent = bool(redis_client and message_id)
        if use_persistent:
            try:
                persisted =                     await redis_client.hget(
                    _retry_key(event_type, message_id), _RETRY_HASH_FIELD
                )
                retry_count = int(persisted) if persisted is not None else 0
            except Exception as exc:
                logger.warning(
                    "retry_count_read_failed_fallback_in_memory",
                    event_type=event_type,
                    error=str(exc),
                )
                retry_count = int(data.get(_RETRY_COUNT_KEY, 0))
        else:
            retry_count = int(data.get(_RETRY_COUNT_KEY, 0))

        async def _cleanup_retry_key() -> None:
            """Best-effort DEL of the persistent retry counter."""
            if not use_persistent:
                return
            try:
                await redis_client.delete(_retry_key(event_type, message_id))
            except Exception as exc:
                logger.warning(
                    "retry_count_cleanup_failed",
                    event_type=event_type,
                    error=str(exc),
                )

        try:
            if event_type == "auth.login":
                EventBus._handle_auth_login(data)
            else:
                logger.debug("no_handler_for_event_type", event_type=event_type)
            # Success: clear the persistent counter so a recycled message_id
            # starts fresh.
            await _cleanup_retry_key()
            return True
        except Exception as exc:
            if retry_count < settings.EVENT_MAX_RETRIES:
                # Retry: persist the incremented counter so it survives a
                # consumer restart. Fall back to in-memory if Redis is down.
                if use_persistent:
                    try:
                        key = _retry_key(event_type, message_id)
                        # HINCRBY is atomic; refresh TTL on each increment.
                        new_count = await redis_client.hincrby(
                            key, _RETRY_HASH_FIELD, 1
                        )
                        await redis_client.expire(
                            key, settings.EVENT_RETRY_TTL_SECONDS
                        )
                        retry_count = new_count
                    except Exception as redis_exc:
                        logger.warning(
                            "retry_count_write_failed_fallback_in_memory",
                            event_type=event_type,
                            error=str(redis_exc),
                        )
                        retry_count += 1
                        data[_RETRY_COUNT_KEY] = retry_count
                else:
                    retry_count += 1
                    data[_RETRY_COUNT_KEY] = retry_count
                logger.warning(
                    "event_handler_retry",
                    event_type=event_type,
                    retry_count=retry_count,
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
                # Clear the persistent counter so a recycled message_id
                # doesn't immediately re-DLQ.
                await _cleanup_retry_key()
                if redis_client is None:
                    # No Redis client available — the DLQ entry would be lost
                    # forever. Surface this as a CRITICAL so ops can alert.
                    logger.critical(
                        "dlq_skipped_no_redis_client",
                        event_type=event_type,
                        retry_count=retry_count,
                    )
                    return False
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
                # Schedule the DLQ write as a Task and hold a strong reference
                # in the module-level registry. Without this strong reference
                # the Task can be garbage-collected before the xadd coroutine
                # resumes, silently dropping the event (issue #126).
                task = asyncio.ensure_future(
                    redis_client.xadd(dlq_stream, dlq_payload)
                )
                _INFLIGHT_DLQ.add(task)
                task.add_done_callback(_INFLIGHT_DLQ.discard)
                # The xadd errors will surface as the task's exception; the
                # done callback in lifespan drain reports them.
                return False

    @staticmethod
    def _handle_auth_login(data: dict) -> None:
        """Handle a consumed auth.login event.

        Logs the event payload in structured form. This handler is
        idempotent and non-throwing.

        Args:
            data: The event payload dict with fields:
                  event_id, event_type, tenant_id, user_id, email_hash,
                  ip_prefix, user_agent, timestamp.
        """
        user_id = data.get("user_id", "unknown")
        email_hash = data.get("email_hash", None)
        ip_prefix = data.get("ip_prefix", None)
        user_agent = data.get("user_agent", None)
        tenant_id = data.get("tenant_id", None)

        user_agent_short = user_agent[:64] if user_agent else user_agent

        logger.info(
            "auth.login_event_consumed",
            user_id=user_id,
            email_hash=email_hash,
            ip_prefix=ip_prefix,
            user_agent=user_agent_short,
            tenant_id=tenant_id,
        )
