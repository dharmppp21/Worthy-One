from sqlalchemy import text
from fastapi import APIRouter, Response, status

from app.config import config
from app.database import engine
from app.kafka_client import kafka_client
from app.redis_client import redis_window
from app.logging_config import get_logger

logger = get_logger("app.routers.health")

router = APIRouter(tags=["health"])


def _db_ok() -> bool:
    """True if the database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("health check: database connection failed")
        return False


@router.get("/health")
def health() -> dict:
    """Detailed health: process + dependency connectivity. Always 200."""
    db_ok = _db_ok()
    return {
        "status": "ok" if db_ok else "degraded",
        "environment": config.ENVIRONMENT,
        "dependencies": {
            "database": "available" if db_ok else "unavailable",
            "redis": "available" if redis_window.is_available() else "unavailable",
            "kafka": "available" if kafka_client.is_available() else "unavailable",
        },
    }


@router.get("/health/live")
def liveness() -> dict:
    """Liveness probe. The process is up; no dependency checks run, so a
    dependency blip never gets the pod killed and restarted."""
    return {"status": "alive"}


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    """Readiness probe. The database is the hard dependency; when it is down we
    return 503 so the orchestrator stops routing traffic here. Redis and Kafka
    degrade gracefully and do not fail readiness."""
    db_ok = _db_ok()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if db_ok else "not_ready",
        "database": "available" if db_ok else "unavailable",
    }

