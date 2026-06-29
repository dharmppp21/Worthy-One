from fastapi import APIRouter, HTTPException, Depends

from app.auth import get_current_tenant
from app.ai_triage import ai_triage_incident
from app.schemas import AITriageResponse
from app.services.telemetry_service import get_incident_detail

router = APIRouter(tags=["ai-triage"])


@router.get("/incidents/{incident_id}/ai-triage", response_model=AITriageResponse)
def get_ai_triage(incident_id: str, tenant_id: str = Depends(get_current_tenant)) -> AITriageResponse:
    """Generate an AI triage analysis for an incident.

    The AI analyzes only the evidence provided in the incident timeline
    (anomaly stats, deployments, rolling window context) and produces a
    structured summary, likely causes, evidence points, and suggested actions.

    The LLM is NOT treated as the source of truth — it augments the
    rule-based root-cause engine with natural-language analysis.

    Falls back to a deterministic mock provider if OpenAI is not available.
    """
    try:
        incident = get_incident_detail(incident_id, tenant_id=tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Incident not found: {exc}")

    return ai_triage_incident(incident)
