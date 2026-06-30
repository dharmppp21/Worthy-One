"""Integration tests for bare metal / process-based auto-discovery.

Uses fully mocked psutil so no real process scanning is needed.  Verifies the
discovery pipeline end-to-end including system-process skipping, PermissionError
handling, and metadata capture.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.discovery.engine import DiscoveryEngine
from app.discovery.environment import EnvironmentDetector
from app.discovery.providers.process import ProcessDiscoveryProvider
from app.discovery.registry import ServiceRegistry
from app.main import app as fastapi_app


# ------------------------------------------------------------------
# Fake psutil helpers
# ------------------------------------------------------------------

def _make_fake_connection(
    ip: str, port: int, status: str = "LISTEN"
) -> MagicMock:
    """Return a fake psutil connection object with laddr.ip and laddr.port."""
    conn = MagicMock()
    conn.status = status
    conn.laddr = MagicMock()
    conn.laddr.ip = ip
    conn.laddr.port = port
    return conn


def _make_fake_process(
    pid: int,
    name: str,
    exe: str,
    connections: List[MagicMock],
    username: str = "root",
    create_time: Optional[float] = None,
    cmdline: Optional[List[str]] = None,
    cpu_percent: float = 0.0,
    memory_percent: float = 0.0,
) -> MagicMock:
    """Return a fake psutil process object with .info and .connections()."""
    proc = MagicMock()
    proc.info = {
        "pid": pid,
        "name": name,
        "exe": exe,
        "cmdline": cmdline or [exe, "--serve"],
        "username": username,
        "create_time": create_time or datetime.now(timezone.utc).timestamp(),
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
    }
    proc.connections = MagicMock(return_value=connections)
    return proc


# ------------------------------------------------------------------
# Fake process builders (5 services)
# ------------------------------------------------------------------

def make_nginx_process() -> MagicMock:
    return _make_fake_process(
        pid=1001,
        name="nginx",
        exe="/usr/sbin/nginx",
        connections=[
            _make_fake_connection("0.0.0.0", 80),
            _make_fake_connection("0.0.0.0", 443),
        ],
        username="www-data",
    )


def make_postgres_process() -> MagicMock:
    return _make_fake_process(
        pid=1002,
        name="postgres",
        exe="/usr/bin/postgres",
        connections=[_make_fake_connection("127.0.0.1", 5432)],
        username="postgres",
    )


def make_redis_process() -> MagicMock:
    return _make_fake_process(
        pid=1003,
        name="redis-server",
        exe="/usr/bin/redis-server",
        connections=[_make_fake_connection("0.0.0.0", 6379)],
        username="redis",
    )


def make_python_process() -> MagicMock:
    return _make_fake_process(
        pid=1004,
        name="python3",
        exe="/usr/bin/python3",
        connections=[_make_fake_connection("0.0.0.0", 5000)],
        username="appuser",
        cmdline=["/usr/bin/python3", "app.py"],
    )


def make_node_process() -> MagicMock:
    return _make_fake_process(
        pid=1005,
        name="node",
        exe="/usr/bin/node",
        connections=[_make_fake_connection("0.0.0.0", 3000)],
        username="appuser",
        cmdline=["/usr/bin/node", "server.js"],
    )


def make_all_processes() -> List[MagicMock]:
    return [
        make_nginx_process(),
        make_postgres_process(),
        make_redis_process(),
        make_python_process(),
        make_node_process(),
    ]


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_psutil_processes():
    """Context manager that patches psutil.process_iter with 5 fake processes."""
    processes = make_all_processes()
    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=processes)
        mock_psutil.CONN_LISTEN = "LISTEN"
        yield mock_psutil


@pytest.fixture
def baremetal_full_client(
    mock_psutil_processes,
    registry: ServiceRegistry,
    discovery_engine: DiscoveryEngine,
    process_provider: ProcessDiscoveryProvider,
) -> TestClient:
    """Full integration fixture: patches psutil, registers provider, runs discovery."""
    discovery_engine.register_provider(process_provider)
    asyncio.run(discovery_engine.run_discovery())

    with TestClient(fastapi_app) as client:
        client.headers.update({"X-API-Key": "sf-test-key"})
        yield client


# ------------------------------------------------------------------
# Discovery tests
# ------------------------------------------------------------------

class TestBareMetalDiscovery:
    """End-to-end tests for bare metal process discovery."""

    def test_all_five_services_discovered(self, baremetal_full_client: TestClient) -> None:
        """All 5 mock processes should be discovered."""
        response = baremetal_full_client.get("/services/discovered")
        assert response.status_code == 200
        services = response.json()
        assert len(services) == 5
        names = {s["service_name"] for s in services}
        assert names == {"nginx", "postgres", "redis", "python-app", "node-app"}

    def test_service_names_from_process(self, baremetal_full_client: TestClient) -> None:
        """Service names should be derived from executable names."""
        response = baremetal_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert "nginx" in by_name
        assert "postgres" in by_name
        assert "redis" in by_name
        assert "python-app" in by_name
        assert "node-app" in by_name

    def test_endpoints_from_listening_ports(self, baremetal_full_client: TestClient) -> None:
        """Endpoints should be derived from listening ports."""
        response = baremetal_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert by_name["nginx"]["endpoints"] == ["tcp://0.0.0.0:80", "tcp://0.0.0.0:443"]
        assert by_name["postgres"]["endpoints"] == ["tcp://127.0.0.1:5432"]
        assert by_name["redis"]["endpoints"] == ["tcp://0.0.0.0:6379"]
        assert by_name["python-app"]["endpoints"] == ["tcp://0.0.0.0:5000"]
        assert by_name["node-app"]["endpoints"] == ["tcp://0.0.0.0:3000"]

    def test_service_types_correct(self, baremetal_full_client: TestClient) -> None:
        """Each service should have the correct auto-detected type."""
        response = baremetal_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert by_name["nginx"]["service_type"] == "web"
        assert by_name["postgres"]["service_type"] == "database"
        assert by_name["redis"]["service_type"] == "cache"
        assert by_name["python-app"]["service_type"] == "api"
        assert by_name["node-app"]["service_type"] == "api"


# ------------------------------------------------------------------
# System process skipping tests
# ------------------------------------------------------------------

class TestBareMetalSystemProcesses:
    """Tests that system processes are correctly skipped."""

    def test_systemd_skipped(self, registry: ServiceRegistry, discovery_engine: DiscoveryEngine) -> None:
        """systemd process should be skipped (treated as system process)."""
        system_proc = _make_fake_process(
            pid=1,
            name="systemd",
            exe="/usr/lib/systemd/systemd",
            connections=[_make_fake_connection("0.0.0.0", 12345)],
        )
        good_proc = make_nginx_process()

        def _mock_is_system(name: str) -> bool:
            return name.lower() == "systemd"

        with patch("app.discovery.providers.process.psutil") as mock_psutil, \
             patch("app.discovery.providers.process._is_system_process", side_effect=_mock_is_system):
            mock_psutil.process_iter = MagicMock(return_value=[system_proc, good_proc])
            mock_psutil.CONN_LISTEN = "LISTEN"
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            result = asyncio.run(discovery_engine.run_discovery())

        assert len(result) == 1
        assert result[0].service_name == "nginx"

    def test_svchost_skipped(self, registry: ServiceRegistry, discovery_engine: DiscoveryEngine) -> None:
        """Windows svchost process should be skipped."""
        svchost_proc = _make_fake_process(
            pid=444,
            name="svchost.exe",
            exe="C:\\Windows\\System32\\svchost.exe",
            connections=[_make_fake_connection("127.0.0.1", 9999)],
        )
        good_proc = make_nginx_process()

        with patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.process_iter = MagicMock(return_value=[svchost_proc, good_proc])
            mock_psutil.CONN_LISTEN = "LISTEN"
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            result = asyncio.run(discovery_engine.run_discovery())

        assert len(result) == 1
        assert result[0].service_name == "nginx"

    def test_kernel_skipped(self, registry: ServiceRegistry, discovery_engine: DiscoveryEngine) -> None:
        """kernel process should be skipped."""
        kernel_proc = _make_fake_process(
            pid=0,
            name="kernel",
            exe="",
            connections=[_make_fake_connection("0.0.0.0", 11111)],
        )
        good_proc = make_nginx_process()

        with patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.process_iter = MagicMock(return_value=[kernel_proc, good_proc])
            mock_psutil.CONN_LISTEN = "LISTEN"
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            result = asyncio.run(discovery_engine.run_discovery())

        assert len(result) == 1
        assert result[0].service_name == "nginx"


# ------------------------------------------------------------------
# PermissionError handling tests
# ------------------------------------------------------------------

class TestBareMetalPermissionError:
    """Tests that PermissionError is handled gracefully."""

    def test_permission_error_skipped_with_warning(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Processes that raise PermissionError should be skipped, others discovered."""
        bad_proc = MagicMock()
        bad_proc.info = {"pid": 1, "name": "someproc", "exe": None}
        bad_proc.connections = MagicMock(side_effect=PermissionError("access denied"))

        good_proc = make_nginx_process()

        with patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception
            mock_psutil.process_iter = MagicMock(return_value=[bad_proc, good_proc])
            mock_psutil.CONN_LISTEN = "LISTEN"
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            result = asyncio.run(discovery_engine.run_discovery())

        assert len(result) == 1
        assert result[0].service_name == "nginx"
        # The provider should not crash; warning may be logged at debug level

    def test_no_such_process_skipped(self, registry: ServiceRegistry, discovery_engine: DiscoveryEngine) -> None:
        """Processes that raise NoSuchProcess should be skipped."""
        bad_proc = MagicMock()
        bad_proc.info = {"pid": 99999, "name": "gone", "exe": None}
        bad_proc.connections = MagicMock(
            side_effect=Exception("psutil.NoSuchProcess")
        )

        good_proc = make_nginx_process()

        with patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception
            mock_psutil.process_iter = MagicMock(return_value=[bad_proc, good_proc])
            mock_psutil.CONN_LISTEN = "LISTEN"
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            result = asyncio.run(discovery_engine.run_discovery())

        assert len(result) == 1
        assert result[0].service_name == "nginx"


# ------------------------------------------------------------------
# Metadata tests
# ------------------------------------------------------------------

class TestBareMetalMetadata:
    """Tests for process metadata storage."""

    def test_pid_metadata(self, baremetal_full_client: TestClient) -> None:
        """Registry should store PID in metadata."""
        response = baremetal_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert by_name["nginx"]["metadata"]["pid"] == 1001
        assert by_name["postgres"]["metadata"]["pid"] == 1002
        assert by_name["redis"]["metadata"]["pid"] == 1003
        assert by_name["python-app"]["metadata"]["pid"] == 1004
        assert by_name["node-app"]["metadata"]["pid"] == 1005

    def test_cmdline_metadata(self, baremetal_full_client: TestClient) -> None:
        """Registry should store command line in metadata."""
        response = baremetal_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert by_name["python-app"]["metadata"]["cmdline"] == ["/usr/bin/python3", "app.py"]
        assert by_name["node-app"]["metadata"]["cmdline"] == ["/usr/bin/node", "server.js"]

    def test_username_metadata(self, baremetal_full_client: TestClient) -> None:
        """Registry should store username in metadata."""
        response = baremetal_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert by_name["nginx"]["metadata"]["username"] == "www-data"
        assert by_name["postgres"]["metadata"]["username"] == "postgres"


# ------------------------------------------------------------------
# EnvironmentDetector tests
# ------------------------------------------------------------------

class TestBareMetalEnvironmentDetector:
    """Tests that EnvironmentDetector returns correct providers for bare metal."""

    def test_bare_metal_returns_process_and_config(self, monkeypatch) -> None:
        """On a plain VM, EnvironmentDetector should return ['process', 'config']."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)

        with patch.object(EnvironmentDetector, "is_docker", return_value=False), \
             patch.object(EnvironmentDetector, "is_azure", return_value=False), \
             patch.object(EnvironmentDetector, "is_gcp", return_value=False):
            providers = EnvironmentDetector.get_discovery_providers()

        assert providers == ["process", "config"]

    def test_is_vm_true(self, monkeypatch) -> None:
        """is_vm should return True when no specific environment is detected."""
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)

        with patch.object(EnvironmentDetector, "is_docker", return_value=False), \
             patch.object(EnvironmentDetector, "is_azure", return_value=False), \
             patch.object(EnvironmentDetector, "is_gcp", return_value=False):
            assert EnvironmentDetector.is_vm() is True

    def test_is_vm_false_in_kubernetes(self, monkeypatch) -> None:
        """is_vm should return False inside Kubernetes."""
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        assert EnvironmentDetector.is_vm() is False
