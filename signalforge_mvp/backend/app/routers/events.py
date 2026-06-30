from fastapi import APIRouter, Depends
from typing import Optional

from app.auth import get_current_tenant
from app.services.telemetry_service import list_recent_events, list_uncorrelated_events

router = APIRouter(tags=["telemetry"])


@router.get("/events")
def list_events(tenant_id: str = Depends(get_current_tenant)) -> dict:
    return list_recent_events(tenant_id=tenant_id)


@router.get("/events/uncorrelated")
def list_uncorrelated(
    limit: int = 50,
    offset: int = 0,
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    """Return events that could not be correlated to any known service.

    Query parameters:
        limit: Maximum number of events to return (default 50).
        offset: Number of events to skip (default 0).
    """
    return list_uncorrelated_events(tenant_id=tenant_id, limit=limit, offset=offset)

