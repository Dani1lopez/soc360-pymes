from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import setup_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app):
    #Inicialización de servicios al arrancar
    setup_logging()
    logger.info("soc360.startup", environment=settings.ENVIRONMENT)
    
    yield
    
    #Liberación de recursos al apagar
    logger.info("soc360.shutdown")

def create_app() -> FastAPI:
    app = FastAPI(
        title="SOC 360 PYMEs",
        description="SOC as a Service para pequeñas y medianas empresas",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    
    #Filtrado de dominios permitidos
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    
    #Endpoint para verificar que el servidor está vivo
    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "version": "0.1.0"}
    
    return app

app = create_app()