"""Discovery API endpoints for querying and triggering service discovery."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.discovery.dependencies.traffic_analyzer import TrafficAnalyzer
from app.discovery.dependencies.trace_analyzer import TraceAnalyzer
from app.discovery.engine import DiscoveryEngine
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.models import DiscoveredServiceDB

router = APIRouter(prefix="/services", tags=["discovery"])

# Module-level engine and registry (created once per app lifetime)
_discovery_engine: Optional[DiscoveryEngine] = None
_service_registry: Optional[ServiceRegistry] = None
_graph_builder: Optional[DependencyGraphBuilder] = None


# ------------------------------------------------------------------
# Pydantic models for debug endpoints
# ------------------------------------------------------------------

class TrafficDebugRequest(BaseModel):
    log_lines: List[str] = Field(default_factory=list, description="HTTP log lines to analyze")
    log_format: str = Field(default="auto", description="Log format: auto, nginx_combined, envoy, json")


class TraceDebugRequest(BaseModel):
    raw_traces: List[Dict[str, Any]] = Field(default_factory=list, description="Raw trace JSON objects")
    backend_type: str = Field(default="mock", description="Trace backend type: jaeger, zipkin, mock")


class DependencyDebugResponse(BaseModel):
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    source: str = ""


class ServiceDependenciesResponse(BaseModel):
    upstream: List[Dict[str, Any]] = Field(default_factory=list)
    downstream: List[Dict[str, Any]] = Field(default_factory=list)
    self_service: Optional[Dict[str, Any]] = Field(default=None, alias="self")


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


def set_graph_builder(builder: DependencyGraphBuilder) -> None:
    """Called from main.py during app startup to wire the graph builder."""
    global _graph_builder
    _graph_builder = builder


def get_graph_builder() -> DependencyGraphBuilder:
    if _graph_builder is None:
        raise HTTPException(status_code=503, detail="Graph builder not initialized")
    return _graph_builder


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


# ------------------------------------------------------------------
# Service dependencies
# ------------------------------------------------------------------

@router.get("/{service_id}/dependencies")
async def get_service_dependencies(
    service_id: str,
    builder: DependencyGraphBuilder = Depends(get_graph_builder),
) -> ServiceDependenciesResponse:
    """Return upstream and downstream dependencies for a given service."""
    graph = builder.get_graph()

    upstream = graph.get_upstream(service_id)
    downstream = graph.get_downstream(service_id)

    self_node = None
    for node in graph.nodes:
        if node.service_id == service_id:
            self_node = node.model_dump()
            break

    return ServiceDependenciesResponse(
        upstream=[dep.model_dump() for dep in upstream],
        downstream=[dep.model_dump() for dep in downstream],
        self_service=self_node,
    )


# ------------------------------------------------------------------
# Debug endpoints for dependency analyzers
# ------------------------------------------------------------------

@router.post("/dependencies/traffic")
async def debug_traffic_analyzer(
    request: TrafficDebugRequest,
    db: Session = Depends(get_db),
) -> DependencyDebugResponse:
    """Debug endpoint: analyze HTTP traffic logs and return inferred dependencies.

    Accepts raw log lines and runs the TrafficAnalyzer against them.
    """
    registry = ServiceRegistry(db_session=db)
    analyzer = TrafficAnalyzer(
        registry=registry,
        log_format=request.log_format,
    )
    deps = await analyzer.analyze(log_lines=request.log_lines)
    return DependencyDebugResponse(
        dependencies=[dep.model_dump() for dep in deps],
        count=len(deps),
        source="traffic_logs",
    )


@router.post("/dependencies/traces")
async def debug_trace_analyzer(
    request: TraceDebugRequest,
    db: Session = Depends(get_db),
) -> DependencyDebugResponse:
    """Debug endpoint: analyze distributed trace data and return inferred dependencies.

    Accepts raw trace JSON objects and runs the TraceAnalyzer against them.
    """
    registry = ServiceRegistry(db_session=db)
    analyzer = TraceAnalyzer(
        registry=registry,
        backend_type=request.backend_type,
    )
    deps = await analyzer.analyze(raw_traces=request.raw_traces)
    return DependencyDebugResponse(
        dependencies=[dep.model_dump() for dep in deps],
        count=len(deps),
        source="distributed_tracing",
    )
