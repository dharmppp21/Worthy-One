"""Environment auto-detection and discovery configuration.

Detects the runtime environment (Docker, Kubernetes, AWS, Azure, GCP, VM)
and configures the appropriate discovery providers.
"""

from __future__ import annotations

import logging
import os
import platform
from typing import List, Optional

logger = logging.getLogger(__name__)

# Provider module paths mapped to provider class names
_PROVIDER_MAP = {
    "cloud_aws": "app.discovery.providers.cloud.CloudDiscoveryProvider",
    "kubernetes": "app.discovery.providers.kubernetes.KubernetesDiscoveryProvider",
    "docker": "app.discovery.providers.docker.DockerDiscoveryProvider",
    "process": "app.discovery.providers.process.ProcessDiscoveryProvider",
    "config": "app.discovery.providers.config.ConfigDiscoveryProvider",
}


class EnvironmentDetector:
    """Detects the current runtime environment."""

    @staticmethod
    def is_docker() -> bool:
        """Check if running inside a Docker container."""
        # Linux: check /proc/1/cgroup for docker references
        if os.path.isfile("/proc/1/cgroup"):
            try:
                with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
                    content = f.read()
                return "docker" in content or ".docker" in content
            except Exception:
                pass
        # Windows: check for Docker Desktop processes
        if platform.system() == "Windows":
            try:
                import psutil

                for proc in psutil.process_iter(attrs=["name"]):
                    name = (proc.info.get("name") or "").lower()
                    if "docker" in name or "dockerd" in name:
                        return True
            except Exception:
                pass
        return False

    @staticmethod
    def is_kubernetes() -> bool:
        """Check if running inside a Kubernetes pod."""
        return bool(os.environ.get("KUBERNETES_SERVICE_HOST"))

    @staticmethod
    def is_aws_ecs() -> bool:
        """Check if running in AWS ECS."""
        aws_exec_env = os.environ.get("AWS_EXECUTION_ENV", "")
        return "AWS_ECS" in aws_exec_env

    @staticmethod
    def is_aws_eks() -> bool:
        """Check if running in AWS EKS."""
        if not EnvironmentDetector.is_kubernetes():
            return False
        # Check AWS metadata or web identity token
        if os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE"):
            return True
        if os.environ.get("AWS_DEFAULT_REGION"):
            return True
        try:
            import requests

            resp = requests.get("http://169.254.169.254/latest/meta-data/", timeout=1)
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def is_azure() -> bool:
        """Check if running in Azure."""
        for key in os.environ:
            if key.startswith("AZURE_"):
                return True
        try:
            import requests

            resp = requests.get(
                "http://169.254.169.254/metadata/instance?api-version=2021-02-01",
                headers={"Metadata": "true"},
                timeout=1,
            )
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def is_gcp() -> bool:
        """Check if running in GCP."""
        for key in os.environ:
            if key.startswith("GOOGLE_"):
                return True
        try:
            import requests

            resp = requests.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/",
                headers={"Metadata-Flavor": "Google"},
                timeout=1,
            )
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def is_vm() -> bool:
        """Default to True if no specific environment detected."""
        return not (
            EnvironmentDetector.is_docker()
            or EnvironmentDetector.is_kubernetes()
            or EnvironmentDetector.is_aws_ecs()
            or EnvironmentDetector.is_aws_eks()
            or EnvironmentDetector.is_azure()
            or EnvironmentDetector.is_gcp()
        )

    @staticmethod
    def get_cloud_provider() -> Optional[str]:
        """Returns 'aws', 'azure', 'gcp', or None."""
        if EnvironmentDetector.is_aws_ecs() or EnvironmentDetector.is_aws_eks():
            return "aws"
        if EnvironmentDetector.is_azure():
            return "azure"
        if EnvironmentDetector.is_gcp():
            return "gcp"
        return None

    @staticmethod
    def get_discovery_providers() -> List[str]:
        """Return a list of provider names based on the environment.

        Priority: cloud-specific -> container -> process -> config
        """
        if EnvironmentDetector.is_aws_eks():
            return ["cloud_aws", "kubernetes", "docker", "process", "config"]
        if EnvironmentDetector.is_aws_ecs():
            return ["cloud_aws", "docker", "process", "config"]
        if EnvironmentDetector.is_kubernetes():
            return ["kubernetes", "docker", "process", "config"]
        if EnvironmentDetector.is_docker():
            return ["docker", "process", "config"]
        # VM / bare metal
        return ["process", "config"]


class AutoConfigurator:
    """Reads environment variables and configures the DiscoveryEngine."""

    def __init__(self) -> None:
        """Initialize the auto-configurator from environment variables."""
        self.enabled = (
            os.environ.get("SIGNALFORGE_DISCOVERY_ENABLED", "true").lower() == "true"
        )
        self.interval = int(os.environ.get("SIGNALFORGE_DISCOVERY_INTERVAL", "30"))
        self.overrides = os.environ.get("SIGNALFORGE_DISCOVERY_PROVIDERS", "")
        self.k8s_namespace = os.environ.get("SIGNALFORGE_K8S_NAMESPACE")

    def get_provider_names(self) -> List[str]:
        """Return the list of provider names to use."""
        if self.overrides:
            return [p.strip() for p in self.overrides.split(",") if p.strip()]
        return EnvironmentDetector.get_discovery_providers()

    def instantiate_providers(self):
        """Import and instantiate each provider class."""
        from app.discovery.base import ServiceDiscoveryProvider

        providers: List[ServiceDiscoveryProvider] = []
        for name in self.get_provider_names():
            module_path = _PROVIDER_MAP.get(name)
            if not module_path:
                logger.warning("Unknown discovery provider: %s", name)
                continue

            try:
                parts = module_path.split(".")
                module_name = ".".join(parts[:-1])
                class_name = parts[-1]
                mod = __import__(module_name, fromlist=[class_name])
                cls = getattr(mod, class_name)

                # Special case: Kubernetes with namespace
                if name == "kubernetes" and self.k8s_namespace:
                    instance = cls(namespace=self.k8s_namespace)
                else:
                    instance = cls()

                providers.append(instance)
            except Exception as exc:
                logger.warning("Failed to instantiate provider %s: %s", name, exc)
                continue

        return providers
