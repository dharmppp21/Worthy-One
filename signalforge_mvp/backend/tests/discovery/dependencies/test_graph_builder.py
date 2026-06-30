"""Tests for the DependencyGraphBuilder and ServiceMeshAnalyzer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.discovery.dependencies.base import BaseDependencyAnalyzer
from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.discovery.dependencies.mesh_analyzer import ServiceMeshAnalyzer, httpx
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry


# ------------------------------------------------------------------
# Mock analyzers
# ------------------------------------------------------------------

class MockAnalyzer(BaseDependencyAnalyzer):
    """Mock analyzer that returns pre-configured dependencies."""

    def __init__(self, deps: List[ServiceDependency], healthy: bool = True) -> None:
        self._deps = deps
        self._healthy = healthy

    def health_check(self) -> bool:
        return self._healthy

    async def analyze(self) -> List[ServiceDependency]:
        return list(self._deps)


class FailingAnalyzer(BaseDependencyAnalyzer):
    """Mock analyzer that always raises an exception."""

    async def analyze(self) -> List[ServiceDependency]:
        raise RuntimeError("analyzer failure")


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
def service_registry(db_session):
    return ServiceRegistry(db_session=db_session)


@pytest.fixture
def dep_registry(db_session):
    return DependencyRegistry(db_session=db_session)


@pytest.fixture
def builder(service_registry, dep_registry):
    return DependencyGraphBuilder(
        analyzers=[],
        registry=service_registry,
        dep_registry=dep_registry,
    )


# ------------------------------------------------------------------
# DependencyGraphBuilder tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_no_analyzers(builder):
    """With no analyzers, should return empty graph."""
    graph = await builder.build()
    assert graph.nodes == []
    assert graph.edges == []


@pytest.mark.asyncio
async def test_build_single_analyzer(builder, dep_registry, service_registry):
    """A single analyzer with one dependency should produce a graph with one edge."""
    svc = DiscoveredService(
        service_name="api", host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:8080"],
    )
    service_registry.register_service(svc)

    dep = ServiceDependency(
        source_service_id=svc.service_id,
        target_service_id="svc-b",
        dependency_type="http",
        connection_count=5,
        confidence_score=0.7,
        discovery_sources=["network"],
    )
    builder._analyzers = [MockAnalyzer([dep])]

    graph = await builder.build()
    assert len(graph.edges) == 1
    assert graph.edges[0].connection_count == 5
    assert graph.edges[0].confidence_score == 0.7


@pytest.mark.asyncio
async def test_build_overlapping_analyzers(builder, dep_registry, service_registry):
    """Two analyzers detect the same dependency; confidence should be boosted."""
    svc_a = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    svc_b = DiscoveredService(service_name="b", host="10.0.0.2", endpoints=["tcp://10.0.0.2:8080"])
    service_registry.register_service(svc_a)
    service_registry.register_service(svc_b)

    dep1 = ServiceDependency(
        source_service_id=svc_a.service_id,
        target_service_id=svc_b.service_id,
        dependency_type="http",
        connection_count=10,
        confidence_score=0.7,
        avg_latency_ms=50.0,
        error_rate=0.1,
        discovery_sources=["network"],
    )
    dep2 = ServiceDependency(
        source_service_id=svc_a.service_id,
        target_service_id=svc_b.service_id,
        dependency_type="http",
        connection_count=20,
        confidence_score=0.8,
        avg_latency_ms=60.0,
        error_rate=0.05,
        discovery_sources=["traffic_logs"],
    )
    builder._analyzers = [MockAnalyzer([dep1]), MockAnalyzer([dep2])]

    graph = await builder.build()
    assert len(graph.edges) == 1
    edge = graph.edges[0]

    # Weighted confidence: (0.7*10 + 0.8*20) / 30 = 0.7667, +0.1 boost = ~0.8667
    assert edge.confidence_score == pytest.approx(0.7667 + 0.1, abs=0.01)

    # Connection count should be summed
    assert edge.connection_count == 30

    # Discovery sources should be merged
    assert set(edge.discovery_sources) == {"network", "traffic_logs"}

    # Weighted latency: (50*10 + 60*20) / 30 = 56.67
    assert edge.avg_latency_ms == pytest.approx(56.67, abs=0.1)

    # Weighted error rate: (0.1*10 + 0.05*20) / 30 = 0.0667
    assert edge.error_rate == pytest.approx(0.0667, abs=0.01)


@pytest.mark.asyncio
async def test_build_three_analyzers_boost(builder, service_registry):
    """Three analyzers detecting the same edge should get +0.2 confidence boost."""
    svc_a = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    svc_b = DiscoveredService(service_name="b", host="10.0.0.2", endpoints=["tcp://10.0.0.2:8080"])
    service_registry.register_service(svc_a)
    service_registry.register_service(svc_b)

    deps = [
        ServiceDependency(
            source_service_id=svc_a.service_id, target_service_id=svc_b.service_id,
            dependency_type="http", connection_count=1, confidence_score=0.5,
            discovery_sources=["network"],
        ),
        ServiceDependency(
            source_service_id=svc_a.service_id, target_service_id=svc_b.service_id,
            dependency_type="http", connection_count=1, confidence_score=0.6,
            discovery_sources=["traffic_logs"],
        ),
        ServiceDependency(
            source_service_id=svc_a.service_id, target_service_id=svc_b.service_id,
            dependency_type="http", connection_count=1, confidence_score=0.7,
            discovery_sources=["distributed_tracing"],
        ),
    ]
    builder._analyzers = [MockAnalyzer([d]) for d in deps]

    graph = await builder.build()
    assert len(graph.edges) == 1
    # Base confidence = (0.5+0.6+0.7)/3 = 0.6, +0.2 boost = 0.8
    assert graph.edges[0].confidence_score == pytest.approx(0.8, abs=0.01)


@pytest.mark.asyncio
async def test_build_non_overlapping_analyzers(builder, service_registry):
    """Two analyzers with different edges should produce two edges."""
    svc_a = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    svc_b = DiscoveredService(service_name="b", host="10.0.0.2", endpoints=["tcp://10.0.0.2:8080"])
    svc_c = DiscoveredService(service_name="c", host="10.0.0.3", endpoints=["tcp://10.0.0.3:8080"])
    for svc in [svc_a, svc_b, svc_c]:
        service_registry.register_service(svc)

    dep1 = ServiceDependency(
        source_service_id=svc_a.service_id, target_service_id=svc_b.service_id,
        dependency_type="http", connection_count=1, confidence_score=0.7,
        discovery_sources=["network"],
    )
    dep2 = ServiceDependency(
        source_service_id=svc_a.service_id, target_service_id=svc_c.service_id,
        dependency_type="http", connection_count=1, confidence_score=0.8,
        discovery_sources=["traffic_logs"],
    )
    builder._analyzers = [MockAnalyzer([dep1]), MockAnalyzer([dep2])]

    graph = await builder.build()
    assert len(graph.edges) == 2
    targets = {e.target_service_id for e in graph.edges}
    assert targets == {svc_b.service_id, svc_c.service_id}


@pytest.mark.asyncio
async def test_build_failing_analyzer_skipped(builder, service_registry):
    """A failing analyzer should not break the build."""
    svc = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    service_registry.register_service(svc)

    dep = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="svc-b",
        dependency_type="http", connection_count=1, confidence_score=0.7,
        discovery_sources=["network"],
    )
    builder._analyzers = [FailingAnalyzer(), MockAnalyzer([dep])]

    graph = await builder.build()
    assert len(graph.edges) == 1


@pytest.mark.asyncio
async def test_build_unhealthy_analyzer_skipped(builder, service_registry):
    """An unhealthy analyzer should be skipped."""
    svc = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    service_registry.register_service(svc)

    dep = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="svc-b",
        dependency_type="http", connection_count=1, confidence_score=0.7,
        discovery_sources=["network"],
    )
    builder._analyzers = [MockAnalyzer([], healthy=False), MockAnalyzer([dep])]

    graph = await builder.build()
    assert len(graph.edges) == 1


@pytest.mark.asyncio
async def test_build_capped_at_1_0(builder, service_registry):
    """Confidence boost should not exceed 1.0."""
    svc_a = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    svc_b = DiscoveredService(service_name="b", host="10.0.0.2", endpoints=["tcp://10.0.0.2:8080"])
    service_registry.register_service(svc_a)
    service_registry.register_service(svc_b)

    deps = [
        ServiceDependency(
            source_service_id=svc_a.service_id, target_service_id=svc_b.service_id,
            dependency_type="http", connection_count=1, confidence_score=0.95,
            discovery_sources=["network"],
        ),
        ServiceDependency(
            source_service_id=svc_a.service_id, target_service_id=svc_b.service_id,
            dependency_type="http", connection_count=1, confidence_score=0.95,
            discovery_sources=["traffic_logs"],
        ),
    ]
    builder._analyzers = [MockAnalyzer([d]) for d in deps]

    graph = await builder.build()
    assert len(graph.edges) == 1
    assert graph.edges[0].confidence_score == 1.0


# ------------------------------------------------------------------
# get_graph filtering tests
# ------------------------------------------------------------------

def test_get_graph_min_confidence(builder, dep_registry, service_registry):
    """get_graph should filter by min_confidence."""
    svc = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    service_registry.register_service(svc)

    dep_high = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="b",
        dependency_type="http", confidence_score=0.9, discovery_sources=["network"],
    )
    dep_low = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="c",
        dependency_type="http", confidence_score=0.3, discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep_high)
    dep_registry.store_dependency(dep_low)

    graph = builder.get_graph(min_confidence=0.5)
    assert len(graph.edges) == 1
    assert graph.edges[0].target_service_id == "b"


def test_get_graph_dependency_type_filter(builder, dep_registry, service_registry):
    """get_graph should filter by dependency_type."""
    svc = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    service_registry.register_service(svc)

    dep_http = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="b",
        dependency_type="http", confidence_score=0.9, discovery_sources=["network"],
    )
    dep_db = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="c",
        dependency_type="database", confidence_score=0.9, discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep_http)
    dep_registry.store_dependency(dep_db)

    graph = builder.get_graph(dependency_types=["http"])
    assert len(graph.edges) == 1
    assert graph.edges[0].dependency_type == "http"


# ------------------------------------------------------------------
# Background task tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_background_build_start_stop(builder):
    """Background task should start and stop cleanly."""
    builder.start_background_build(interval_seconds=1)
    assert builder._background_task is not None
    assert builder._stop_event is not None

    builder.stop_background_build()
    assert builder._stop_event is None or builder._stop_event.is_set()


@pytest.mark.asyncio
async def test_background_build_runs(builder, service_registry):
    """Background task should actually run the build."""
    svc = DiscoveredService(service_name="a", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    service_registry.register_service(svc)

    dep = ServiceDependency(
        source_service_id=svc.service_id, target_service_id="b",
        dependency_type="http", connection_count=1, confidence_score=0.7,
        discovery_sources=["network"],
    )
    builder._analyzers = [MockAnalyzer([dep])]

    builder.start_background_build(interval_seconds=1)
    # Wait a bit for the first iteration
    import asyncio
    await asyncio.sleep(0.5)
    builder.stop_background_build()

    # Verify the dependency was stored
    stored = builder._dep_registry.get_all_dependencies()
    assert len(stored) == 1


# ------------------------------------------------------------------
# ServiceMeshAnalyzer tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mesh_analyzer_disabled_without_url(service_registry):
    """If no Prometheus URL is set, analyzer should be disabled."""
    with patch.dict("os.environ", {}, clear=True):
        analyzer = ServiceMeshAnalyzer(
            registry=service_registry,
            prometheus_url="",
        )
    assert analyzer.health_check() is False
    result = await analyzer.analyze()
    assert result == []


def test_mesh_analyzer_health_check(service_registry):
    """Health check should return True when Prometheus URL is set."""
    analyzer = ServiceMeshAnalyzer(
        registry=service_registry,
        prometheus_url="http://prometheus:9090",
    )
    assert analyzer.health_check() is True


@pytest.mark.asyncio
async def test_mesh_analyze_no_httpx(service_registry):
    """If httpx is not installed, should return empty list."""
    with patch("app.discovery.dependencies.mesh_analyzer.httpx", None):
        analyzer = ServiceMeshAnalyzer(
            registry=service_registry,
            prometheus_url="http://prometheus:9090",
        )
        result = await analyzer.analyze()
    assert result == []


@pytest.mark.asyncio
async def test_mesh_analyze_prometheus_query(service_registry):
    """Mock Prometheus response and verify dependency extraction."""
    svc_a = DiscoveredService(service_name="frontend", host="10.0.0.1", endpoints=["tcp://10.0.0.1:8080"])
    svc_b = DiscoveredService(service_name="backend", host="10.0.0.2", endpoints=["tcp://10.0.0.2:8080"])
    service_registry.register_service(svc_a)
    service_registry.register_service(svc_b)

    analyzer = ServiceMeshAnalyzer(
        registry=service_registry,
        prometheus_url="http://prometheus:9090",
    )

    prom_response = [
        {
            "metric": {
                "source_app": "frontend",
                "destination_app": "backend",
                "reporter": "source",
                "response_code": "200",
            },
            "value": [1704110400, "42"],
        },
        {
            "metric": {
                "source_app": "frontend",
                "destination_app": "backend",
                "reporter": "source",
                "response_code": "500",
            },
            "value": [1704110400, "3"],
        },
    ]

    with patch.object(analyzer, "_prometheus_query_with_retry", return_value=prom_response):
        with patch.object(analyzer, "_enrich_with_latency", return_value=None):
            result = await analyzer.analyze()

    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_a.service_id
    assert dep.target_service_id == svc_b.service_id
    assert dep.connection_count == 45  # 42 + 3
    assert dep.error_rate == pytest.approx(3 / 45, abs=0.01)
    assert dep.confidence_score == 0.95
    assert dep.discovery_sources == ["service_mesh"]


@pytest.mark.asyncio
async def test_mesh_analyze_envoy_fallback(service_registry):
    """Mock Envoy admin endpoint and verify fallback parsing."""
    analyzer = ServiceMeshAnalyzer(
        registry=service_registry,
        prometheus_url="http://prometheus:9090",
    )

    # Force Prometheus query to return empty so fallback kicks in
    with patch.object(analyzer, "_prometheus_query_with_retry", return_value=[]):
        with patch.object(analyzer, "_query_envoy_metrics", return_value=[
            ServiceDependency(
                source_service_id="envoy-proxy",
                target_service_id="envoy-backend",
                dependency_type="http",
                connection_count=100,
                avg_latency_ms=50.0,
                confidence_score=0.6,
                discovery_sources=["envoy_metrics"],
            )
        ]) as mock_envoy:
            result = await analyzer.analyze()

    assert len(result) == 1
    assert result[0].target_service_id == "envoy-backend"
    # The actual Envoy text parsing is tested via _query_envoy_metrics directly below


def test_mesh_query_envoy_metrics(service_registry):
    """Test the Envoy text parsing directly."""
    analyzer = ServiceMeshAnalyzer(
        registry=service_registry,
        prometheus_url="http://prometheus:9090",
    )

    envoy_text = """
# TYPE envoy_cluster_upstream_rq_total counter
envoy_cluster_upstream_rq_total{cluster="outbound|8080||backend.default.svc.cluster.local"} 100
envoy_cluster_upstream_rq_time_sum{cluster="outbound|8080||backend.default.svc.cluster.local"} 5000
"""

    with patch.object(httpx, "AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = envoy_text
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = asyncio.run(analyzer._query_envoy_metrics())

    assert len(result) == 1
    dep = result[0]
    assert dep.target_service_id == "envoy-backend"
    assert dep.connection_count == 100
    assert dep.avg_latency_ms == 50.0  # 5000 / 100
    assert dep.confidence_score == 0.6


@pytest.mark.asyncio
async def test_mesh_retry_logic(service_registry):
    """Prometheus query should retry on failure."""
    analyzer = ServiceMeshAnalyzer(
        registry=service_registry,
        prometheus_url="http://prometheus:9090",
    )

    call_count = 0

    async def flaky_query(query):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("refused")
        return []

    with patch.object(analyzer, "_prometheus_query", side_effect=flaky_query):
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await analyzer._prometheus_query_with_retry("test_query")

    assert call_count == 3
    assert result == []


def test_parse_envoy_line():
    """Test Envoy Prometheus text format parsing."""
    line = 'envoy_cluster_upstream_rq_total{cluster="outbound|8080||backend.default.svc.cluster.local"} 100'
    cluster, count = ServiceMeshAnalyzer._parse_envoy_line(line, "envoy_cluster_upstream_rq_total")
    assert cluster == "outbound|8080||backend.default.svc.cluster.local"
    assert count == 100.0


def test_extract_service_from_cluster():
    """Test cluster name to service name extraction."""
    assert ServiceMeshAnalyzer._extract_service_from_cluster(
        "outbound|8080||backend.default.svc.cluster.local"
    ) == "backend"
    assert ServiceMeshAnalyzer._extract_service_from_cluster("my-service") == "my-service"
    assert ServiceMeshAnalyzer._extract_service_from_cluster("_internal") is None
