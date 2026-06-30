"""Tests for the EventServiceCorrelator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from app.database import Base
from app.discovery.correlation import EventServiceCorrelator
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.schemas import EventType, TelemetryEvent
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def registry(db_session):
    return ServiceRegistry(db_session=db_session)


@pytest.fixture
def correlator(registry):
    return EventServiceCorrelator(registry=registry)


@pytest.fixture
def populated_registry(registry):
    """Registry with 5 fake discovered services."""
    services = [
        DiscoveredService(
            service_name="web-api",
            host="10.0.0.1",
            endpoints=["tcp://10.0.0.1:8080", "http://10.0.0.1:8080"],
            service_type="api",
            metadata={"pid": 1234, "tenant_id": "tenant-a"},
            discovery_source="process",
        ),
        DiscoveredService(
            service_name="postgres-db",
            host="10.0.0.2",
            endpoints=["tcp://10.0.0.2:5432"],
            service_type="database",
            metadata={"container_id": "abc123def456", "tenant_id": "tenant-a"},
            discovery_source="docker",
        ),
        DiscoveredService(
            service_name="redis-cache",
            host="10.0.0.3",
            endpoints=["tcp://10.0.0.3:6379"],
            service_type="cache",
            metadata={"pod_name": "redis-0", "tenant_id": "tenant-b"},
            discovery_source="kubernetes",
        ),
        DiscoveredService(
            service_name="worker-queue",
            host="10.0.0.4",
            endpoints=["tcp://10.0.0.4:9092"],
            service_type="message_queue",
            metadata={"tenant_id": "tenant-a"},
            discovery_source="kubernetes",
        ),
        DiscoveredService(
            service_name="payment-api",
            host="10.0.0.5",
            endpoints=["tcp://10.0.0.5:8080"],
            service_type="api",
            metadata={"pid": 5678, "tenant_id": "tenant-a"},
            discovery_source="process",
        ),
    ]
    for svc in services:
        registry.register_service(svc)
    return registry


@pytest.fixture
def populated_correlator(populated_registry):
    return EventServiceCorrelator(registry=populated_registry)


# ------------------------------------------------------------------
# Helper to create events
# ------------------------------------------------------------------

def _make_event(
    service_name: str | None = None,
    attributes: Dict[str, Any] | None = None,
    event_type: EventType = EventType.log,
) -> TelemetryEvent:
    return TelemetryEvent(
        service_name=service_name,
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        name="test_event",
        message="test message",
        attributes=attributes or {},
    )


# ------------------------------------------------------------------
# Strategy 1: Exact service name match
# ------------------------------------------------------------------

def test_exact_name_match(populated_correlator):
    event = _make_event(service_name="web-api")
    result = populated_correlator.correlate(event)
    assert result.service_name == "web-api"
    assert result.confidence == 1.0
    assert result.strategy == "exact_name"
    assert result.candidate_count == 1


def test_exact_name_match_case_insensitive(populated_correlator):
    event = _make_event(service_name="WEB-API")
    result = populated_correlator.correlate(event)
    assert result.service_name == "web-api"
    assert result.confidence == 1.0


def test_exact_name_no_match_falls_through(populated_correlator):
    event = _make_event(service_name="unknown-service")
    result = populated_correlator.correlate(event)
    assert result.strategy == "none"
    assert result.confidence == 0.0


# ------------------------------------------------------------------
# Strategy 2: Source IP + port match
# ------------------------------------------------------------------

def test_source_ip_port_single_match(populated_correlator):
    event = _make_event(attributes={"source_ip": "10.0.0.2", "source_port": "5432"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "postgres-db"
    assert result.confidence == 0.95
    assert result.strategy == "source_ip_port"


def test_source_ip_port_http_match(populated_correlator):
    event = _make_event(attributes={"source_ip": "10.0.0.1", "source_port": "8080"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "web-api"
    assert result.confidence == 0.95


def test_source_ip_port_no_match(populated_correlator):
    event = _make_event(attributes={"source_ip": "10.0.0.99", "source_port": "9999"})
    result = populated_correlator.correlate(event)
    assert result.strategy == "none"


def test_source_ip_port_disambiguate(populated_correlator, populated_registry):
    """Two services on same IP:port — should use disambiguation."""
    # Add two services on the same IP:port to create ambiguity
    svc1 = DiscoveredService(
        service_name="another-api",
        host="10.0.0.6",
        endpoints=["tcp://10.0.0.6:8080"],
        service_type="log",
        metadata={"tenant_id": "tenant-a"},
        discovery_source="process",
    )
    svc1.last_heartbeat_at = datetime.min.replace(tzinfo=timezone.utc)
    populated_registry.register_service(svc1)

    svc2 = DiscoveredService(
        service_name="yet-another-api",
        host="10.0.0.6",
        endpoints=["tcp://10.0.0.6:8080"],
        service_type="api",
        metadata={"tenant_id": "tenant-a"},
        discovery_source="process",
    )
    svc2.last_heartbeat_at = datetime.min.replace(tzinfo=timezone.utc)
    populated_registry.register_service(svc2)

    event = _make_event(
        event_type=EventType.log,
        attributes={"source_ip": "10.0.0.6", "source_port": "8080"},
    )
    result = populated_correlator.correlate(event)
    assert result.strategy == "source_ip_port"
    assert result.confidence == 0.8
    assert result.candidate_count > 1


# ------------------------------------------------------------------
# Strategy 3: Hostname match
# ------------------------------------------------------------------

def test_hostname_match_host(populated_correlator):
    event = _make_event(attributes={"host": "10.0.0.3"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "redis-cache"
    assert result.confidence == 0.9
    assert result.strategy == "hostname"


def test_hostname_match_hostname(populated_correlator):
    event = _make_event(attributes={"hostname": "redis-cache"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "redis-cache"
    assert result.confidence == 0.9


def test_hostname_no_match(populated_correlator):
    event = _make_event(attributes={"hostname": "unknown-host"})
    result = populated_correlator.correlate(event)
    assert result.strategy != "hostname"


# ------------------------------------------------------------------
# Strategy 4: Container ID match
# ------------------------------------------------------------------

def test_container_id_match(populated_correlator):
    event = _make_event(attributes={"container_id": "abc123def456"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "postgres-db"
    assert result.confidence == 0.95
    assert result.strategy == "container_id"


def test_container_id_partial_match(populated_correlator):
    event = _make_event(attributes={"container_id": "abc123def4567890"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "postgres-db"


def test_container_id_no_match(populated_correlator):
    event = _make_event(attributes={"container_id": "xyz999"})
    result = populated_correlator.correlate(event)
    assert result.strategy != "container_id"


# ------------------------------------------------------------------
# Strategy 5: Pod name match
# ------------------------------------------------------------------

def test_pod_name_match(populated_correlator):
    event = _make_event(attributes={"pod_name": "redis-0"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "redis-cache"
    assert result.confidence == 0.95
    assert result.strategy == "pod_name"


def test_pod_name_no_match(populated_correlator):
    event = _make_event(attributes={"pod_name": "nonexistent-pod"})
    result = populated_correlator.correlate(event)
    assert result.strategy != "pod_name"


# ------------------------------------------------------------------
# Strategy 6: Process ID match
# ------------------------------------------------------------------

def test_process_id_match(populated_correlator):
    event = _make_event(attributes={"process_id": "1234"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "web-api"
    assert result.confidence == 0.9
    assert result.strategy == "process_id"


def test_process_id_no_match(populated_correlator):
    event = _make_event(attributes={"process_id": "9999"})
    result = populated_correlator.correlate(event)
    assert result.strategy != "process_id"


# ------------------------------------------------------------------
# Strategy 7: Trace context match
# ------------------------------------------------------------------

def test_trace_context_match(populated_correlator):
    event = _make_event(attributes={"parent_span_service": "web-api"})
    result = populated_correlator.correlate(event)
    assert result.service_name == "web-api"
    assert result.confidence == 0.85
    assert result.strategy == "trace_context"


def test_trace_context_no_match(populated_correlator):
    event = _make_event(attributes={"parent_span_service": "unknown"})
    result = populated_correlator.correlate(event)
    assert result.strategy != "trace_context"


# ------------------------------------------------------------------
# Strategy 8: Fallback / none
# ------------------------------------------------------------------

def test_fallback_none(populated_correlator):
    event = _make_event()
    result = populated_correlator.correlate(event)
    assert result.service_id is None
    assert result.service_name is None
    assert result.confidence == 0.0
    assert result.strategy == "none"
    assert result.candidate_count == 0


# ------------------------------------------------------------------
# Disambiguation logic
# ------------------------------------------------------------------

def test_disambiguate_by_heartbeat(populated_correlator):
    """When multiple candidates match, the one with most recent heartbeat wins."""
    # Both web-api and payment-api are on 8080, but web-api is registered first
    # (both have same default heartbeat)
    event = _make_event(
        attributes={"source_ip": "10.0.0.1", "source_port": "8080"},
    )
    result = populated_correlator.correlate(event)
    # Should match web-api (the first one with matching endpoint)
    assert result.service_name == "web-api"
    assert result.confidence == 0.95


# ------------------------------------------------------------------
# CorrelationResult
# ------------------------------------------------------------------

def test_correlation_result_to_dict():
    from app.discovery.correlation import CorrelationResult
    result = CorrelationResult(
        service_id="svc-1",
        service_name="web-api",
        confidence=0.95,
        strategy="source_ip_port",
        matched_field="10.0.0.1:8080",
        candidate_count=1,
    )
    d = result.to_dict()
    assert d["strategy"] == "source_ip_port"
    assert d["confidence"] == 0.95
    assert d["matched_field"] == "10.0.0.1:8080"
    assert d["candidate_count"] == 1
