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
from app.routers import discovery as discovery_router
from app.database import DATABASE_URL, SessionLocal
from app.services.kafka_consumer_worker import start_consumer_worker

from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.discovery.dependencies.mesh_analyzer import ServiceMeshAnalyzer
from app.discovery.dependencies.network_scanner import NetworkConnectionScanner
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.dependencies.trace_analyzer import TraceAnalyzer
from app.discovery.environment import AutoConfigurator
from app.discovery.engine import DiscoveryEngine
from app.discovery.registry import ServiceRegistry
from app.routers.discovery import set_discovery_engine, set_graph_builder

from app.discovery.correlation import EventServiceCorrelator
from app.services.event_processor import event_processor

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
    app.include_router(discovery_router.router)

    # Start Kafka consumer worker in background thread
    start_consumer_worker()

    # ------------------------------------------------------------------
    # Service Discovery Setup
    # ------------------------------------------------------------------
    configurator = AutoConfigurator()
    if configurator.enabled:
        db_session = SessionLocal()
        try:
            registry = ServiceRegistry(db_session=db_session)
            engine = DiscoveryEngine(registry=registry)
            providers = configurator.instantiate_providers()
            for provider in providers:
                engine.register_provider(provider)
            set_discovery_engine(engine)
            if providers:
                engine.start_background_discovery(interval_seconds=configurator.interval)
            else:
                from app.logging_config import get_logger
                logger_local = get_logger("app.main")
                logger_local.info("No discovery providers configured; discovery engine idle.")

            # ------------------------------------------------------------------
            # Dependency Graph Builder Setup
            # ------------------------------------------------------------------
            dep_registry = DependencyRegistry(db_session=db_session)
            analyzers = [
                NetworkConnectionScanner(registry=registry),
                TraceAnalyzer(registry=registry),
                ServiceMeshAnalyzer(registry=registry),
            ]
            graph_builder = DependencyGraphBuilder(
                analyzers=analyzers,
                registry=registry,
                dep_registry=dep_registry,
            )
            set_graph_builder(graph_builder)
            graph_builder.start_background_build(interval_seconds=60)

            # ------------------------------------------------------------------
            # Event Correlator Setup
            # ------------------------------------------------------------------
            correlator = EventServiceCorrelator(registry=registry)
            event_processor.set_correlator(correlator)

        except Exception as exc:
            from app.logging_config import get_logger
            logger_local = get_logger("app.main")
            logger_local.warning("Discovery engine setup failed: %s", exc)

    return app


app = create_app()
