"""
Discovery engine: orchestrates multiple discovery providers and runs them periodically.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

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

        # Update registry
        for service in discovered:
            self._registry.register_service(service)

        return discovered

    async def _safe_discover(self, provider: ServiceDiscoveryProvider) -> List[DiscoveredService]:
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
            logger.warning("Background discovery already running; ignoring start request.")
            return

        self._stop_event = asyncio.Event()
        self._background_task = asyncio.create_task(
            self._discovery_loop(interval_seconds)
        )
        logger.info("Background discovery started (interval=%ds).", interval_seconds)

    def stop_background_discovery(self) -> None:
        """Signal the background discovery loop to stop."""
        if self._background_task is None:
            logger.warning("Background discovery is not running; ignoring stop request.")
            return

        if self._stop_event is not None:
            self._stop_event.set()
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
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval_seconds,
                )
            except asyncio.TimeoutError:
                pass  # Normal interval timeout; continue loop
