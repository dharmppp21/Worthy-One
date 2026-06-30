"""Traffic log analyzer for inferring service dependencies from HTTP logs."""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.dependencies.models import ServiceDependency
from app.discovery.registry import ServiceRegistry

logger = logging.getLogger(__name__)

# Common log format patterns
_LOG_PATTERNS = {
    "nginx_combined": re.compile(
        r'^(?P<remote_addr>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
        r'(?P<status>\d{3})\s+(?P<bytes>\d+|-)\s+'
        r'"(?P<referer>[^"]*)"\s+"(?P<user_agent>[^"]*)"\s+'
        r'"(?P<host>[^"]*)"(?:\s+(?P<req_time>\S+))?'
    ),
    "envoy": re.compile(
        r'^(?P<remote_addr>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
        r'(?P<status>\d{3})\s+(?P<bytes>\d+|-)\s+'
        r'(?P<resp_flags>\S+)\s+(?P<resp_time>\S+)\s+'
        r'"(?P<referer>[^"]*)"\s+"(?P<user_agent>[^"]*)"\s+'
        r'"(?P<host>[^"]*)"\s+"(?P<upstream>[^"]*)"'
    ),
}

# Service name extraction patterns from URL paths
_SERVICE_PATH_PATTERNS = [
    re.compile(r'^/api/v\d+/(?P<service>[^/]+)'),
    re.compile(r'^/services/(?P<service>[^/]+)'),
    re.compile(r'^/(?P<service>[^/]+)/api'),
]


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse a common log timestamp string."""
    formats = [
        "%d/%b/%Y:%H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def _extract_service_from_host(host: str) -> Optional[str]:
    """Extract service name from a host header like 'service.namespace.svc.cluster.local'."""
    if not host:
        return None
    # Kubernetes-style service naming
    parts = host.split('.')
    if parts:
        return parts[0]
    return None


def _extract_service_from_path(path: str) -> Optional[str]:
    """Extract target service name from a URL path."""
    if not path:
        return None
    for pattern in _SERVICE_PATH_PATTERNS:
        m = pattern.match(path)
        if m:
            return m.group("service")
    return None


class TrafficAnalyzer:
    """Analyzes HTTP traffic logs to infer service dependencies.

    Supports nginx combined logs, Envoy access logs, and JSON-formatted logs.
    """

    def __init__(
        self,
        registry: ServiceRegistry,
        log_source: Optional[str] = None,
        log_format: str = "nginx_combined",
    ) -> None:
        """
        Args:
            registry: ServiceRegistry for looking up known services.
            log_source: Path to log file, URL to fetch logs from, or None for manual feed.
            log_format: Log format name ("nginx_combined", "envoy", "json", "auto").
        """
        self._registry = registry
        self._log_source = log_source
        self._log_format = log_format

    async def analyze(self, log_lines: Optional[List[str]] = None) -> List[ServiceDependency]:
        """Analyze traffic logs and return inferred service dependencies.

        Args:
            log_lines: Optional list of log lines to analyze. If None and log_source
                is set, reads from the configured source.

        Returns:
            List of ServiceDependency objects derived from HTTP traffic patterns.
        """
        lines = log_lines or []
        if not lines and self._log_source:
            lines = await self._fetch_logs()

        if not lines:
            return []

        # Parse each log line into a structured entry
        entries: List[Dict[str, Any]] = []
        for line in lines:
            entry = self._parse_line(line.strip())
            if entry:
                entries.append(entry)

        if not entries:
            logger.warning("No valid log entries found in traffic analysis.")
            return []

        # Group by (source_service, target_service) and aggregate metrics
        grouped: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "latencies": [],
                "errors": 0,
                "last_seen": None,
            }
        )

        for entry in entries:
            source_name = self._resolve_source_service(entry)
            target_name = self._resolve_target_service(entry)
            if not source_name or not target_name:
                continue
            if source_name == target_name:
                continue

            key = (source_name, target_name)
            grouped[key]["count"] += 1

            status = entry.get("status")
            if status and int(status) >= 500:
                grouped[key]["errors"] += 1

            req_time = entry.get("req_time")
            if req_time is not None:
                try:
                    grouped[key]["latencies"].append(float(req_time))
                except (ValueError, TypeError):
                    pass

            entry_time = entry.get("timestamp")
            if entry_time:
                current_last = grouped[key]["last_seen"]
                if current_last is None or entry_time > current_last:
                    grouped[key]["last_seen"] = entry_time

        # Build ServiceDependency objects
        dependencies: List[ServiceDependency] = []
        now = datetime.now(timezone.utc)

        for (source_name, target_name), metrics in grouped.items():
            source_svc = self._find_service_by_name(source_name)
            target_svc = self._find_service_by_name(target_name)

            source_id = source_svc.service_id if source_svc else f"traffic-{source_name}"
            target_id = target_svc.service_id if target_svc else f"traffic-{target_name}"

            count = metrics["count"]
            latencies = metrics["latencies"]
            avg_latency = sum(latencies) / len(latencies) if latencies else None
            errors = metrics["errors"]
            error_rate = errors / count if count > 0 else None

            confidence = 0.7 if (source_svc and target_svc) else 0.4
            last_seen = metrics["last_seen"] or now

            dependencies.append(
                ServiceDependency(
                    source_service_id=source_id,
                    target_service_id=target_id,
                    dependency_type="http",
                    connection_count=count,
                    avg_latency_ms=avg_latency,
                    error_rate=error_rate,
                    last_seen_at=last_seen,
                    confidence_score=confidence,
                    discovery_sources=["traffic_logs"],
                )
            )

        return dependencies

    def _parse_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single log line into a dictionary of fields."""
        if not line:
            return None

        # Try JSON first if auto or explicitly json
        if self._log_format in ("json", "auto"):
            try:
                return self._parse_json_line(line)
            except (json.JSONDecodeError, ValueError):
                if self._log_format == "json":
                    return None

        # Try regex patterns
        for fmt_name, pattern in _LOG_PATTERNS.items():
            if self._log_format in (fmt_name, "auto"):
                m = pattern.match(line)
                if m:
                    return self._extract_from_match(m)

        return None

    def _parse_json_line(self, line: str) -> Dict[str, Any]:
        """Parse a JSON-formatted log line."""
        data = json.loads(line)
        # Normalize common field names
        entry: Dict[str, Any] = {}
        entry["remote_addr"] = data.get("remote_addr") or data.get("client_ip") or data.get("ip")
        entry["method"] = data.get("method") or data.get("request_method")
        entry["path"] = data.get("path") or data.get("request_path") or data.get("uri")
        entry["status"] = data.get("status") or data.get("response_code") or data.get("status_code")
        entry["host"] = data.get("host") or data.get("authority") or data.get("server_name")
        entry["req_time"] = data.get("request_time") or data.get("duration") or data.get("latency_ms")
        entry["upstream"] = data.get("upstream") or data.get("upstream_service")

        ts = data.get("time") or data.get("timestamp") or data.get("time_local")
        if ts:
            entry["timestamp"] = _parse_timestamp(str(ts))

        return entry

    def _extract_from_match(self, match: Any) -> Dict[str, Any]:
        """Extract fields from a regex match object."""
        entry: Dict[str, Any] = {}
        entry["remote_addr"] = match.group("remote_addr")
        entry["method"] = match.group("method")
        entry["path"] = match.group("path")
        entry["status"] = match.group("status")
        entry["host"] = match.group("host") if "host" in match.groupdict() else None
        entry["req_time"] = match.group("req_time") if "req_time" in match.groupdict() else None
        if entry["req_time"] is None and "resp_time" in match.groupdict():
            entry["req_time"] = match.group("resp_time")
        entry["upstream"] = match.group("upstream") if "upstream" in match.groupdict() else None

        ts = match.group("time")
        if ts:
            entry["timestamp"] = _parse_timestamp(ts)

        return entry

    def _resolve_source_service(self, entry: Dict[str, Any]) -> Optional[str]:
        """Determine the source service name from a log entry."""
        # Try remote_addr matching a known service host
        remote_addr = entry.get("remote_addr")
        if remote_addr:
            for svc in self._registry.list_services(active_only=True):
                if svc.host == remote_addr:
                    return svc.service_name

        return None

    def _resolve_target_service(self, entry: Dict[str, Any]) -> Optional[str]:
        """Determine the target service name from a log entry."""
        # Prefer upstream field if present (the backend being called)
        upstream = entry.get("upstream")
        if upstream:
            return upstream.split(":")[0].strip()

        # Try host header next (most reliable for proxy logs)
        host = entry.get("host")
        if host:
            svc = _extract_service_from_host(host)
            if svc:
                return svc

        # Try path-based extraction
        path = entry.get("path")
        if path:
            svc = _extract_service_from_path(path)
            if svc:
                return svc

        return None

    def _find_service_by_name(self, name: str) -> Optional[Any]:
        """Look up a service in the registry by matching service_name."""
        for svc in self._registry.list_services(active_only=True):
            if svc.service_name.lower() == name.lower():
                return svc
        return None

    async def _fetch_logs(self) -> List[str]:
        """Fetch log lines from the configured log_source."""
        if not self._log_source:
            return []

        # If it's a URL, fetch it
        if self._log_source.startswith(("http://", "https://")):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(self._log_source)
                    resp.raise_for_status()
                    return resp.text.splitlines()
            except ImportError:
                logger.warning("httpx is not installed; cannot fetch remote logs.")
                return []
            except Exception as exc:
                logger.warning("Failed to fetch remote logs: %s", exc)
                return []

        # Otherwise treat as a local file path
        try:
            with open(self._log_source, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except OSError as exc:
            logger.warning("Failed to read log file %s: %s", self._log_source, exc)
            return []
