from datetime import datetime, timezone

from app.anomaly import AnomalyResult, WindowStats
from app.incident_engine import maybe_create_incident
from app.schemas import EventType, IncidentStatus, IncidentStatusUpdate, IncidentTimelineEvent, TelemetryEvent
from app.services.telemetry_service import update_incident_status
from app.storage import store


def reset_store() -> None:
    store.reset()


def make_event(index: int) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"incident-test-event-{index}",
        tenant_id="demo-company",
        service_name="payment-service",
        event_type=EventType.metric,
        timestamp=datetime.now(timezone.utc),
        name="http_request",
        value=1,
        attributes={
            "status_code": 500,
            "latency_ms": 1500,
            "endpoint": "/charge",
        },
    )


def make_anomaly() -> AnomalyResult:
    return AnomalyResult(
        is_anomaly=True,
        severity="warning",
        title="Service health anomaly detected",
        evidence=[
            "Analyzed the last 20 request events.",
            "Error count is 5/20 (25%).",
            "Warning error-rate breach: 25% >= 20%.",
        ],
        stats=WindowStats(
            sample_count=20,
            error_count=5,
            error_rate=0.25,
            avg_latency_ms=900,
            p95_latency_ms=1400,
        ),
    )


def test_duplicate_open_incident_is_not_created():
    reset_store()
    anomaly = make_anomaly()
    event = make_event(1)

    first = maybe_create_incident(event, anomaly, [event])
    second = maybe_create_incident(event, anomaly, [event])

    assert first is not None
    assert second is None
    assert len(store.list_incidents()) == 1


def test_resolved_incident_allows_future_incident_for_same_service():
    reset_store()
    anomaly = make_anomaly()
    event = make_event(1)

    first = maybe_create_incident(event, anomaly, [event])
    assert first is not None

    update_incident_status(
        first.id,
        IncidentStatusUpdate(status=IncidentStatus.resolved, actor="test", note="Recovered"),
        tenant_id="demo-company",
    )

    second = maybe_create_incident(make_event(2), anomaly, [make_event(2)])

    assert second is not None
    assert len(store.list_incidents()) == 2


def test_status_update_changes_status_and_appends_timeline():
    reset_store()
    anomaly = make_anomaly()
    event = make_event(1)
    incident = maybe_create_incident(event, anomaly, [event])
    assert incident is not None

    updated = update_incident_status(
        incident.id,
        IncidentStatusUpdate(status=IncidentStatus.mitigated, actor="on-call", note="Rolled back v42"),
        tenant_id="demo-company",
    )

    assert updated.status == IncidentStatus.mitigated
    assert updated.updated_at >= updated.created_at
    assert len(updated.timeline) == len(incident.timeline) + 1
    assert updated.timeline[-1].actor == "on-call"
    assert "Rolled back v42" in updated.timeline[-1].message


def test_mitigated_incident_prevents_duplicate_open_incident():
    reset_store()
    anomaly = make_anomaly()
    event = make_event(1)

    first = maybe_create_incident(event, anomaly, [event])
    assert first is not None

    update_incident_status(
        first.id,
        IncidentStatusUpdate(status=IncidentStatus.mitigated, actor="test", note="Partial fix applied"),
        tenant_id="demo-company",
    )

    second = maybe_create_incident(make_event(2), anomaly, [make_event(2)])
    assert second is None
    assert len(store.list_incidents()) == 1


def test_status_update_to_same_status_is_noop():
    reset_store()
    anomaly = make_anomaly()
    event = make_event(1)
    incident = maybe_create_incident(event, anomaly, [event])
    assert incident is not None

    updated = update_incident_status(
        incident.id,
        IncidentStatusUpdate(status=IncidentStatus.investigating, actor="test"),
        tenant_id="demo-company",
    )

    assert updated.status == IncidentStatus.investigating
    assert len(updated.timeline) == len(incident.timeline)


def test_incident_timeline_has_created_and_evidence_entries():
    reset_store()
    anomaly = make_anomaly()
    event = make_event(1)
    incident = maybe_create_incident(event, anomaly, [event])
    assert incident is not None

    assert len(incident.timeline) == 2
    assert incident.timeline[0].event_type == IncidentTimelineEvent.created
    assert incident.timeline[1].event_type == IncidentTimelineEvent.evidence_added
    assert incident.timeline[1].metadata.get("recent_event_count") == 1
    assert incident.timeline[1].metadata.get("sample_count") == 20
    assert incident.timeline[1].metadata.get("error_rate") == 0.25
    assert incident.timeline[1].metadata.get("avg_latency_ms") == 900
    assert incident.timeline[1].metadata.get("p95_latency_ms") == 1400
