from fastapi import APIRouter, Depends

from app.auth import get_current_tenant
from app.schemas import Incident, IncidentStatusUpdate, RemediationDecision, RemediationProposal
from app.services.telemetry_service import (
    apply_remediation_decision,
    get_incident_detail,
    get_remediation_proposal,
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


@router.get("/incidents/{incident_id}/remediation", response_model=RemediationProposal)
def get_incident_remediation(incident_id: str, tenant_id: str = Depends(get_current_tenant)) -> RemediationProposal:
    return get_remediation_proposal(incident_id, tenant_id=tenant_id)


@router.post("/incidents/{incident_id}/remediation/decision", response_model=Incident)
def decide_incident_remediation(incident_id: str, decision: RemediationDecision, tenant_id: str = Depends(get_current_tenant)) -> Incident:
    return apply_remediation_decision(incident_id, decision, tenant_id=tenant_id)
