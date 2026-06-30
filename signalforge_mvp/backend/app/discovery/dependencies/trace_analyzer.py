"""Distributed tracing analyzer for inferring service dependencies from trace data."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.dependencies.base import BaseDependencyAnalyzer
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.registry import ServiceRegistry

logger = logging.getLogger(__name__)

# Trace backend types and their API endpoints
_JAEGER_TRACE_API = "/api/traces"
_ZIPKIN_TRACE_API = "/api/v2/traces"


def _normalize_service_name(name: str) -> str:
    """Normalize a service name from trace data (strip ports, lowercase)."""
    if not name:
        return "unknown"
    # Remove common suffixes like ":8080"
    if ":" in name:
        name = name.split(":")[0]
    return name.strip().lower()


class TraceAnalyzer(BaseDependencyAnalyzer):
    """Analyzes distributed tracing data to infer service dependencies.

    Supports Jaeger and Zipkin trace backends. Can also accept raw trace JSON
    for offline analysis or testing.
    """

    def __init__(
        self,
        registry: ServiceRegistry,
        backend_url: Optional[str] = None,
        backend_type: str = "jaeger",
        lookback_hours: int = 1,
        limit: int = 100,
    ) -> None:
        """
        Args:
            registry: ServiceRegistry for looking up known services.
            backend_url: URL of the trace backend (e.g., http://jaeger:16686).
            backend_type: Type of trace backend ("jaeger", "zipkin", "mock").
            lookback_hours: How many hours back to query for traces.
            limit: Maximum number of traces to fetch.
        """
        self._registry = registry
        self._backend_url = backend_url
        self._backend_type = backend_type.lower()
        self._lookback_hours = lookback_hours
        self._limit = limit

    async def analyze(self, raw_traces: Optional[List[Dict[str, Any]]] = None) -> List[ServiceDependency]:
        """Analyze trace data and return inferred service dependencies.

        Args:
            raw_traces: Optional pre-fetched trace data. If None and backend_url
                is set, queries the trace backend.

        Returns:
            List of ServiceDependency objects derived from parent-child span relationships.
        """
        traces = raw_traces or []
        if not traces and self._backend_url:
            traces = await self._fetch_traces()

        if not traces:
            return []

        # Extract (parent_service, child_service) relationships with metrics
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "latencies": [],
                "errors": 0,
                "last_seen": None,
            }
        )

        for trace in traces:
            spans = self._extract_spans(trace)
            if not spans:
                continue

            # Build span ID -> span lookup
            span_map: Dict[str, Dict[str, Any]] = {}
            for span in spans:
                span_id = self._get_span_id(span)
                if span_id:
                    span_map[span_id] = span

            for span in spans:
                parent_id = self._get_parent_id(span)
                if not parent_id or parent_id not in span_map:
                    continue

                parent_span = span_map[parent_id]
                parent_service = _normalize_service_name(self._get_service_name(parent_span))
                child_service = _normalize_service_name(self._get_service_name(span))

                if not parent_service or not child_service:
                    continue
                if parent_service == child_service:
                    continue

                key = (parent_service, child_service)
                grouped[key]["count"] += 1

                # Latency in milliseconds
                latency = self._get_span_duration_ms(span)
                if latency is not None:
                    grouped[key]["latencies"].append(latency)

                # Error detection
                if self._span_has_error(span):
                    grouped[key]["errors"] += 1

                # Timestamp
                ts = self._get_span_timestamp(span)
                if ts:
                    current_last = grouped[key]["last_seen"]
                    if current_last is None or ts > current_last:
                        grouped[key]["last_seen"] = ts

        # Build ServiceDependency objects
        dependencies: List[ServiceDependency] = []
        now = datetime.now(timezone.utc)

        for (parent_service, child_service), metrics in grouped.items():
            parent_svc = self._find_service_by_name(parent_service)
            child_svc = self._find_service_by_name(child_service)

            parent_id = parent_svc.service_id if parent_svc else f"trace-{parent_service}"
            child_id = child_svc.service_id if child_svc else f"trace-{child_service}"

            count = metrics["count"]
            latencies = metrics["latencies"]
            avg_latency = sum(latencies) / len(latencies) if latencies else None
            errors = metrics["errors"]
            error_rate = errors / count if count > 0 else None

            confidence = 0.85 if (parent_svc and child_svc) else 0.5
            last_seen = metrics["last_seen"] or now

            dependencies.append(
                ServiceDependency(
                    source_service_id=parent_id,
                    target_service_id=child_id,
                    dependency_type="rpc",
                    connection_count=count,
                    avg_latency_ms=avg_latency,
                    error_rate=error_rate,
                    last_seen_at=last_seen,
                    confidence_score=confidence,
                    discovery_sources=["distributed_tracing"],
                )
            )

        return dependencies

    def _extract_spans(self, trace: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract a flat list of spans from a trace object."""
        if self._backend_type == "jaeger":
            # Jaeger format: trace.data[0].spans
            data = trace.get("data") or []
            if data and isinstance(data, list):
                return data[0].get("spans", []) if isinstance(data[0], dict) else []
            # Also support direct span list
            return trace.get("spans", [])
        elif self._backend_type == "zipkin":
            # Zipkin format: list of spans
            if isinstance(trace, list):
                return trace
            return trace.get("trace", trace.get("spans", []))
        elif self._backend_type == "mock":
            # Generic mock format: just a list of spans
            if isinstance(trace, list):
                return trace
            return trace.get("spans", [])
        return []

    def _get_span_id(self, span: Dict[str, Any]) -> Optional[str]:
        """Extract span ID from a span object."""
        # Jaeger uses spanID, Zipkin uses id
        return span.get("spanID") or span.get("id") or span.get("span_id")

    def _get_parent_id(self, span: Dict[str, Any]) -> Optional[str]:
        """Extract parent span ID from a span object."""
        # Jaeger uses references array
        refs = span.get("references", [])
        if refs and isinstance(refs, list):
            for ref in refs:
                if ref.get("refType") == "CHILD_OF" or ref.get("ref_type") == "child_of":
                    return ref.get("spanID") or ref.get("span_id")
        # Zipkin uses parentId directly
        return span.get("parentId") or span.get("parent_id")

    def _get_service_name(self, span: Dict[str, Any]) -> Optional[str]:
        """Extract service name from a span object."""
        # Jaeger: process.serviceName
        process = span.get("process", {})
        if process:
            return process.get("serviceName") or process.get("service_name")
        # Zipkin: localEndpoint.serviceName
        local = span.get("localEndpoint", {})
        if local:
            return local.get("serviceName") or local.get("service_name")
        # Fallbacks
        tags = span.get("tags", {})
        if tags and isinstance(tags, dict):
            return tags.get("service.name") or tags.get("service_name")
        return span.get("service")

    def _get_span_duration_ms(self, span: Dict[str, Any]) -> Optional[float]:
        """Extract duration in milliseconds from a span."""
        duration = span.get("duration")
        if duration is None:
            return None
        try:
            dur = float(duration)
            # Zipkin uses microseconds; Jaeger uses microseconds
            if dur > 1000000:
                # Likely nanoseconds
                return dur / 1_000_000.0
            elif dur > 1000:
                # Likely microseconds
                return dur / 1000.0
            else:
                # Already milliseconds
                return dur
        except (ValueError, TypeError):
            return None

    def _span_has_error(self, span: Dict[str, Any]) -> bool:
        """Check if a span indicates an error."""
        tags = span.get("tags", {})
        if tags and isinstance(tags, dict):
            error_tag = tags.get("error") or tags.get("span.kind")
            if error_tag is True or error_tag == "error":
                return True
        # Jaeger uses span tag with key "error"
        for tag in span.get("tags", []):
            if isinstance(tag, dict):
                if tag.get("key") == "error" and tag.get("value") in (True, "true", 1):
                    return True
        return False

    def _get_span_timestamp(self, span: Dict[str, Any]) -> Optional[datetime]:
        """Extract timestamp from a span."""
        ts = span.get("startTime") or span.get("start_time") or span.get("timestamp")
        if ts is None:
            return None
        try:
            # Try microseconds first (common in trace data)
            ts_val = int(ts)
            if ts_val > 10**15:  # nanoseconds
                ts_val = ts_val / 1_000_000_000
            elif ts_val > 10**12:  # microseconds
                ts_val = ts_val / 1_000_000
            elif ts_val > 10**9:  # milliseconds
                ts_val = ts_val / 1000
            return datetime.fromtimestamp(ts_val, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

    def _find_service_by_name(self, name: str) -> Optional[Any]:
        """Look up a service in the registry by matching service_name."""
        for svc in self._registry.list_services(active_only=True):
            if svc.service_name.lower() == name.lower():
                return svc
        return None

    async def _fetch_traces(self) -> List[Dict[str, Any]]:
        """Fetch traces from the configured trace backend."""
        if not self._backend_url:
            return []

        if self._backend_type == "mock":
            return []

        try:
            import httpx
        except ImportError:
            logger.warning("httpx is not installed; cannot fetch traces from backend.")
            return []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if self._backend_type == "jaeger":
                    url = f"{self._backend_url}{_JAEGER_TRACE_API}"
                    params = {
                        "service": "all",
                        "lookback": f"{self._lookback_hours}h",
                        "limit": self._limit,
                    }
                    resp = await client.get(url, params=params)
                elif self._backend_type == "zipkin":
                    url = f"{self._backend_url}{_ZIPKIN_TRACE_API}"
                    params = {
                        "lookback": self._lookback_hours * 3600 * 1000,  # ms
                        "limit": self._limit,
                    }
                    resp = await client.get(url, params=params)
                else:
                    logger.warning("Unknown trace backend type: %s", self._backend_type)
                    return []

                resp.raise_for_status()
                data = resp.json()
                # Jaeger returns {"data": [...], "total": N}
                if self._backend_type == "jaeger" and isinstance(data, dict):
                    return data.get("data", [])
                # Zipkin returns list of traces directly
                return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("Failed to fetch traces from %s: %s", self._backend_url, exc)
            return []
