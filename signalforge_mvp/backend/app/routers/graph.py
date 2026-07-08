from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_tenant
from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.discovery.models import DiscoveredService
from app.routers.discovery import get_graph_builder
from app.schemas import ServiceGraphResponse, ServiceGraphNode, ServiceGraphEdge
from app.storage import store

router = APIRouter(tags=["graph"])


class AutoDependencyEdge(BaseModel):
    """A dependency edge with the full detail the discovery UI renders."""

    source: str
    target: str
    dependency_type: str
    confidence: float
    connection_count: int
    avg_latency_ms: Optional[float] = None
    error_rate: Optional[float] = None
    sources: List[str] = Field(default_factory=list)
    first_detected_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None


class AutoDependencyGraphResponse(BaseModel):
    """Rich auto-discovered dependency graph (nodes + detailed edges)."""

    nodes: List[DiscoveredService] = Field(default_factory=list)
    edges: List[AutoDependencyEdge] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


@router.get("/graph", response_model=ServiceGraphResponse)
def get_service_graph(tenant_id: str = Depends(get_current_tenant)) -> ServiceGraphResponse:
    """Return the service dependency graph built from trace events."""
    return store.get_service_graph(tenant_id=tenant_id)


@router.get("/graph/auto", response_model=ServiceGraphResponse)
async def get_auto_discovered_graph(
    min_confidence: float = 0.0,
    dependency_type: Optional[str] = None,
    tenant_id: str = Depends(get_current_tenant),
    builder: DependencyGraphBuilder = Depends(get_graph_builder),
) -> ServiceGraphResponse:
    """Return the auto-discovered dependency graph from all analyzers.

    Query parameters:
        min_confidence: Minimum confidence score for edges (default 0.0).
        dependency_type: Filter by dependency type (e.g., "http", "database").
    """
    dep_types = [dependency_type] if dependency_type else None
    graph = builder.get_graph(
        tenant_id=tenant_id,
        min_confidence=min_confidence,
        dependency_types=dep_types,
    )

    nodes = [
        ServiceGraphNode(id=node.service_id, label=node.service_name)
        for node in graph.nodes
    ]
    edges = [
        ServiceGraphEdge(
            source=edge.source_service_id,
            target=edge.target_service_id,
            label=edge.dependency_type,
            count=edge.connection_count,
        )
        for edge in graph.edges
    ]

    return ServiceGraphResponse(nodes=nodes, edges=edges)


@router.get("/graph/dependencies", response_model=AutoDependencyGraphResponse)
async def get_auto_dependency_graph(
    min_confidence: float = 0.0,
    dependency_type: Optional[str] = None,
    tenant_id: str = Depends(get_current_tenant),
    builder: DependencyGraphBuilder = Depends(get_graph_builder),
) -> AutoDependencyGraphResponse:
    """Return the auto-discovered dependency graph with full edge detail.

    Unlike /graph/auto (which returns the reduced node/label/count shape for the
    SVG service graph), this endpoint keeps confidence, connection counts,
    latency, and discovery sources so the topology map and service-detail panel
    can display them. Only edges between two known nodes are returned, so stale
    or inferred targets that no longer resolve to a service are dropped.
    """
    dep_types = [dependency_type] if dependency_type else None
    graph = builder.get_graph(
        tenant_id=tenant_id,
        min_confidence=min_confidence,
        dependency_types=dep_types,
    )

    node_ids = {node.service_id for node in graph.nodes}
    edges = [
        AutoDependencyEdge(
            source=edge.source_service_id,
            target=edge.target_service_id,
            dependency_type=edge.dependency_type,
            confidence=edge.confidence_score,
            connection_count=edge.connection_count,
            avg_latency_ms=edge.avg_latency_ms,
            error_rate=edge.error_rate,
            sources=edge.discovery_sources,
            first_detected_at=edge.last_seen_at,
            last_updated_at=edge.last_seen_at,
        )
        for edge in graph.edges
        if edge.source_service_id in node_ids and edge.target_service_id in node_ids
    ]

    return AutoDependencyGraphResponse(
        nodes=graph.nodes, edges=edges, generated_at=graph.generated_at
    )
