"""
Discovery engine: orchestrates multiple discovery providers and runs them periodically.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from .base import ServiceDiscoveryProvider
from .models import DiscoveredService
from .registry import ServiceRegistry

logger = logging.getLogger(__name__)


class DiscoveryEngine:
    """
    Orchestrates a set of discovery providers and runs them either
    on-demand or in a background asyncio task.
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        """
        Args:
            registry: ServiceRegistry instance for persisting discovered services.
        """
        self._registry = registry
        self._providers: List[ServiceDiscoveryProvider] = []
        self._background_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._publisher: Optional[Any] = None

    def set_publisher(self, publisher: Any) -> None:
        """Set the discovery event publisher for broadcasting events."""
        self._publisher = publisher

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def register_provider(self, provider: ServiceDiscoveryProvider) -> None:
        """Add a discovery provider to the engine."""
        self._providers.append(provider)

    # ------------------------------------------------------------------
    # Discovery execution
    # ------------------------------------------------------------------

    async def run_discovery(self) -> List[DiscoveredService]:
        """
        Run all registered providers concurrently, deduplicate results by
        (service_name, host), update the registry, and return the list of
        discovered services.

        Returns:
            A list of unique DiscoveredService objects found in this run.
        """
        if not self._providers:
            logger.warning("No discovery providers registered; skipping run.")
            return []

        # Run all providers concurrently via asyncio.gather
        results = await asyncio.gather(
            *[self._safe_discover(p) for p in self._providers],
            return_exceptions=True,
        )

        # Flatten and deduplicate
        seen: set = set()
        discovered: List[DiscoveredService] = []
        for provider_result in results:
            if isinstance(provider_result, Exception):
                # Already logged in _safe_discover; skip
                continue
            for service in provider_result:
                key = (service.service_name, service.host)
                if key not in seen:
                    seen.add(key)
                    discovered.append(service)

        # Update registry and publish events
        for service in discovered:
            service_id, is_new = self._registry.register_service(service)
            if is_new and self._publisher is not None:
                await self._publisher.publish_service_discovered(service)
            # Track health changes
            if self._publisher is not None:
                status = (
                    service.health_status
                    if hasattr(service, "health_status") and service.health_status
                    else "unknown"
                )
                if self._publisher.track_health(service_id, status):
                    # Health changed — publish event (but only if we had a prior value)
                    old_status = self._publisher.get_cached_health(service_id)
                    if old_status is not None:
                        await self._publisher.publish_health_changed(
                            service_id, service.service_name, old_status, status
                        )

        return discovered

    async def remove_stale(self, timeout_seconds: int = 120) -> None:
        """Remove stale services and publish events."""
        removed = self._registry.remove_stale_services(timeout_seconds)
        if self._publisher is not None:
            for service_id, service_name in removed:
                await self._publisher.publish_service_removed(service_id, service_name)

    async def _safe_discover(
        self, provider: ServiceDiscoveryProvider
    ) -> List[DiscoveredService]:
        """
        Wrap a provider's discover() in a try/except so that one failing
        provider does not break the whole run.
        """
        try:
            return await provider.discover()
        except Exception as exc:
            logger.error(
                "Provider %s failed during discovery: %s",
                provider.__class__.__name__,
                exc,
                exc_info=True,
            )
            return []

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    def start_background_discovery(self, interval_seconds: int = 30) -> None:
        """
        Start an asyncio background task that runs ``run_discovery`` every
        ``interval_seconds``.

        Args:
            interval_seconds: Sleep interval between discovery runs.
        """
        if self._background_task is not None:
            logger.warning(
                "Background discovery already running; ignoring start request."
            )
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No running event loop; skipping background discovery startup."
            )
            return

        self._stop_event = asyncio.Event()
        self._background_task = asyncio.create_task(
            self._discovery_loop(interval_seconds)
        )
        logger.info("Background discovery started (interval=%ds).", interval_seconds)

    def stop_background_discovery(self) -> None:
        """Signal and cancel the background discovery loop."""
        if self._background_task is None:
            logger.warning(
                "Background discovery is not running; ignoring stop request."
            )
            return

        if self._stop_event is not None:
            self._stop_event.set()
        self._background_task.cancel()
        self._background_task = None
        logger.info("Background discovery stopped.")

    async def _discovery_loop(self, interval_seconds: int) -> None:
        """Internal loop that sleeps and runs discovery periodically."""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self.run_discovery()
            except Exception as exc:
                logger.error("Discovery loop error: %s", exc, exc_info=True)

            try:
                await self.remove_stale(timeout_seconds=interval_seconds * 3)
            except Exception as exc:
                logger.error("Stale removal error: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval_seconds,
                )
            except asyncio.TimeoutError:
                pass  # Normal interval timeout; continue loop
