"""Tests for the DockerDiscoveryProvider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.discovery.models import DiscoveredService
from app.discovery.providers.docker import DockerDiscoveryProvider, _clean_container_name, _get_service_type_from_image, _build_endpoints_from_ports


@pytest.fixture
def provider():
    return DockerDiscoveryProvider()


# ------------------------------------------------------------------
# Helper function tests
# ------------------------------------------------------------------

def test_clean_container_name():
    assert _clean_container_name("/myapp_1") == "myapp"
    assert _clean_container_name("myapp_1") == "myapp"
    assert _clean_container_name("myapp_12") == "myapp"
    assert _clean_container_name("myapp") == "myapp"
    assert _clean_container_name("/redis") == "redis"


def test_get_service_type_from_image():
    assert _get_service_type_from_image("postgres:15") == "database"
    assert _get_service_type_from_image("redis:latest") == "cache"
    assert _get_service_type_from_image("nginx:alpine") == "web"
    assert _get_service_type_from_image("node:18") == "api"
    assert _get_service_type_from_image("my-custom-app") is None


def test_build_endpoints_from_ports():
    ports = {
        "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
        "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}],
    }
    endpoints = _build_endpoints_from_ports(ports)
    assert "tcp://0.0.0.0:8080" in endpoints
    assert "tcp://127.0.0.1:5432" in endpoints
    assert len(endpoints) == 2


def test_build_endpoints_from_ports_empty_bindings():
    ports = {
        "8080/tcp": None,
        "5432/tcp": [],
    }
    endpoints = _build_endpoints_from_ports(ports)
    assert endpoints == []


# ------------------------------------------------------------------
# Health check tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_ok(provider):
    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.ping = MagicMock(return_value=True)
        mock_docker.from_env = MagicMock(return_value=mock_client)
        result = await provider.health_check()
        assert result is True


@pytest.mark.asyncio
async def test_health_check_ping_false(provider):
    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.ping = MagicMock(return_value=False)
        mock_docker.from_env = MagicMock(return_value=mock_client)
        result = await provider.health_check()
        assert result is False


@pytest.mark.asyncio
async def test_health_check_docker_exception(provider):
    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_docker.from_env = MagicMock(side_effect=Exception("docker not found"))
        result = await provider.health_check()
        assert result is False


# ------------------------------------------------------------------
# Mock container builders
# ------------------------------------------------------------------

def _make_mock_container(name, image_name, short_id, status, ports, networks=None, labels=None, cmd=None, created="2024-01-01T00:00:00Z"):
    container = MagicMock()
    container.name = name
    container.short_id = short_id
    container.status = status
    container.labels = labels or {}

    image = MagicMock()
    image.tags = [image_name] if image_name else []
    image.id = "sha256:abc123"
    container.image = image

    container.attrs = {
        "NetworkSettings": {
            "Ports": ports,
            "Networks": networks or {"bridge": {"IPAddress": "172.17.0.2"}},
        },
        "Config": {
            "Cmd": cmd or ["python", "app.py"],
        },
        "Created": created,
    }
    return container


# ------------------------------------------------------------------
# Discovery tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_single_container(provider):
    container = _make_mock_container(
        name="/myapp_1",
        image_name="node:18",
        short_id="abc123def456",
        status="running",
        ports={"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    svc = result[0]
    assert isinstance(svc, DiscoveredService)
    assert svc.service_name == "myapp"  # cleaned name
    assert svc.service_type == "api"  # from image "node"
    assert svc.endpoints == ["tcp://0.0.0.0:8080"]
    assert svc.host == "0.0.0.0"
    assert svc.discovery_source == "docker"
    assert svc.metadata["container_id"] == "abc123def456"
    assert svc.metadata["image"] == "node:18"
    assert svc.metadata["status"] == "running"
    assert svc.metadata["labels"] == {}
    assert svc.metadata["networks"] == ["bridge"]
    assert svc.metadata["command"] == ["python", "app.py"]
    assert svc.metadata["created_at"] == "2024-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_discover_label_based_naming(provider):
    container = _make_mock_container(
        name="/random_123",
        image_name="postgres:15",
        short_id="pg123",
        status="running",
        ports={"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]},
        labels={"app": "billing-db"},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    assert result[0].service_name == "billing-db"  # from label, not container name
    assert result[0].service_type == "database"  # from postgres image


@pytest.mark.asyncio
async def test_discover_service_name_label(provider):
    container = _make_mock_container(
        name="/redis_1",
        image_name="redis:latest",
        short_id="r123",
        status="running",
        ports={"6379/tcp": [{"HostIp": "127.0.0.1", "HostPort": "6379"}]},
        labels={"service.name": "session-cache"},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    assert result[0].service_name == "session-cache"  # from service.name label


@pytest.mark.asyncio
async def test_discover_multiple_containers(provider):
    c1 = _make_mock_container(
        name="/web_1", image_name="nginx:alpine", short_id="w1", status="running",
        ports={"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}]},
    )
    c2 = _make_mock_container(
        name="/api_1", image_name="python:3.11", short_id="a1", status="running",
        ports={"5000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5000"}]},
    )
    c3 = _make_mock_container(
        name="/db_1", image_name="postgres:15", short_id="d1", status="running",
        ports={"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[c1, c2, c3])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 3
    names = {svc.service_name for svc in result}
    assert names == {"web", "api", "db"}

    types = {svc.service_type for svc in result}
    assert types == {"web", "api", "database"}


@pytest.mark.asyncio
async def test_discover_deduplicates(provider):
    """Containers with same name and host should be deduplicated."""
    c1 = _make_mock_container(
        name="/myapp_1", image_name="node:18", short_id="a", status="running",
        ports={"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
    )
    c2 = _make_mock_container(
        name="/myapp_2", image_name="node:18", short_id="b", status="running",
        ports={"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[c1, c2])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    # Both have same cleaned name "myapp" and same host "127.0.0.1"
    assert len(result) == 1
    assert result[0].service_name == "myapp"


@pytest.mark.asyncio
async def test_discover_no_docker_running(provider):
    """If Docker is not running, return empty list."""
    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception
        mock_docker.from_env = MagicMock(side_effect=mock_docker.errors.DockerException("Docker not running"))
        result = await provider.discover()

    assert result == []


@pytest.mark.asyncio
async def test_discover_no_bindings_fallback(provider):
    """If no host bindings, fall back to exposed port numbers."""
    container = _make_mock_container(
        name="/cache_1",
        image_name="redis:latest",
        short_id="c1",
        status="running",
        ports={"6379/tcp": None},  # No host bindings
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    assert result[0].endpoints == ["tcp://127.0.0.1:6379"]


@pytest.mark.asyncio
async def test_discover_no_ports_uses_network_ip(provider):
    """If no ports at all, use container IP from network."""
    container = _make_mock_container(
        name="/worker_1",
        image_name="my-custom-image:latest",
        short_id="w1",
        status="running",
        ports={},
        networks={"mynet": {"IPAddress": "10.0.0.5"}},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    assert result[0].endpoints == ["tcp://10.0.0.5:0"]
    assert result[0].host == "10.0.0.5"


@pytest.mark.asyncio
async def test_discover_infer_type_from_port_fallback(provider):
    """If image name doesn't match known types, infer from port numbers."""
    container = _make_mock_container(
        name="/app_1",
        image_name="custom/api-server:latest",
        short_id="a1",
        status="running",
        ports={"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    assert result[0].service_type == "api"  # inferred from port 8080


@pytest.mark.asyncio
async def test_discover_unknown_type(provider):
    """If neither image nor port matches, type is unknown."""
    container = _make_mock_container(
        name="/app_1",
        image_name="custom/unknown",
        short_id="a1",
        status="running",
        ports={"12345/tcp": [{"HostIp": "127.0.0.1", "HostPort": "12345"}]},
    )

    with patch("app.discovery.providers.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_client.containers.list = MagicMock(return_value=[container])
        mock_docker.from_env = MagicMock(return_value=mock_client)
        mock_docker.errors = MagicMock()
        mock_docker.errors.DockerException = Exception

        result = await provider.discover()

    assert len(result) == 1
    assert result[0].service_type == "unknown"


@pytest.mark.asyncio
async def test_discover_no_docker_installed(provider):
    """If docker SDK is not installed, return empty list."""
    with patch("app.discovery.providers.docker.docker", side_effect=ImportError("no docker")):
        result = await provider.discover()
    assert result == []
