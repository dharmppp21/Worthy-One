import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException

from app.services.event_processor import event_processor


from app.anomaly import analyze_service_window
from app.incident_engine import maybe_create_incident
from app.routers.websocket import broadcast_incident_event
from app.schemas import (
    IncidentStatusUpdate,
    IncidentTimelineEntry,
    IncidentTimelineEvent,
    IngestResponse,
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
