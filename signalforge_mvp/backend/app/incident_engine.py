import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.anomaly import AnomalyResult
from app.schemas import (
    Incident,
    IncidentStatus,
    IncidentTimelineEntry,
    IncidentTimelineEvent,
    TelemetryEvent,
)
from app.storage import store


from app.embeddings import embedding_service
from app.routers.websocket import broadcast_incident_event


def maybe_create_incident(
    event: TelemetryEvent,
    anomaly: AnomalyResult,
    recent_events: list[TelemetryEvent] | None = None,
) -> Incident | None:
    if not anomaly.is_anomaly:
        return None

    now = datetime.now(timezone.utc)
    timeline = [
        IncidentTimelineEntry(
            timestamp=now,
            event_type=IncidentTimelineEvent.created,
            message=f"Incident opened for {event.service_name} after anomaly detection.",
            metadata={
                "trigger_event_id": event.event_id,
                "trigger_event_type": event.event_type.value,
                "trigger_event_name": event.name,
            },
        )
    ]

    if recent_events:
        stats_meta = {}
        if anomaly.stats:
            stats_meta = {
                "sample_count": anomaly.stats.sample_count,
                "error_count": anomaly.stats.error_count,
                "error_rate": anomaly.stats.error_rate,
                "avg_latency_ms": anomaly.stats.avg_latency_ms,
                "p95_latency_ms": anomaly.stats.p95_latency_ms,
            }
        timeline.append(
            IncidentTimelineEntry(
                timestamp=now,
                event_type=IncidentTimelineEvent.evidence_added,
                message=f"Attached rolling-window context from {len(recent_events)} recent events.",
                metadata={
                    "recent_event_count": len(recent_events),
                    "recent_event_ids": [recent_event.event_id for recent_event in recent_events[-5:]],
                    **stats_meta,
                },
            )
        )

    # Check for recent deployments — change-based root cause analysis
    recent_deployments = store.get_recent_deployments(
        event.tenant_id, event.service_name, window_minutes=30
    )
    if recent_deployments:
        deploy = recent_deployments[0]  # Most recent deployment
        version = deploy.attributes.get("version", "unknown")
        timeline.append(
            IncidentTimelineEntry(
                timestamp=now,
                event_type=IncidentTimelineEvent.evidence_added,
                message=f"Recent deployment detected: {event.service_name} v{version} at {deploy.timestamp.isoformat()}.",
                metadata={
                    "deployment_event_id": deploy.event_id,
                    "deployment_version": version,
                    "deployment_time": deploy.timestamp.isoformat(),
                    "deployments_in_window": len(recent_deployments),
                },
            )
        )

    # Boost severity for infrastructure services (database, message_queue)
    severity = anomaly.severity
    if event.service_name:
        # Check if this is an infrastructure service by looking up in storage
        infra_types = {"database", "message_queue", "cache"}
        # We don't have direct service_type lookup here, so we check if the
        # service name contains known infrastructure keywords as a heuristic
        # or if the anomaly title indicates infrastructure
        svc_lower = event.service_name.lower()
        if any(kw in svc_lower for kw in ("db", "database", "postgres", "mysql", "redis", "kafka", "mq", "queue", "cache")):
            severity = _boost_severity(severity)

    incident = Incident(
        id=str(uuid4()),
        tenant_id=event.tenant_id,
        service_name=event.service_name,
        title=f"{event.service_name}: {anomaly.title}",
        severity=severity,
        status=IncidentStatus.investigating,
        summary=f"SignalForge detected abnormal behavior in {event.service_name}.",
        evidence=anomaly.evidence,
        timeline=timeline,
        created_at=now,
        updated_at=now,
    )

    inserted = store.add_incident(incident)
    if inserted and embedding_service.is_available():
        text_to_embed = f"{incident.title}. {incident.summary}"
        embedding = embedding_service.embed(text_to_embed)
        if embedding:
            store.store_embedding("incident", incident.id, embedding)
    if inserted:
        try:
            import asyncio
            asyncio.create_task(broadcast_incident_event("incident_created", incident.model_dump(mode="json")))
        except RuntimeError:
            # No running event loop (e.g. in tests) — skip broadcast
            pass
    return incident if inserted else None


def _boost_severity(current: str) -> str:
    """Boost severity by one level for infrastructure services."""
    severity_order = {"info": "warning", "warning": "critical", "critical": "critical"}
    return severity_order.get(current, current)
