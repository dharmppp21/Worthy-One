"""Root-cause ranking — the history dimension (learning from past incidents)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.anomaly import AnomalyResult, WindowStats
from app.incident_engine import maybe_create_incident
from app.root_cause_engine import rank_root_causes
from app.schemas import EventType, IncidentStatus, IncidentStatusUpdate, TelemetryEvent
from app.services.telemetry_service import update_incident_status
from app.storage import store


def _event(i: int) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"rc-event-{i}",
        tenant_id="demo-company",
        service_name="payment-service",
        event_type=EventType.metric,
        timestamp=datetime.now(timezone.utc),
        name="http_request",
        value=1,
        attributes={"status_code": 500, "latency_ms": 1500},
    )


def _anomaly() -> AnomalyResult:
    return AnomalyResult(
        is_anomaly=True,
        severity="warning",
        title="Service health anomaly detected",
        evidence=["Error count is 5/20 (25%)."],
        stats=WindowStats(
            sample_count=20, error_count=5, error_rate=0.25,
            avg_latency_ms=900, p95_latency_ms=1400,
        ),
    )


def test_history_dimension_uses_past_resolution():
    store.reset()
    anomaly = _anomaly()

    # A past incident on this service, resolved with an operator note.
    first = maybe_create_incident(_event(1), anomaly, [_event(1)])
    update_incident_status(
        first.id,
        IncidentStatusUpdate(status=IncidentStatus.resolved, actor="oncall", note="rolled back to v1"),
        tenant_id="demo-company",
    )
    # A fresh open incident for the same service (bypass the anti-flap cooldown).
    with patch("app.storage.INCIDENT_REOPEN_COOLDOWN", timedelta(0)):
        second = maybe_create_incident(_event(2), anomaly, [_event(2)])
    assert second is not None

    result = rank_root_causes("payment-service", tenant_id="demo-company")
    top = result.hypotheses[0]
    assert top.service_name == "payment-service"

    history = next(e for e in top.evidence if e.type == "history")
    assert history.score >= 7
    assert "resolved" in history.reason.lower()
    # The recommendation learns from the past resolution.
    assert "rolled back to v1" in top.recommended_action


def test_history_dimension_empty_without_past_incident():
    store.reset()
    maybe_create_incident(_event(1), _anomaly(), [_event(1)])  # open, never resolved

    result = rank_root_causes("payment-service", tenant_id="demo-company")
    history = next(e for e in result.hypotheses[0].evidence if e.type == "history")
    assert history.score == 0
    assert "no prior" in history.reason.lower()
