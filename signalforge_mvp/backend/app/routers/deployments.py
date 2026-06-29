from fastapi import APIRouter, HTTPException, Depends

from app.auth import get_current_tenant
from app.schemas import TelemetryEvent
from app.storage import store

router = APIRouter(tags=["deployments"])


@router.get("/deployments")
def list_deployments(tenant_id: str = Depends(get_current_tenant), limit: int = 50) -> dict:
    """Return recent deployment events."""
    events = store.list_events(tenant_id=tenant_id, limit=limit)
    deployments = [e for e in events if e.event_type.value == "deployment"]
    return {"deployments": [e.model_dump(mode="json") for e in deployments]}
