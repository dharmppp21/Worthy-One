"""Tests for the ProcessDiscoveryProvider."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.discovery.models import DiscoveredService
from app.discovery.providers.process import ProcessDiscoveryProvider, _is_system_process, _get_service_name_from_exe, _get_service_type_from_ports


@pytest.fixture
def provider():
    return ProcessDiscoveryProvider()


# ------------------------------------------------------------------
# Helper function tests
# ------------------------------------------------------------------

def test_is_system_process():
    assert _is_system_process("svchost.exe") is True
    assert _is_system_process("svchost") is True
    assert _is_system_process("SYSTEM") is True
    assert _is_system_process("nginx") is False
    assert _is_system_process("python") is False


def test_get_service_name_from_exe():
    assert _get_service_name_from_exe("/usr/sbin/nginx", "nginx") == "nginx"
    assert _get_service_name_from_exe("/usr/bin/python3.11", "python") == "python-app"
    assert _get_service_name_from_exe("C:\\Program Files\\nginx\\nginx.exe", "nginx") == "nginx"
    assert _get_service_name_from_exe(None, "myapp") == "myapp"


def test_get_service_type_from_ports():
    assert _get_service_type_from_ports([80]) == "web"
    assert _get_service_type_from_ports([5432]) == "database"
    assert _get_service_type_from_ports([6379]) == "cache"
    assert _get_service_type_from_ports([9092]) == "message_queue"
    assert _get_service_type_from_ports([8080]) == "api"
    assert _get_service_type_from_ports([99999]) == "unknown"


# ------------------------------------------------------------------
# Health check tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_ok(provider):
    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_iter = MagicMock()
        mock_iter.__iter__ = MagicMock(return_value=iter([MagicMock(info={"name": "test"})]))
        mock_psutil.process_iter = MagicMock(return_value=mock_iter)
        result = await provider.health_check()
        assert result is True


@pytest.mark.asyncio
async def test_health_check_import_error(provider):
    """If psutil is not available, health_check should return False."""
    with patch("app.discovery.providers.process.psutil", None):
        result = await provider.health_check()
        assert result is False


@pytest.mark.asyncio
async def test_health_check_permission_error(provider):
    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(side_effect=PermissionError("access denied"))
        result = await provider.health_check()
        assert result is False


# ------------------------------------------------------------------
# Discovery tests
# ------------------------------------------------------------------

def _make_mock_process(name, exe, pid, connections, username="root", create_time=None, cpu_percent=0.0, memory_percent=0.0):
    proc = MagicMock()
    proc.info = {
        "pid": pid,
        "name": name,
        "exe": exe,
        "cmdline": [exe, "--serve"],
        "username": username,
        "create_time": create_time or datetime.now(timezone.utc).timestamp(),
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
    }
    proc.connections = MagicMock(return_value=connections)
    return proc


def _make_mock_connection(ip, port, status="LISTEN"):
    conn = MagicMock()
    conn.status = status
    conn.laddr = MagicMock()
    conn.laddr.ip = ip
    conn.laddr.port = port
    return conn


@pytest.mark.asyncio
async def test_discover_single_process(provider):
    conn = _make_mock_connection("127.0.0.1", 8080)
    proc = _make_mock_process("python", "/usr/bin/python3", 1234, [conn])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 1
    svc = result[0]
    assert isinstance(svc, DiscoveredService)
    assert svc.service_name == "python-app"
    assert svc.service_type == "api"
    assert svc.endpoints == ["tcp://127.0.0.1:8080"]
    assert svc.host == "127.0.0.1"
    assert svc.discovery_source == "process"
    assert svc.metadata["pid"] == 1234
    assert svc.metadata["exe"] == "/usr/bin/python3"
    assert svc.metadata["username"] == "root"
    assert "create_time" in svc.metadata


@pytest.mark.asyncio
async def test_discover_multiple_ports(provider):
    conn1 = _make_mock_connection("0.0.0.0", 80)
    conn2 = _make_mock_connection("0.0.0.0", 443)
    proc = _make_mock_process("nginx", "/usr/sbin/nginx", 5678, [conn1, conn2])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 1
    svc = result[0]
    assert svc.service_name == "nginx"
    assert svc.service_type == "web"  # from port 80
    assert svc.endpoints == ["tcp://0.0.0.0:80", "tcp://0.0.0.0:443"]


@pytest.mark.asyncio
async def test_discover_multiple_ips_deterministic_host(provider):
    """A process bound to several IPs yields one service with a stable host.

    psutil does not order connections deterministically, so the provider must
    normalize the ordering; otherwise the registry accumulates duplicate entries
    for the same process across discovery runs.
    """
    # Connections supplied out of sorted order on purpose.
    conn1 = _make_mock_connection("::1", 8000)
    conn2 = _make_mock_connection("127.0.0.1", 8000)
    proc = _make_mock_process("python", "/usr/bin/python3", 4242, [conn1, conn2])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 1
    svc = result[0]
    # "127.0.0.1" sorts before "::1", so it is the canonical host regardless of
    # the order psutil happened to return the connections in.
    assert svc.host == "127.0.0.1"
    assert svc.endpoints == ["tcp://127.0.0.1:8000", "tcp://::1:8000"]


@pytest.mark.asyncio
async def test_discover_skips_non_listening(provider):
    conn = _make_mock_connection("127.0.0.1", 5432, status="ESTABLISHED")
    proc = _make_mock_process("postgres", "/usr/bin/postgres", 9999, [conn])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 0


@pytest.mark.asyncio
async def test_discover_skips_system_processes(provider):
    conn = _make_mock_connection("127.0.0.1", 12345)
    proc = _make_mock_process("svchost.exe", "C:\\Windows\\System32\\svchost.exe", 444, [conn])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 0


@pytest.mark.asyncio
async def test_discover_deduplicates(provider):
    conn1 = _make_mock_connection("127.0.0.1", 5432)
    conn2 = _make_mock_connection("127.0.0.1", 5432)
    proc = _make_mock_process("postgres", "/usr/bin/postgres", 1000, [conn1, conn2])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 1
    assert result[0].endpoints == ["tcp://127.0.0.1:5432"]


@pytest.mark.asyncio
async def test_discover_ignores_access_denied(provider):
    bad_proc = MagicMock()
    bad_proc.info = {"pid": 1, "name": "system", "exe": None}
    bad_proc.connections = MagicMock(side_effect=PermissionError("access denied"))

    good_conn = _make_mock_connection("127.0.0.1", 6379)
    good_proc = _make_mock_process("redis-server", "/usr/bin/redis-server", 2222, [good_conn])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[bad_proc, good_proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 1
    assert result[0].service_name == "redis"
    assert result[0].service_type == "cache"


@pytest.mark.asyncio
async def test_discover_no_listening_ports(provider):
    proc = _make_mock_process("python", "/usr/bin/python3", 5555, [])

    with patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=[proc])
        mock_psutil.CONN_LISTEN = "LISTEN"
        result = await provider.discover()

    assert len(result) == 0


@pytest.mark.asyncio
async def test_discover_maps_known_ports(provider):
    """Verify that all known port mappings produce the correct service_type."""
    test_cases = [
        (80, "web"), (443, "web"),
        (5432, "database"), (3306, "database"), (27017, "database"),
        (6379, "cache"), (11211, "cache"),
        (9092, "message_queue"),
        (8080, "api"), (3000, "api"), (5000, "api"), (8000, "api"),
        (9200, "search"), (5601, "dashboard"),
    ]

    for port, expected_type in test_cases:
        conn = _make_mock_connection("127.0.0.1", port)
        proc = _make_mock_process("myapp", "/usr/bin/myapp", 1000 + port, [conn])

        with patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.process_iter = MagicMock(return_value=[proc])
            mock_psutil.CONN_LISTEN = "LISTEN"
            result = await provider.discover()

        assert len(result) == 1, f"port {port}"
        assert result[0].service_type == expected_type, f"port {port} expected {expected_type}"


@pytest.mark.asyncio
async def test_discover_no_psutil(provider):
    """If psutil is not installed, return empty list."""
    with patch("app.discovery.providers.process.psutil", side_effect=ImportError("no psutil")):
        result = await provider.discover()
    assert result == []
