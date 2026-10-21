"""Guarded rollback remediation — proposal + audited human decision.

SignalForge proposes a rollback and records the operator's decision; it never
executes an infrastructure change itself.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.anomaly import AnomalyResult, WindowStats
from app.incident_engine import maybe_create_incident
from app.remediation import propose_rollback
from app.schemas import EventType, IncidentStatus, RemediationDecision, TelemetryEvent
from app.services.telemetry_service import apply_remediation_decision
from app.storage import store

TENANT = "demo-company"
SERVICE = "payment-service"


def _metric(i: int) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"rem-metric-{i}",
        tenant_id=TENANT,
        service_name=SERVICE,
        event_type=EventType.metric,
        timestamp=datetime.now(timezone.utc),
        name="http_request",
        value=1,
        attributes={"status_code": 500, "latency_ms": 1500},
    )


def _deploy(i: int, version: str, minutes_ago: int) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=f"rem-deploy-{i}",
        tenant_id=TENANT,
        service_name=SERVICE,
        event_type=EventType.deployment,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        name="service_deployed",
        attributes={"version": version},
    )


def _anomaly() -> AnomalyResult:
    return AnomalyResult(
        is_anomaly=True, severity="warning", title="Service health anomaly detected",
        evidence=["Error count is 5/20 (25%)."],
        stats=WindowStats(sample_count=20, error_count=5, error_rate=0.25,
                          avg_latency_ms=900, p95_latency_ms=1400),
    )


def _open_incident():
    return maybe_create_incident(_metric(1), _anomaly(), [_metric(1)])


def test_proposal_recommends_rollback_to_prior_version():
    store.reset()
    incident = _open_incident()
    store.add_event(_deploy(1, "1", minutes_ago=10))  # prior known-good
    store.add_event(_deploy(2, "2", minutes_ago=2))   # newest -> suspected bad change

    proposal = propose_rollback(incident)
    assert proposal.action == "rollback"
    assert proposal.from_version == "2"
    assert proposal.to_version == "1"
    assert proposal.requires_approval is True


def test_proposal_without_deployment_falls_back_to_investigate():
    store.reset()
    incident = _open_incident()

    proposal = propose_rollback(incident)
    assert proposal.action == "investigate"
    assert proposal.requires_approval is False


def test_approve_mitigates_incident_and_audits_decision():
    store.reset()
    incident = _open_incident()
    store.add_event(_deploy(1, "1", minutes_ago=10))
    store.add_event(_deploy(2, "2", minutes_ago=2))

    updated = apply_remediation_decision(
        incident.id,
        RemediationDecision(approved=True, actor="oncall", note="verified in staging"),
        tenant_id=TENANT,
    )

    assert updated.status == IncidentStatus.mitigated
    entry = updated.timeline[-1]
    assert entry.event_type.value == "remediation"
    assert entry.metadata["approved"] is True
    assert entry.metadata["from_version"] == "2"
    assert entry.metadata["to_version"] == "1"
    assert entry.actor == "oncall"


def test_reject_records_decision_without_changing_status():
    store.reset()
    incident = _open_incident()
    store.add_event(_deploy(1, "2", minutes_ago=2))

    updated = apply_remediation_decision(
        incident.id,
        RemediationDecision(approved=False, actor="oncall"),
        tenant_id=TENANT,
    )

    assert updated.status == incident.status  # unchanged — rejection only audits
    assert updated.timeline[-1].metadata["approved"] is False


def test_decision_without_rollback_is_rejected():
    store.reset()
    incident = _open_incident()  # no deployment -> proposal is "investigate"

    with pytest.raises(HTTPException) as exc:
        apply_remediation_decision(
            incident.id, RemediationDecision(approved=True), tenant_id=TENANT
        )
    assert exc.value.status_code == 400
