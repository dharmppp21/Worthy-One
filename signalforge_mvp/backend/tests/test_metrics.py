"""Prometheus /metrics endpoint + RED and domain metrics."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.schemas import EventType, TelemetryEvent
from app.services.event_processor import event_processor


def test_metrics_endpoint_exposes_http_metrics(client, reset_store):
    client.get("/incidents")  # generate one request to record
    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "signalforge_http_requests_total" in body
    assert "signalforge_http_request_duration_seconds" in body
    # Labelled by the route template, not the raw path (cardinality guard).
    assert 'path="/incidents"' in body


def test_metrics_counts_ingested_events(reset_store):
    event = TelemetryEvent(
        event_id="metrics-ingest-1",
        tenant_id="demo-company",
        service_name="svc",
        event_type=EventType.metric,
        timestamp=datetime.now(timezone.utc),
        name="http_request",
        value=1,
        attributes={"status_code": 200, "latency_ms": 50},
    )
    event_processor.process(event)

    body = TestClient(fastapi_app).get("/metrics").text
    assert "signalforge_events_ingested_total" in body
    assert 'event_type="metric"' in body
