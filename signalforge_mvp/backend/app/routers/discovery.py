"""Discovery API endpoints for querying and triggering service discovery."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.discovery.engine import DiscoveryEngine
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.models import DiscoveredServiceDB

router = APIRouter(prefix="/services", tags=["discovery"])

# Module-level engine and registry (created once per app lifetime)
_discovery_engine: Optional[DiscoveryEngine] = None
_service_registry: Optional[ServiceRegistry] = None


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_registry() -> ServiceRegistry:
    global _service_registry
    if _service_registry is None:
        session = SessionLocal()
        _service_registry = ServiceRegistry(db_session=session)
    return _service_registry


def set_discovery_engine(engine: DiscoveryEngine) -> None:
    """Called from main.py during app startup to wire the discovery engine."""
    global _discovery_engine
    _discovery_engine = engine


def get_discovery_engine() -> DiscoveryEngine:
    if _discovery_engine is None:
        raise HTTPException(status_code=503, detail="Discovery engine not initialized")
    return _discovery_engine


@router.get("/discovered")
async def list_discovered_services(
    tenant_id: Optional[str] = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
) -> List[dict]:
    """Return all discovered services from the registry."""
    registry = ServiceRegistry(db_session=db)
    services = registry.list_services(tenant_id=tenant_id, active_only=active_only)
    return [svc.model_dump() for svc in services]


@router.post("/discover")
async def trigger_discovery(
    engine: DiscoveryEngine = Depends(get_discovery_engine),
) -> List[dict]:
    """Trigger an on-demand discovery run and return results."""
    discovered = await engine.run_discovery()
    return [svc.model_dump() for svc in discovered]
