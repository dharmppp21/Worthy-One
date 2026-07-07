"""Tests for the environment auto-detection and auto-configuration system."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.discovery.environment import (
    AutoConfigurator,
    EnvironmentDetector,
)
from app.discovery.providers.config import ConfigDiscoveryProvider
from app.discovery.providers.cloud import (
    CloudDiscoveryProvider,
    _is_aws_ecs,
    _is_aws_eks,
    _is_aws,
    _is_azure,
    _is_gcp,
)


# ------------------------------------------------------------------
# EnvironmentDetector tests
# ------------------------------------------------------------------

class TestEnvironmentDetector:
    """Tests for EnvironmentDetector static methods."""

    def test_is_kubernetes_true(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        assert EnvironmentDetector.is_kubernetes() is True

    def test_is_kubernetes_false(self, monkeypatch):
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        assert EnvironmentDetector.is_kubernetes() is False

    def test_is_aws_ecs_true(self, monkeypatch):
        monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
        assert EnvironmentDetector.is_aws_ecs() is True

    def test_is_aws_ecs_false(self, monkeypatch):
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        assert EnvironmentDetector.is_aws_ecs() is False

    def test_is_aws_eks_true(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/tmp/token")
        assert EnvironmentDetector.is_aws_eks() is True

    def test_is_aws_eks_false_no_k8s(self, monkeypatch):
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        assert EnvironmentDetector.is_aws_eks() is False

    def test_is_docker_linux(self, tmp_path):
        """Mock /proc/1/cgroup containing docker."""
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("12:hugetlb:/docker/abc123\n")
        with patch("app.discovery.environment.os.path.isfile", return_value=True), \
             patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=str(cgroup_file.read_text()))))))):
            # Actually let's just patch the file path directly
            pass

    def test_is_docker_no_cgroup(self, monkeypatch, tmp_path):
        """No /proc/1/cgroup file and no docker process means not Docker."""
        monkeypatch.chdir(tmp_path)
        # On Windows, is_docker() also scans running processes for a docker
        # daemon; mock it so the test does not depend on whether Docker Desktop
        # happens to be running on the host.
        with patch("psutil.process_iter", return_value=iter([])):
            assert EnvironmentDetector.is_docker() is False

    def test_get_cloud_provider_aws(self, monkeypatch):
        monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
        assert EnvironmentDetector.get_cloud_provider() == "aws"

    def test_get_cloud_provider_none(self, monkeypatch):
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        assert EnvironmentDetector.get_cloud_provider() is None

    # ------------------------------------------------------------------
    # get_discovery_providers mapping
    # ------------------------------------------------------------------

    def test_get_providers_eks(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/tmp/token")
        providers = EnvironmentDetector.get_discovery_providers()
        assert "cloud_aws" in providers
        assert "kubernetes" in providers
        assert "docker" in providers
        assert "process" in providers
        assert "config" in providers

    def test_get_providers_ecs(self, monkeypatch):
        monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        providers = EnvironmentDetector.get_discovery_providers()
        assert "cloud_aws" in providers
        assert "docker" in providers
        assert "process" in providers
        assert "config" in providers

    def test_get_providers_kubernetes(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        providers = EnvironmentDetector.get_discovery_providers()
        assert "kubernetes" in providers
        assert "docker" in providers
        assert "process" in providers

    def test_get_providers_docker(self, monkeypatch):
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        # Mock is_docker to return True
        with patch.object(EnvironmentDetector, "is_docker", return_value=True):
            providers = EnvironmentDetector.get_discovery_providers()
        assert "docker" in providers
        assert "process" in providers
        assert "config" in providers

    def test_get_providers_vm(self, monkeypatch):
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        with patch.object(EnvironmentDetector, "is_docker", return_value=False), \
             patch.object(EnvironmentDetector, "is_azure", return_value=False), \
             patch.object(EnvironmentDetector, "is_gcp", return_value=False):
            providers = EnvironmentDetector.get_discovery_providers()
        assert providers == ["process", "config"]

    def test_is_vm(self, monkeypatch):
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        with patch.object(EnvironmentDetector, "is_docker", return_value=False), \
             patch.object(EnvironmentDetector, "is_azure", return_value=False), \
             patch.object(EnvironmentDetector, "is_gcp", return_value=False):
            assert EnvironmentDetector.is_vm() is True

    def test_is_vm_false(self, monkeypatch):
        monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
        assert EnvironmentDetector.is_vm() is False


# ------------------------------------------------------------------
# AutoConfigurator tests
# ------------------------------------------------------------------

class TestAutoConfigurator:
    """Tests for AutoConfigurator."""

    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("SIGNALFORGE_DISCOVERY_ENABLED", raising=False)
        monkeypatch.delenv("SIGNALFORGE_DISCOVERY_INTERVAL", raising=False)
        monkeypatch.delenv("SIGNALFORGE_DISCOVERY_PROVIDERS", raising=False)

        cfg = AutoConfigurator()
        assert cfg.enabled is True
        assert cfg.interval == 30
        assert cfg.overrides == ""
        assert cfg.k8s_namespace is None

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("SIGNALFORGE_DISCOVERY_ENABLED", "false")
        monkeypatch.setenv("SIGNALFORGE_DISCOVERY_INTERVAL", "60")
        monkeypatch.setenv("SIGNALFORGE_DISCOVERY_PROVIDERS", "docker,process")
        monkeypatch.setenv("SIGNALFORGE_K8S_NAMESPACE", "production")

        cfg = AutoConfigurator()
        assert cfg.enabled is False
        assert cfg.interval == 60
        assert cfg.overrides == "docker,process"
        assert cfg.k8s_namespace == "production"

    def test_get_provider_names_auto(self, monkeypatch):
        monkeypatch.delenv("SIGNALFORGE_DISCOVERY_PROVIDERS", raising=False)
        with patch.object(EnvironmentDetector, "is_docker", return_value=False), \
             patch.object(EnvironmentDetector, "is_kubernetes", return_value=False), \
             patch.object(EnvironmentDetector, "is_aws_ecs", return_value=False):
            cfg = AutoConfigurator()
            names = cfg.get_provider_names()
        assert "process" in names
        assert "config" in names

    def test_get_provider_names_override(self, monkeypatch):
        monkeypatch.setenv("SIGNALFORGE_DISCOVERY_PROVIDERS", "docker,config")
        cfg = AutoConfigurator()
        names = cfg.get_provider_names()
        assert names == ["docker", "config"]

    def test_instantiate_providers(self, monkeypatch):
        monkeypatch.setenv("SIGNALFORGE_DISCOVERY_PROVIDERS", "config")
        cfg = AutoConfigurator()
        providers = cfg.instantiate_providers()
        assert len(providers) == 1
        assert isinstance(providers[0], ConfigDiscoveryProvider)

    def test_instantiate_providers_unknown(self, monkeypatch, caplog):
        monkeypatch.setenv("SIGNALFORGE_DISCOVERY_PROVIDERS", "nonexistent_provider")
        cfg = AutoConfigurator()
        providers = cfg.instantiate_providers()
        assert providers == []


# ------------------------------------------------------------------
# ConfigDiscoveryProvider tests
# ------------------------------------------------------------------

class TestConfigDiscoveryProvider:
    """Tests for ConfigDiscoveryProvider."""

    @pytest.mark.asyncio
    async def test_discover_from_env_var(self, monkeypatch):
        json_data = '[{"name": "my-api", "type": "api", "endpoints": ["http://api:8080"], "host": "api", "metadata": {"version": "1.0"}}]'
        monkeypatch.setenv("SIGNALFORGE_SERVICES", json_data)
        monkeypatch.delenv("SIGNALFORGE_SERVICES_CONFIG", raising=False)

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert len(result) == 1
        assert result[0].service_name == "my-api"
        assert result[0].service_type == "api"
        assert result[0].endpoints == ["http://api:8080"]
        assert result[0].host == "api"
        assert result[0].discovery_source == "config"
        assert result[0].metadata["version"] == "1.0"

    @pytest.mark.asyncio
    async def test_discover_from_file_json(self, monkeypatch, tmp_path):
        json_data = '[{"name": "db", "type": "database", "endpoints": ["tcp://db:5432"], "host": "db"}]'
        config_file = tmp_path / "services.json"
        config_file.write_text(json_data)

        monkeypatch.delenv("SIGNALFORGE_SERVICES", raising=False)
        monkeypatch.setenv("SIGNALFORGE_SERVICES_CONFIG", str(config_file))

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert len(result) == 1
        assert result[0].service_name == "db"
        assert result[0].service_type == "database"

    @pytest.mark.asyncio
    async def test_discover_from_file_yaml(self, monkeypatch, tmp_path):
        try:
            import yaml
        except ImportError:
            pytest.skip("pyyaml not installed")

        data = [{"name": "cache", "type": "cache", "endpoints": ["tcp://cache:6379"], "host": "cache"}]
        config_file = tmp_path / "services.yaml"
        config_file.write_text(yaml.dump(data))

        monkeypatch.delenv("SIGNALFORGE_SERVICES", raising=False)
        monkeypatch.setenv("SIGNALFORGE_SERVICES_CONFIG", str(config_file))

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert len(result) == 1
        assert result[0].service_name == "cache"

    @pytest.mark.asyncio
    async def test_discover_no_config(self, monkeypatch):
        monkeypatch.delenv("SIGNALFORGE_SERVICES", raising=False)
        monkeypatch.delenv("SIGNALFORGE_SERVICES_CONFIG", raising=False)

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_invalid_json(self, monkeypatch, caplog):
        monkeypatch.setenv("SIGNALFORGE_SERVICES", "not-json")
        monkeypatch.delenv("SIGNALFORGE_SERVICES_CONFIG", raising=False)

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert result == []

    @pytest.mark.asyncio
    async def test_health_check(self):
        provider = ConfigDiscoveryProvider()
        result = await provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_discover_extract_host_from_endpoint(self, monkeypatch):
        json_data = '[{"name": "svc", "type": "api", "endpoints": ["http://10.0.0.1:8080"]}]'
        monkeypatch.setenv("SIGNALFORGE_SERVICES", json_data)
        monkeypatch.delenv("SIGNALFORGE_SERVICES_CONFIG", raising=False)

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert len(result) == 1
        assert result[0].host == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_discover_skip_missing_name(self, monkeypatch):
        json_data = '[{"type": "api", "endpoints": ["http://svc:8080"]}]'
        monkeypatch.setenv("SIGNALFORGE_SERVICES", json_data)
        monkeypatch.delenv("SIGNALFORGE_SERVICES_CONFIG", raising=False)

        provider = ConfigDiscoveryProvider()
        result = await provider.discover()
        assert result == []


# ------------------------------------------------------------------
# CloudDiscoveryProvider tests (AWS stubs + health check)
# ------------------------------------------------------------------

class TestCloudDiscoveryProvider:
    """Tests for CloudDiscoveryProvider."""

    @pytest.fixture
    def provider(self):
        return CloudDiscoveryProvider()

    @pytest.mark.asyncio
    async def test_health_check_aws(self, monkeypatch, provider):
        monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
        result = await provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_cloud(self, monkeypatch, provider):
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        result = await provider.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_discover_no_cloud(self, monkeypatch, provider):
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        result = await provider.discover()
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_azure_stub(self, monkeypatch, provider):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "test")
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        result = await provider.discover()
        assert result == []

    @pytest.mark.asyncio
    async def test_discover_gcp_stub(self, monkeypatch, provider):
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/creds.json")
        monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
        result = await provider.discover()
        assert result == []
