"""Integration tests for Kubernetes-based auto-discovery.

Uses fully mocked Kubernetes API so no real cluster is needed.  Verifies
the discovery pipeline end-to-end including namespace filtering, RBAC
handling, and dynamic add/remove.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.discovery.engine import DiscoveryEngine
from app.discovery.providers.kubernetes import KubernetesDiscoveryProvider
from app.discovery.registry import ServiceRegistry
from app.main import app as fastapi_app


# ------------------------------------------------------------------
# Fake Kubernetes objects
# ------------------------------------------------------------------

class FakeMetadata:
    """Mimics kubernetes.client.V1ObjectMeta."""

    def __init__(
        self,
        name: str,
        namespace: str = "default",
        labels: Optional[Dict[str, str]] = None,
        cluster_name: Optional[str] = None,
    ) -> None:
        self.name = name
        self.namespace = namespace
        self.labels = labels or {}
        self.cluster_name = cluster_name or "test-cluster"


class FakeContainerStatus:
    """Mimics kubernetes.client.V1ContainerStatus."""

    def __init__(self, restart_count: int = 0) -> None:
        self.restart_count = restart_count


class FakeContainerPort:
    """Mimics kubernetes.client.V1ContainerPort."""

    def __init__(self, container_port: int) -> None:
        self.container_port = container_port


class FakeContainerSpec:
    """Mimics kubernetes.client.V1Container."""

    def __init__(self, ports: Optional[List[FakeContainerPort]] = None) -> None:
        self.ports = ports or []


class FakePodStatus:
    """Mimics kubernetes.client.V1PodStatus."""

    def __init__(
        self,
        pod_ip: Optional[str] = None,
        phase: str = "Running",
        start_time: Optional[datetime] = None,
        container_statuses: Optional[List[FakeContainerStatus]] = None,
    ) -> None:
        self.pod_ip = pod_ip
        self.phase = phase
        self.start_time = start_time
        self.container_statuses = container_statuses or []


class FakePodSpec:
    """Mimics kubernetes.client.V1PodSpec."""

    def __init__(
        self,
        containers: Optional[List[FakeContainerSpec]] = None,
        node_name: Optional[str] = None,
    ) -> None:
        self.containers = containers or []
        self.node_name = node_name


class FakePod:
    """Mimics kubernetes.client.V1Pod."""

    def __init__(
        self,
        metadata: FakeMetadata,
        status: FakePodStatus,
        spec: FakePodSpec,
    ) -> None:
        self.metadata = metadata
        self.status = status
        self.spec = spec


class FakePodList:
    """Mimics the response from list_pod_for_all_namespaces / list_namespaced_pod."""

    def __init__(self, items: List[FakePod]) -> None:
        self.items = items


# ------------------------------------------------------------------
# Fake pod builders
# ------------------------------------------------------------------

def make_frontend_pod() -> FakePod:
    return FakePod(
        metadata=FakeMetadata(
            name="frontend-7d8f9b2c4-x1z2a",
            namespace="default",
            labels={"app": "frontend", "app.kubernetes.io/component": "frontend"},
        ),
        status=FakePodStatus(
            pod_ip="10.0.1.10",
            phase="Running",
            start_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            container_statuses=[FakeContainerStatus(restart_count=0)],
        ),
        spec=FakePodSpec(
            containers=[FakeContainerSpec(ports=[FakeContainerPort(80)])],
            node_name="node-1",
        ),
    )


def make_api_pod() -> FakePod:
    return FakePod(
        metadata=FakeMetadata(
            name="api-9a2b3c4d5-e6f7g",
            namespace="default",
            labels={"app": "api", "app.kubernetes.io/component": "api"},
        ),
        status=FakePodStatus(
            pod_ip="10.0.1.20",
            phase="Running",
            start_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            container_statuses=[FakeContainerStatus(restart_count=1)],
        ),
        spec=FakePodSpec(
            containers=[FakeContainerSpec(ports=[FakeContainerPort(8080)])],
            node_name="node-1",
        ),
    )


def make_database_pod() -> FakePod:
    return FakePod(
        metadata=FakeMetadata(
            name="database-1a2b3c4d5-e6f7g",
            namespace="default",
            labels={"app": "database", "app.kubernetes.io/component": "database"},
        ),
        status=FakePodStatus(
            pod_ip="10.0.1.30",
            phase="Running",
            start_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            container_statuses=[FakeContainerStatus(restart_count=0)],
        ),
        spec=FakePodSpec(
            containers=[FakeContainerSpec(ports=[FakeContainerPort(5432)])],
            node_name="node-1",
        ),
    )


def make_all_pods() -> List[FakePod]:
    return [make_frontend_pod(), make_api_pod(), make_database_pod()]


# ------------------------------------------------------------------
# Mock Kubernetes client builder
# ------------------------------------------------------------------

def build_mock_kubernetes(pods: List[FakePod]):
    """Return a context manager that patches kubernetes.config and kubernetes.client."""

    mock_v1 = MagicMock()
    mock_v1.list_pod_for_all_namespaces = MagicMock(return_value=FakePodList(pods))
    mock_v1.list_namespaced_pod = MagicMock(return_value=FakePodList(pods))

    def _make_core_v1_api():
        return mock_v1

    @patch("kubernetes.config.load_config")
    @patch("kubernetes.client.CoreV1Api", new=_make_core_v1_api)
    def _cm(func):
        return func()

    return mock_v1


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_kubernetes():
    """Context manager that patches the Kubernetes API with 3 fake pods."""
    pods = make_all_pods()
    mock_v1 = MagicMock()
    mock_v1.list_pod_for_all_namespaces = MagicMock(return_value=FakePodList(pods))
    mock_v1.list_namespaced_pod = MagicMock(return_value=FakePodList(pods))

    with patch("kubernetes.config.load_config"), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
        yield mock_v1


@pytest.fixture
def k8s_full_client(
    mock_kubernetes,
    registry: ServiceRegistry,
    discovery_engine: DiscoveryEngine,
    k8s_provider: KubernetesDiscoveryProvider,
) -> TestClient:
    """Full integration fixture: patches K8s, registers provider, runs discovery."""
    discovery_engine.register_provider(k8s_provider)
    asyncio.run(discovery_engine.run_discovery())

    with TestClient(fastapi_app) as client:
        client.headers.update({"X-API-Key": "sf-test-key"})
        yield client


# ------------------------------------------------------------------
# Discovery tests
# ------------------------------------------------------------------

class TestKubernetesDiscovery:
    """End-to-end tests for Kubernetes-based service discovery."""

    def test_all_three_services_discovered(self, k8s_full_client: TestClient) -> None:
        """All 3 mock pods should be discovered."""
        response = k8s_full_client.get("/services/discovered")
        assert response.status_code == 200
        services = response.json()
        assert len(services) == 3
        names = {s["service_name"] for s in services}
        assert names == {"frontend", "api", "database"}

    def test_service_types_correct(self, k8s_full_client: TestClient) -> None:
        """Each service should have the correct auto-detected type."""
        response = k8s_full_client.get("/services/discovered")
        services = {s["service_name"]: s for s in response.json()}

        assert services["frontend"]["service_type"] == "web"
        assert services["api"]["service_type"] == "api"
        assert services["database"]["service_type"] == "database"

    def test_endpoints_populated(self, k8s_full_client: TestClient) -> None:
        """Each service should have endpoints derived from pod IP + container port."""
        response = k8s_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        assert by_name["frontend"]["endpoints"] == ["tcp://10.0.1.10:80"]
        assert by_name["api"]["endpoints"] == ["tcp://10.0.1.20:8080"]
        assert by_name["database"]["endpoints"] == ["tcp://10.0.1.30:5432"]

    def test_metadata_stored(self, k8s_full_client: TestClient) -> None:
        """Registry should store K8s metadata (labels, namespace, node name, pod name)."""
        response = k8s_full_client.get("/services/discovered")
        by_name = {s["service_name"]: s for s in response.json()}

        db = by_name["database"]
        meta = db["metadata"]
        assert meta["pod_name"] == "database-1a2b3c4d5-e6f7g"
        assert meta["namespace"] == "default"
        assert meta["node_name"] == "node-1"
        assert meta["labels"]["app"] == "database"
        assert meta["container_ports"] == [5432]
        assert meta["phase"] == "Running"
        assert meta["restart_count"] == 0
        assert meta["cluster_name"] == "test-cluster"


# ------------------------------------------------------------------
# RBAC tests
# ------------------------------------------------------------------

class TestKubernetesRBAC:
    """Tests for RBAC / permission handling."""

    def test_403_forbidden_returns_empty(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        k8s_provider: KubernetesDiscoveryProvider,
    ) -> None:
        """If the K8s API returns 403, the provider should log a warning and return []."""

        class FakeApiException(Exception):
            def __init__(self, status: int, reason: str) -> None:
                self.status = status
                self.reason = reason

        mock_v1 = MagicMock()
        mock_v1.list_pod_for_all_namespaces = MagicMock(
            side_effect=FakeApiException(403, "Forbidden")
        )

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
             patch("kubernetes.client.rest.ApiException", FakeApiException):
            discovery_engine.register_provider(k8s_provider)
            result = asyncio.run(discovery_engine.run_discovery())

        assert result == []
        # Registry should still be functional (no exception raised)
        assert registry.list_services(active_only=True) == []


# ------------------------------------------------------------------
# Dynamic discovery tests
# ------------------------------------------------------------------

class TestKubernetesDynamic:
    """Tests for adding and removing pods dynamically."""

    def test_new_pod_detected(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        k8s_provider: KubernetesDiscoveryProvider,
    ) -> None:
        """Simulate a new pod starting and verify it's discovered."""
        initial_pods = make_all_pods()
        mock_v1 = MagicMock()
        mock_v1.list_pod_for_all_namespaces = MagicMock(
            return_value=FakePodList(initial_pods)
        )

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            discovery_engine.register_provider(k8s_provider)
            asyncio.run(discovery_engine.run_discovery())
            assert len(registry.list_services(active_only=True)) == 3

        # Add a new pod
        new_pod = FakePod(
            metadata=FakeMetadata(
                name="cache-7d8f9b2c4-x1z2a",
                namespace="default",
                labels={"app": "cache", "app.kubernetes.io/component": "cache"},
            ),
            status=FakePodStatus(
                pod_ip="10.0.1.40",
                phase="Running",
                start_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                container_statuses=[FakeContainerStatus(restart_count=0)],
            ),
            spec=FakePodSpec(
                containers=[FakeContainerSpec(ports=[FakeContainerPort(6379)])],
                node_name="node-1",
            ),
        )
        mock_v1.list_pod_for_all_namespaces = MagicMock(
            return_value=FakePodList(initial_pods + [new_pod])
        )

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            asyncio.run(discovery_engine.run_discovery())
            updated = registry.list_services(active_only=True)
            assert len(updated) == 4
            names = {s.service_name for s in updated}
            assert "cache" in names

    def test_removed_pod_marked_stale(
        self,
        registry: ServiceRegistry,
        discovery_engine: DiscoveryEngine,
        k8s_provider: KubernetesDiscoveryProvider,
    ) -> None:
        """Simulate a pod being deleted and verify it's marked stale."""
        all_pods = make_all_pods()
        mock_v1 = MagicMock()
        mock_v1.list_pod_for_all_namespaces = MagicMock(
            return_value=FakePodList(all_pods)
        )

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            discovery_engine.register_provider(k8s_provider)
            asyncio.run(discovery_engine.run_discovery())
            initial = registry.list_services(active_only=True)
            assert len(initial) == 3
            assert "api" in {s.service_name for s in initial}

        # Remove the API pod
        remaining = [p for p in all_pods if p.metadata.name != "api-9a2b3c4d5-e6f7g"]
        mock_v1.list_pod_for_all_namespaces = MagicMock(
            return_value=FakePodList(remaining)
        )

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            asyncio.run(discovery_engine.run_discovery())
            # Update heartbeats of remaining services so they stay fresh
            for svc in registry.list_services(active_only=True):
                if svc.service_name != "api":
                    registry.update_heartbeat(svc.service_id)

            # Make the API heartbeat old so it gets marked stale
            from datetime import timedelta
            api_svc = next((s for s in registry.list_services(active_only=True) if s.service_name == "api"), None)
            if api_svc:
                db_obj = (
                    registry._db.query(
                        registry._to_db(api_svc).__class__
                    )
                    .filter_by(service_id=api_svc.service_id)
                    .first()
                )
                if db_obj:
                    db_obj.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=10)
                    registry._db.commit()
                    registry._db.refresh(db_obj)

            asyncio.run(discovery_engine.remove_stale(timeout_seconds=5))
            names_after = {s.service_name for s in registry.list_services(active_only=True)}
            assert "api" not in names_after


# ------------------------------------------------------------------
# Namespace filtering tests
# ------------------------------------------------------------------

class TestKubernetesNamespace:
    """Tests for namespace filtering."""

    def test_namespace_filter_default(self) -> None:
        """When namespace is set to 'default', only pods in that namespace are discovered."""
        provider = KubernetesDiscoveryProvider(namespace="default")

        default_pods = make_all_pods()
        prod_pod = FakePod(
            metadata=FakeMetadata(
                name="prod-api-123",
                namespace="production",
                labels={"app": "prod-api"},
            ),
            status=FakePodStatus(pod_ip="10.0.2.10", phase="Running"),
            spec=FakePodSpec(containers=[FakeContainerSpec(ports=[FakeContainerPort(8080)])]),
        )
        all_pods = default_pods + [prod_pod]

        mock_v1 = MagicMock()
        mock_v1.list_namespaced_pod = MagicMock(return_value=FakePodList(default_pods))
        mock_v1.list_pod_for_all_namespaces = MagicMock(return_value=FakePodList(all_pods))

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            result = asyncio.run(provider.discover())

        # Should only return default namespace pods (3)
        assert len(result) == 3
        names = {s.service_name for s in result}
        assert "prod-api" not in names
        # Verify it called list_namespaced_pod, not list_pod_for_all_namespaces
        mock_v1.list_namespaced_pod.assert_called_once_with(namespace="default")
        mock_v1.list_pod_for_all_namespaces.assert_not_called()

    def test_all_namespaces_when_none_set(self) -> None:
        """When namespace is None, all namespaces are discovered."""
        provider = KubernetesDiscoveryProvider(namespace=None)

        prod_pod = FakePod(
            metadata=FakeMetadata(
                name="prod-api-123",
                namespace="production",
                labels={"app": "prod-api"},
            ),
            status=FakePodStatus(pod_ip="10.0.2.10", phase="Running"),
            spec=FakePodSpec(containers=[FakeContainerSpec(ports=[FakeContainerPort(8080)])]),
        )
        all_pods = make_all_pods() + [prod_pod]

        mock_v1 = MagicMock()
        mock_v1.list_pod_for_all_namespaces = MagicMock(return_value=FakePodList(all_pods))

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            result = asyncio.run(provider.discover())

        assert len(result) == 4
        names = {s.service_name for s in result}
        assert "prod-api" in names
        mock_v1.list_pod_for_all_namespaces.assert_called_once()
        mock_v1.list_namespaced_pod.assert_not_called()


# ------------------------------------------------------------------
# ClusterRole vs Role tests
# ------------------------------------------------------------------

class TestKubernetesClusterRole:
    """Tests for cluster-scoped vs namespace-scoped API calls."""

    def test_cluster_role_calls_all_namespaces(self) -> None:
        """Default provider (namespace=None) calls list_pod_for_all_namespaces."""
        provider = KubernetesDiscoveryProvider(namespace=None)
        mock_v1 = MagicMock()
        mock_v1.list_pod_for_all_namespaces = MagicMock(return_value=FakePodList(make_all_pods()))

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            asyncio.run(provider.discover())

        mock_v1.list_pod_for_all_namespaces.assert_called_once()
        mock_v1.list_namespaced_pod.assert_not_called()

    def test_role_calls_namespaced(self) -> None:
        """Provider with namespace set calls list_namespaced_pod."""
        provider = KubernetesDiscoveryProvider(namespace="default")
        mock_v1 = MagicMock()
        mock_v1.list_namespaced_pod = MagicMock(return_value=FakePodList(make_all_pods()))

        with patch("kubernetes.config.load_config"), \
             patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
            asyncio.run(provider.discover())

        mock_v1.list_namespaced_pod.assert_called_once_with(namespace="default")
        mock_v1.list_pod_for_all_namespaces.assert_not_called()
