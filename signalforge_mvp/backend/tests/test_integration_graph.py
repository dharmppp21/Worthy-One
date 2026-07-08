from datetime import datetime, timezone


class TestServiceGraph:
    """End-to-end test: trace events build the service dependency graph."""

    def test_empty_graph_has_no_nodes_or_edges(self, client, reset_store):
        resp = client.get("/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_single_trace_creates_nodes_and_edge(self, client, reset_store):
        payload = {
            "event_id": "graph-trace-001",
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "event_type": "trace",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": "service_call",
            "trace_id": "trace-001",
            "attributes": {"caller": "checkout-service", "callee": "payment-service", "status": "success"},
        }
        assert client.post("/ingest", json=payload).status_code in (200, 202)

        resp = client.get("/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {"checkout-service", "payment-service"}

        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert edge["source"] == "checkout-service"
        assert edge["target"] == "payment-service"
        assert edge["label"] == "calls"
        assert edge["count"] == 1

    def test_multiple_traces_aggregate_counts(self, client, reset_store):
        """Multiple calls between the same pair should aggregate the count."""
        for i in range(5):
            payload = {
                "event_id": f"graph-trace-{i:03d}",
                "tenant_id": "demo-company",
                "service_name": "checkout-service",
                "event_type": "trace",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "service_call",
                "trace_id": f"trace-{i:03d}",
                "attributes": {"caller": "checkout-service", "callee": "inventory-service", "status": "success"},
            }
            client.post("/ingest", json=payload)

        data = client.get("/graph").json()
        assert len(data["nodes"]) == 2
        edges = [e for e in data["edges"] if e["source"] == "checkout-service" and e["target"] == "inventory-service"]
        assert len(edges) == 1
        assert edges[0]["count"] == 5

    def test_different_callers_create_multiple_edges(self, client, reset_store):
        """Different caller→callee pairs create separate edges."""
        traces = [
            ("checkout-service", "payment-service"),
            ("checkout-service", "inventory-service"),
            ("payment-service", "fraud-service"),
        ]
        for i, (caller, callee) in enumerate(traces):
            payload = {
                "event_id": f"graph-multi-{i:03d}",
                "tenant_id": "demo-company",
                "service_name": caller,
                "event_type": "trace",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "service_call",
                "trace_id": f"trace-{i:03d}",
                "attributes": {"caller": caller, "callee": callee, "status": "success"},
            }
            client.post("/ingest", json=payload)

        data = client.get("/graph").json()
        assert len(data["nodes"]) == 4
        assert len(data["edges"]) == 3

        edge_pairs = {(e["source"], e["target"]) for e in data["edges"]}
        assert edge_pairs == set(traces)


class TestAutoDependencyGraph:
    """The /graph/dependencies endpoint returns full edge detail and drops orphans."""

    def test_returns_rich_edges_and_filters_orphans(self, client, reset_store):
        from app.main import app as fastapi_app
        from app.routers.discovery import get_graph_builder
        from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
        from app.discovery.models import DiscoveredService

        svc_a = DiscoveredService(
            service_name="api", host="127.0.0.1", endpoints=["tcp://127.0.0.1:8000"]
        )
        svc_b = DiscoveredService(
            service_name="postgres", host="127.0.0.1", endpoints=["tcp://127.0.0.1:5432"]
        )
        real_edge = ServiceDependency(
            source_service_id=svc_a.service_id,
            target_service_id=svc_b.service_id,
            dependency_type="database",
            connection_count=7,
            avg_latency_ms=12.5,
            confidence_score=0.9,
            discovery_sources=["network"],
        )
        # Target is not one of the graph nodes — must be filtered out.
        orphan_edge = ServiceDependency(
            source_service_id=svc_a.service_id,
            target_service_id="inferred-10-0-0-1-5000",
            dependency_type="unknown",
            confidence_score=0.3,
            discovery_sources=["network"],
        )
        graph = DependencyGraph(nodes=[svc_a, svc_b], edges=[real_edge, orphan_edge])

        class _FakeBuilder:
            def get_graph(self, **kwargs):
                return graph

        fastapi_app.dependency_overrides[get_graph_builder] = lambda: _FakeBuilder()
        try:
            resp = client.get("/graph/dependencies")
        finally:
            fastapi_app.dependency_overrides.pop(get_graph_builder, None)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1  # orphan filtered

        edge = data["edges"][0]
        assert edge["source"] == svc_a.service_id
        assert edge["target"] == svc_b.service_id
        assert edge["dependency_type"] == "database"
        assert edge["confidence"] == 0.9
        assert edge["connection_count"] == 7
        assert edge["avg_latency_ms"] == 12.5
        assert edge["sources"] == ["network"]
