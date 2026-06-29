from fastapi import APIRouter, HTTPException, Depends

from app.auth import get_current_tenant
from app.root_cause_engine import rank_root_causes
from app.schemas import RootCauseResponse

router = APIRouter(tags=["root-cause"])


@router.get("/services/{service_name}/root-cause", response_model=RootCauseResponse)
def get_root_cause(service_name: str, tenant_id: str = Depends(get_current_tenant)) -> RootCauseResponse:
    """Generate evidence-backed root-cause hypotheses for a service.

    Combines anomaly stats, deployment recency, error logs, trace failures,
    and runbook knowledge into a ranked list of explainable hypotheses.
    No LLM required — pure rule-based scoring.
    """
    return rank_root_causes(service_name, tenant_id=tenant_id)
