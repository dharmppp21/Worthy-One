"""Performance tests for dependency graph queries at scale.

Builds a graph with 100 services and 500 dependencies, then measures
query latency for common graph operations.
"""
from __future__ import annotations

import json
import statistics
import time
from typing import List

import pytest

from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.schemas import ServiceGraphResponse, ServiceGraphNode, ServiceGraphEdge


# ------------------------------------------------------------------
# Fixtures (db_session and perf_db are in conftest.py)
# ------------------------------------------------------------------

@pytest.fixture
def populated_graph(
    db_session,
    mock_services: List[DiscoveredService],
    mock_dependencies: List[ServiceDependency],
) -> DependencyGraph:
    """Build and return a graph with 100 nodes and 500 edges."""
    registry = ServiceRegistry(db_session=db_session)
    for svc in mock_services:
        registry.register_service(svc)

    dep_registry = DependencyRegistry(db_session=db_session)
    for dep in mock_dependencies:
        dep_registry.store_dependency(dep)

    return dep_registry.get_dependency_graph(mock_services)


# ------------------------------------------------------------------
# Query latency benchmarks
# ------------------------------------------------------------------

class TestGraphQueryScale:
    """Measure graph query latency with 100 nodes and 500 edges."""

    def test_get_all_dependencies_latency(
        self,
        populated_graph: DependencyGraph,
    ) -> None:
        """get_all_dependencies (all 500 edges) should avg < 100 ms."""
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            edges = populated_graph.edges
            latencies.append(time.perf_counter() - start)

        avg_ms = statistics.mean(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000
        p99_ms = sorted(latencies)[int(len(latencies) * 0.99)] * 1000

        assert len(edges) == 500
        assert avg_ms < 100.0, f"avg get_all_dependencies {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_all_dependencies {p95_ms:.1f}ms"
        assert p99_ms < 100.0, f"p99 get_all_dependencies {p99_ms:.1f}ms"

    def test_get_upstream_latency(
        self,
        populated_graph: DependencyGraph,
        mock_services: List[DiscoveredService],
    ) -> None:
        """get_upstream (~5 edges avg) should avg < 100 ms."""
        latencies = []
        for _ in range(100):
            svc = mock_services[_ % len(mock_services)]
            start = time.perf_counter()
            upstream = populated_graph.get_upstream(svc.service_id)
            latencies.append(time.perf_counter() - start)

        avg_ms = statistics.mean(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000

        assert avg_ms < 100.0, f"avg get_upstream {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_upstream {p95_ms:.1f}ms"

    def test_get_downstream_latency(
        self,
        populated_graph: DependencyGraph,
        mock_services: List[DiscoveredService],
    ) -> None:
        """get_downstream (~5 edges avg) should avg < 100 ms."""
        latencies = []
        for _ in range(100):
            svc = mock_services[_ % len(mock_services)]
            start = time.perf_counter()
            downstream = populated_graph.get_downstream(svc.service_id)
            latencies.append(time.perf_counter() - start)

        avg_ms = statistics.mean(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000

        assert avg_ms < 100.0, f"avg get_downstream {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_downstream {p95_ms:.1f}ms"

    def test_get_critical_path_latency(
        self,
        populated_graph: DependencyGraph,
        mock_services: List[DiscoveredService],
    ) -> None:
        """BFS shortest path should avg < 100 ms."""
        latencies = []
        for _ in range(100):
            src = mock_services[_ % len(mock_services)]
            tgt = mock_services[(_ + 10) % len(mock_services)]
            start = time.perf_counter()
            populated_graph.get_critical_path(src.service_id, tgt.service_id)
            latencies.append(time.perf_counter() - start)

        avg_ms = statistics.mean(latencies) * 1000
        p95_ms = sorted(latencies)[int(len(latencies) * 0.95)] * 1000

        assert avg_ms < 100.0, f"avg get_critical_path {avg_ms:.1f}ms"
        assert p95_ms < 100.0, f"p95 get_critical_path {p95_ms:.1f}ms"

    def test_graph_rendering_json_size_under_1_mb(
        self,
        populated_graph: DependencyGraph,
    ) -> None:
        """Serializing to the same format as GET /graph/auto should be < 1 MB."""
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

    def test_graph_rendering_json_size_sanity(
        self,
        populated_graph: DependencyGraph,
    ) -> None:
        """100 nodes + 500 edges should be roughly 100-200 KB."""
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
        size_kb = len(json_bytes) / 1024

        # With 100 nodes and 500 edges, expect ~100-200 KB
        assert 50.0 < size_kb < 500.0, f"Graph JSON size {size_kb:.1f} KB outside expected range"
