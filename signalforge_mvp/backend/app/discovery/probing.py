"""
Service health probing and auto-classification.

Provides HTTP and TCP health probes, protocol detection, and service
type classification based on response analysis and known port/image/process
heuristics.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

import httpx

from .models import DiscoveredService, HealthProbeResult, ProbeStatus, ProbeType
from .registry import ServiceRegistry

logger = logging.getLogger(__name__)

# Common HTTP health endpoints tried in order
_HEALTH_ENDPOINTS = [
    "/health",
    "/healthz",
    "/ready",
    "/alive",
    "/status",
    "/actuator/health",
    "/api/health",
    "/health/check",
]

# Known service types mapped from image/process keywords
_IMAGE_KEYWORDS: Dict[str, str] = {
    "postgres": "database",
    "mysql": "database",
    "redis": "cache",
    "kafka": "message_queue",
    "nginx": "web",
    "mongo": "database",
    "elasticsearch": "search",
    "grafana": "dashboard",
    "prometheus": "monitoring",
}

_PROCESS_KEYWORDS: Dict[str, str] = {
    "nginx": "web",
    "apache": "web",
    "postgres": "database",
    "redis": "cache",
    "kafka": "message_queue",
    "mongod": "database",
    "mysqld": "database",
    "elasticsearch": "search",
}

# Framework detection strings mapped to service types
_FRAMEWORK_PATTERNS: Dict[str, str] = {
    "spring boot": "java_api",
    "express": "nodejs_api",
    "fastify": "nodejs_api",
    "django": "python_api",
    "flask": "python_api",
    "fastapi": "python_api",
    "rails": "ruby_api",
    "laravel": "php_api",
    "asp.net": "dotnet_api",
    "dotnet": "dotnet_api",
}

# Known port -> service type mappings
_PORT_TO_TYPE: Dict[int, str] = {
    5432: "database",
    3306: "database",
    6379: "cache",
    9092: "message_queue",
    11211: "cache",
    9200: "search",
    5601: "dashboard",
    27017: "database",
    50051: "grpc_api",
}

# Ports commonly used for HTTP services
_HTTP_PORTS = {80, 443, 8080, 3000, 5000, 8000, 5173}


class ServiceProber:
    """
    Probes discovered services for health and classifies their type.

    Accepts a ServiceRegistry and an optional DiscoveryEventPublisher.
    Runs HTTP health checks on HTTP-facing services and TCP checks on
    everything else.  Detects protocols and auto-classifies services.
    """

    def __init__(
        self,
        registry: ServiceRegistry,
        publisher: Optional[Any] = None,
    ) -> None:
        """Initialize the health probe runner."""
        self._registry = registry
        self._publisher = publisher
        self._http_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=5.0,
        )
        self._background_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------
    # Probing helpers
    # ------------------------------------------------------------------

    async def probe_http(
        self,
        service: DiscoveredService,
    ) -> HealthProbeResult:
        """
        Try common HTTP health endpoints and return the first successful result.

        Args:
            service: The service to probe.

        Returns:
            A HealthProbeResult with the outcome of the probe.
        """
        service_id = service.service_id
        host = service.host
        port = _extract_http_port(service.endpoints)
        base_url = f"http://{host}:{port}"

        last_error: Optional[str] = None

        for endpoint in _HEALTH_ENDPOINTS:
            url = f"{base_url}{endpoint}"
            start = time.monotonic()
            try:
                response = await self._http_client.get(url)
                elapsed_ms = (time.monotonic() - start) * 1000

                if 200 <= response.status_code < 300:
                    # UP — parse JSON status if present
                    body_preview = _truncate_body(response.text)
                    status = _parse_json_status(response)
                    return HealthProbeResult(
                        service_id=service_id,
                        status=status,
                        probe_type=ProbeType.http,
                        endpoint=url,
                        response_time_ms=round(elapsed_ms, 2),
                        response_status_code=response.status_code,
                        response_body_preview=body_preview,
                        probed_at=datetime.now(timezone.utc),
                    )

                if 400 <= response.status_code < 500:
                    # Client error — endpoint doesn't exist, try next
                    last_error = f"HTTP {response.status_code} at {endpoint}"
                    continue

                # 500+ = DOWN
                return HealthProbeResult(
                    service_id=service_id,
                    status=ProbeStatus.down,
                    probe_type=ProbeType.http,
                    endpoint=url,
                    response_time_ms=round(elapsed_ms, 2),
                    response_status_code=response.status_code,
                    response_body_preview=_truncate_body(response.text),
                    error_message=f"HTTP {response.status_code}",
                    probed_at=datetime.now(timezone.utc),
                )

            except (httpx.TimeoutException, httpx.ConnectError):
                last_error = f"Connection error at {endpoint}"
                continue
            except Exception as exc:
                last_error = f"Unexpected error at {endpoint}: {exc}"
                continue

        # All endpoints failed
        return HealthProbeResult(
            service_id=service_id,
            status=ProbeStatus.unknown,
            probe_type=ProbeType.http,
            error_message=last_error or "All health endpoints failed",
            probed_at=datetime.now(timezone.utc),
        )

    async def probe_tcp(
        self,
        service: DiscoveredService,
        port: int,
    ) -> HealthProbeResult:
        """
        Open a TCP connection to host:port and record the result.

        Args:
            service: The service to probe.
            port: The TCP port to connect to.

        Returns:
            A HealthProbeResult with the outcome of the probe.
        """
        service_id = service.service_id
        host = service.host
        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=3.0,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            writer.close()
            await writer.wait_closed()
            return HealthProbeResult(
                service_id=service_id,
                status=ProbeStatus.up,
                probe_type=ProbeType.tcp,
                endpoint=f"{host}:{port}",
                response_time_ms=round(elapsed_ms, 2),
                probed_at=datetime.now(timezone.utc),
            )
        except asyncio.TimeoutError:
            return HealthProbeResult(
                service_id=service_id,
                status=ProbeStatus.down,
                probe_type=ProbeType.tcp,
                endpoint=f"{host}:{port}",
                error_message="TCP connection timeout",
                probed_at=datetime.now(timezone.utc),
            )
        except OSError as exc:
            return HealthProbeResult(
                service_id=service_id,
                status=ProbeStatus.down,
                probe_type=ProbeType.tcp,
                endpoint=f"{host}:{port}",
                error_message=str(exc),
                probed_at=datetime.now(timezone.utc),
            )

    async def detect_protocol(self, host: str, port: int) -> str:
        """
        Detect the protocol spoken on a given host:port.

        Args:
            host: The hostname or IP address.
            port: The port number.

        Returns:
            One of "http", "http2", "grpc", or "raw_tcp".
        """
        # gRPC heuristic: common port
        if port == 50051:
            return "grpc"

        try:
            url = f"http://{host}:{port}/"
            response = await self._http_client.get(url, timeout=3.0)
            # If we get here, it's HTTP
            server = response.headers.get("server", "").lower()
            if "http/2" in server or response.http_version == "HTTP/2":
                return "http2"
            return "http"
        except httpx.RemoteProtocolError:
            # Non-HTTP response — could be raw TCP or gRPC
            return "raw_tcp"
        except (httpx.ConnectError, httpx.TimeoutException):
            return "raw_tcp"
        except Exception:
            return "raw_tcp"

    async def classify_service(
        self,
        service: DiscoveredService,
        probe_results: List[HealthProbeResult],
    ) -> str:
        """
        Classify a service into a type based on multiple heuristics.

        Priority:
        1. K8s label ``app.kubernetes.io/component``.
        2. Docker image keyword match.
        3. Process name keyword match.
        4. HTTP framework detection from response headers/body.
        5. Known port mapping.
        6. Content-Type inference (html -> web, json -> api).
        7. Fallback to ``unknown``.

        Args:
            service: The service to classify.
            probe_results: Probe results that may contain response headers/body.

        Returns:
            The classified service type string.
        """
        # 1. Kubernetes label
        labels = service.metadata.get("labels", {})
        if isinstance(labels, dict):
            k8s_component = labels.get("app.kubernetes.io/component")
            if k8s_component:
                return str(k8s_component).lower()

        # 2. Docker image keyword
        image = service.metadata.get("image", "")
        if image:
            img_lower = image.lower()
            for keyword, svc_type in _IMAGE_KEYWORDS.items():
                if keyword in img_lower:
                    return svc_type

        # 3. Process name keyword
        process_name = service.metadata.get("process_name", "")
        if process_name:
            proc_lower = process_name.lower()
            for keyword, svc_type in _PROCESS_KEYWORDS.items():
                if keyword in proc_lower:
                    return svc_type

        # 4. HTTP framework detection from probe results
        for result in probe_results:
            if result.probe_type == ProbeType.http and result.response_body_preview:
                body_lower = result.response_body_preview.lower()
                for pattern, svc_type in _FRAMEWORK_PATTERNS.items():
                    if pattern in body_lower:
                        return svc_type

        # 5. Known port mapping
        for port in _extract_ports(service.endpoints):
            if port in _PORT_TO_TYPE:
                return _PORT_TO_TYPE[port]

        # 6. Content-Type inference from HTTP probe
        for result in probe_results:
            if result.probe_type == ProbeType.http and result.status == ProbeStatus.up:
                # We don't have the Content-Type header in the result model,
                # so we infer from response body preview
                preview = result.response_body_preview or ""
                if preview.startswith("<") or "html" in preview.lower():
                    return "web"
                if preview.startswith("{") or preview.startswith("["):
                    return "api"

        # 7. Fallback
        return "unknown"

    # ------------------------------------------------------------------
    # Batch probing
    # ------------------------------------------------------------------

    async def probe_all_services(self) -> List[HealthProbeResult]:
        """
        Probe all active services and update their health status in the registry.

        HTTP probes are used for services on known HTTP ports; TCP probes are
        used for all other ports.  All probes run concurrently.

        Returns:
            A list of HealthProbeResult for every service/port probed.
        """
        services = self._registry.list_services(active_only=True)
        if not services:
            return []

        tasks: List[asyncio.Task] = []
        task_to_service: Dict[asyncio.Task, DiscoveredService] = {}

        for service in services:
            ports = _extract_ports(service.endpoints)
            http_ports = [p for p in ports if p in _HTTP_PORTS]
            tcp_ports = [p for p in ports if p not in _HTTP_PORTS]

            if http_ports:
                # Probe the first HTTP port
                task = asyncio.create_task(self.probe_http(service))
                tasks.append(task)
                task_to_service[task] = service
            elif tcp_ports:
                for port in tcp_ports:
                    task = asyncio.create_task(self.probe_tcp(service, port))
                    tasks.append(task)
                    task_to_service[task] = service
            else:
                # No ports — try HTTP on default port 80
                task = asyncio.create_task(self.probe_http(service))
                tasks.append(task)
                task_to_service[task] = service

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_results: List[HealthProbeResult] = []

        for task, result in zip(tasks, results):
            service = task_to_service[task]
            if isinstance(result, Exception):
                logger.error("Probe failed for %s: %s", service.service_name, result)
                result = HealthProbeResult(
                    service_id=service.service_id,
                    status=ProbeStatus.unknown,
                    probe_type=ProbeType.tcp,
                    error_message=str(result),
                    probed_at=datetime.now(timezone.utc),
                )

            all_results.append(result)

            # Update health status
            old_status = getattr(service, "health_status", None)
            new_status = result.status.value
            service.health_status = new_status

            # Persist updated health status
            try:
                self._registry.update_health_status(service.service_id, new_status)
                self._registry.update_heartbeat(service.service_id)
            except ValueError:
                pass

            # Publish health change if applicable
            if self._publisher is not None and old_status is not None:
                if old_status != new_status:
                    await self._publisher.publish_health_changed(
                        service.service_id,
                        service.service_name,
                        old_status,
                        new_status,
                    )

        return all_results

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    def start_background_probing(self, interval_seconds: int = 15) -> None:
        """
        Start a background task that probes all services periodically.

        Args:
            interval_seconds: Interval between probe runs (default 15s).
        """
        if self._background_task is not None:
            logger.warning("Background probing already running; ignoring.")
            return

        self._stop_event = asyncio.Event()
        self._background_task = asyncio.create_task(self._probe_loop(interval_seconds))
        logger.info("Background probing started (interval=%ds).", interval_seconds)

    def stop_background_probing(self) -> None:
        """Signal the background probing loop to stop."""
        if self._background_task is None:
            logger.warning("Background probing not running; ignoring.")
            return

        if self._stop_event is not None:
            self._stop_event.set()
        self._background_task = None
        logger.info("Background probing stopped.")

    async def _probe_loop(self, interval_seconds: int) -> None:
        """Internal loop that probes services periodically."""
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self.probe_all_services()
            except Exception as exc:
                logger.error("Probe loop error: %s", exc, exc_info=True)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=interval_seconds,
                )
            except asyncio.TimeoutError:
                pass  # Normal interval timeout

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the internal HTTP client."""
        await self._http_client.aclose()


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _extract_ports(endpoints: List[str]) -> List[int]:
    """Parse integer ports from endpoint URLs."""
    ports: List[int] = []
    for ep in endpoints:
        try:
            if ep.startswith("http://"):
                # Default to 80 if no port specified
                base = ep[7:]  # strip "http://"
                if ":" in base.split("/", 1)[0]:
                    port_str = base.rsplit(":", 1)[1].split("/", 1)[0]
                    ports.append(int(port_str))
                else:
                    ports.append(80)
            elif ep.startswith("https://"):
                # Default to 443 if no port specified
                base = ep[8:]  # strip "https://"
                if ":" in base.split("/", 1)[0]:
                    port_str = base.rsplit(":", 1)[1].split("/", 1)[0]
                    ports.append(int(port_str))
                else:
                    ports.append(443)
            elif ":" in ep:
                # Raw host:port string
                port_str = ep.rsplit(":", 1)[1]
                port_str = port_str.split("/", 1)[0]
                ports.append(int(port_str))
        except (ValueError, IndexError):
            continue
    return ports


def _extract_http_port(endpoints: List[str]) -> int:
    """Return the first HTTP port found, or 80 as default."""
    for port in _extract_ports(endpoints):
        if port in _HTTP_PORTS or port == 80 or port == 443:
            return port
    return 80


def _truncate_body(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len characters, preserving first chars."""
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _parse_json_status(response: httpx.Response) -> ProbeStatus:
    """Try to parse JSON response for a 'status' field."""
    try:
        data = response.json()
        status = data.get("status", "up")
        if status in ("up", "healthy", "ok", "running"):
            return ProbeStatus.up
        if status in ("down", "unhealthy", "error", "failed"):
            return ProbeStatus.down
    except Exception:
        pass
    return ProbeStatus.up
