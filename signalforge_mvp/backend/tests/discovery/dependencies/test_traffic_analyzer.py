"""Tests for the TrafficAnalyzer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.discovery.dependencies.traffic_analyzer import (
    TrafficAnalyzer,
    _extract_service_from_host,
    _extract_service_from_path,
    _parse_timestamp,
)
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry


# ------------------------------------------------------------------
# Helper tests
# ------------------------------------------------------------------

def test_parse_timestamp_nginx():
    ts = _parse_timestamp("01/Jan/2024:12:00:00 +0000")
    assert ts is not None
    assert ts.year == 2024


def test_parse_timestamp_iso():
    ts = _parse_timestamp("2024-01-01T12:00:00+0000")
    assert ts is not None
    assert ts.year == 2024


def test_parse_timestamp_invalid():
    assert _parse_timestamp("not-a-date") is None


def test_extract_service_from_host():
    assert _extract_service_from_host("web-api.default.svc.cluster.local") == "web-api"
    assert _extract_service_from_host("web-api") == "web-api"
    assert _extract_service_from_host("") is None


def test_extract_service_from_path():
    assert _extract_service_from_path("/api/v1/payments/transactions") == "payments"
    assert _extract_service_from_path("/services/user-service/profile") == "user-service"
    assert _extract_service_from_path("/orders/api/v2/items") == "orders"
    assert _extract_service_from_path("/health") is None


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
def analyzer(registry):
    return TrafficAnalyzer(registry=registry, log_format="auto")


# ------------------------------------------------------------------
# TrafficAnalyzer.analyze tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_empty(analyzer):
    result = await analyzer.analyze([])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_no_valid_lines(analyzer):
    result = await analyzer.analyze(["garbage line", "another bad line"])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_nginx_log(analyzer, registry):
    """Parse a standard nginx combined log and infer a dependency."""
    svc_source = DiscoveredService(
        service_name="web-api",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="user-service",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    log_line = (
        '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
        '"GET /api/v1/user-service/profile HTTP/1.1" 200 42 '
        '"-" "Mozilla/5.0" "user-service" 0.023'
    )

    result = await analyzer.analyze([log_line])
    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_source.service_id
    assert dep.target_service_id == svc_target.service_id
    assert dep.dependency_type == "http"
    assert dep.connection_count == 1
    assert dep.confidence_score == 0.7
    assert dep.discovery_sources == ["traffic_logs"]
    assert dep.avg_latency_ms == 0.023
    assert dep.error_rate == 0.0


@pytest.mark.asyncio
async def test_analyze_detects_error(analyzer, registry):
    """A 5xx status should be reflected in error_rate."""
    svc_source = DiscoveredService(
        service_name="web-api",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="payment-service",
        host="10.0.0.3",
        endpoints=["tcp://10.0.0.3:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    log_line = (
        '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
        '"POST /api/v1/payment-service/charge HTTP/1.1" 502 12 '
        '"-" "Mozilla/5.0" "payment-service" 0.5'
    )

    result = await analyzer.analyze([log_line])
    assert len(result) == 1
    dep = result[0]
    assert dep.error_rate == 1.0
    assert dep.avg_latency_ms == 0.5


@pytest.mark.asyncio
async def test_analyze_unknown_services(analyzer, registry):
    """If target is not in the registry, confidence should be lower."""
    svc_source = DiscoveredService(
        service_name="known-source",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    registry.register_service(svc_source)

    log_line = (
        '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
        '"GET /api/v1/unknown-service/data HTTP/1.1" 200 100 '
        '"-" "Go-http-client/1.1" "unknown-service" 0.1'
    )

    result = await analyzer.analyze([log_line])
    assert len(result) == 1
    dep = result[0]
    assert dep.confidence_score == 0.4
    assert dep.source_service_id == svc_source.service_id
    assert dep.target_service_id.startswith("traffic-")


@pytest.mark.asyncio
async def test_analyze_aggregates_multiple_requests(analyzer, registry):
    """Multiple log lines between same source/target should aggregate."""
    svc_source = DiscoveredService(
        service_name="gateway",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="catalog-service",
        host="10.0.0.4",
        endpoints=["tcp://10.0.0.4:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    logs = [
        (
            '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
            '"GET /api/v1/catalog-service/items HTTP/1.1" 200 200 '
            '"-" "Mozilla/5.0" "catalog-service" 0.05'
        ),
        (
            '10.0.0.1 - - [01/Jan/2024:12:00:01 +0000] '
            '"GET /api/v1/catalog-service/items HTTP/1.1" 200 200 '
            '"-" "Mozilla/5.0" "catalog-service" 0.07'
        ),
        (
            '10.0.0.1 - - [01/Jan/2024:12:00:02 +0000] '
            '"GET /api/v1/catalog-service/items HTTP/1.1" 500 50 '
            '"-" "Mozilla/5.0" "catalog-service" 0.2'
        ),
    ]

    result = await analyzer.analyze(logs)
    assert len(result) == 1
    dep = result[0]
    assert dep.connection_count == 3
    assert dep.error_rate == pytest.approx(1 / 3)
    assert dep.avg_latency_ms == pytest.approx((0.05 + 0.07 + 0.2) / 3)


@pytest.mark.asyncio
async def test_analyze_json_log(analyzer, registry):
    """Parse JSON-formatted log lines."""
    svc_source = DiscoveredService(
        service_name="api",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="inventory",
        host="10.0.0.5",
        endpoints=["tcp://10.0.0.5:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    log_line = (
        '{"remote_addr": "10.0.0.1", "method": "GET", '
        '"path": "/api/v1/inventory/stock", "status": 200, '
        '"host": "inventory", "request_time": 0.042, '
        '"timestamp": "2024-01-01T12:00:00+0000"}'
    )

    result = await analyzer.analyze([log_line])
    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_source.service_id
    assert dep.target_service_id == svc_target.service_id
    assert dep.avg_latency_ms == 0.042


@pytest.mark.asyncio
async def test_analyze_skips_self_loops(analyzer, registry):
    """A service calling itself should not create a dependency."""
    svc = DiscoveredService(
        service_name="self-caller",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    registry.register_service(svc)

    log_line = (
        '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
        '"GET /api/v1/self-caller/health HTTP/1.1" 200 10 '
        '"-" "Go-http-client/1.1" "self-caller" 0.01'
    )

    result = await analyzer.analyze([log_line])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_from_file(tmp_path, registry):
    """Read log lines from a file path."""
    svc_source = DiscoveredService(
        service_name="frontend",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="backend",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    log_file = tmp_path / "access.log"
    log_file.write_text(
        '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
        '"GET /api/v1/backend/data HTTP/1.1" 200 100 '
        '"-" "Mozilla/5.0" "backend" 0.05\n'
    )

    analyzer = TrafficAnalyzer(
        registry=registry,
        log_source=str(log_file),
        log_format="auto",
    )
    result = await analyzer.analyze()
    assert len(result) == 1
    assert result[0].target_service_id == svc_target.service_id


@pytest.mark.asyncio
async def test_analyze_envoy_log(analyzer, registry):
    """Parse Envoy access log format."""
    svc_source = DiscoveredService(
        service_name="gateway",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="reviews",
        host="10.0.0.6",
        endpoints=["tcp://10.0.0.6:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    log_line = (
        '10.0.0.1 - - [01/Jan/2024:12:00:00 +0000] '
        '"GET /api/v1/reviews/list HTTP/1.1" 200 150 '
        '- 0.045 "-" "Mozilla/5.0" "reviews" "reviews:8080"'
    )

    result = await analyzer.analyze([log_line])
    assert len(result) == 1
    dep = result[0]
    assert dep.target_service_id == svc_target.service_id
    assert dep.avg_latency_ms == 0.045


@pytest.mark.asyncio
async def test_analyze_missing_file(registry):
    """A missing log file should return empty results gracefully."""
    analyzer = TrafficAnalyzer(
        registry=registry,
        log_source="/nonexistent/path/access.log",
        log_format="auto",
    )
    result = await analyzer.analyze()
    assert result == []
