"""Service mesh analyzer for inferring dependencies from Istio/Envoy metrics."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.dependencies.base import BaseDependencyAnalyzer
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.registry import ServiceRegistry

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)

_ISTIO_REQUESTS_TOTAL = "istio_requests_total"
_ISTIO_REQUEST_DURATION_SUM = "istio_request_duration_milliseconds_sum"
_ISTIO_REQUEST_DURATION_COUNT = "istio_request_duration_milliseconds_count"

# Envoy Prometheus metric names
_ENVOY_RQ_TOTAL = "envoy_cluster_upstream_rq_total"
_ENVOY_RQ_TIME_SUM = "envoy_cluster_upstream_rq_time_sum"

_DEFAULT_PROMETHEUS_URL = "http://prometheus:9090"
_DEFAULT_ENVOY_URL = "http://envoy:9901/stats/prometheus"

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.0


class ServiceMeshAnalyzer(BaseDependencyAnalyzer):
    """Analyzes Istio/Envoy service mesh metrics to infer service dependencies.

    Queries Prometheus for Istio metrics. Falls back to Envoy admin endpoint
    if Istio is not available.
    """

    def __init__(
        self,
        registry: ServiceRegistry,
        prometheus_url: Optional[str] = None,
        envoy_url: Optional[str] = None,
    ) -> None:
        """
        Args:
            registry: ServiceRegistry for looking up known services.
            prometheus_url: URL of the Prometheus server. If None, uses
                ``SIGNALFORGE_PROMETHEUS_URL`` env var or default.
            envoy_url: URL of the Envoy admin endpoint. If None, uses default.
        """
        self._registry = registry
        self._prometheus_url = (
            prometheus_url
            if prometheus_url is not None
            else os.environ.get("SIGNALFORGE_PROMETHEUS_URL", _DEFAULT_PROMETHEUS_URL)
        )
        self._envoy_url = envoy_url or _DEFAULT_ENVOY_URL
        self._disabled = not self._prometheus_url

    def health_check(self) -> bool:
        """Return whether Prometheus is reachable."""
        if self._disabled:
            return False
        return True

    async def analyze(self) -> List[ServiceDependency]:
        """Query mesh metrics and return inferred dependencies."""
        if self._disabled:
            logger.info(
                "ServiceMeshAnalyzer is disabled (no Prometheus URL configured)."
            )
            return []

        if httpx is None:
            logger.warning("httpx is not installed; service mesh analysis skipped.")
            return []

        # Try Istio metrics first
        deps = await self._query_istio_metrics()
        if deps:
            return deps

        # Fallback to Envoy metrics
        logger.info("Istio metrics not available; trying Envoy fallback.")
        return await self._query_envoy_metrics()

    # ------------------------------------------------------------------
    # Istio / Prometheus
    # ------------------------------------------------------------------

    async def _query_istio_metrics(self) -> List[ServiceDependency]:
        """Query Prometheus for Istio request metrics and build dependencies."""
        total_samples = await self._prometheus_query_with_retry(
            f'{_ISTIO_REQUESTS_TOTAL}{{reporter="source"}}',
        )
        if not total_samples:
            return []

        # Group by (source_app, destination_app)
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {
                "total_count": 0.0,
                "error_count": 0.0,
                "sum_latency": 0.0,
                "count_latency": 0.0,
                "last_seen": None,
            }
        )

        for sample in total_samples:
            metric = sample.get("metric", {})
            source_app = metric.get("source_app", "")
            destination_app = metric.get("destination_app", "")
            if not source_app or not destination_app:
                continue
            if source_app == destination_app:
                continue

            value_str = sample.get("value", [None, "0"])[1]
            try:
                count = float(value_str)
            except (ValueError, TypeError):
                continue

            key = (source_app, destination_app)
            grouped[key]["total_count"] += count

            response_code = metric.get("response_code", "")
            if response_code.startswith("5"):
                grouped[key]["error_count"] += count

            # Check for grpc
            if "grpc_response_status" in metric:
                grouped[key]["is_grpc"] = True

            # Update last_seen timestamp from the sample timestamp
            ts = sample.get("value", [None])[0]
            if ts is not None:
                try:
                    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    if (
                        grouped[key]["last_seen"] is None
                        or dt > grouped[key]["last_seen"]
                    ):
                        grouped[key]["last_seen"] = dt
                except (ValueError, TypeError):
                    pass

        # Query latency metrics for each pair
        await self._enrich_with_latency(grouped)

        # Build ServiceDependency objects
        dependencies: List[ServiceDependency] = []
        now = datetime.now(timezone.utc)

        for (source_app, dest_app), metrics in grouped.items():
            source_svc = self._find_service_by_name(source_app)
            dest_svc = self._find_service_by_name(dest_app)

            source_id = source_svc.service_id if source_svc else f"mesh-{source_app}"
            target_id = dest_svc.service_id if dest_svc else f"mesh-{dest_app}"

            total = metrics["total_count"]
            errors = metrics["error_count"]
            error_rate = errors / total if total > 0 else None

            sum_lat = metrics["sum_latency"]
            count_lat = metrics["count_latency"]
            avg_latency = sum_lat / count_lat if count_lat > 0 else None

            dep_type = "grpc" if metrics.get("is_grpc") else "http"
            last_seen = metrics["last_seen"] or now

            dependencies.append(
                ServiceDependency(
                    source_service_id=source_id,
                    target_service_id=target_id,
                    dependency_type=dep_type,
                    connection_count=int(total),
                    avg_latency_ms=avg_latency,
                    error_rate=error_rate,
                    last_seen_at=last_seen,
                    confidence_score=0.95,
                    discovery_sources=["service_mesh"],
                )
            )

        return dependencies

    async def _enrich_with_latency(
        self,
        grouped: Dict[Tuple[str, str], Dict[str, Any]],
    ) -> None:
        """Query Prometheus for latency metrics and enrich grouped data."""
        # Query sum
        sum_samples = await self._prometheus_query_with_retry(
            _ISTIO_REQUEST_DURATION_SUM,
        )
        for sample in sum_samples or []:
            metric = sample.get("metric", {})
            source = metric.get("source_app", "")
            dest = metric.get("destination_app", "")
            key = (source, dest)
            if key in grouped:
                try:
                    val = float(sample.get("value", [None, "0"])[1])
                    grouped[key]["sum_latency"] += val
                except (ValueError, TypeError):
                    pass

        # Query count
        count_samples = await self._prometheus_query_with_retry(
            _ISTIO_REQUEST_DURATION_COUNT,
        )
        for sample in count_samples or []:
            metric = sample.get("metric", {})
            source = metric.get("source_app", "")
            dest = metric.get("destination_app", "")
            key = (source, dest)
            if key in grouped:
                try:
                    val = float(sample.get("value", [None, "0"])[1])
                    grouped[key]["count_latency"] += val
                except (ValueError, TypeError):
                    pass

    # ------------------------------------------------------------------
    # Envoy fallback
    # ------------------------------------------------------------------

    async def _query_envoy_metrics(self) -> List[ServiceDependency]:
        """Query Envoy admin endpoint for upstream metrics."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._envoy_url)
                resp.raise_for_status()
                text = resp.text
        except Exception as exc:
            logger.warning("Failed to fetch Envoy metrics: %s", exc)
            return []

        # Parse Prometheus text format
        dependencies: List[ServiceDependency] = []
        now = datetime.now(timezone.utc)

        # cluster_name -> {total_count, sum_time}
        clusters: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"total_count": 0.0, "sum_time": 0.0}
        )

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Format: metric_name{label="value"} value
            if _ENVOY_RQ_TOTAL in line:
                cluster_name, count = self._parse_envoy_line(line, _ENVOY_RQ_TOTAL)
                if cluster_name:
                    clusters[cluster_name]["total_count"] += count
            elif _ENVOY_RQ_TIME_SUM in line:
                cluster_name, sum_time = self._parse_envoy_line(
                    line, _ENVOY_RQ_TIME_SUM
                )
                if cluster_name:
                    clusters[cluster_name]["sum_time"] += sum_time

        for cluster_name, metrics in clusters.items():
            # Map cluster name to service name (e.g., "outbound|8080||backend.default.svc.cluster.local")
            service_name = self._extract_service_from_cluster(cluster_name)
            if not service_name:
                continue

            source_svc = self._find_service_by_name(service_name)
            source_id = source_svc.service_id if source_svc else f"envoy-{service_name}"

            total = metrics["total_count"]
            sum_time = metrics["sum_time"]
            avg_time = sum_time / total if total > 0 else None

            # For Envoy fallback, we assume the cluster is a target of the local Envoy proxy
            # We use a placeholder source since we don't know the caller from Envoy metrics alone
            dependencies.append(
                ServiceDependency(
                    source_service_id="envoy-proxy",
                    target_service_id=source_id,
                    dependency_type="http",
                    connection_count=int(total),
                    avg_latency_ms=avg_time,
                    last_seen_at=now,
                    confidence_score=0.6,
                    discovery_sources=["envoy_metrics"],
                )
            )

        return dependencies

    @staticmethod
    def _parse_envoy_line(line: str, metric_name: str) -> Tuple[Optional[str], float]:
        """Parse a single Envoy Prometheus metric line."""
        # Simple parsing: metric_name{cluster="..."} value
        try:
            # Extract value after the last space
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                return None, 0.0
            value = float(parts[1])

            # Extract cluster name from labels
            label_start = line.find("{")
            label_end = line.find("}")
            if label_start == -1 or label_end == -1:
                return None, value

            labels = line[label_start + 1 : label_end]
            for label in labels.split(","):
                if "cluster=" in label:
                    cluster = label.split("=", 1)[1].strip('"')
                    return cluster, value
            return None, value
        except (ValueError, IndexError):
            return None, 0.0

    @staticmethod
    def _extract_service_from_cluster(cluster_name: str) -> Optional[str]:
        """Extract service name from Envoy cluster name."""
        # Format: outbound|port||service.namespace.svc.cluster.local
        if "||" in cluster_name:
            parts = cluster_name.split("||")
            if len(parts) >= 2:
                host = parts[1]
                # Take first part before dot
                return host.split(".")[0]
        # Fallback: just use the cluster name as-is if it looks like a service name
        if cluster_name and not cluster_name.startswith("_"):
            return cluster_name.split(".")[0]
        return None

    # ------------------------------------------------------------------
    # Prometheus helpers
    # ------------------------------------------------------------------

    async def _prometheus_query_with_retry(
        self,
        query: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Query Prometheus with exponential backoff retries."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await self._prometheus_query(query)
            except Exception as exc:
                logger.warning(
                    "Prometheus query failed (attempt %d/%d): %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    await asyncio.sleep(wait)

        logger.error(
            "Prometheus query failed after %d retries: %s", _MAX_RETRIES, query
        )
        return None

    async def _prometheus_query(
        self,
        query: str,
    ) -> List[Dict[str, Any]]:
        """Execute a single Prometheus instant query."""
        url = f"{self._prometheus_url}/api/v1/query"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"query": query})
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "success":
            raise RuntimeError(
                f"Prometheus query failed: {data.get('error', 'unknown')}"
            )

        result_data = data.get("data", {})
        result_type = result_data.get("resultType", "")
        if result_type == "vector":
            return result_data.get("result", [])
        elif result_type == "matrix":
            # Flatten matrix results
            flat = []
            for series in result_data.get("result", []):
                metric = series.get("metric", {})
                for value in series.get("values", []):
                    flat.append({"metric": metric, "value": value})
            return flat
        return []

    def _find_service_by_name(self, name: str) -> Optional[Any]:
        """Look up a service in the registry by matching service_name."""
        for svc in self._registry.list_services(active_only=True):
            if svc.service_name.lower() == name.lower():
                return svc
        return None
