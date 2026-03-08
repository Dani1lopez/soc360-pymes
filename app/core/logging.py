import logging
import structlog
from app.core.config import settings

_SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "authorization"}

def _filter_sensitive_data(logger, method, event_dict):
    """Redacta campos sensibles para que nunca aparezcan en logs"""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict

def setup_logging() -> None:
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.ENVIRONMENT == "development"
        else structlog.processors.JSONRenderer()
    )
    
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _filter_sensitive_data,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    log_level = logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO
    logging.basicConfig(level=log_level)

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)