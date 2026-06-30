from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from app.auth import get_current_tenant
from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
from app.routers.discovery import get_graph_builder
from app.schemas import ServiceGraphResponse, ServiceGraphNode, ServiceGraphEdge
from app.storage import store

router = APIRouter(tags=["graph"])


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
