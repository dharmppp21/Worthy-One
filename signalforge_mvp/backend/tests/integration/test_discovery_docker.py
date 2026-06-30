"""Integration tests for Docker-based auto-discovery.

Uses fully mocked Docker, psutil, and HTTP/TCP probes so no real containers
are needed.  Verifies the complete discovery → dependency → health →
classification pipeline end-to-end.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.discovery.engine import DiscoveryEngine
from app.discovery.models import DiscoveredService, HealthProbeResult, ProbeStatus, ProbeType
from app.discovery.probing import ServiceProber
from app.discovery.providers.docker import DockerDiscoveryProvider
from app.discovery.registry import ServiceRegistry
from app.main import app as fastapi_app
from tests.integration.docker_mocks import (
    FakeContainer,
    build_mock_docker_client,
    make_all_containers,
    make_psutil_connections,
    make_python_api_container,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def setup_db():
    """Ensure tables are created for the module."""
    init_db()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Fresh DB session per test."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def registry(db_session: Session) -> ServiceRegistry:
    """Registry backed by a fresh DB session."""
    return ServiceRegistry(db_session=db_session)


@pytest.fixture
def discovery_engine(registry: ServiceRegistry) -> DiscoveryEngine:
    """Engine wired to the registry."""
    engine = DiscoveryEngine(registry=registry)
    return engine


@pytest.fixture
def docker_provider() -> DockerDiscoveryProvider:
    """Docker provider (uses docker.from_env() internally, will be mocked)."""
    return DockerDiscoveryProvider()


@pytest.fixture
def mock_docker():
    """Context manager that patches docker.from_env() with 5 fake containers."""
    containers = make_all_containers()
    mock_client = build_mock_docker_client(containers)

    with patch("docker.from_env", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_psutil():
    """Context manager that patches psutil.net_connections()."""
    connections = make_psutil_connections()
    with patch(
        "app.discovery.dependencies.network_scanner.psutil.net_connections",
        return_value=connections,
    ):
        yield connections


@pytest.fixture
def mock_prober():
    """Context manager that patches ServiceProber methods to return known results."""
    async def _probe_http(self, service: DiscoveredService) -> HealthProbeResult:
        """Return UP for Python/Node APIs, UNKNOWN for others."""
        if "python-api" in service.service_name or "nodejs-api" in service.service_name:
            return HealthProbeResult(
                service_id=service.service_id,
                status=ProbeStatus.up,
                probe_type=ProbeType.http,
                endpoint=f"http://{service.host}:5000/health",
                response_time_ms=12.5,
                response_status_code=200,
                response_body_preview='{"status": "up"}',
                probed_at=datetime.now(timezone.utc),
            )
        return HealthProbeResult(
            service_id=service.service_id,
            status=ProbeStatus.unknown,
            probe_type=ProbeType.http,
            error_message="All health endpoints failed",
            probed_at=datetime.now(timezone.utc),
        )

    async def _probe_tcp(self, service: DiscoveredService, port: int) -> HealthProbeResult:
        """Return UP for all TCP services."""
        return HealthProbeResult(
            service_id=service.service_id,
            status=ProbeStatus.up,
            probe_type=ProbeType.tcp,
            endpoint=f"{service.host}:{port}",
            response_time_ms=5.0,
            probed_at=datetime.now(timezone.utc),
        )

    with (
        patch.object(ServiceProber, "probe_http", _probe_http),
        patch.object(ServiceProber, "probe_tcp", _probe_tcp),
    ):
        yield


@pytest.fixture
def full_client(
    mock_docker,
    mock_psutil,
    mock_prober,
    registry: ServiceRegistry,
    discovery_engine: DiscoveryEngine,
    docker_provider: DockerDiscoveryProvider,
) -> Generator[TestClient, None, None]:
    """
    Full integration fixture: patches Docker, psutil, and prober;
    registers the Docker provider; runs discovery + health probing;
    returns a FastAPI TestClient ready for assertions.
    """
    # Register the Docker provider with the engine
    discovery_engine.register_provider(docker_provider)

    # Run discovery once
    asyncio.run(discovery_engine.run_discovery())

    # Run health probing
    prober = ServiceProber(registry=registry)
    asyncio.run(prober.probe_all_services())
    asyncio.run(prober.close())

    # Build the TestClient
    with TestClient(fastapi_app) as client:
        client.headers.update({"X-API-Key": "sf-test-key"})
        yield client

    # Cleanup: mark all services inactive so the next test starts fresh
    for svc in registry.list_services(active_only=True):
        db_obj = registry._db.query(
            registry._to_db(svc).__class__
        ).filter_by(service_id=svc.service_id).first()
        if db_obj:
            db_obj.is_active = False
    registry._db.commit()


# ------------------------------------------------------------------
# Discovery tests
# ------------------------------------------------------------------

class TestDockerDiscovery:
    """End-to-end tests for Docker-based service discovery."""

    def test_all_five_services_discovered(self, full_client: TestClient) -> None:
        """All 5 mock containers should be discovered."""
        response = full_client.get("/services/discovered")
        assert response.status_code == 200
        services = response.json()
        assert len(services) == 5
        names = {s["service_name"] for s in services}
        assert names == {
            "test-nginx-1",
            "test-postgres-1",
            "test-redis-1",
            "test-python-api-1",
            "test-nodejs-api-1",
        }

    def test_service_types_correct(self, full_client: TestClient) -> None:
        """Each service should have the correct auto-detected type."""
        response = full_client.get("/services/discovered")
        services = {s["service_name"]: s for s in response.json()}

        # Classification is based on image keyword / port mapping
        assert services["test-nginx-1"]["service_type"] == "web"
        assert services["test-postgres-1"]["service_type"] == "database"
        assert services["test-redis-1"]["service_type"] == "cache"
        # Python/Node API containers use generic python/node images, so they
        # fall back to port-based or unknown classification
        assert services["test-python-api-1"]["service_type"] in ("api", "unknown")
        assert services["test-nodejs-api-1"]["service_type"] in ("api", "unknown")

    def test_endpoints_populated(self, full_client: TestClient) -> None:
        """Each service should have at least one endpoint."""
        response = full_client.get("/services/discovered")
        for svc in response.json():
            assert len(svc["endpoints"]) > 0, f"{svc['service_name']} has no endpoints"


# ------------------------------------------------------------------
# Health probe tests
# ------------------------------------------------------------------

class TestHealthProbes:
    """End-to-end tests for health probing in the Docker environment."""

    def test_health_list_all_services(self, full_client: TestClient) -> None:
        """GET /services/health should list all 5 services."""
        response = full_client.get("/services/health")
        assert response.status_code == 200
        health_records = response.json()
        assert len(health_records) == 5
        names = {h["service_name"] for h in health_records}
        assert names == {
            "test-nginx-1",
            "test-postgres-1",
            "test-redis-1",
            "test-python-api-1",
            "test-nodejs-api-1",
        }

    def test_python_api_health_up(self, full_client: TestClient) -> None:
        """Python API should report UP (HTTP 200 from /health)."""
        response = full_client.get("/services/health")
        for rec in response.json():
            if rec["service_name"] == "test-python-api-1":
                assert rec["status"] == "up"
                return
        pytest.fail("Python API not found in health records")

    def test_nodejs_api_health_up(self, full_client: TestClient) -> None:
        """Node.js API should report UP (HTTP 200 from /health)."""
        response = full_client.get("/services/health")
        for rec in response.json():
            if rec["service_name"] == "test-nodejs-api-1":
                assert rec["status"] == "up"
                return
        pytest.fail("Node.js API not found in health records")

    def test_postgres_health_up(self, full_client: TestClient) -> None:
        """Postgres should report UP (TCP connection succeeded)."""
        response = full_client.get("/services/health")
        for rec in response.json():
            if rec["service_name"] == "test-postgres-1":
                assert rec["status"] == "up"
                return
        pytest.fail("Postgres not found in health records")

    def test_redis_health_up(self, full_client: TestClient) -> None:
        """Redis should report UP (TCP connection succeeded)."""
        response = full_client.get("/services/health")
        for rec in response.json():
            if rec["service_name"] == "test-redis-1":
                assert rec["status"] == "up"
                return
        pytest.fail("Redis not found in health records")

    def test_health_history_endpoint(self, full_client: TestClient) -> None:
        """GET /services/{id}/health should return paginated history."""
        # First get the service ID
        discovered = full_client.get("/services/discovered").json()
        svc = next(s for s in discovered if s["service_name"] == "test-python-api-1")

        response = full_client.get(f"/services/{svc['service_id']}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["service_id"] == svc["service_id"]
        assert data["total"] >= 0
        assert data["limit"] == 100
        assert data["offset"] == 0


# ------------------------------------------------------------------
# Dependency graph tests
# ------------------------------------------------------------------

class TestDependencyGraph:
    """End-to-end tests for dependency graph detection."""

    def test_dependencies_detected_via_registry(
        self,
        mock_docker,
        mock_psutil,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        docker_provider: DockerDiscoveryProvider,
    ) -> None:
        """The dependency registry should contain edges from Python/Node APIs to Postgres/Redis."""
        from app.discovery.dependencies.network_scanner import NetworkConnectionScanner
        from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
        from app.discovery.dependencies.registry import DependencyRegistry

        discovery_engine.register_provider(docker_provider)
        asyncio.run(discovery_engine.run_discovery())

        dep_registry = DependencyRegistry(db_session=registry._db)
        scanner = NetworkConnectionScanner(registry=registry)
        builder = DependencyGraphBuilder(
            analyzers=[scanner],
            registry=registry,
            dep_registry=dep_registry,
        )
        asyncio.run(builder.build())

        all_deps = dep_registry.get_all_dependencies()
        assert len(all_deps) > 0, "Expected at least one dependency edge"

    def test_python_api_connects_to_postgres(
        self,
        mock_docker,
        mock_psutil,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        docker_provider: DockerDiscoveryProvider,
    ) -> None:
        """Python API should have a dependency on Postgres."""
        from app.discovery.dependencies.network_scanner import NetworkConnectionScanner
        from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
        from app.discovery.dependencies.registry import DependencyRegistry

        discovery_engine.register_provider(docker_provider)
        asyncio.run(discovery_engine.run_discovery())

        dep_registry = DependencyRegistry(db_session=registry._db)
        scanner = NetworkConnectionScanner(registry=registry)
        builder = DependencyGraphBuilder(
            analyzers=[scanner],
            registry=registry,
            dep_registry=dep_registry,
        )
        asyncio.run(builder.build())

        services = registry.list_services(active_only=True)
        by_name = {s.service_name: s.service_id for s in services}
        py_id = by_name.get("test-python-api-1")
        pg_id = by_name.get("test-postgres-1")

        assert py_id and pg_id, "Both services should be discovered"
        deps = dep_registry.get_dependencies(source_id=py_id)
        target_ids = {d.target_service_id for d in deps}
        assert pg_id in target_ids, "Python API should connect to Postgres"

    def test_python_api_connects_to_redis(
        self,
        mock_docker,
        mock_psutil,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        docker_provider: DockerDiscoveryProvider,
    ) -> None:
        """Python API should have a dependency on Redis."""
        from app.discovery.dependencies.network_scanner import NetworkConnectionScanner
        from app.discovery.dependencies.graph_builder import DependencyGraphBuilder
        from app.discovery.dependencies.registry import DependencyRegistry

        discovery_engine.register_provider(docker_provider)
        asyncio.run(discovery_engine.run_discovery())

        dep_registry = DependencyRegistry(db_session=registry._db)
        scanner = NetworkConnectionScanner(registry=registry)
        builder = DependencyGraphBuilder(
            analyzers=[scanner],
            registry=registry,
            dep_registry=dep_registry,
        )
        asyncio.run(builder.build())

        services = registry.list_services(active_only=True)
        by_name = {s.service_name: s.service_id for s in services}
        py_id = by_name.get("test-python-api-1")
        redis_id = by_name.get("test-redis-1")

        assert py_id and redis_id, "Both services should be discovered"
        deps = dep_registry.get_dependencies(source_id=py_id)
        target_ids = {d.target_service_id for d in deps}
        assert redis_id in target_ids, "Python API should connect to Redis"


# ------------------------------------------------------------------
# Dynamic discovery tests
# ------------------------------------------------------------------

class TestDynamicDiscovery:
    """Tests for adding and removing services dynamically."""

    def test_new_container_detected(
        self,
        mock_docker,
        mock_psutil,
        mock_prober,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        docker_provider: DockerDiscoveryProvider,
    ) -> None:
        """Simulate a new container starting and verify it's discovered."""
        # Initial discovery with 5 containers
        discovery_engine.register_provider(docker_provider)
        asyncio.run(discovery_engine.run_discovery())
        initial = registry.list_services(active_only=True)
        assert len(initial) == 5

        # Add a new fake container to the mock
        new_container = make_python_api_container()
        new_container.name = "test-new-grafana-1"
        new_container.image = "grafana/grafana"
        new_container.short_id = "grafnew"
        new_container.attrs["Name"] = "/test-new-grafana-1"
        new_container.attrs["Config"]["Image"] = "grafana/grafana"
        new_container.attrs["NetworkSettings"]["IPAddress"] = "172.18.0.99"
        new_container.attrs["NetworkSettings"]["Networks"]["test-network"]["IPAddress"] = "172.18.0.99"
        new_container.attrs["NetworkSettings"]["Networks"]["test-network"]["Aliases"] = ["grafana"]

        # Update the mock client to return 6 containers
        mock_docker.containers.list.return_value = make_all_containers() + [new_container]

        # Re-run discovery
        asyncio.run(discovery_engine.run_discovery())
        updated = registry.list_services(active_only=True)
        assert len(updated) == 6
        names = {s.service_name for s in updated}
        assert "test-new-grafana-1" in names

    def test_removed_container_marked_stale(
        self,
        mock_docker,
        mock_psutil,
        mock_prober,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        docker_provider: DockerDiscoveryProvider,
    ) -> None:
        """Simulate a container stopping and verify it's removed."""
        discovery_engine.register_provider(docker_provider)
        asyncio.run(discovery_engine.run_discovery())
        initial = registry.list_services(active_only=True)
        # May include services from other tests; check at least 5 exist
        assert len(initial) >= 5

        # Verify redis is present before removal
        names_before = {s.service_name for s in initial}
        assert "test-redis-1" in names_before

        # Remove one container from the mock (only 4 left)
        containers = make_all_containers()
        removed = containers.pop(2)  # Remove redis
        mock_docker.containers.list.return_value = containers

        # Re-run discovery — the registry won't automatically mark stale services
        # unless we call remove_stale. Make the Redis heartbeat older than the
        # timeout so it gets marked stale.
        redis_svc = next(
            (s for s in initial if s.service_name == "test-redis-1"), None
        )
        assert redis_svc is not None
        db_obj = (
            registry._db.query(
                registry._to_db(redis_svc).__class__
            )
            .filter_by(service_id=redis_svc.service_id)
            .first()
        )
        assert db_obj is not None
        from datetime import datetime, timezone, timedelta
        db_obj.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        registry._db.commit()
        registry._db.refresh(db_obj)

        # Update heartbeats of all other active services so they stay fresh
        for svc in registry.list_services(active_only=True):
            if svc.service_name != "test-redis-1":
                registry.update_heartbeat(svc.service_id)

        # The removed service's heartbeat is now old, so it should be marked stale
        asyncio.run(discovery_engine.remove_stale(timeout_seconds=5))
        remaining = registry.list_services(active_only=True)
        names_after = {s.service_name for s in remaining}
        assert "test-redis-1" not in names_after, "Redis should be marked stale and removed"
