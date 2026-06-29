"""Rule-based root-cause ranking engine.

Scores each service by combining evidence from:
- Anomaly severity (error rate, latency)
- Deployment recency (change correlation)
- Error log frequency (symptom density)
- Trace dependency impact (cascading failure)
- Runbook similarity (past operational knowledge)

Each score has a clear, explainable rule. No LLM required.
"""

from datetime import datetime, timezone, timedelta
from typing import Any

from app.schemas import RootCauseEvidence, RootCauseHypothesis, RootCauseResponse
from app.storage import store


MAX_SCORE = 100


def _score_deployment_recency(tenant_id: str, service_name: str) -> tuple[int, str, str | None]:
    """Score based on how recently a deployment occurred."""
    deployments = store.get_recent_deployments(tenant_id, service_name, window_minutes=60)
    if not deployments:
        return 0, "No recent deployments in the last 60 minutes.", None

    newest = deployments[0]
    age_minutes = (datetime.now(timezone.utc) - newest.timestamp).total_seconds() / 60
    version = newest.attributes.get("version", "unknown")

    if age_minutes <= 5:
        score = 25
        reason = f"Deployment v{version} happened {age_minutes:.0f} min ago — very recent change."
    elif age_minutes <= 15:
        score = 20
        reason = f"Deployment v{version} happened {age_minutes:.0f} min ago — recent change."
    elif age_minutes <= 30:
        score = 15
        reason = f"Deployment v{version} happened {age_minutes:.0f} min ago — moderate recency."
    elif age_minutes <= 60:
        score = 10
        reason = f"Deployment v{version} happened {age_minutes:.0f} min ago — within the hour."
    else:
        score = 0
        reason = f"Deployment v{version} happened {age_minutes:.0f} min ago — too old."

    detail = f"{len(deployments)} deployment(s) in the last 60 minutes."
    return score, reason, detail


def _score_anomaly_severity(incident: Any) -> tuple[int, str, str | None]:
    """Score based on anomaly stats from the incident timeline."""
    # Extract anomaly stats from timeline evidence
    stats = {}
    for entry in incident.timeline:
        if entry.event_type.value == "evidence_added":
            meta = entry.metadata or {}
            if "error_rate" in meta:
                stats = meta
                break

    if not stats:
        return 0, "No anomaly statistics available in incident timeline.", None

    error_rate = stats.get("error_rate", 0)
    p95 = stats.get("p95_latency_ms", 0)
    avg = stats.get("avg_latency_ms", 0)
    sample_count = stats.get("sample_count", 0)

    # Critical thresholds from anomaly.py
    if error_rate >= 0.5 or p95 >= 2500:
        score = 25
        reason = "Critical anomaly: error rate ≥ 50% or p95 latency ≥ 2500ms."
    elif error_rate >= 0.2 or p95 >= 1500 or avg >= 1800:
        score = 20
        reason = "Warning-level anomaly: error rate ≥ 20% or p95 ≥ 1500ms or avg ≥ 1800ms."
    elif error_rate >= 0.1:
        score = 15
        reason = "Elevated anomaly: error rate ≥ 10%."
    else:
        score = 10
        reason = "Anomaly detected but within mild thresholds."

    detail = (
        f"error_rate={error_rate:.1%}, p95={p95:.0f}ms, "
        f"avg={avg:.0f}ms, samples={sample_count}"
    )
    return score, reason, detail


def _score_error_log_frequency(tenant_id: str, service_name: str) -> tuple[int, str, str]:
    """Score based on number of error/critical logs in the last 30 minutes."""
    logs = store.get_recent_error_logs(tenant_id, service_name, window_minutes=30)
    count = len(logs)

    if count >= 50:
        score = 25
    elif count >= 20:
        score = 20
    elif count >= 10:
        score = 15
    elif count >= 5:
        score = 10
    elif count >= 1:
        score = 5
    else:
        score = 0

    reason = f"{count} error/critical log(s) in the last 30 minutes."
    return score, reason, f"Most recent: {logs[0].message[:120] if logs else 'N/A'}"


def _score_trace_dependency_impact(
    tenant_id: str, service_name: str
) -> tuple[int, str, str | None]:
    """Score based on downstream service failures and cascading impact."""
    callees = store.get_callees(service_name)
    if not callees:
        return 0, f"{service_name} has no downstream service dependencies.", None

    # Check if downstream services also have incidents
    downstream_incidents = store.get_downstream_incidents(
        tenant_id, callees, window_minutes=30
    )
    if downstream_incidents:
        affected = [i.service_name for i in downstream_incidents]
        score = 15
        reason = f"Downstream services also failing: {', '.join(set(affected))}."
        detail = f"{len(downstream_incidents)} downstream incident(s) in the last 30 minutes."
        return score, reason, detail

    # Check for trace failures from this service to its callees
    trace_failures = store.get_recent_trace_failures(
        tenant_id, service_name, window_minutes=30
    )
    if trace_failures:
        score = 10
        reason = f"Trace failures detected from {service_name} to callees."
        detail = f"{len(trace_failures)} failed trace(s) in the last 30 minutes."
        return score, reason, detail

    score = 5
    reason = f"Has downstream callees ({', '.join(callees)}) but no trace failures detected."
    return score, reason, None


def _score_runbook_similarity(service_name: str) -> tuple[int, str, str | None]:
    """Score based on existence of runbooks or similar incidents."""
    runbooks = store.list_runbooks(service_name=service_name)
    if runbooks:
        return 10, f"Runbook available: '{runbooks[0].title}'.", None

    # Check if similar incidents exist (same service, different time)
    similar = store.search_incidents(service_name)
    if len(similar) > 1:
        return 5, f"{len(similar)} similar incident(s) recorded for this service.", None

    return 0, "No runbook or similar incidents found.", None


def _confidence_level(total_score: int) -> str:
    if total_score >= 70:
        return "high"
    if total_score >= 40:
        return "medium"
    return "low"


def _recommended_action(total_score: int, deployment_score: int, has_runbook: bool) -> str:
    if total_score >= 70 and deployment_score >= 15:
        return "Rollback the recent deployment and monitor recovery."
    if total_score >= 70 and deployment_score < 15:
        return "Investigate infrastructure or upstream dependency issues."
    if has_runbook:
        return "Follow the available runbook steps and monitor metrics."
    if total_score >= 40:
        return "Check service logs and health endpoints; review recent config changes."
    return "Gather more telemetry; monitor for pattern emergence."


def rank_root_causes(service_name: str, tenant_id: str = "default") -> RootCauseResponse:
    """Generate evidence-backed root-cause hypotheses for a service.

    Scores the primary service and its downstream callees, then ranks
    all hypotheses by total score descending.
    """
    services_to_analyze = [service_name] + store.get_callees(service_name)
    hypotheses: list[RootCauseHypothesis] = []

    for svc in services_to_analyze:
        # Gather evidence for each scoring dimension
        dep_score, dep_reason, dep_detail = _score_deployment_recency(tenant_id, svc)
        log_score, log_reason, log_detail = _score_error_log_frequency(tenant_id, svc)
        trace_score, trace_reason, trace_detail = _score_trace_dependency_impact(tenant_id, svc)
        rb_score, rb_reason, rb_detail = _score_runbook_similarity(svc)

        # Anomaly severity: only meaningful for the primary service with an open incident
        anom_score = 0
        anom_reason = "No open incident for this service."
        anom_detail = None
        if svc == service_name:
            incidents = store.list_incidents()
            open_incidents = [i for i in incidents if i.service_name == svc and i.status.value != "resolved"]
            if open_incidents:
                anom_score, anom_reason, anom_detail = _score_anomaly_severity(open_incidents[0])

        total_score = dep_score + anom_score + log_score + trace_score + rb_score

        evidence = [
            RootCauseEvidence(type="deployment", score=dep_score, reason=dep_reason, details=dep_detail),
            RootCauseEvidence(type="anomaly", score=anom_score, reason=anom_reason, details=anom_detail),
            RootCauseEvidence(type="logs", score=log_score, reason=log_reason, details=log_detail),
            RootCauseEvidence(type="traces", score=trace_score, reason=trace_reason, details=trace_detail),
            RootCauseEvidence(type="runbook", score=rb_score, reason=rb_reason, details=rb_detail),
        ]

        # Sort evidence by score descending for display
        evidence.sort(key=lambda e: e.score, reverse=True)

        has_runbook = rb_score >= 10
        action = _recommended_action(total_score, dep_score, has_runbook)

        hypotheses.append(
            RootCauseHypothesis(
                rank=0,  # Will be set after sorting
                service_name=svc,
                total_score=total_score,
                confidence=_confidence_level(total_score),
                evidence=evidence,
                recommended_action=action,
            )
        )

    # Rank by total score descending
    hypotheses.sort(key=lambda h: h.total_score, reverse=True)
    for i, h in enumerate(hypotheses, start=1):
        h.rank = i

    return RootCauseResponse(
        service_name=service_name,
        hypotheses=hypotheses,
        generated_at=datetime.now(timezone.utc),
    )
