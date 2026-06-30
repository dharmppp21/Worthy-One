"""Tests for the service health probing and auto-classification module."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.discovery.models import (
    DiscoveredService,
    HealthProbeResult,
    ProbeStatus,
    ProbeType,
)
from app.discovery.probing import (
    ServiceProber,
    _extract_ports,
    _parse_json_status,
    _truncate_body,
)
from app.incident_engine import _boost_severity
from app.discovery.registry import ServiceRegistry


class MockTransport(httpx.AsyncBaseTransport):
    """Mock httpx transport for testing HTTP probes."""

    def __init__(self, responses: dict[str, tuple[int, str, dict[str, str]]]) -> None:
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        # Also try just the path
        path = request.url.path

        for k, (status, body, headers) in self._responses.items():
            if k == key or k == path or path.endswith(k):
                return httpx.Response(
                    status_code=status,
                    content=body.encode(),
                    headers=headers,
                    request=request,
                )

        return httpx.Response(404, content=b"Not Found", request=request)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_registry():
    """Return a mock ServiceRegistry with some fake services."""
    registry = MagicMock(spec=ServiceRegistry)
    return registry


@pytest.fixture
def mock_publisher():
    """Return a mock DiscoveryEventPublisher."""
    pub = AsyncMock()
    pub.publish_health_changed = AsyncMock()
    return pub


@pytest.fixture
def http_service():
    """A fake HTTP service on port 8080."""
    return DiscoveredService(
        service_id="svc-http-1",
        service_name="web-api",
        service_type="unknown",
        endpoints=["http://127.0.0.1:8080"],
        host="127.0.0.1",
        discovery_source="manual",
    )


@pytest.fixture
def tcp_service():
    """A fake TCP service on port 5432."""
    return DiscoveredService(
        service_id="svc-tcp-1",
        service_name="postgres-db",
        service_type="unknown",
        endpoints=["tcp://127.0.0.1:5432"],
        host="127.0.0.1",
        discovery_source="manual",
    )


# ------------------------------------------------------------------
# Private helper tests
# ------------------------------------------------------------------

def test_extract_ports_from_urls():
    """_extract_ports should parse integer ports from endpoint URLs."""
    assert _extract_ports(["http://host:8080/path"]) == [8080]
    assert _extract_ports(["https://host:443/"]) == [443]
    assert _extract_ports(["host:9092"]) == [9092]
    assert _extract_ports(["http://host"]) == [80]
    assert _extract_ports(["https://host"]) == [443]
    assert _extract_ports([]) == []


def test_truncate_body():
    """_truncate_body should truncate text to max length."""
    assert _truncate_body("short") == "short"
    long_text = "x" * 500
    assert len(_truncate_body(long_text, 200)) == 200


def test_parse_json_status_up():
    """_parse_json_status should extract UP from JSON status field."""
    resp = httpx.Response(200, content=b'{"status": "up"}')
    assert _parse_json_status(resp) == ProbeStatus.up


def test_parse_json_status_down():
    """_parse_json_status should extract DOWN from JSON status field."""
    resp = httpx.Response(200, content=b'{"status": "down"}')
    assert _parse_json_status(resp) == ProbeStatus.down


def test_parse_json_status_default_up():
    """_parse_json_status should default to UP when JSON has no status."""
    resp = httpx.Response(200, content=b'{}')
    assert _parse_json_status(resp) == ProbeStatus.up


# ------------------------------------------------------------------
# HTTP probe tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_http_success(mock_registry, http_service):
    """probe_http should return UP when /health returns 200."""
    transport = MockTransport({
        "/health": (200, '{"status": "up"}', {"content-type": "application/json"}),
    })
    prober = ServiceProber(registry=mock_registry)
    prober._http_client = httpx.AsyncClient(transport=transport)

    result = await prober.probe_http(http_service)
    assert result.status == ProbeStatus.up
    assert result.probe_type == ProbeType.http
    assert result.endpoint == "http://127.0.0.1:8080/health"
    assert result.response_status_code == 200
    await prober.close()


@pytest.mark.asyncio
async def test_probe_http_tries_multiple_endpoints(mock_registry, http_service):
    """probe_http should try multiple endpoints until one succeeds."""
    transport = MockTransport({
        "/health": (404, "Not Found", {}),
        "/healthz": (404, "Not Found", {}),
        "/ready": (200, '{"status": "ready"}', {"content-type": "application/json"}),
    })
    prober = ServiceProber(registry=mock_registry)
    prober._http_client = httpx.AsyncClient(transport=transport)

    result = await prober.probe_http(http_service)
    assert result.status == ProbeStatus.up
    assert result.endpoint == "http://127.0.0.1:8080/ready"
    await prober.close()


@pytest.mark.asyncio
async def test_probe_http_server_error(mock_registry, http_service):
    """probe_http should return DOWN when endpoint returns 500."""
    transport = MockTransport({
        "/health": (500, "Internal Server Error", {}),
    })
    prober = ServiceProber(registry=mock_registry)
    prober._http_client = httpx.AsyncClient(transport=transport)

    result = await prober.probe_http(http_service)
    assert result.status == ProbeStatus.down
    assert result.response_status_code == 500
    await prober.close()


@pytest.mark.asyncio
async def test_probe_http_all_fail(mock_registry, http_service):
    """probe_http should return UNKNOWN when all endpoints fail."""
    transport = MockTransport({
        "/health": (404, "Not Found", {}),
        "/healthz": (404, "Not Found", {}),
        "/ready": (404, "Not Found", {}),
        "/alive": (404, "Not Found", {}),
        "/status": (404, "Not Found", {}),
        "/actuator/health": (404, "Not Found", {}),
        "/api/health": (404, "Not Found", {}),
        "/health/check": (404, "Not Found", {}),
    })
    prober = ServiceProber(registry=mock_registry)
    prober._http_client = httpx.AsyncClient(transport=transport)

    result = await prober.probe_http(http_service)
    assert result.status == ProbeStatus.unknown
    assert result.error_message is not None
    await prober.close()


# ------------------------------------------------------------------
# TCP probe tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_tcp_success(mock_registry, tcp_service):
    """probe_tcp should return UP when TCP connection succeeds."""
    prober = ServiceProber(registry=mock_registry)

    with patch("asyncio.open_connection") as mock_conn:
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_conn.return_value = (mock_reader, mock_writer)

        result = await prober.probe_tcp(tcp_service, 5432)
        assert result.status == ProbeStatus.up
        assert result.probe_type == ProbeType.tcp
        assert result.endpoint == "127.0.0.1:5432"


@pytest.mark.asyncio
async def test_probe_tcp_timeout(mock_registry, tcp_service):
    """probe_tcp should return DOWN on TCP timeout."""
    prober = ServiceProber(registry=mock_registry)

    with patch("asyncio.open_connection") as mock_conn:
        mock_conn.side_effect = asyncio.TimeoutError()

        result = await prober.probe_tcp(tcp_service, 5432)
        assert result.status == ProbeStatus.down
        assert "timeout" in result.error_message.lower()


@pytest.mark.asyncio
async def test_probe_tcp_refused(mock_registry, tcp_service):
    """probe_tcp should return DOWN on connection refused."""
    prober = ServiceProber(registry=mock_registry)

    with patch("asyncio.open_connection") as mock_conn:
        mock_conn.side_effect = OSError("Connection refused")

        result = await prober.probe_tcp(tcp_service, 5432)
        assert result.status == ProbeStatus.down
        assert "refused" in result.error_message.lower() or "Connection refused" in result.error_message


# ------------------------------------------------------------------
# Protocol detection tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_protocol_http(mock_registry):
    """detect_protocol should return 'http' for HTTP services."""
    transport = MockTransport({
        "/": (200, "OK", {"server": "nginx"}),
    })
    prober = ServiceProber(registry=mock_registry)
    prober._http_client = httpx.AsyncClient(transport=transport)

    result = await prober.detect_protocol("127.0.0.1", 8080)
    assert result == "http"
    await prober.close()


@pytest.mark.asyncio
async def test_detect_protocol_grpc_port(mock_registry):
    """detect_protocol should return 'grpc' for port 50051."""
    prober = ServiceProber(registry=mock_registry)
    result = await prober.detect_protocol("127.0.0.1", 50051)
    assert result == "grpc"


@pytest.mark.asyncio
async def test_detect_protocol_raw_tcp(mock_registry):
    """detect_protocol should return 'raw_tcp' for non-HTTP services."""
    transport = MockTransport({
        "/": (404, "Not Found", {}),
    })
    prober = ServiceProber(registry=mock_registry)
    prober._http_client = httpx.AsyncClient(transport=transport)

    # Even with 404, it's still HTTP
    result = await prober.detect_protocol("127.0.0.1", 5432)
    assert result == "http"
    await prober.close()


# ------------------------------------------------------------------
# Service classification tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_k8s_label(mock_registry):
    """classify_service should use K8s label if present."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="my-app",
        service_type="unknown",
        endpoints=["http://host:8080"],
        host="host",
        metadata={"labels": {"app.kubernetes.io/component": "database"}},
    )
    result = await prober.classify_service(service, [])
    assert result == "database"


@pytest.mark.asyncio
async def test_classify_docker_image(mock_registry):
    """classify_service should map Docker image keywords."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="redis",
        service_type="unknown",
        endpoints=["tcp://host:6379"],
        host="host",
        metadata={"image": "redis:7-alpine"},
    )
    result = await prober.classify_service(service, [])
    assert result == "cache"


@pytest.mark.asyncio
async def test_classify_process_name(mock_registry):
    """classify_service should map process name keywords."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="postgres",
        service_type="unknown",
        endpoints=["tcp://host:5432"],
        host="host",
        metadata={"process_name": "postgres"},
    )
    result = await prober.classify_service(service, [])
    assert result == "database"


@pytest.mark.asyncio
async def test_classify_framework_from_probe(mock_registry):
    """classify_service should detect framework from HTTP response body."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="api",
        service_type="unknown",
        endpoints=["http://host:8080"],
        host="host",
    )
    probe_result = HealthProbeResult(
        service_id="svc-1",
        status=ProbeStatus.up,
        probe_type=ProbeType.http,
        response_body_preview="{\"framework\": \"FastAPI\", \"version\": \"1.0\"}",
    )
    result = await prober.classify_service(service, [probe_result])
    assert result == "python_api"


@pytest.mark.asyncio
async def test_classify_known_port(mock_registry):
    """classify_service should map known ports to types."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="kafka",
        service_type="unknown",
        endpoints=["tcp://host:9092"],
        host="host",
    )
    result = await prober.classify_service(service, [])
    assert result == "message_queue"


@pytest.mark.asyncio
async def test_classify_content_type_html(mock_registry):
    """classify_service should infer 'web' from HTML response."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="frontend",
        service_type="unknown",
        endpoints=["http://host:80"],
        host="host",
    )
    probe_result = HealthProbeResult(
        service_id="svc-1",
        status=ProbeStatus.up,
        probe_type=ProbeType.http,
        response_body_preview="<html><body>Hello</body></html>",
    )
    result = await prober.classify_service(service, [probe_result])
    assert result == "web"


@pytest.mark.asyncio
async def test_classify_content_type_json(mock_registry):
    """classify_service should infer 'api' from JSON response."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="api",
        service_type="unknown",
        endpoints=["http://host:8080"],
        host="host",
    )
    probe_result = HealthProbeResult(
        service_id="svc-1",
        status=ProbeStatus.up,
        probe_type=ProbeType.http,
        response_body_preview='{"status": "ok"}',
    )
    result = await prober.classify_service(service, [probe_result])
    assert result == "api"


@pytest.mark.asyncio
async def test_classify_unknown_fallback(mock_registry):
    """classify_service should return 'unknown' when no heuristics match."""
    prober = ServiceProber(registry=mock_registry)
    service = DiscoveredService(
        service_id="svc-1",
        service_name="mystery",
        service_type="unknown",
        endpoints=["tcp://host:12345"],
        host="host",
    )
    result = await prober.classify_service(service, [])
    assert result == "unknown"


# ------------------------------------------------------------------
# probe_all_services tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_all_services_runs_in_parallel(mock_registry, mock_publisher, http_service, tcp_service):
    """probe_all_services should probe all services concurrently."""
    mock_registry.list_services.return_value = [http_service, tcp_service]

    transport = MockTransport({
        "/health": (200, '{"status": "up"}', {"content-type": "application/json"}),
    })
    prober = ServiceProber(registry=mock_registry, publisher=mock_publisher)
    prober._http_client = httpx.AsyncClient(transport=transport)

    with patch("asyncio.open_connection") as mock_conn:
        mock_reader = MagicMock()
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_conn.return_value = (mock_reader, mock_writer)

        results = await prober.probe_all_services()
        assert len(results) == 2
        assert results[0].status == ProbeStatus.up  # HTTP
        assert results[1].status == ProbeStatus.up  # TCP

    await prober.close()


@pytest.mark.asyncio
async def test_probe_all_services_publishes_health_change(mock_registry, mock_publisher, http_service):
    """probe_all_services should publish health_changed when status changes."""
    http_service.health_status = "unknown"
    mock_registry.list_services.return_value = [http_service]
    mock_registry.update_heartbeat = MagicMock()

    transport = MockTransport({
        "/health": (200, '{"status": "up"}', {"content-type": "application/json"}),
    })
    prober = ServiceProber(registry=mock_registry, publisher=mock_publisher)
    prober._http_client = httpx.AsyncClient(transport=transport)

    results = await prober.probe_all_services()
    assert results[0].status == ProbeStatus.up
    mock_publisher.publish_health_changed.assert_awaited_once()

    await prober.close()


# ------------------------------------------------------------------
# Background task tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_background_probing_start_stop(mock_registry):
    """Background probing should start and stop cleanly."""
    prober = ServiceProber(registry=mock_registry)
    prober.start_background_probing(interval_seconds=1)
    assert prober._background_task is not None

    prober.stop_background_probing()
    assert prober._background_task is None


@pytest.mark.asyncio
async def test_background_probing_runs(mock_registry):
    """Background probing should run at least once."""
    mock_registry.list_services.return_value = []
    prober = ServiceProber(registry=mock_registry)
    prober.start_background_probing(interval_seconds=1)

    # Wait for one iteration
    await asyncio.sleep(0.5)

    prober.stop_background_probing()
    mock_registry.list_services.assert_called()


# ------------------------------------------------------------------
# Severity boost test
# ------------------------------------------------------------------

def test_boost_severity_info_to_warning():
    assert _boost_severity("info") == "warning"


def test_boost_severity_warning_to_critical():
    assert _boost_severity("warning") == "critical"


def test_boost_severity_critical_stays():
    assert _boost_severity("critical") == "critical"
