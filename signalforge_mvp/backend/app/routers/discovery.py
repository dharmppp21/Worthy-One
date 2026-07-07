"""Discovery API endpoints for querying and triggering service discovery."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.discovery.dependencies.traffic_analyzer import TrafficAnalyzer
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.dependencies.trace_analyzer import TraceAnalyzer
from app.discovery.engine import DiscoveryEngine
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.discovery.probing import ServiceProber
from app.models import DiscoveredServiceDB, ServiceHealthDB

router = APIRouter(prefix="/services", tags=["discovery"])

# Module-level engine, registry, graph builder, and prober (created once per app lifetime)
_discovery_engine: Optional[DiscoveryEngine] = None
_service_registry: Optional[ServiceRegistry] = None
_graph_builder: Optional[DependencyGraphBuilder] = None
_prober: Optional[ServiceProber] = None

# Pydantic response models for health endpoints
class HealthRecordResponse(BaseModel):
    service_id: str
    service_name: str
    status: str
    last_probed_at: Optional[datetime] = None
    response_time_ms: Optional[float] = None
    uptime_percentage: Optional[float] = None

class HealthHistoryResponse(BaseModel):
    service_id: str
    service_name: str
    probes: List[dict]
    total: int
    limit: int
    offset: int


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


def set_prober(prober: ServiceProber) -> None:
    """Called from main.py during app startup to wire the health prober."""
    global _prober
    _prober = prober


def get_prober() -> Optional[ServiceProber]:
    return _prober


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


# ------------------------------------------------------------------
# Manual dependency injection
# ------------------------------------------------------------------

class DependencyDebugRequest(BaseModel):
    source_service_id: str = Field(..., description="Source service ID")
    target_service_id: str = Field(..., description="Target service ID")
    dependency_type: str = Field(default="network", description="Type of dependency")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence score")

class DependencyInjectResponse(BaseModel):
    success: bool = True
    message: str = "Dependency injected"

@router.post("/dependencies/inject")
async def inject_manual_dependency(
    request: DependencyDebugRequest,
    db: Session = Depends(get_db),
) -> DependencyInjectResponse:
    """Manually inject a dependency edge between two services.

    Useful for testing or when auto-discovery cannot detect a connection.
    """
    registry = ServiceRegistry(db_session=db)
    
    # Verify both services exist
    source = registry.get_service(request.source_service_id)
    target = registry.get_service(request.target_service_id)
    
    if not source:
        raise HTTPException(status_code=404, detail=f"Source service {request.source_service_id} not found")
    if not target:
        raise HTTPException(status_code=404, detail=f"Target service {request.target_service_id} not found")
    
    dep_registry = DependencyRegistry(db_session=db)
    dep = ServiceDependency(
        source_service_id=request.source_service_id,
        target_service_id=request.target_service_id,
        dependency_type=request.dependency_type,
        connection_count=1,
        avg_latency_ms=None,
        error_rate=None,
        last_seen_at=datetime.now(timezone.utc),
        confidence_score=request.confidence,
        discovery_sources=["manual"],
    )
    
    dep_registry.store_dependency(dep)
    
    return DependencyInjectResponse(
        success=True,
        message=f"Created dependency: {source.service_name} -> {target.service_name} ({request.dependency_type})"
    )


@router.get("/health")
async def list_services_health(
    db: Session = Depends(get_db),
) -> List[HealthRecordResponse]:
    """Return health records for all active services with latest probe data."""
    registry = ServiceRegistry(db_session=db)
    services = registry.list_services(active_only=True)

    # Get latest health record for each service
    results = []
    for s in services:
        health_rec = (
            db.query(ServiceHealthDB)
            .filter_by(service_id=s.service_id)
            .order_by(ServiceHealthDB.last_probed_at.desc())
            .first()
        )

        response_time_ms = None
        uptime_percentage = None
        last_probed_at = None

        if health_rec:
            last_probed_at = health_rec.last_probed_at
            uptime_percentage = getattr(health_rec, "uptime_percentage", None)
            probe_results = health_rec.probe_results or []
            if probe_results and isinstance(probe_results, list):
                latest = probe_results[-1]
                response_time_ms = latest.get("response_time_ms")

        results.append(
            HealthRecordResponse(
                service_id=s.service_id,
                service_name=s.service_name,
                status=s.health_status or "unknown",
                last_probed_at=last_probed_at,
                response_time_ms=response_time_ms,
                uptime_percentage=uptime_percentage,
            )
        )
    return results


@router.get("/{service_id}/health")
async def get_service_health_history(
    service_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HealthHistoryResponse:
    """Return detailed health probe history for a specific service."""
    registry = ServiceRegistry(db_session=db)
    service = registry.get_service(service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    # Query health history from DB
    health_records = (
        db.query(ServiceHealthDB)
        .filter_by(service_id=service_id)
        .order_by(ServiceHealthDB.last_probed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = (
        db.query(ServiceHealthDB)
        .filter_by(service_id=service_id)
        .count()
    )

    probes = []
    for rec in health_records:
        probe_list = rec.probe_results or []
        if probe_list:
            latest = probe_list[-1]
            probes.append({
                "status": rec.status,
                "probed_at": rec.last_probed_at.isoformat() if rec.last_probed_at else None,
                "response_time_ms": latest.get("response_time_ms"),
                "response_status_code": latest.get("response_status_code"),
                "error_message": latest.get("error_message"),
            })

    return HealthHistoryResponse(
        service_id=service_id,
        service_name=service.service_name,
        probes=probes,
        total=total,
        limit=limit,
        offset=offset,
    )
