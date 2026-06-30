"""Integration tests for mixed / hybrid discovery environments.

Simulates a realistic dev environment where Docker Desktop runs both
standalone containers and a Kubernetes cluster, plus local processes.
Verifies that the DiscoveryEngine deduplicates and merges correctly.
"""
from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.discovery.engine import DiscoveryEngine
from app.discovery.providers.docker import DockerDiscoveryProvider
from app.discovery.providers.kubernetes import KubernetesDiscoveryProvider
from app.discovery.providers.process import ProcessDiscoveryProvider
from app.discovery.registry import ServiceRegistry
from app.main import app as fastapi_app
from tests.integration.docker_mocks import (
    build_mock_docker_client,
    make_all_containers,
    make_nginx_container,
    make_postgres_container,
    make_redis_container,
)
from tests.integration.test_discovery_baremetal import (
    make_nginx_process,
    make_postgres_process,
    make_redis_process,
)
from tests.integration.test_discovery_kubernetes import (
    FakeContainerPort,
    FakeContainerSpec,
    FakeMetadata,
    FakePod,
    FakePodList,
    FakePodSpec,
    FakePodStatus,
    make_api_pod,
    make_database_pod,
    make_frontend_pod,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_all_providers():
    """Context manager that patches Docker, K8s, and psutil simultaneously."""
    # Docker mocks
    docker_containers = make_all_containers()
    docker_client = build_mock_docker_client(docker_containers)

    # K8s mocks
    k8s_pods = [make_frontend_pod(), make_api_pod(), make_database_pod()]
    k8s_v1 = MagicMock()
    k8s_v1.list_pod_for_all_namespaces = MagicMock(return_value=FakePodList(k8s_pods))

    # psutil mocks
    psutil_procs = [make_nginx_process(), make_postgres_process(), make_redis_process()]

    with patch("docker.from_env", return_value=docker_client), \
         patch("kubernetes.config.load_config"), \
         patch("kubernetes.client.CoreV1Api", return_value=k8s_v1), \
         patch("app.discovery.providers.process.psutil") as mock_psutil:
        mock_psutil.process_iter = MagicMock(return_value=psutil_procs)
        mock_psutil.CONN_LISTEN = "LISTEN"
        yield {
            "docker": docker_client,
            "k8s": k8s_v1,
            "psutil": mock_psutil,
        }


@pytest.fixture
def mixed_full_client(
    mock_all_providers,
    registry: ServiceRegistry,
    discovery_engine: DiscoveryEngine,
    docker_provider: DockerDiscoveryProvider,
    k8s_provider: KubernetesDiscoveryProvider,
    process_provider: ProcessDiscoveryProvider,
) -> TestClient:
    """Full integration fixture with all three providers active."""
    discovery_engine.register_provider(docker_provider)
    discovery_engine.register_provider(k8s_provider)
    discovery_engine.register_provider(process_provider)
    asyncio.run(discovery_engine.run_discovery())

    with TestClient(fastapi_app) as client:
        client.headers.update({"X-API-Key": "sf-test-key"})
        yield client


# ------------------------------------------------------------------
# Mixed discovery tests
# ------------------------------------------------------------------

class TestMixedDiscovery:
    """Tests for simultaneous discovery across Docker, K8s, and bare metal."""

    def test_all_providers_active(self, mixed_full_client: TestClient) -> None:
        """When all three providers are active, services from all should be discovered."""
        response = mixed_full_client.get("/services/discovered")
        assert response.status_code == 200
        services = response.json()

        # Docker: 5 services (nginx, postgres, redis, python-api, nodejs-api)
        # K8s: 3 services (frontend, api, database)
        # Process: 3 services (nginx 0.0.0.0, postgres 127.0.0.1, redis 0.0.0.0)
        # All process hosts differ from Docker hosts, so no deduplication occurs.
        # Total unique: 5 Docker + 3 K8s + 3 Process = 11
        names = {s["service_name"] for s in services}

        # Docker names
        assert "test-nginx-1" in names
        assert "test-postgres-1" in names
        assert "test-redis-1" in names
        assert "test-python-api-1" in names
        assert "test-nodejs-api-1" in names

        # K8s names
        assert "frontend" in names
        assert "api" in names
        assert "database" in names

        # Process names
        assert "nginx" in names
        assert "postgres" in names
        assert "redis" in names

        # Verify total count (11 unique services)
        assert len(services) == 11

    def test_deduplication_by_name_and_host(self, mixed_full_client: TestClient) -> None:
        """Services with the same (service_name, host) should be deduplicated."""
        response = mixed_full_client.get("/services/discovered")
        services = response.json()

        # Docker nginx uses host from endpoint (172.18.0.2)
        # Process nginx uses host 0.0.0.0
        # K8s frontend uses host 10.0.1.10
        # All have different hosts, so they should all be present
        # But Docker postgres (172.18.0.3) and process postgres (127.0.0.1)
        # also have different hosts

        # Check that no duplicate (name, host) pairs exist
        keys = {(s["service_name"], s["host"]) for s in services}
        assert len(keys) == len(services), "Each (name, host) pair should be unique"

    def test_discovery_source_field(self, mixed_full_client: TestClient) -> None:
        """discovery_source should reflect the provider that discovered each service."""
        response = mixed_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        # Docker-discovered services
        assert by_name["test-nginx-1"]["discovery_source"] == "docker"
        assert by_name["test-postgres-1"]["discovery_source"] == "docker"
        assert by_name["test-redis-1"]["discovery_source"] == "docker"

        # K8s-discovered services
        assert by_name["frontend"]["discovery_source"] == "kubernetes"
        assert by_name["api"]["discovery_source"] == "kubernetes"
        assert by_name["database"]["discovery_source"] == "kubernetes"


class TestMixedDeduplication:
    """Tests for deduplication when the same service is found by multiple providers."""

    def test_same_service_docker_and_process(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
    ) -> None:
        """If Docker and process both discover the same (name, host), only one entry."""
        # Create a Docker container and a process with the same name and host
        docker_container = make_nginx_container()
        # Force the Docker container to use 127.0.0.1 as host so it matches the process
        docker_container.attrs["NetworkSettings"]["Ports"]["80/tcp"][0]["HostIp"] = "127.0.0.1"
        # Add an 'app' label so Docker provider derives the same service name as process
        docker_container.attrs["Config"]["Labels"]["app"] = "nginx"

        docker_client = build_mock_docker_client([docker_container])
        process = make_nginx_process()
        # Force process to use same host
        process.connections = MagicMock(return_value=[
            MagicMock(status="LISTEN", laddr=MagicMock(ip="127.0.0.1", port=80))
        ])

        with patch("docker.from_env", return_value=docker_client), \
             patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.process_iter = MagicMock(return_value=[process])
            mock_psutil.CONN_LISTEN = "LISTEN"

            discovery_engine.register_provider(DockerDiscoveryProvider())
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            result = asyncio.run(discovery_engine.run_discovery())

        # Should only get 1 service (deduplicated)
        names = [s.service_name for s in result]
        assert names.count("nginx") == 1

        # Verify registry has only 1 entry
        registry_services = registry.list_services(active_only=True)
        assert len(registry_services) == 1
        # The last provider wins for discovery_source (process in this case because
        # it runs after Docker in the engine)
        assert registry_services[0].discovery_source in ("docker", "process")

    def test_merged_metadata_on_update(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
    ) -> None:
        """When a service is re-discovered, metadata should be updated."""
        # First discovery: Docker container
        docker_container = make_postgres_container()
        docker_container.attrs["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] = "127.0.0.1"
        # Remove pid from Docker metadata so we can verify it comes from process later
        docker_container.attrs["State"].pop("Pid", None)
        docker_client = build_mock_docker_client([docker_container])

        with patch("docker.from_env", return_value=docker_client):
            discovery_engine.register_provider(DockerDiscoveryProvider())
            asyncio.run(discovery_engine.run_discovery())

        services = registry.list_services(active_only=True)
        assert len(services) == 1
        assert services[0].metadata.get("container_id") == "pg5678"
        assert "pid" not in services[0].metadata

        # Second discovery: same service via process provider with additional metadata
        process = make_postgres_process()
        # Force the process provider to derive the same service name as Docker
        process.info["name"] = "test-postgres-1"
        process.connections = MagicMock(return_value=[
            MagicMock(status="LISTEN", laddr=MagicMock(ip="127.0.0.1", port=5432))
        ])

        with patch("app.discovery.providers.process.psutil") as mock_psutil, \
             patch("app.discovery.providers.process._get_service_name_from_exe", return_value="test-postgres-1"):
            mock_psutil.process_iter = MagicMock(return_value=[process])
            mock_psutil.CONN_LISTEN = "LISTEN"
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            asyncio.run(discovery_engine.run_discovery())

        # Should still be 1 service, but metadata updated
        services = registry.list_services(active_only=True)
        assert len(services) == 1
        # The registry updates existing records, so metadata from the latest discovery wins
        assert services[0].metadata.get("pid") == 1002
        # discovery_source is updated to the latest provider
        assert services[0].discovery_source == "process"

    def test_different_hosts_are_separate_services(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
    ) -> None:
        """Same service name but different hosts should be separate entries."""
        # Docker container on 172.18.0.3
        docker_container = make_postgres_container()
        docker_client = build_mock_docker_client([docker_container])

        # Process on 127.0.0.1 (different host)
        process = make_postgres_process()
        process.connections = MagicMock(return_value=[
            MagicMock(status="LISTEN", laddr=MagicMock(ip="127.0.0.1", port=5432))
        ])

        with patch("docker.from_env", return_value=docker_client), \
             patch("app.discovery.providers.process.psutil") as mock_psutil:
            mock_psutil.process_iter = MagicMock(return_value=[process])
            mock_psutil.CONN_LISTEN = "LISTEN"

            discovery_engine.register_provider(DockerDiscoveryProvider())
            discovery_engine.register_provider(ProcessDiscoveryProvider())
            asyncio.run(discovery_engine.run_discovery())

        services = registry.list_services(active_only=True)
        assert len(services) == 2
        hosts = {s.host for s in services}
        assert hosts == {"172.18.0.3", "127.0.0.1"}
