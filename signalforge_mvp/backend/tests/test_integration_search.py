from datetime import datetime, timezone


class TestIncidentSearch:
    """End-to-end test: keyword search finds incidents."""

    def test_search_finds_incident_by_title(self, client, reset_store):
        """Ingest bad events to create an incident, then search for it."""
        # Create an incident by ingesting 20 bad events
        for i in range(20):
            client.post("/ingest", json={
                "event_id": f"search-inc-{i:03d}",
                "tenant_id": "demo-company",
                "service_name": "notification-service",
                "event_type": "metric",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "http_request",
                "value": 1,
                "attributes": {
                    "status_code": 500,
                    "latency_ms": 2000,
                    "endpoint": "/notify",
                },
            })

        resp = client.get("/search?q=notification")
        assert resp.status_code == 200
        data = resp.json()
        results = [r for r in data["results"] if r["type"] == "incident"]
        assert len(results) >= 1
        assert any("notification" in r["title"] for r in results)

    def test_search_finds_incident_by_service_name(self, client, reset_store):
        for i in range(20):
            client.post("/ingest", json={
                "event_id": f"search-svc-{i:03d}",
                "tenant_id": "demo-company",
                "service_name": "inventory-service",
                "event_type": "metric",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "http_request",
                "value": 1,
                "attributes": {
                    "status_code": 500,
                    "latency_ms": 2000,
                    "endpoint": "/stock",
                },
            })

        resp = client.get("/search?q=inventory-service")
        assert resp.status_code == 200
        data = resp.json()
        results = [r for r in data["results"] if r["type"] == "incident"]
        assert any(r["service_name"] == "inventory-service" for r in results)

    def test_search_returns_mixed_results(self, client, reset_store):
        """Search should return both incidents and runbooks."""
        # Create incident
        for i in range(20):
            client.post("/ingest", json={
                "event_id": f"search-mix-{i:03d}",
                "tenant_id": "demo-company",
                "service_name": "checkout-service",
                "event_type": "metric",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "http_request",
                "value": 1,
                "attributes": {
                    "status_code": 500,
                    "latency_ms": 2000,
                    "endpoint": "/cart",
                },
            })
        # Create runbook
        client.post("/runbooks", json={
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "title": "Checkout runbook",
            "description": "Handle checkout failures",
            "steps": [],
        })

        resp = client.get("/search?q=checkout")
        assert resp.status_code == 200
        data = resp.json()
        types = {r["type"] for r in data["results"]}
        assert "incident" in types
        assert "runbook" in types

    def test_search_no_results(self, client, reset_store):
        resp = client.get("/search?q=xyznonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    def test_search_empty_query_returns_422(self, client, reset_store):
        resp = client.get("/search?q=")
        assert resp.status_code == 422


class TestHealthCheck:
    """End-to-end test: health endpoint reports system status."""

    def test_health_returns_ok(self, client, reset_store):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "environment" in data
        assert "dependencies" in data
        assert data["dependencies"]["database"] in ("available", "unavailable")
        assert data["dependencies"]["kafka"] in ("available", "unavailable")
        assert data["dependencies"]["redis"] in ("available", "unavailable")
