"""Service dependency detection and graph models."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.discovery.models import DiscoveredService


class ServiceDependency(BaseModel):
    """Represents a directed dependency between two discovered services."""

    model_config = ConfigDict(populate_by_name=True)

    source_service_id: str
    target_service_id: str
    dependency_type: str = Field(default="unknown")
    connection_count: int = Field(default=1, ge=1)
    avg_latency_ms: Optional[float] = None
    error_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    discovery_sources: List[str] = Field(default_factory=list)

    @field_validator("confidence_score")
    @classmethod
    def _check_confidence(cls, v: float) -> float:
        """Ensure confidence score is between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence_score must be between 0.0 and 1.0")
        return v


class DependencyGraph(BaseModel):
    """Graph of discovered services and their dependencies."""

    model_config = ConfigDict(populate_by_name=True)

    nodes: List[DiscoveredService] = Field(default_factory=list)
    edges: List[ServiceDependency] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_upstream(self, service_id: str) -> List[ServiceDependency]:
        """Return edges where the given service is the target (dependencies on it)."""
        return [e for e in self.edges if e.target_service_id == service_id]

    def get_downstream(self, service_id: str) -> List[ServiceDependency]:
        """Return edges where the given service is the source (its dependencies)."""
        return [e for e in self.edges if e.source_service_id == service_id]

    def get_critical_path(
        self, source_id: str, target_id: str
    ) -> List[ServiceDependency]:
        """Return the shortest dependency path from source_id to target_id using BFS."""
        if source_id == target_id:
            return []

        # Build adjacency list
        adj: Dict[str, List[tuple]] = {}
        for edge in self.edges:
            adj.setdefault(edge.source_service_id, []).append(
                (edge.target_service_id, edge)
            )

        # BFS
        visited: set = {source_id}
        queue: deque = deque([(source_id, [])])

        while queue:
            current, path = queue.popleft()
            for next_svc, edge in adj.get(current, []):
                if next_svc in visited:
                    continue
                new_path = path + [edge]
                if next_svc == target_id:
                    return new_path
                visited.add(next_svc)
                queue.append((next_svc, new_path))

        return []
