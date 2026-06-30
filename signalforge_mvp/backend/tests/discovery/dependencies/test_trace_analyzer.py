"""Tests for the TraceAnalyzer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.discovery.dependencies.trace_analyzer import (
    TraceAnalyzer,
    _normalize_service_name,
)
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry


# ------------------------------------------------------------------
# Helper tests
# ------------------------------------------------------------------

def test_normalize_service_name():
    assert _normalize_service_name("web-api:8080") == "web-api"
    assert _normalize_service_name("  WEB-API  ") == "web-api"
    assert _normalize_service_name("") == "unknown"
    assert _normalize_service_name(None) == "unknown"


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
    return TraceAnalyzer(registry=registry, backend_type="mock")


# ------------------------------------------------------------------
# TraceAnalyzer.analyze tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_empty(analyzer):
    result = await analyzer.analyze([])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_no_spans(analyzer):
    result = await analyzer.analyze([{"trace_id": "abc"}])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_jaeger_spans(analyzer, registry):
    """Parse Jaeger-format trace and infer a dependency."""
    svc_a = DiscoveredService(
        service_name="frontend",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    svc_b = DiscoveredService(
        service_name="backend",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    trace = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "frontend"},
                "duration": 50000,  # microseconds
                "startTime": 1704110400000000,  # microseconds
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "backend"},
                "duration": 30000,  # microseconds
                "startTime": 1704110400100000,
            },
        ]
    }

    result = await analyzer.analyze([trace])
    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_a.service_id
    assert dep.target_service_id == svc_b.service_id
    assert dep.dependency_type == "rpc"
    assert dep.connection_count == 1
    assert dep.confidence_score == 0.85
    assert dep.discovery_sources == ["distributed_tracing"]
    assert dep.avg_latency_ms == 30.0
    assert dep.error_rate == 0.0


@pytest.mark.asyncio
async def test_analyze_jaeger_nested_data(analyzer, registry):
    """Jaeger API returns {"data": [{...traces...}]}."""
    svc_a = DiscoveredService(
        service_name="gateway",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    svc_b = DiscoveredService(
        service_name="orders",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    trace = {
        "data": [
            {
                "spans": [
                    {
                        "spanID": "span-1",
                        "process": {"serviceName": "gateway"},
                        "duration": 100000,  # microseconds
                        "startTime": 1704110400000000,
                    },
                    {
                        "spanID": "span-2",
                        "references": [
                            {"refType": "CHILD_OF", "spanID": "span-1"}
                        ],
                        "process": {"serviceName": "orders"},
                        "duration": 50000,
                        "startTime": 1704110400100000,
                    },
                ]
            }
        ]
    }

    analyzer._backend_type = "jaeger"
    result = await analyzer.analyze([trace])
    assert len(result) == 1
    assert result[0].source_service_id == svc_a.service_id
    assert result[0].target_service_id == svc_b.service_id
    assert result[0].avg_latency_ms == 50.0


@pytest.mark.asyncio
async def test_analyze_zipkin_spans(analyzer, registry):
    """Parse Zipkin-format trace and infer a dependency."""
    svc_a = DiscoveredService(
        service_name="api",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    svc_b = DiscoveredService(
        service_name="db",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:5432"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    # Zipkin returns a list of spans directly
    trace = [
        {
            "id": "span-1",
            "localEndpoint": {"serviceName": "api"},
            "duration": 100000,
            "timestamp": 1704110400000000,  # microseconds
        },
        {
            "id": "span-2",
            "parentId": "span-1",
            "localEndpoint": {"serviceName": "db"},
            "duration": 20000,
            "timestamp": 1704110400100000,
        },
    ]

    analyzer._backend_type = "zipkin"
    result = await analyzer.analyze([trace])
    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_a.service_id
    assert dep.target_service_id == svc_b.service_id
    assert dep.avg_latency_ms == 20.0


@pytest.mark.asyncio
async def test_analyze_detects_error(analyzer, registry):
    """A span with an error tag should be reflected in error_rate."""
    svc_a = DiscoveredService(
        service_name="client",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    svc_b = DiscoveredService(
        service_name="server",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    trace = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "client"},
                "duration": 50000,
                "startTime": 1704110400000000,
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "server"},
                "duration": 50000,
                "startTime": 1704110400100000,
                "tags": [
                    {"key": "error", "value": True},
                ],
            },
        ]
    }

    result = await analyzer.analyze([trace])
    assert len(result) == 1
    assert result[0].error_rate == 1.0


@pytest.mark.asyncio
async def test_analyze_unknown_services(analyzer):
    """If services are not in the registry, confidence should be lower."""
    trace = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "unknown-a"},
                "duration": 50000,
                "startTime": 1704110400000000,
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "unknown-b"},
                "duration": 30000,
                "startTime": 1704110400100000,
            },
        ]
    }

    result = await analyzer.analyze([trace])
    assert len(result) == 1
    dep = result[0]
    assert dep.confidence_score == 0.5
    assert dep.source_service_id == "trace-unknown-a"
    assert dep.target_service_id == "trace-unknown-b"


@pytest.mark.asyncio
async def test_analyze_skips_self_loops(analyzer, registry):
    """A service calling itself should not create a dependency."""
    svc = DiscoveredService(
        service_name="self-caller",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc)

    trace = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "self-caller"},
                "duration": 50000,
                "startTime": 1704110400000000,
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "self-caller"},
                "duration": 30000,
                "startTime": 1704110400100000,
            },
        ]
    }

    result = await analyzer.analyze([trace])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_multiple_traces(analyzer, registry):
    """Multiple traces between same services should aggregate."""
    svc_a = DiscoveredService(
        service_name="api",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    svc_b = DiscoveredService(
        service_name="db",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:5432"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    traces: List[Dict[str, Any]] = [
        {
            "spans": [
                {
                    "spanID": f"span-{i}-1",
                    "process": {"serviceName": "api"},
                    "duration": 100000,
                    "startTime": 1704110400000000 + i * 1000000,
                },
                {
                    "spanID": f"span-{i}-2",
                    "references": [
                        {"refType": "CHILD_OF", "spanID": f"span-{i}-1"}
                    ],
                    "process": {"serviceName": "db"},
                    "duration": 20000 + i * 5000,
                    "startTime": 1704110400100000 + i * 1000000,
                },
            ]
        }
        for i in range(3)
    ]

    result = await analyzer.analyze(traces)
    assert len(result) == 1
    dep = result[0]
    assert dep.connection_count == 3
    assert dep.avg_latency_ms == pytest.approx((20 + 25 + 30) / 3)


@pytest.mark.asyncio
async def test_analyze_no_backend_url(analyzer):
    """Without backend_url or raw_traces, should return empty."""
    analyzer._backend_url = None
    result = await analyzer.analyze()
    assert result == []


@pytest.mark.asyncio
async def test_analyze_span_without_parent(analyzer, registry):
    """Spans without a parent should be ignored (they're roots)."""
    svc = DiscoveredService(
        service_name="root-service",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc)

    trace = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "root-service"},
                "duration": 50000,
                "startTime": 1704110400000000,
            },
        ]
    }

    result = await analyzer.analyze([trace])
    assert result == []


@pytest.mark.asyncio
async def test_analyze_span_duration_normalization(analyzer, registry):
    """Test duration normalization from nanoseconds, microseconds, and ms."""
    svc_a = DiscoveredService(
        service_name="a",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
        discovery_source="kubernetes",
    )
    svc_b = DiscoveredService(
        service_name="b",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:8080"],
        discovery_source="kubernetes",
    )
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    # Test nanoseconds
    trace_ns = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "a"},
                "duration": 50_000_000,  # 50ms in nanoseconds
                "startTime": 1704110400000000000,
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "b"},
                "duration": 30_000_000,  # 30ms in nanoseconds
                "startTime": 1704110400010000000,
            },
        ]
    }

    result = await analyzer.analyze([trace_ns])
    assert result[0].avg_latency_ms == pytest.approx(30.0, rel=0.01)

    # Test microseconds (default Jaeger)
    trace_us = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "a"},
                "duration": 50000,  # 50ms in microseconds
                "startTime": 1704110400000000,
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "b"},
                "duration": 30000,  # 30ms in microseconds
                "startTime": 1704110400010000,
            },
        ]
    }

    result = await analyzer.analyze([trace_us])
    assert result[0].avg_latency_ms == 30.0

    # Test milliseconds
    trace_ms = {
        "spans": [
            {
                "spanID": "span-1",
                "process": {"serviceName": "a"},
                "duration": 50,  # 50ms
                "startTime": 1704110400000,
            },
            {
                "spanID": "span-2",
                "references": [
                    {"refType": "CHILD_OF", "spanID": "span-1"}
                ],
                "process": {"serviceName": "b"},
                "duration": 30,  # 30ms
                "startTime": 1704110400010,
            },
        ]
    }

    result = await analyzer.analyze([trace_ms])
    assert result[0].avg_latency_ms == 30.0
