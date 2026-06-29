from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import config
from app.logging_config import configure_logging
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_logging import RequestLoggingMiddleware
from app.routers import (
    ai_triage,
    deployments,
    events,
    graph,
    health,
    incidents,
    ingest,
    root_cause,
    runbooks,
    search,
    websocket,
)
from app.database import DATABASE_URL
from app.services.kafka_consumer_worker import start_consumer_worker

from alembic.config import Config
from alembic import command

# Configure structured logging before anything else runs
configure_logging()


def run_migrations() -> None:
    """Run Alembic migrations to ensure the database schema is current."""
    import os

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(backend_dir, "alembic.ini")
    alembic_cfg = Config(alembic_ini)
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SignalForge API",
        version="0.1.0",
        docs_url="/docs" if config.is_development() else None,
        redoc_url="/redoc" if config.is_development() else None,
    )

    # CORS — allow local frontend in dev, more restrictive in production
    origins = (
        ["http://127.0.0.1:5173", "http://localhost:5173"]
        if config.is_development()
        else []
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging — adds request_id and logs every request/response
    app.add_middleware(RequestLoggingMiddleware)

    # Safe error handling — no stack traces leaked to clients in production
    register_exception_handlers(app)

    run_migrations()

    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(events.router)
    app.include_router(deployments.router)
    app.include_router(runbooks.router)
    app.include_router(incidents.router)
    app.include_router(graph.router)
    app.include_router(search.router)
    app.include_router(root_cause.router)
    app.include_router(ai_triage.router)
    app.include_router(websocket.router)

    # Start Kafka consumer worker in background thread
    start_consumer_worker()

    return app


app = create_app()
