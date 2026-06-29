"""Structured logging configuration for SignalForge.

Production: JSON logs with level, timestamp, message, and request fields.
Development: human-readable single-line format.

Usage:
    from app.logging_config import get_logger
    logger = get_logger("app.routers.ingest")
    logger.info("event ingested", extra={"event_id": "123", "tenant_id": "demo"})
"""

import logging
import sys
from datetime import datetime, timezone

from app.config import config


class StructuredFormatter(logging.Formatter):
    """Format log records as structured key=value pairs for development,
    or JSON-like dict for production.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        parts = [
            f"timestamp={ts}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"message={record.getMessage()}",
        ]
        # Add extra fields from the record (if present)
        for key in ("event_id", "tenant_id", "request_id", "endpoint", "status_code", "duration_ms"):
            if hasattr(record, key):
                parts.append(f"{key}={getattr(record, key)}")
        # Add exception info if present
        if record.exc_info:
            parts.append(f"exception={self.formatException(record.exc_info)}")
        return " ".join(parts)


def configure_logging() -> None:
    """Configure root logger with the appropriate handler and formatter."""
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []
    root.addHandler(handler)

    # Suppress noisy third-party libraries in production
    if config.is_production():
        logging.getLogger("kafka").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
