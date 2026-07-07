from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.middleware import HTTPSRedirectMiddleware, SecurityHeadersMiddleware
from app.core.redis import ping_redis_with_retry, close_pool, get_redis_client
from app.event_bus import EventConsumer, EventBus, drain_dlq_tasks
from app.modules.auth.router import router as auth_router
from app.modules.tenants.router import router as tenants_router
from app.modules.users.router import router as users_router

setup_logging()
logger = get_logger(__name__)

APP_VERSION = "0.1.0"

# Maximum milliseconds XREADGROUP blocks waiting for new messages (issue #133).
# Replaces the old asyncio.sleep(1) busy-poll.
_XREADGROUP_BLOCK_MS: int = 5000

# Backoff after an unexpected error in the consumer loop.
# Intentionally short — just enough to avoid a tight spin if Redis is flaky.
_ERROR_BACKOFF_SECONDS: float = 0.1


async def _consumer_loop(
    *,
    redis_client: Redis,
    consumer: EventConsumer,
    stop_event: asyncio.Event,
) -> None:
    """Background loop that processes events until stop_event is set.

    Recovery + blocking read pattern (issue #133):
      1. Each iteration first drains pending (unacked) messages via
         ``read_pending()`` so messages stranded by a previous crash are
         not lost.
      2. When no pending messages remain, ``read_new(block=_XREADGROUP_BLOCK_MS)``
         blocks for up to 5 s waiting for new messages — eliminating the
         old 1 s busy-poll.

    Closes the Redis client exactly once on exit (normal, exception, or
    cancellation).  Re-raises asyncio.CancelledError so the asyncio task
    machinery handles it correctly.
    """
    try:
        while not stop_event.is_set():
            try:
                # Step 1 — recover any pending (unacked) messages first.
                # read_pending() is non-blocking; when there are no pending
                # entries the XPENDING call returns an empty list quickly.
                pending = await consumer.read_pending()
                if pending:
                    messages = pending
                else:
                    # Step 2 — no pending work; block for new messages.
                    messages = await consumer.read_new(block=_XREADGROUP_BLOCK_MS)

                for msg in messages:
                    raw_msg_id = msg["message_id"]
                    msg_id = raw_msg_id.decode() if isinstance(raw_msg_id, bytes) else raw_msg_id
                    await EventBus._dispatch_event(
                        "auth.login",
                        msg.get("data", {}),
                        redis_client,
                        message_id=msg_id,
                    )
                    await consumer.ack(msg["message_id"])
            except asyncio.CancelledError:
                logger.info("event_consumer_loop_cancelled")
                raise
            except Exception:
                # Log unexpected errors and back off briefly; do not busy-loop.
                logger.exception("event_consumer_loop_error")
                await asyncio.sleep(_ERROR_BACKOFF_SECONDS)
    finally:
        # Always close the redis client, even on cancellation or exception.
        await redis_client.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    #Inicialización de servicios al arrancar
    logger.info("soc360.startup", environment=settings.ENVIRONMENT)

    # Guard: MockLLMProvider must never run in production (issue #139).
    # If LLM_PROVIDER=mock accidentally lands in prod, the system would
    # "work" but return fake vulnerability analysis — undetectable without
    # this explicit check.
    if settings.ENVIRONMENT == "production" and settings.LLM_PROVIDER == "mock":
        raise RuntimeError(
            "MockLLMProvider is not allowed in production. "
            "Set LLM_PROVIDER to a real provider (groq, openai, anthropic, etc.)."
        )

    # Log the active LLM provider at startup for operational visibility.
    from app.core.llm import get_llm_provider
    active_provider = get_llm_provider()
    logger.warning(
        "soc360.llm_provider_active",
        provider=type(active_provider).__name__,
        provider_name=settings.LLM_PROVIDER,
    )

    #Verificar Redis — retry on transient blips (issue #128)
    if not await ping_redis_with_retry(
        max_attempts=settings.REDIS_STARTUP_MAX_ATTEMPTS,
        backoff_base_seconds=settings.REDIS_STARTUP_BACKOFF_BASE_SECONDS,
    ):
        raise RuntimeError(
            f"No se pudo conectar a Redis tras {settings.REDIS_STARTUP_MAX_ATTEMPTS} intentos"
        )
    logger.info("soc360.redis_connected")

    # Start event consumer background task
    redis_client = await get_redis_client()
    consumer = EventConsumer(
        redis_client=redis_client,
        event_type="auth.login",
        consumer_name="soc360-lifespan",
        group_name=settings.EVENT_CONSUMER_GROUP,
    )
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        _consumer_loop(
            redis_client=redis_client,
            consumer=consumer,
            stop_event=stop_event,
        ),
        name="event-consumer",
    )

    yield

    #Liberación de recursos al apagar
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
    # Drain any in-flight DLQ write tasks before closing the Redis pool
    # (issue #126). A bounded timeout prevents a slow write from blocking
    # shutdown forever.
    await drain_dlq_tasks(timeout=2.0)
    await close_pool()
    # Close the LLM provider's HTTP connection pool (issue #194).
    from app.core.llm import get_llm_provider
    from app.core.llm.providers import _BaseHTTPProvider
    provider = get_llm_provider()
    if isinstance(provider, _BaseHTTPProvider):
        await provider.close()
    logger.info("soc360.shutdown")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="SOC as a Service para pequeñas y medianas empresas",
        version=APP_VERSION,
        docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
        lifespan=lifespan,
    )
    
    #Guardia: credentials + wildcard es inseguro
    if "*" in settings.CORS_ORIGINS:
        raise ValueError(
            "CORS_ORIGINS no puede contener '*' cuando allow_credentials=True"
        )
    
    #Filtrado de dominios permitidos
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    
    #Routers
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    
    #Endpoint para verificar que el servidor está vivo
    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "version": APP_VERSION}
    
    return app


app = create_app()
