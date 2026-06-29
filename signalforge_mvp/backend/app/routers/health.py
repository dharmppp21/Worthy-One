from sqlalchemy import text
from fastapi import APIRouter

from app.config import config
from app.database import engine
from app.kafka_client import kafka_client
from app.redis_client import redis_window
from app.logging_config import get_logger

logger = get_logger("app.routers.health")

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Return service health status including dependency connectivity."""
    # Check database connectivity
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.warning("health check: database connection failed")

    redis_ok = redis_window.is_available()
    kafka_ok = kafka_client.is_available()

    overall = "ok" if db_ok else "degraded"

    return {
        "status": overall,
        "environment": config.ENVIRONMENT,
        "dependencies": {
            "database": "available" if db_ok else "unavailable",
            "redis": "available" if redis_ok else "unavailable",
            "kafka": "available" if kafka_ok else "unavailable",
        },
    }

