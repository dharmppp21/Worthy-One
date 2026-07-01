"""Dependency graph builder that merges results from multiple analyzers."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.discovery.dependencies.base import BaseDependencyAnalyzer
from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.registry import ServiceRegistry

logger = logging.getLogger(__name__)


class DependencyGraphBuilder:
    """Runs multiple dependency analyzers, merges their results, and builds
    a unified dependency graph.

    The builder runs all analyzers in parallel, merges discovered dependencies
    by (source_id, target_id), and stores the result in a DependencyRegistry.
    """

    def __init__(
        self,
        analyzers: List[BaseDependencyAnalyzer],
        registry: ServiceRegistry,
        dep_registry: DependencyRegistry,
    ) -> None:
        """
        Args:
            analyzers: List of BaseDependencyAnalyzer instances to run.
            registry: ServiceRegistry for looking up service nodes.
            dep_registry: DependencyRegistry for persisting merged edges.
        """
        self._analyzers = analyzers
        self._registry = registry
        self._dep_registry = dep_registry
        self._background_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._publisher: Optional[Any] = None
        self._lock = asyncio.Lock()

    def set_publisher(self, publisher: Any) -> None:
        """Set the discovery event publisher for broadcasting dependency events."""
        self._publisher = publisher

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(self) -> DependencyGraph:
        """Run all analyzers, merge results, store in registry, and return graph.

        Uses an asyncio.Lock to prevent concurrent builds from racing.

        Returns:
            DependencyGraph built from merged analyzer results.
        """
        async with self._lock:
            if not self._analyzers:
                logger.warning("No analyzers configured; returning empty graph.")
                return DependencyGraph()

            # Run all analyzers concurrently
            results = await asyncio.gather(
                *[self._safe_analyze(a) for a in self._analyzers],
                return_exceptions=True,
            )

            # Flatten and collect all dependencies
            all_deps: List[ServiceDependency] = []
            for result in results:
                if isinstance(result, Exception):
                    continue
                all_deps.extend(result)

            # Merge by (source_id, target_id)
            merged = self._merge_dependencies(all_deps)

            # Store merged dependencies incrementally and publish new ones
            for dep in merged:
                is_new = self._dep_registry.store_dependency(dep)
                if is_new and self._publisher is not None:
                    await self._publisher.publish_dependency_detected(dep)

            # Build graph with known service nodes
            services = self._registry.list_services(active_only=True)
            return self._dep_registry.get_dependency_graph(services)

    def get_graph(
        self,
        tenant_id: Optional[str] = None,
        min_confidence: float = 0.0,
        dependency_types: Optional[List[str]] = None,
    ) -> DependencyGraph:
        """Return the current dependency graph with optional filtering.

        Args:
            tenant_id: Optional tenant filter (not yet implemented on DB level).
            min_confidence: Minimum confidence score for edges.
            dependency_types: Optional list of dependency types to include.

        Returns:
            Filtered DependencyGraph.
        """
        services = self._registry.list_services(active_only=True)
        edges = self._dep_registry.get_dependencies(min_confidence=min_confidence)

        if dependency_types:
            edges = [e for e in edges if e.dependency_type in dependency_types]

        return DependencyGraph(nodes=services, edges=edges)

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    def start_background_build(self, interval_seconds: int = 60) -> None:
        """Start an asyncio background task that rebuilds the graph periodically."""
        if self._background_task is not None:
            logger.warning("Background graph builder already running.")
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop; skipping background graph builder startup."
            )
            return

        self._stop_event = asyncio.Event()
        self._background_task = asyncio.create_task(self._build_loop(interval_seconds))
        logger.info(
            "Background graph builder started (interval=%ds).", interval_seconds
        )

    def stop_background_build(self) -> None:
        """Signal and cancel the background graph builder loop."""
        if self._background_task is None:
            logger.warning("Background graph builder is not running.")
            return

        if self._stop_event is not None:
            self._stop_event.set()
        self._background_task.cancel()
        self._background_task = None
        logger.info("Background graph builder stopped.")

    async def _build_loop(self, interval_seconds: int) -> None:
        """Internal loop that sleeps and rebuilds the graph periodically."""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self.build()
            except Exception as exc:
                logger.error("Graph builder loop error: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    def _merge_dependencies(
        self,
        deps: List[ServiceDependency],
    ) -> List[ServiceDependency]:
        """Merge dependencies by (source_id, target_id) with weighted averages."""
        grouped: Dict[Tuple[str, str], List[ServiceDependency]] = defaultdict(list)
        for dep in deps:
            key = (dep.source_service_id, dep.target_service_id)
            grouped[key].append(dep)

        merged: List[ServiceDependency] = []
        for key, dep_list in grouped.items():
            merged.append(self._merge_single_dependency(key, dep_list))
        return merged

    def _merge_single_dependency(
        self,
        key: Tuple[str, str],
        dep_list: List[ServiceDependency],
    ) -> ServiceDependency:
        """Merge a list of dependencies for the same (source, target) pair."""
        source_id, target_id = key

        # Collect weights and metrics
        total_weight = 0.0
        weighted_confidence = 0.0
        weighted_latency = 0.0
        latency_weight = 0.0
        weighted_error = 0.0
        error_weight = 0.0
        total_connections = 0
        last_seen = datetime.min.replace(tzinfo=timezone.utc)
        all_sources: Set[str] = set()
        all_types: Set[str] = set()

        for dep in dep_list:
            weight = max(dep.connection_count, 1)
            total_weight += weight

            weighted_confidence += dep.confidence_score * weight
            total_connections += dep.connection_count
            all_sources.update(dep.discovery_sources)
            all_types.add(dep.dependency_type)

            if dep.avg_latency_ms is not None:
                weighted_latency += dep.avg_latency_ms * weight
                latency_weight += weight

            if dep.error_rate is not None:
                weighted_error += dep.error_rate * weight
                error_weight += weight

            if dep.last_seen_at > last_seen:
                last_seen = dep.last_seen_at

        # Base confidence (weighted average)
        base_confidence = (
            weighted_confidence / total_weight if total_weight > 0 else 0.5
        )

        # Multi-analyzer confidence boost
        num_analyzers = len(dep_list)
        if num_analyzers >= 3:
            confidence = min(base_confidence + 0.2, 1.0)
        elif num_analyzers >= 2:
            confidence = min(base_confidence + 0.1, 1.0)
        else:
            confidence = base_confidence

        # Determine primary dependency type (prefer most common, or mesh > tracing > traffic > network)
        type_priority = {
            "service_mesh": 4,
            "distributed_tracing": 3,
            "traffic_logs": 2,
            "network": 1,
        }
        best_type = max(all_types, key=lambda t: type_priority.get(t, 0))

        return ServiceDependency(
            source_service_id=source_id,
            target_service_id=target_id,
            dependency_type=best_type,
            connection_count=total_connections,
            avg_latency_ms=(
                (weighted_latency / latency_weight) if latency_weight > 0 else None
            ),
            error_rate=(weighted_error / error_weight) if error_weight > 0 else None,
            last_seen_at=(
                last_seen
                if last_seen != datetime.min.replace(tzinfo=timezone.utc)
                else datetime.now(timezone.utc)
            ),
            confidence_score=confidence,
            discovery_sources=sorted(all_sources),
        )

    # ------------------------------------------------------------------
    # Safe wrapper
    # ------------------------------------------------------------------

    async def _safe_analyze(
        self, analyzer: BaseDependencyAnalyzer
    ) -> List[ServiceDependency]:
        """Wrap an analyzer's analyze() in try/except so one failing analyzer
        does not break the whole build.
        """
        try:
            if not analyzer.health_check():
                logger.debug(
                    "Analyzer %s is unhealthy; skipping.", analyzer.__class__.__name__
                )
                return []
            return await analyzer.analyze()
        except Exception as exc:
            logger.error(
                "Analyzer %s failed: %s",
                analyzer.__class__.__name__,
                exc,
                exc_info=True,
            )
            return []
