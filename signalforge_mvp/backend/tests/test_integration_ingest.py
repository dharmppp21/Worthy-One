from datetime import datetime, timezone

from app.schemas import EventType, TelemetryEvent
from app.storage import store


def make_request_event(index: int, service_name: str, status_code: int = 200, latency_ms: int = 100) -> dict:
    """Build a JSON payload for a metric/http_request event."""
    return {
        "event_id": f"integ-{service_name}-{index:03d}",
        "tenant_id": "demo-company",
        "service_name": service_name,
        "event_type": "metric",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": "http_request",
        "value": 1,
        "attributes": {
            "status_code": status_code,
            "latency_ms": latency_ms,
            "endpoint": "/test",
        },
    }


def make_trace_event(index: int, caller: str, callee: str) -> dict:
    """Build a JSON payload for a trace/service_call event."""
    return {
        "event_id": f"integ-trace-{caller}-{callee}-{index:03d}",
        "tenant_id": "demo-company",
        "service_name": caller,
        "event_type": "trace",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": "service_call",
        "trace_id": f"trace-{index:03d}",
        "attributes": {
            "caller": caller,
            "callee": callee,
            "status": "success",
        },
    }


class TestIngestToIncidentFlow:
    """End-to-end test: ingest events → detect anomaly → create incident."""

    def test_healthy_events_no_incident(self, client, reset_store):
        """20 healthy events should not trigger any incident."""
        for i in range(20):
            resp = client.post("/ingest", json=make_request_event(i, "checkout-service", 200, 100))
            assert resp.status_code in (200, 202)
            data = resp.json()
            assert data["accepted"] is True
            assert data["duplicate"] is False

        incidents = client.get("/incidents").json()
        assert incidents["count"] == 0

    def test_bad_events_create_incident(self, client, reset_store):
        """20 failed events should trigger an incident for the service."""
        for i in range(20):
            resp = client.post("/ingest", json=make_request_event(i, "payment-service", 500, 2000))
            assert resp.status_code in (200, 202)

        incidents = client.get("/incidents").json()
        assert incidents["count"] == 1
        inc = incidents["incidents"][0]
        assert inc["service_name"] == "payment-service"
        assert inc["severity"] in ("warning", "critical")
        assert inc["status"] == "investigating"
        assert "timeline" in inc
        assert len(inc["timeline"]) >= 2  # created + evidence entries

    def test_incident_detail_is_available(self, client, reset_store):
        """Created incident can be fetched by ID with full detail."""
        for i in range(20):
            client.post("/ingest", json=make_request_event(i, "inventory-service", 500, 2000))

        incidents = client.get("/incidents").json()
        inc_id = incidents["incidents"][0]["id"]

        detail = client.get(f"/incidents/{inc_id}").json()
        assert detail["id"] == inc_id
        assert detail["service_name"] == "inventory-service"
        assert "evidence" in detail
        assert len(detail["evidence"]) > 0

    def test_incident_status_update(self, client, reset_store):
        """PATCH /incidents/{id}/status updates the incident and appends timeline."""
        for i in range(20):
            client.post("/ingest", json=make_request_event(i, "fraud-service", 500, 2000))

        inc_id = client.get("/incidents").json()["incidents"][0]["id"]
        original = client.get(f"/incidents/{inc_id}").json()
        original_timeline_len = len(original["timeline"])

        patch = client.patch(
            f"/incidents/{inc_id}/status",
            json={"status": "mitigated", "actor": "test-user", "note": "Rolled back"},
        )
        assert patch.status_code == 200
        updated = patch.json()
        assert updated["status"] == "mitigated"
        assert len(updated["timeline"]) == original_timeline_len + 1
        last_entry = updated["timeline"][-1]
        assert last_entry["event_type"] == "status_changed"
        assert "mitigated" in last_entry["message"]
        assert last_entry["actor"] == "test-user"

    def test_events_persisted_and_listed(self, client, reset_store):
        """GET /events returns the latest ingested events."""
        for i in range(5):
            client.post("/ingest", json=make_request_event(i, "notification-service", 200, 100))

        events_resp = client.get("/events").json()
        assert events_resp["count"] >= 5
        assert any(e["service_name"] == "notification-service" for e in events_resp["events"])

    def test_duplicate_event_accepted_but_not_stored(self, client, reset_store):
        """Same event_id twice returns duplicate=True but still accepted."""
        payload = make_request_event(0, "checkout-service", 200, 100)
        r1 = client.post("/ingest", json=payload).json()
        r2 = client.post("/ingest", json=payload).json()
        assert r1["accepted"] is True
        assert r1["duplicate"] is False
        assert r2["accepted"] is True
        assert r2["duplicate"] is True

        events = client.get("/events").json()
        matching = [e for e in events["events"] if e["event_id"] == payload["event_id"]]
        assert len(matching) == 1

    def test_resolved_incident_allows_new_incident(self, client, reset_store):
        """Resolving an incident should allow a new incident for the same service."""
        for i in range(20):
            client.post("/ingest", json=make_request_event(i, "checkout-service", 500, 2000))

        inc_id = client.get("/incidents").json()["incidents"][0]["id"]
        client.patch(f"/incidents/{inc_id}/status", json={"status": "resolved", "actor": "test"})

        # New batch of bad events should create a second incident
        for i in range(20, 40):
            client.post("/ingest", json=make_request_event(i, "checkout-service", 500, 2000))

        incidents = client.get("/incidents").json()
        assert incidents["count"] == 2

    def test_mitigated_incident_blocks_duplicate(self, client, reset_store):
        """Mitigating an incident should NOT allow a new incident until resolved."""
        for i in range(20):
            client.post("/ingest", json=make_request_event(i, "payment-service", 500, 2000))

        inc_id = client.get("/incidents").json()["incidents"][0]["id"]
        client.patch(f"/incidents/{inc_id}/status", json={"status": "mitigated", "actor": "test"})

        # New bad events should NOT create a second incident
        for i in range(20, 40):
            client.post("/ingest", json=make_request_event(i, "payment-service", 500, 2000))

        incidents = client.get("/incidents").json()
        assert incidents["count"] == 1


class TestIngestValidation:
    """Ensure the ingest endpoint validates payloads correctly."""

    def test_metric_event_missing_status_code_returns_422(self, client, reset_store):
        payload = {
            "event_id": "bad-metric-001",
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "event_type": "metric",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": "http_request",
            "attributes": {"latency_ms": 100},  # missing status_code
        }
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_log_event_missing_message_returns_422(self, client, reset_store):
        payload = {
            "event_id": "bad-log-001",
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "event_type": "log",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": "error",
            "severity": "error",
            # missing message
        }
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_trace_event_missing_trace_id_returns_422(self, client, reset_store):
        payload = {
            "event_id": "bad-trace-001",
            "tenant_id": "demo-company",
            "service_name": "checkout-service",
            "event_type": "trace",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": "service_call",
            "attributes": {"caller": "a", "callee": "b"},
            # missing trace_id
        }
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422
