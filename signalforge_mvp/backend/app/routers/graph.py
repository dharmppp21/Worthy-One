from fastapi import APIRouter, Depends

from app.auth import get_current_tenant
from app.schemas import ServiceGraphResponse
from app.storage import store

router = APIRouter(tags=["graph"])


@router.get("/graph", response_model=ServiceGraphResponse)
def get_service_graph(tenant_id: str = Depends(get_current_tenant)) -> ServiceGraphResponse:
    """Return the service dependency graph built from trace events."""
    return store.get_service_graph(tenant_id=tenant_id)
