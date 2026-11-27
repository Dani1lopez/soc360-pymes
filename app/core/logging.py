from __future__ import annotations

import ipaddress
import logging
from typing import Any

import structlog

from app.core.config import settings

_SENSITIVE_KEYS = {
    "password",
    "current_password",
    "new_password",
    "password_hash",
    "token",
    "refresh_token",
    "access_token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
}
_IP_KEYS = {"ip", "client_ip", "request_ip"}
_EMAIL_KEYS = {"email", "user_email"}
_MAX_REDACTION_DEPTH = 5


def _mask_ip(value: Any) -> Any:
    """Mask IPv4/IPv6 addresses while keeping non-string/empty values safe."""
    if not isinstance(value, str) or not value.strip():
        return value
    raw = value.strip()
    try:
        addr = ipaddress.ip_address(raw)
        if isinstance(addr, ipaddress.IPv4Address):
            octets = raw.split(".")
            return f"{octets[0]}.{octets[1]}.***.***"
        groups = ipaddress.IPv6Address(int(addr)).exploded.split(":")
        return f"{groups[0]}:{groups[1]}:***"
    except Exception:
        return "***"


def _mask_email(value: Any) -> Any:
    """Mask email local-part while preserving domain for debugging."""
    if not isinstance(value, str) or not value.strip():
        return value
    raw = value.strip()
    if "@" not in raw:
        return "***"
    local, domain = raw.split("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth >= _MAX_REDACTION_DEPTH:
        return value
    if isinstance(value, dict):
        return _sanitize_mapping(value, depth=depth + 1)
    if isinstance(value, list):
        return [_sanitize_value(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item, depth=depth + 1) for item in value)
    return value


def _sanitize_mapping(mapping: dict[Any, Any], *, depth: int = 0) -> dict[Any, Any]:
    """Return a sanitized copy of mapping with secrets redacted and PII masked."""
    sanitized: dict[Any, Any] = {}
    for key, val in mapping.items():
        if isinstance(key, str):
            low = key.lower()
            if low in _SENSITIVE_KEYS:
                sanitized[key] = "***REDACTED***"
                continue
            if low in _IP_KEYS:
                sanitized[key] = _mask_ip(val)
                continue
            if low in _EMAIL_KEYS:
                sanitized[key] = _mask_email(val)
                continue
        sanitized[key] = _sanitize_value(val, depth=depth)
    return sanitized


def _filter_sensitive_data(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redacta campos sensibles para que nunca aparezcan en logs"""
    return _sanitize_mapping(event_dict)


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
