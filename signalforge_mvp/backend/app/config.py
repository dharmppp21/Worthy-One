"""Centralized configuration for SignalForge.

All environment variables are read here. No other module should call
os.environ.get() directly. This makes configuration explicit, testable,
and easy to document.
"""

import os


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
    RATE_LIMIT_RPS: int = int(os.environ.get("RATE_LIMIT_RPS", "100"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

    @classmethod
    def is_production(cls) -> bool:
        return cls.ENVIRONMENT.lower() == "production"

    @classmethod
    def is_development(cls) -> bool:
        return cls.ENVIRONMENT.lower() in ("development", "dev")


config = Config()
