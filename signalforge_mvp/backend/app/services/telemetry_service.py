import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException

from app.services.event_processor import event_processor


from app.anomaly import analyze_service_window
from app.incident_engine import maybe_create_incident
from app.remediation import propose_rollback
from app.routers.websocket import broadcast_incident_event
from app.schemas import (
    IncidentStatus,
    IncidentStatusUpdate,
    IncidentTimelineEntry,
    IncidentTimelineEvent,
    IngestResponse,
    RemediationDecision,
    RemediationProposal,
    TelemetryEvent,
)
from app.storage import store


def ingest_telemetry_event(event: TelemetryEvent) -> IngestResponse:
    """Sync fallback: run the full pipeline inline.

    Called by the API when the stream is unavailable, or by the worker
    consumer. Delegates to EventProcessor, which owns the pipeline.
    """
    result = event_processor.process(event)
    return IngestResponse(
        accepted=result["accepted"],
        event_id=result["event_id"],
        duplicate=result["duplicate"],
        mode="sync",
    )


def list_recent_events(tenant_id: str, limit: int = 50) -> dict:
    events = store.list_events(tenant_id=tenant_id, limit=limit)
    return {
        "count": len(events),
        "events": events,
        "server_time": datetime.now(timezone.utc),
    }


def list_uncorrelated_events(tenant_id: str, limit: int = 50, offset: int = 0) -> dict:
    events = store.list_uncorrelated_events(tenant_id=tenant_id, limit=limit, offset=offset)
    return {
        "count": len(events),
        "events": events,
        "limit": limit,
        "offset": offset,
        "server_time": datetime.now(timezone.utc),
    }


def list_current_incidents(tenant_id: str) -> dict:
    incidents = store.list_incidents(tenant_id=tenant_id)
    return {"count": len(incidents), "incidents": incidents}


def get_incident_detail(incident_id: str, tenant_id: str):
    incident = store.get_incident(incident_id, tenant_id=tenant_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


def update_incident_status(incident_id: str, update: IncidentStatusUpdate, tenant_id: str):
    incident = store.get_incident(incident_id, tenant_id=tenant_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.status == update.status:
        return incident

    now = datetime.now(timezone.utc)
    message = f"Status changed from {incident.status.value} to {update.status.value}."
    if update.note:
        message = f"{message} Note: {update.note}"

    timeline_entry = IncidentTimelineEntry(
        timestamp=now,
        event_type=IncidentTimelineEvent.status_changed,
        message=message,
        actor=update.actor,
        metadata={
            "from_status": incident.status.value,
            "to_status": update.status.value,
        },
    )

    updated = store.update_incident_status(incident_id, update.status, timeline_entry)
    if updated is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        asyncio.create_task(broadcast_incident_event("incident_updated", updated.model_dump(mode="json")))
    except RuntimeError:
        pass
    return updated


def get_remediation_proposal(incident_id: str, tenant_id: str) -> RemediationProposal:
    incident = get_incident_detail(incident_id, tenant_id=tenant_id)
    return propose_rollback(incident)


def apply_remediation_decision(incident_id: str, decision: RemediationDecision, tenant_id: str):
    """Record an operator's approve/reject of the rollback proposal.

    This never performs the rollback — it audits the human decision. Approving
    marks the incident mitigated; rejecting leaves the status unchanged.
    """
    incident = get_incident_detail(incident_id, tenant_id=tenant_id)
    proposal = propose_rollback(incident)
    if proposal.action != "rollback":
        raise HTTPException(
            status_code=400, detail="No rollback remediation is available for this incident."
        )

    now = datetime.now(timezone.utc)
    verb = "approved" if decision.approved else "rejected"
    message = (
        f"Rollback {verb} by {decision.actor}: {incident.service_name} "
        f"v{proposal.from_version} -> v{proposal.to_version or 'previous'}."
    )
    if decision.note:
        message = f"{message} Note: {decision.note}"

    timeline_entry = IncidentTimelineEntry(
        timestamp=now,
        event_type=IncidentTimelineEvent.remediation,
        message=message,
        actor=decision.actor,
        metadata={
            "approved": decision.approved,
            "action": "rollback",
            "from_version": proposal.from_version,
            "to_version": proposal.to_version,
        },
    )

    # Approving a rollback mitigates the incident; rejecting keeps the status.
    new_status = IncidentStatus.mitigated if decision.approved else incident.status
    updated = store.update_incident_status(incident_id, new_status, timeline_entry)
    if updated is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        asyncio.create_task(broadcast_incident_event("incident_updated", updated.model_dump(mode="json")))
    except RuntimeError:
        pass
    return updated
