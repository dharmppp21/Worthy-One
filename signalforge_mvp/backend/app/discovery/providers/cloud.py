"""Cloud-based service discovery provider (AWS, Azure, GCP)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from app.discovery.base import ServiceDiscoveryProvider
from app.discovery.models import DiscoveredService

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

logger = logging.getLogger(__name__)

# AWS metadata endpoint
_AWS_METADATA_URL = "http://169.254.169.254/latest/meta-data/"
_AWS_TOKEN_URL = "http://169.254.169.254/latest/api/token"

# Azure metadata endpoint
_AZURE_METADATA_URL = "http://169.254.169.254/metadata/instance?api-version=2021-02-01"

# GCP metadata endpoint
_GCP_METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/"


# Image name keywords -> service_type
_IMAGE_TYPE_HINTS = {
    "postgres": "database",
    "mysql": "database",
    "mariadb": "database",
    "mongo": "database",
    "mongodb": "database",
    "redis": "cache",
    "kafka": "message_queue",
    "zookeeper": "message_queue",
    "nginx": "web",
    "apache": "web",
    "caddy": "web",
    "node": "api",
    "python": "api",
    "go": "api",
    "java": "api",
    "dotnet": "api",
    "elasticsearch": "search",
    "kibana": "dashboard",
}


def _get_service_type_from_image(image_name: str) -> str:
    """Infer service type from container image name."""
    img_lower = image_name.lower()
    for keyword, stype in _IMAGE_TYPE_HINTS.items():
        if keyword in img_lower:
            return stype
    return "unknown"


def _is_aws_ecs() -> bool:
    """Check if running in AWS ECS."""
    aws_exec_env = os.environ.get("AWS_EXECUTION_ENV", "")
    return "AWS_ECS" in aws_exec_env


def _is_aws_eks() -> bool:
    """Check if running in AWS EKS."""
    k8s_host = os.environ.get("KUBERNETES_SERVICE_HOST")
    if not k8s_host:
        return False
    # Check AWS metadata or web identity token
    web_identity = os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")
    if web_identity:
        return True
    # Try metadata endpoint
    if requests is None:
        return False
    try:
        resp = requests.get(_AWS_METADATA_URL, timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def _is_aws() -> bool:
    """Check if running in any AWS environment."""
    return (
        _is_aws_ecs()
        or _is_aws_eks()
        or os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")
    )


def _is_azure() -> bool:
    """Check if running in Azure."""
    for key in os.environ:
        if key.startswith("AZURE_"):
            return True
    if requests is None:
        return False
    try:
        resp = requests.get(
            _AZURE_METADATA_URL,
            headers={"Metadata": "true"},
            timeout=1,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _is_gcp() -> bool:
    """Check if running in GCP."""
    for key in os.environ:
        if key.startswith("GOOGLE_"):
            return True
    if requests is None:
        return False
    try:
        resp = requests.get(
            _GCP_METADATA_URL,
            headers={"Metadata-Flavor": "Google"},
            timeout=1,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _discover_aws_ecs() -> List[DiscoveredService]:
    """Discover ECS tasks and services."""
    if boto3 is None:
        logger.warning("boto3 is not installed; AWS ECS discovery skipped.")
        return []

    discovered: List[DiscoveredService] = []
    seen_keys: set = set()

    try:
        ecs = boto3.client("ecs")
        clusters = ecs.list_clusters()["clusterArns"]
    except Exception as exc:
        logger.warning("AWS ECS cluster listing failed: %s", exc)
        return []

    for cluster_arn in clusters:
        try:
            services = ecs.list_services(cluster=cluster_arn, maxResults=10)[
                "serviceArns"
            ]
        except Exception:
            continue

        for service_arn in services:
            try:
                task_list = ecs.list_tasks(
                    cluster=cluster_arn, serviceName=service_arn, maxResults=10
                )["taskArns"]
            except Exception:
                continue

            if not task_list:
                continue

            try:
                task_desc = ecs.describe_tasks(cluster=cluster_arn, tasks=task_list)[
                    "tasks"
                ]
            except Exception:
                continue

            for task in task_desc:
                try:
                    service_name = (
                        service_arn.split("/")[-1]
                        if "/" in service_arn
                        else service_arn
                    )
                    host = "127.0.0.1"
                    endpoints: List[str] = []
                    image_name = ""

                    for container in task.get("containers", []):
                        image_name = container.get("image", "")
                        for binding in container.get("networkBindings", []):
                            host_ip = binding.get("hostIp") or "127.0.0.1"
                            host_port = binding.get("hostPort")
                            if host_port:
                                endpoints.append(f"tcp://{host_ip}:{host_port}")
                            host = host_ip

                    if not endpoints:
                        continue

                    service_type = _get_service_type_from_image(image_name)
                    metadata: Dict[str, Any] = {
                        "task_arn": task.get("taskArn"),
                        "cluster_arn": cluster_arn,
                        "image": image_name,
                        "launch_type": task.get("launchType"),
                        "status": task.get("lastStatus"),
                    }

                    key = (service_name, host)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    discovered.append(
                        DiscoveredService(
                            service_name=service_name,
                            service_type=service_type,
                            endpoints=endpoints,
                            host=host,
                            metadata=metadata,
                            discovery_source="cloud_aws_ecs",
                        )
                    )
                except Exception as exc:
                    logger.debug("Error scanning ECS task: %s", exc)
                    continue

    return discovered


class CloudDiscoveryProvider(ServiceDiscoveryProvider):
    """Discovers services in cloud environments (AWS ECS/EKS, Azure, GCP)."""

    async def health_check(self) -> bool:
        """Check if any cloud provider is detectable."""
        return bool(_is_aws() or _is_azure() or _is_gcp())

    async def discover(self) -> List[DiscoveredService]:
        """Auto-detect cloud provider and discover services."""
        if _is_aws_ecs():
            return _discover_aws_ecs()
        elif _is_aws_eks():
            # Delegate to Kubernetes provider but with AWS source
            from app.discovery.providers.kubernetes import KubernetesDiscoveryProvider

            provider = KubernetesDiscoveryProvider()
            services = await provider.discover()
            for svc in services:
                svc.discovery_source = "cloud_aws"
            return services
        elif _is_azure():
            logger.warning("Azure discovery not yet implemented")
            return []
        elif _is_gcp():
            logger.warning("GCP discovery not yet implemented")
            return []
        return []
