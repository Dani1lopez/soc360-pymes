from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.middleware import HTTPSRedirectMiddleware, SecurityHeadersMiddleware
from app.core.redis import ping_redis_with_retry, close_pool, get_redis_client
from app.event_bus import EventConsumer, drain_dlq_tasks
from app.modules.auth.router import router as auth_router
from app.modules.tenants.router import router as tenants_router
from app.modules.users.router import router as users_router

setup_logging()
logger = get_logger(__name__)

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    #Inicialización de servicios al arrancar
    logger.info("soc360.startup", environment=settings.ENVIRONMENT)

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

    async def _consumer_loop() -> None:
        """Background loop that processes events until stop_event is set."""
        while not stop_event.is_set():
            try:
                pending = await consumer.read_pending()
                for msg in pending:
                    from app.event_bus import EventBus
                    # Normalize message_id (Redis returns bytes) and pass it
                    # to dispatch so the retry counter is persisted (issue #127).
                    raw_msg_id = msg["message_id"]
                    msg_id = raw_msg_id.decode() if isinstance(raw_msg_id, bytes) else raw_msg_id
                    await EventBus._dispatch_event(
                        "auth.login",
                        msg.get("data", {}),
                        redis_client,
                        message_id=msg_id,
                    )
                    await consumer.ack(msg["message_id"])
            except Exception:
                logger.exception("event_consumer_loop_error")
            await asyncio.sleep(1)

    task = asyncio.create_task(_consumer_loop(), name="event-consumer")

    yield

    #Liberación de recursos al apagar
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
    # Drain DLQ write Tasks so events dispatched right before shutdown
    # actually land in Redis (issue #126). Must run BEFORE close_pool(),
    # otherwise the redis client is closed before the DLQ xadd can flush.
    await drain_dlq_tasks(timeout=2.0)
    await close_pool()
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
