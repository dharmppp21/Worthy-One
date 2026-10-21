"""Centralized configuration for SignalForge.

All environment variables are read here. No other module should call
os.environ.get() directly. This makes configuration explicit, testable,
and easy to document.
"""

import os

# Dev-only fallback API keys. In production, keys MUST come from the
# SIGNALFORGE_API_KEYS env var; if it is unset there we fail closed (no keys),
# so the demo key never silently grants access to a real deployment.
_DEFAULT_DEV_API_KEYS = "sf-api-key-demo:demo-company,sf-test-key:demo-company"


def _parse_api_keys(raw: str) -> dict[str, str]:
    """Parse ``key:tenant,key2:tenant2`` into a {api_key: tenant_id} map."""
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        key, sep, tenant = pair.partition(":")
        key, tenant = key.strip(), tenant.strip()
        if key and sep and tenant:
            mapping[key] = tenant
    return mapping


class Config:
    """Application configuration loaded from environment variables."""

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./signforge.db")

    # Redis
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Kafka
    KAFKA_BROKERS: str = os.environ.get("KAFKA_BROKERS", "localhost:9092")

    # OpenAI / AI
    OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY")

    # Application
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

    # API key -> tenant map. From SIGNALFORGE_API_KEYS ("key:tenant,key2:tenant2").
    # Unset: dev gets demo keys; production fails closed (empty, every request 401).
    API_KEYS: dict[str, str] = _parse_api_keys(
        os.environ.get(
            "SIGNALFORGE_API_KEYS",
            "" if ENVIRONMENT.lower() == "production" else _DEFAULT_DEV_API_KEYS,
        )
    )
    RATE_LIMIT_RPS: int = int(os.environ.get("RATE_LIMIT_RPS", "1000"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

    # Reject request bodies larger than this (bytes) with HTTP 413. Protects the
    # ingestion endpoints from memory exhaustion. Default 5 MiB; raise for very
    # large OTLP batches.
    MAX_REQUEST_BODY_BYTES: int = int(os.environ.get("MAX_REQUEST_BODY_BYTES", str(5 * 1024 * 1024)))

    @classmethod
    def is_production(cls) -> bool:
        return cls.ENVIRONMENT.lower() == "production"

    @classmethod
    def is_development(cls) -> bool:
        return cls.ENVIRONMENT.lower() in ("development", "dev")


config = Config()
