from fastapi import APIRouter, Depends

from app.auth import get_current_tenant
from app.schemas import Incident, IncidentStatusUpdate
from app.services.telemetry_service import (
    get_incident_detail,
    list_current_incidents,
    update_incident_status,
)

router = APIRouter(tags=["incidents"])


@router.get("/incidents")
def list_incidents(tenant_id: str = Depends(get_current_tenant)) -> dict:
    return list_current_incidents(tenant_id=tenant_id)


@router.get("/incidents/{incident_id}", response_model=Incident)
def get_incident(incident_id: str, tenant_id: str = Depends(get_current_tenant)) -> Incident:
    return get_incident_detail(incident_id, tenant_id=tenant_id)


@router.patch("/incidents/{incident_id}/status", response_model=Incident)
def patch_incident_status(incident_id: str, update: IncidentStatusUpdate, tenant_id: str = Depends(get_current_tenant)) -> Incident:
    return update_incident_status(incident_id, update, tenant_id=tenant_id)
