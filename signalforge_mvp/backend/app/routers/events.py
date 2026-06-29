from fastapi import APIRouter, Depends

from app.auth import get_current_tenant
from app.services.telemetry_service import list_recent_events

router = APIRouter(tags=["telemetry"])


@router.get("/events")
def list_events(tenant_id: str = Depends(get_current_tenant)) -> dict:
    return list_recent_events(tenant_id=tenant_id)

