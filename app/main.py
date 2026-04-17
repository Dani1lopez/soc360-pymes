from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.redis import ping_redis, close_pool
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
    
    #Verificar Redis
    if not await ping_redis():
        raise RuntimeError("No se puede conectar a Redis")
    logger.info("soc360.redis_connected")
    
    yield
    
    #Liberación de recursos al apagar
    await close_pool()
    logger.info("soc360.shutdown")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="SOC as a Service para pequeñas y medianas empresas",
        version=APP_VERSION,
        docs_url="/api/docs",
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
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