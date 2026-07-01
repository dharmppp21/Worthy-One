"""Shared fixtures and helpers for performance tests.

Generates deterministic mock data at scale (100+ services, 500+ dependencies,
1000+ events) so each perf test can focus on measuring latency and memory.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.discovery.dependencies.models import ServiceDependency
from app.discovery.models import DiscoveredService
from app.schemas import EventType, TelemetryEvent


# Deterministic seed for reproducible perf benchmarks
random.seed(42)


# ------------------------------------------------------------------
# Service generation
# ------------------------------------------------------------------

_SERVICE_TYPES = ["api", "web", "database", "cache", "message_queue", "search", "dashboard"]
_SERVICE_NAMES = [
    "frontend", "backend", "api-gateway", "auth-service", "billing-service",
    "payment-service", "notification-service", "search-service", "recommendation",
    "user-service", "order-service", "inventory", "shipping", "analytics",
    "reporting", "webhook-service", "email-service", "sms-service", "push-service",
    "cdn", "load-balancer", "rate-limiter", "circuit-breaker", "retry-service",
    "logging-service", "metrics-service", "tracing-service", "alerting",
    "postgres-primary", "postgres-replica", "mysql-primary", "mysql-replica",
    "redis-cluster", "redis-cache", "memcached", "elasticsearch", "kafka",
    "zookeeper", "rabbitmq", "cassandra", "mongodb", "dynamodb", "s3-proxy",
    "vault", "secrets-manager", "config-service", "feature-flags", "ab-testing",
    "ml-inference", "ml-training", "data-pipeline", "etl-service", "warehouse",
    "orchestrator", "scheduler", "worker-pool", "job-queue", "dead-letter",
    "ingestion-service", "validation-service", "transform-service", "enrichment",
    "aggregation-service", "rollup-service", "dashboard-ui", "admin-panel",
    "mobile-api", "partner-api", "public-api", "internal-api", "graphql-gateway",
    "rest-gateway", "grpc-gateway", "websocket-hub", "sse-hub", "polling-service",
    "batch-processor", "stream-processor", "event-sink", "event-source",
    "notification-hub", "message-router", "delivery-service", "compliance",
    "audit-service", "security-scanner", "penetration-test", "backup-service",
    "restore-service", "migration-service", "schema-registry", "topic-manager",
    "consumer-group", "producer-service", "stream-aggregator",
]


def generate_services(count: int = 100) -> List[DiscoveredService]:
    """Generate ``count`` deterministic mock DiscoveredService objects."""
    services: List[DiscoveredService] = []
    for i in range(count):
        name = _SERVICE_NAMES[i % len(_SERVICE_NAMES)] + f"-{i // len(_SERVICE_NAMES)}"
        svc_type = _SERVICE_TYPES[i % len(_SERVICE_TYPES)]
        host = f"10.0.{i // 256}.{i % 256}"
        port = 8000 + (i % 8000)
        services.append(
            DiscoveredService(
                service_id=str(uuid.uuid4()),
                service_name=name,
                service_type=svc_type,
                endpoints=[f"tcp://{host}:{port}"],
                host=host,
                metadata={
                    "pod_name": f"{name}-pod-abc123",
                    "container_id": f"container-{i:04x}",
                    "pid": 1000 + i,
                    "namespace": "default" if i < 50 else "production",
                },
                discovery_source="kubernetes" if i < 50 else "docker",
            )
        )
    return services


# ------------------------------------------------------------------
# Dependency generation
# ------------------------------------------------------------------

_DEPENDENCY_TYPES = ["network", "traffic_logs", "distributed_tracing", "service_mesh"]


def generate_dependencies(
    services: List[DiscoveredService],
    count: int = 500,
) -> List[ServiceDependency]:
    """Generate ``count`` random ServiceDependency edges among ``services``."""
    deps: List[ServiceDependency] = []
    n = len(services)
    seen: set = set()
    for i in range(count):
        src_idx = random.randint(0, n - 1)
        tgt_idx = random.randint(0, n - 1)
        while tgt_idx == src_idx or (src_idx, tgt_idx) in seen:
            src_idx = random.randint(0, n - 1)
            tgt_idx = random.randint(0, n - 1)
        seen.add((src_idx, tgt_idx))

        deps.append(
            ServiceDependency(
                source_service_id=services[src_idx].service_id,
                target_service_id=services[tgt_idx].service_id,
                dependency_type=random.choice(_DEPENDENCY_TYPES),
                connection_count=random.randint(1, 100),
                avg_latency_ms=round(random.uniform(1.0, 500.0), 2),
                error_rate=round(random.uniform(0.0, 0.1), 4),
                confidence_score=round(random.uniform(0.5, 1.0), 2),
                discovery_sources=[random.choice(["network_scanner", "trace_analyzer", "traffic_analyzer"])],
            )
        )
    return deps


# ------------------------------------------------------------------
# Event generation
# ------------------------------------------------------------------

_EVENT_NAMES = ["http_request", "db_query", "cache_hit", "cache_miss", "queue_enqueue", "queue_dequeue"]


def generate_events(
    services: List[DiscoveredService],
    count: int = 1000,
    correlated: bool = True,
) -> List[TelemetryEvent]:
    """Generate ``count`` TelemetryEvent objects.

    If ``correlated`` is True, each event carries metadata that maps to exactly
    one service (hostname match). If False, attributes are empty.
    """
    events: List[TelemetryEvent] = []
    for i in range(count):
        if correlated:
            svc = services[i % len(services)]
            attrs: Dict[str, Any] = {
                "hostname": svc.host,
                "source_ip": svc.host,
                "source_port": int(svc.endpoints[0].split(":")[-1]),
                "container_id": svc.metadata.get("container_id"),
                "pod_name": svc.metadata.get("pod_name"),
                "process_id": svc.metadata.get("pid"),
            }
            service_name = svc.service_name
        else:
            attrs = {}
            service_name = None

        events.append(
            TelemetryEvent(
                event_id=str(uuid.uuid4()),
                service_name=service_name,
                event_type=EventType.log,
                timestamp=datetime.now(timezone.utc),
                name=random.choice(_EVENT_NAMES),
                message="perf test event",
                attributes=attrs,
            )
        )
    return events


# ------------------------------------------------------------------
# Pytest fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def mock_services() -> List[DiscoveredService]:
    """100 deterministic mock services."""
    return generate_services(100)


@pytest.fixture(scope="module")
def mock_dependencies(mock_services: List[DiscoveredService]) -> List[ServiceDependency]:
    """500 deterministic mock dependencies."""
    return generate_dependencies(mock_services, 500)


@pytest.fixture(scope="module")
def mock_correlated_events(mock_services: List[DiscoveredService]) -> List[TelemetryEvent]:
    """1000 correlated telemetry events."""
    return generate_events(mock_services, 1000, correlated=True)


@pytest.fixture(scope="module")
def mock_uncorrelated_events() -> List[TelemetryEvent]:
    """1000 uncorrelated telemetry events (empty attributes)."""
    return generate_events([], 1000, correlated=False)


from app.database import SessionLocal, init_db
from sqlalchemy.orm import Session


@pytest.fixture(scope="module")
def perf_db():
    """Ensure tables exist for the performance test module."""
    init_db()


@pytest.fixture
def db_session(perf_db) -> Session:
    """Fresh DB session per test."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _cleanup_perf_tables(db_session) -> None:
    """After every perf test, wipe discovery and dependency tables so the next test starts fresh."""
    yield
    from app.models import DiscoveredServiceDB, ServiceDependencyDB, TelemetryEventModel
    db_session.query(ServiceDependencyDB).delete()
    db_session.query(TelemetryEventModel).delete()
    db_session.query(DiscoveredServiceDB).delete()
    db_session.commit()
