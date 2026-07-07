"""Structured logging configuration for SignalForge.

Production: JSON logs with level, timestamp, message, and request fields.
Development: human-readable single-line format.

Usage:
    from app.logging_config import get_logger
    logger = get_logger("app.routers.ingest")
    logger.info("event ingested", extra={"event_id": "123", "tenant_id": "demo"})
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from app.config import config


class StructuredFormatter(logging.Formatter):
    """Format log records as structured key=value pairs for development,
    or JSON for production.
    """

    def __init__(self, use_json: bool = False) -> None:
        super().__init__()
        self.use_json = use_json

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        data: Dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from the record (if present)
        for key in ("event_id", "tenant_id", "request_id", "endpoint", "status_code",
                    "duration_ms", "service_id", "service_name", "dependency_type"):
            if hasattr(record, key):
                data[key] = getattr(record, key)

        # Add exception info if present
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)

        if self.use_json:
            return json.dumps(data, default=str)
        else:
            parts = [f"{k}={v}" for k, v in data.items()]
            return " ".join(parts)


class RequestContextFilter(logging.Filter):
    """Add request context to all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        # These will be set by the RequestLoggingMiddleware
        for key in ("request_id", "endpoint", "method"):
            if not hasattr(record, key):
                setattr(record, key, "")
        return True


def configure_logging() -> None:
    """Configure root logger with the appropriate handler and formatter."""
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    use_json = config.is_production()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter(use_json=use_json))
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []
    root.addHandler(handler)

    # Suppress noisy third-party libraries in production
    if config.is_production():
        logging.getLogger("kafka").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    else:
        # In dev, still keep SQLAlchemy quiet unless debugging
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
