"""Performance tests for discovery engine, registry, and graph at scale.

Measures latency and memory with 100 services and 500 dependencies.
All providers are mocked so the measurement focuses on engine overhead.
"""
from __future__ import annotations

import asyncio
import json
import time
import tracemalloc
from typing import List
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
from app.discovery.dependencies.network_scanner import NetworkConnectionScanner
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.engine import DiscoveryEngine
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.schemas import ServiceGraphResponse, ServiceGraphNode, ServiceGraphEdge


# ------------------------------------------------------------------
# Fixtures (db_session and perf_db are in conftest.py)
# ------------------------------------------------------------------

@pytest.fixture
def registry(db_session: Session) -> ServiceRegistry:
    return ServiceRegistry(db_session=db_session)


@pytest.fixture
def dep_registry(db_session: Session) -> DependencyRegistry:
    return DependencyRegistry(db_session=db_session)


@pytest.fixture
def engine(registry: ServiceRegistry) -> DiscoveryEngine:
    return DiscoveryEngine(registry=registry)


@pytest.fixture
def graph_builder(registry: ServiceRegistry, dep_registry: DependencyRegistry) -> DependencyGraphBuilder:
    return DependencyGraphBuilder(
        analyzers=[],
        registry=registry,
        dep_registry=dep_registry,
    )


# ------------------------------------------------------------------
# Discovery engine latency
# ------------------------------------------------------------------

class TestDiscoveryEngineLatency:
    """Measure how fast the engine processes 100 services end-to-end."""

    @pytest.mark.asyncio
    async def test_run_discovery_under_10_seconds(
        self,
        engine: DiscoveryEngine,
        mock_services: List[DiscoveredService],
    ) -> None:
        """Mock provider returns 100 services instantly; engine should finish < 10s."""
        from unittest.mock import AsyncMock

        provider = AsyncMock()
        provider.discover = AsyncMock(return_value=mock_services)
        engine.register_provider(provider)

        start = time.perf_counter()
        result = await engine.run_discovery()
        elapsed = time.perf_counter() - start

        assert len(result) == 100
        assert elapsed < 10.0, f"Discovery took {elapsed:.2f}s, expected < 10s"

    def test_memory_footprint_under_200_mb(
        self,
        registry: ServiceRegistry,
        mock_services: List[DiscoveredService],
    ) -> None:
        """Register 100 services and verify memory stays under 200 MB (baseline < 10 MB)."""
        tracemalloc.start()
        before = tracemalloc.take_snapshot()

        for svc in mock_services:
            registry.register_service(svc)

        after = tracemalloc.take_snapshot()
        diff = after.compare_to(before, "lineno")
        total_bytes = sum(stat.size_diff for stat in diff if stat.size_diff > 0)
        total_mb = total_bytes / (1024 * 1024)

        tracemalloc.stop()
        assert total_mb < 200.0, f"Memory footprint {total_mb:.2f} MB exceeds 200 MB"


# ------------------------------------------------------------------
# Dependency registry write latency
# ------------------------------------------------------------------

class TestDependencyRegistryLatency:
    """Measure DB write performance for 500 dependencies."""

    def test_store_500_dependencies_under_5_seconds(
        self,
        dep_registry: DependencyRegistry,
        mock_dependencies: List[ServiceDependency],
    ) -> None:
        """Upsert 500 dependencies and verify total time < 5 seconds."""
        start = time.perf_counter()
        for dep in mock_dependencies:
            dep_registry.store_dependency(dep)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"500 dependency upserts took {elapsed:.2f}s"

        # Verify all were stored
        all_deps = dep_registry.get_all_dependencies()
        assert len(all_deps) == 500


# ------------------------------------------------------------------
# Graph query latency
# ------------------------------------------------------------------

class TestGraphQueryLatency:
    """Measure graph query performance with 100 nodes and 500 edges."""

    @pytest.fixture
    def populated_graph(
        self,
        registry: ServiceRegistry,
        dep_registry: DependencyRegistry,
        mock_services: List[DiscoveredService],
        mock_dependencies: List[ServiceDependency],
    ) -> DependencyGraph:
        """Build a graph with 100 services and 500 dependencies in the registry."""
        for svc in mock_services:
            registry.register_service(svc)
        for dep in mock_dependencies:
            dep_registry.store_dependency(dep)
        return dep_registry.get_dependency_graph(mock_services)

    def test_get_all_dependencies_under_100ms(
        self,
        populated_graph: DependencyGraph,
    ) -> None:
        """Retrieving all 500 edges should be < 100 ms."""
        start = time.perf_counter()
        edges = populated_graph.edges
        elapsed = time.perf_counter() - start

        assert len(edges) == 500
        assert elapsed < 0.1, f"get_all_dependencies took {elapsed*1000:.1f}ms"

    def test_get_upstream_under_100ms(
        self,
        populated_graph: DependencyGraph,
        mock_services: List[DiscoveredService],
    ) -> None:
        """get_upstream for a random service should be < 100 ms."""
        service_id = mock_services[42].service_id

        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            upstream = populated_graph.get_upstream(service_id)
            latencies.append(time.perf_counter() - start)

        avg_ms = sum(latencies) / len(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000

        assert avg_ms < 100.0, f"avg get_upstream {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_upstream {p95_ms:.1f}ms"

    def test_get_downstream_under_100ms(
        self,
        populated_graph: DependencyGraph,
        mock_services: List[DiscoveredService],
    ) -> None:
        """get_downstream for a random service should be < 100 ms."""
        service_id = mock_services[42].service_id

        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            downstream = populated_graph.get_downstream(service_id)
            latencies.append(time.perf_counter() - start)

        avg_ms = sum(latencies) / len(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000

        assert avg_ms < 100.0, f"avg get_downstream {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_downstream {p95_ms:.1f}ms"

    def test_get_critical_path_under_100ms(
        self,
        populated_graph: DependencyGraph,
        mock_services: List[DiscoveredService],
    ) -> None:
        """BFS shortest path should be < 100 ms."""
        src_id = mock_services[0].service_id
        tgt_id = mock_services[50].service_id

        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            path = populated_graph.get_critical_path(src_id, tgt_id)
            latencies.append(time.perf_counter() - start)

        avg_ms = sum(latencies) / len(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000

        assert avg_ms < 100.0, f"avg get_critical_path {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_critical_path {p95_ms:.1f}ms"

    def test_graph_json_size_under_1_mb(
        self,
        populated_graph: DependencyGraph,
    ) -> None:
        """Serializing the graph to the frontend JSON format should be < 1 MB."""
        nodes = [
            ServiceGraphNode(id=node.service_id, label=node.service_name)
            for node in populated_graph.nodes
        ]
        edges = [
            ServiceGraphEdge(
                source=edge.source_service_id,
                target=edge.target_service_id,
                label=edge.dependency_type,
                count=edge.connection_count,
            )
            for edge in populated_graph.edges
        ]
        response = ServiceGraphResponse(nodes=nodes, edges=edges)
        json_bytes = json.dumps(response.model_dump(mode="json")).encode("utf-8")
        size_mb = len(json_bytes) / (1024 * 1024)

        assert size_mb < 1.0, f"Graph JSON size {size_mb:.2f} MB exceeds 1 MB"
        # Sanity check: should be well under 1 MB for 100 nodes + 500 edges
        assert size_mb < 0.5, f"Graph JSON size {size_mb:.2f} MB unexpectedly large"
