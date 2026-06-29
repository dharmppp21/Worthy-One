from datetime import datetime, timezone

from app.schemas import EventType, TelemetryEvent
from app.services.event_processor import event_processor
from app.storage import store


def reset_store():
    store.reset()


def make_event(index: int, status_code: int = 500, latency_ms: int = 1500) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"proc-test-{index}",
        tenant_id="demo-company",
        service_name="checkout-service",
        event_type=EventType.metric,
        timestamp=datetime.now(timezone.utc),
        name="http_request",
        value=1,
        attributes={
            "status_code": status_code,
            "latency_ms": latency_ms,
            "endpoint": "/api/checkout",
        },
    )


def test_process_duplicate_event_returns_duplicate():
    reset_store()
    event = make_event(1)

    first = event_processor.process(event)
    second = event_processor.process(event)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["event_id"] == event.event_id
    assert second["event_id"] == event.event_id


def test_process_healthy_event_no_incident():
    reset_store()
    events = [make_event(i, status_code=200, latency_ms=100) for i in range(20)]
    for event in events:
        event_processor.process(event)

    incidents = store.list_incidents()
    assert len(incidents) == 0


def test_process_anomaly_event_creates_incident():
    reset_store()
    events = [make_event(i, status_code=500, latency_ms=1500) for i in range(20)]
    for event in events:
        event_processor.process(event)

    incidents = store.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].service_name == "checkout-service"
    assert incidents[0].severity in ("warning", "critical")


def test_process_creates_only_one_open_incident_per_service():
    reset_store()
    # First batch creates an incident
    for i in range(20):
        event_processor.process(make_event(i, status_code=500, latency_ms=1500))

    # Second batch should not create a duplicate open incident
    for i in range(20, 40):
        event_processor.process(make_event(i, status_code=500, latency_ms=1500))

    incidents = store.list_incidents()
    assert len(incidents) == 1


def test_process_pipeline_stores_events_in_db():
    reset_store()
    event = make_event(1, status_code=200, latency_ms=100)
    event_processor.process(event)

    events = store.list_events(limit=10)
    assert len(events) >= 1
    assert any(e.event_id == event.event_id for e in events)


def test_process_pipeline_stores_events_in_redis_hot_state():
    reset_store()
    event = make_event(1, status_code=200, latency_ms=100)
    event_processor.process(event)

    # get_recent_events reads from Redis first, then falls back to DB
    recent = store.get_recent_events(event.tenant_id, event.service_name)
    assert len(recent) >= 1
    assert any(e.event_id == event.event_id for e in recent)
