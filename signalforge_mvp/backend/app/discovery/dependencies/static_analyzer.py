"""Static heuristic analyzer that infers dependencies from service co-location and type patterns."""

from __future__ import annotations

import logging
from typing import List, Optional

from app.discovery.dependencies.base import BaseDependencyAnalyzer
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.registry import ServiceRegistry

logger = logging.getLogger(__name__)

# Common dependency patterns: service_type -> [dependency_type]
_TYPE_DEPENDENCY_PATTERNS = {
    "api": ["database", "cache", "message_queue"],
    "web": ["api", "database", "cache"],
    "backend": ["database", "cache", "message_queue"],
    "frontend": ["api", "web"],
}


class StaticHeuristicAnalyzer(BaseDependencyAnalyzer):
    """Infers dependencies based on service co-location and common type patterns.

    This analyzer does not require admin privileges or external backends.
    It creates edges between services on the same host based on:
    - Known service type patterns (e.g., API -> Database)
    - Same-host co-location (services on the same machine likely talk to each other)
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry

    async def analyze(self) -> List[ServiceDependency]:
        """Create heuristic edges between co-located services."""
        from datetime import datetime, timezone

        services = self._registry.list_services(active_only=True)
        if len(services) < 2:
            return []

        dependencies: List[ServiceDependency] = []

        # Group services by host
        by_host: dict[str, list] = {}
        for svc in services:
            host = svc.host or "127.0.0.1"
            by_host.setdefault(host, []).append(svc)

        for host, host_services in by_host.items():
            if len(host_services) < 2:
                continue

            # Find databases, caches, message queues on this host
            infra_services = [s for s in host_services if s.service_type in ("database", "cache", "message_queue")]
            app_services = [s for s in host_services if s.service_type in ("api", "web", "backend", "frontend")]

            # Create edges from app services to infra services
            for app in app_services:
                for infra in infra_services:
                    if app.service_id == infra.service_id:
                        continue

                    dep_type = _TYPE_DEPENDENCY_PATTERNS.get(app.service_type, [])
                    if infra.service_type in dep_type:
                        dependencies.append(
                            ServiceDependency(
                                source_service_id=app.service_id,
                                target_service_id=infra.service_id,
                                dependency_type=infra.service_type,
                                connection_count=1,
                                avg_latency_ms=None,
                                error_rate=None,
                                last_seen_at=datetime.now(timezone.utc),
                                confidence_score=0.5,
                                discovery_sources=["heuristic"],
                            )
                        )

            # Also create edges between any app services on the same host
            for i, app_a in enumerate(app_services):
                for app_b in app_services[i + 1 :]:
                    if app_a.service_id == app_b.service_id:
                        continue

                    # Determine direction: web -> api, frontend -> backend
                    if app_a.service_type == "web" and app_b.service_type == "api":
                        src, tgt = app_a, app_b
                    elif app_a.service_type == "api" and app_b.service_type == "web":
                        src, tgt = app_b, app_a
                    elif app_a.service_type == "frontend" and app_b.service_type in ("api", "backend"):
                        src, tgt = app_a, app_b
                    elif app_b.service_type == "frontend" and app_a.service_type in ("api", "backend"):
                        src, tgt = app_b, app_a
                    else:
                        continue

                    dependencies.append(
                        ServiceDependency(
                            source_service_id=src.service_id,
                            target_service_id=tgt.service_id,
                            dependency_type="http",
                            connection_count=1,
                            avg_latency_ms=None,
                            error_rate=None,
                            last_seen_at=datetime.now(timezone.utc),
                            confidence_score=0.4,
                            discovery_sources=["heuristic"],
                        )
                    )

        logger.info(
            "StaticHeuristicAnalyzer created %d heuristic edges for %d services",
            len(dependencies),
            len(services),
        )
        return dependencies
