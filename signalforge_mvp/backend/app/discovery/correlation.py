"""Event-to-service correlation engine.

Automatically matches telemetry events to discovered services without requiring
the client to specify ``service_name``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.schemas import TelemetryEvent

logger = logging.getLogger(__name__)


class CorrelationResult:
    """Result of an event-to-service correlation attempt."""

    def __init__(
        self,
        service_id: Optional[str] = None,
        service_name: Optional[str] = None,
        tenant_id: Optional[str] = None,
        confidence: float = 0.0,
        strategy: str = "none",
        matched_field: Optional[str] = None,
        candidate_count: int = 0,
    ) -> None:
        self.service_id = service_id
        self.service_name = service_name
        self.tenant_id = tenant_id
        self.confidence = confidence
        self.strategy = strategy
        self.matched_field = matched_field
        self.candidate_count = candidate_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "confidence": self.confidence,
            "matched_field": self.matched_field,
            "candidate_count": self.candidate_count,
        }


class EventServiceCorrelator:
    """Correlates telemetry events to discovered services using multiple strategies."""

    def __init__(self, registry: ServiceRegistry) -> None:
        """
        Args:
            registry: ServiceRegistry for looking up known services.
        """
        self._registry = registry

    def correlate(self, event: TelemetryEvent) -> CorrelationResult:
        """Attempt to correlate an event to a discovered service.

        Strategies are tried in order of priority. The first successful match
        is returned.

        Returns:
            CorrelationResult with service_id, confidence, and strategy used.
        """
        attrs = event.attributes or {}

        # Strategy 1: Exact service name match
        if event.service_name:
            result = self._match_exact_name(event.service_name)
            if result:
                return result

        # Strategy 2: Source IP + port match
        result = self._match_source_ip_port(attrs)
        if result:
            return result

        # Strategy 3: Hostname match
        result = self._match_hostname(attrs)
        if result:
            return result

        # Strategy 4: Container ID match
        result = self._match_container_id(attrs)
        if result:
            return result

        # Strategy 5: Pod name match
        result = self._match_pod_name(attrs)
        if result:
            return result

        # Strategy 6: Process ID match
        result = self._match_process_id(attrs)
        if result:
            return result

        # Strategy 7: Trace context match
        result = self._match_trace_context(attrs)
        if result:
            return result

        # Strategy 8: Fallback — no match
        return CorrelationResult(
            confidence=0.0,
            strategy="none",
            candidate_count=0,
        )

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _match_exact_name(self, service_name: str) -> Optional[CorrelationResult]:
        """Strategy 1: Exact service name match (case-insensitive)."""
        for svc in self._registry.list_services(active_only=True):
            if svc.service_name.lower() == service_name.lower():
                return CorrelationResult(
                    service_id=svc.service_id,
                    service_name=svc.service_name,
                    tenant_id=svc.metadata.get("tenant_id"),
                    confidence=1.0,
                    strategy="exact_name",
                    matched_field="service_name",
                    candidate_count=1,
                )
        return None

    def _match_source_ip_port(self, attrs: Dict[str, Any]) -> Optional[CorrelationResult]:
        """Strategy 2: Match by source IP and port in service endpoints."""
        source_ip = attrs.get("source_ip")
        source_port = attrs.get("source_port")
        if not source_ip or not source_port:
            return None

        try:
            port = int(source_port)
        except (ValueError, TypeError):
            return None

        candidates: List[DiscoveredService] = []
        for svc in self._registry.list_services(active_only=True):
            for ep in svc.endpoints:
                if f"tcp://{source_ip}:{port}" in ep or f"http://{source_ip}:{port}" in ep:
                    candidates.append(svc)
                    break

        if not candidates:
            return None

        if len(candidates) == 1:
            svc = candidates[0]
            return CorrelationResult(
                service_id=svc.service_id,
                service_name=svc.service_name,
                tenant_id=svc.metadata.get("tenant_id"),
                confidence=0.95,
                strategy="source_ip_port",
                matched_field=f"{source_ip}:{port}",
                candidate_count=1,
            )

        # Disambiguate
        winner = self._disambiguate(candidates, attrs)
        if winner:
            return CorrelationResult(
                service_id=winner.service_id,
                service_name=winner.service_name,
                tenant_id=winner.metadata.get("tenant_id"),
                confidence=0.8,
                strategy="source_ip_port",
                matched_field=f"{source_ip}:{port}",
                candidate_count=len(candidates),
            )
        return None

    def _match_hostname(self, attrs: Dict[str, Any]) -> Optional[CorrelationResult]:
        """Strategy 3: Match by hostname or host attribute."""
        hostname = attrs.get("hostname") or attrs.get("host")
        if not hostname:
            return None

        candidates: List[DiscoveredService] = []
        for svc in self._registry.list_services(active_only=True):
            if svc.host.lower() == hostname.lower():
                candidates.append(svc)
            elif svc.service_name.lower() == hostname.lower():
                candidates.append(svc)

        if not candidates:
            return None

        if len(candidates) == 1:
            svc = candidates[0]
            return CorrelationResult(
                service_id=svc.service_id,
                service_name=svc.service_name,
                tenant_id=svc.metadata.get("tenant_id"),
                confidence=0.9,
                strategy="hostname",
                matched_field=hostname,
                candidate_count=1,
            )

        winner = self._disambiguate(candidates, attrs)
        if winner:
            return CorrelationResult(
                service_id=winner.service_id,
                service_name=winner.service_name,
                tenant_id=winner.metadata.get("tenant_id"),
                confidence=0.9,
                strategy="hostname",
                matched_field=hostname,
                candidate_count=len(candidates),
            )
        return None

    def _match_container_id(self, attrs: Dict[str, Any]) -> Optional[CorrelationResult]:
        """Strategy 4: Match by container ID in service metadata."""
        container_id = attrs.get("container_id")
        if not container_id:
            return None

        # Allow partial match (first 12 chars)
        container_prefix = container_id[:12] if len(container_id) >= 12 else container_id

        for svc in self._registry.list_services(active_only=True):
            svc_container_id = svc.metadata.get("container_id")
            if svc_container_id:
                svc_prefix = svc_container_id[:12] if len(svc_container_id) >= 12 else svc_container_id
                if svc_prefix.lower() == container_prefix.lower():
                    return CorrelationResult(
                        service_id=svc.service_id,
                        service_name=svc.service_name,
                        tenant_id=svc.metadata.get("tenant_id"),
                        confidence=0.95,
                        strategy="container_id",
                        matched_field=container_id,
                        candidate_count=1,
                    )
        return None

    def _match_pod_name(self, attrs: Dict[str, Any]) -> Optional[CorrelationResult]:
        """Strategy 5: Match by pod name in service metadata."""
        pod_name = attrs.get("pod_name")
        if not pod_name:
            return None

        for svc in self._registry.list_services(active_only=True):
            svc_pod_name = svc.metadata.get("pod_name")
            if svc_pod_name and svc_pod_name.lower() == pod_name.lower():
                return CorrelationResult(
                    service_id=svc.service_id,
                    service_name=svc.service_name,
                    tenant_id=svc.metadata.get("tenant_id"),
                    confidence=0.95,
                    strategy="pod_name",
                    matched_field=pod_name,
                    candidate_count=1,
                )
        return None

    def _match_process_id(self, attrs: Dict[str, Any]) -> Optional[CorrelationResult]:
        """Strategy 6: Match by process ID in service metadata."""
        process_id = attrs.get("process_id")
        if process_id is None:
            return None

        try:
            pid = int(process_id)
        except (ValueError, TypeError):
            return None

        for svc in self._registry.list_services(active_only=True):
            if svc.metadata.get("pid") == pid:
                return CorrelationResult(
                    service_id=svc.service_id,
                    service_name=svc.service_name,
                    tenant_id=svc.metadata.get("tenant_id"),
                    confidence=0.9,
                    strategy="process_id",
                    matched_field=str(pid),
                    candidate_count=1,
                )
        return None

    def _match_trace_context(self, attrs: Dict[str, Any]) -> Optional[CorrelationResult]:
        """Strategy 7: Match by trace context (parent span service name)."""
        # This would require a trace backend query; for now, we check if the
        # event attributes already contain a parent span's service name.
        parent_service = attrs.get("parent_span_service")
        if not parent_service:
            return None

        for svc in self._registry.list_services(active_only=True):
            if svc.service_name.lower() == parent_service.lower():
                return CorrelationResult(
                    service_id=svc.service_id,
                    service_name=svc.service_name,
                    tenant_id=svc.metadata.get("tenant_id"),
                    confidence=0.85,
                    strategy="trace_context",
                    matched_field=parent_service,
                    candidate_count=1,
                )
        return None

    # ------------------------------------------------------------------
    # Disambiguation helper
    # ------------------------------------------------------------------

    def _disambiguate(
        self, candidates: List[DiscoveredService], event_attrs: Dict[str, Any]
    ) -> Optional[DiscoveredService]:
        """Disambiguate multiple candidate services.

        Prefers services with the most recent heartbeat, then services whose
        type matches the event type.
        """
        if not candidates:
            return None

        # Sort by most recent heartbeat, descending
        sorted_candidates = sorted(
            candidates,
            key=lambda s: s.last_heartbeat_at,
            reverse=True,
        )

        event_type = event_attrs.get("event_type")
        if event_type:
            # Try to find a candidate whose service_type matches the event type
            for svc in sorted_candidates:
                if svc.service_type == event_type:
                    return svc

        return sorted_candidates[0]
