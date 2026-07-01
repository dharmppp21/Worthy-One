"""Kubernetes-based service discovery provider using the Kubernetes client library."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.discovery.base import ServiceDiscoveryProvider
from app.discovery.models import DiscoveredService

try:
    import kubernetes.client
    import kubernetes.config
except ImportError:  # pragma: no cover
    kubernetes = None  # type: ignore

logger = logging.getLogger(__name__)

# Regex to strip Kubernetes hash-replicaset-pod suffixes like checkout-7d8f9b2c4-x1z2a -> checkout
_K8S_SUFFIX_RE = re.compile(r"-[a-z0-9]{8,10}-[a-z0-9]{4,6}$")

# Component label -> service_type
_K8S_COMPONENT_TYPES = {
    "database": "database",
    "db": "database",
    "cache": "cache",
    "redis": "cache",
    "queue": "message_queue",
    "kafka": "message_queue",
    "web": "web",
    "frontend": "web",
    "api": "api",
    "backend": "api",
}

# Known port -> service_type (fallback)
_PORT_TYPE_MAP = {
    80: "web",
    443: "web",
    5432: "database",
    3306: "database",
    27017: "database",
    6379: "cache",
    11211: "cache",
    9092: "message_queue",
    8080: "api",
    3000: "api",
    5000: "api",
    8000: "api",
    9200: "search",
    5601: "dashboard",
}


def _clean_pod_name(name: str) -> str:
    """Remove Kubernetes replica set / pod hash suffixes."""
    return _K8S_SUFFIX_RE.sub("", name)


def _get_service_name_from_pod(pod) -> str:
    """Extract service name from pod labels or pod name."""
    labels = pod.metadata.labels or {}
    name = labels.get("app.kubernetes.io/name") or labels.get("app")
    if name:
        return name
    return _clean_pod_name(pod.metadata.name)


def _get_service_type_from_labels(labels: Optional[Dict[str, str]]) -> Optional[str]:
    """Infer service type from Kubernetes component labels."""
    if not labels:
        return None
    component = labels.get("app.kubernetes.io/component", "").lower()
    if component in _K8S_COMPONENT_TYPES:
        return _K8S_COMPONENT_TYPES[component]
    return None


def _get_service_type_from_ports(ports: List[int]) -> str:
    """Infer service type from container ports."""
    for port in ports:
        if port in _PORT_TYPE_MAP:
            return _PORT_TYPE_MAP[port]
    return "unknown"


class KubernetesDiscoveryProvider(ServiceDiscoveryProvider):
    """Discovers services by scanning Kubernetes pods."""

    def __init__(self, namespace: Optional[str] = None) -> None:
        """
        Args:
            namespace: If set, list pods only in this namespace. If None, all namespaces.
        """
        self._namespace = namespace

    async def health_check(self) -> bool:
        """Verify Kubernetes config is loadable."""
        if kubernetes is None:
            return False
        try:
            kubernetes.config.load_config()
            return True
        except kubernetes.config.ConfigException as exc:
            logger.debug("Kubernetes health check failed: %s", exc)
            return False

    async def discover(self) -> List[DiscoveredService]:
        """Scan Kubernetes pods and return discovered services."""
        if kubernetes is None:
            logger.warning("kubernetes client is not installed; K8s discovery skipped.")
            return []

        try:
            kubernetes.config.load_config()
        except kubernetes.config.ConfigException as exc:
            logger.warning("Kubernetes config not available: %s", exc)
            return []

        try:
            v1 = kubernetes.client.CoreV1Api()
            if self._namespace:
                response = v1.list_namespaced_pod(namespace=self._namespace)
            else:
                response = v1.list_pod_for_all_namespaces()
        except kubernetes.client.rest.ApiException as exc:
            logger.warning("Kubernetes API unavailable: %s", exc)
            return []
        except Exception as exc:  # pragma: no cover
            logger.error("Unexpected Kubernetes error: %s", exc)
            return []

        discovered: List[DiscoveredService] = []
        seen_keys: set = set()

        for pod in response.items:
            try:
                pod_ip = pod.status.pod_ip
                if not pod_ip:
                    continue

                labels = pod.metadata.labels or {}
                service_name = _get_service_name_from_pod(pod)
                if not service_name:
                    continue

                # Collect container ports
                container_ports: List[int] = []
                for container in pod.spec.containers or []:
                    for port in container.ports or []:
                        if port.container_port:
                            container_ports.append(port.container_port)

                if not container_ports:
                    continue

                endpoints = [f"tcp://{pod_ip}:{port}" for port in container_ports]

                # Determine service type
                service_type = _get_service_type_from_labels(labels)
                if not service_type:
                    service_type = _get_service_type_from_ports(container_ports)

                # Restart count
                restart_count = 0
                for cs in pod.status.container_statuses or []:
                    restart_count += cs.restart_count or 0

                # Start time
                start_time = None
                if pod.status.start_time:
                    try:
                        start_time = pod.status.start_time.isoformat()
                    except Exception:
                        pass

                metadata: Dict[str, Any] = {
                    "pod_name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "node_name": pod.spec.node_name,
                    "labels": dict(labels),
                    "container_ports": container_ports,
                    "phase": pod.status.phase,
                    "restart_count": restart_count,
                    "cluster_name": pod.metadata.cluster_name or "unknown",
                }
                if start_time:
                    metadata["start_time"] = start_time

                key = (service_name, pod_ip)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                discovered.append(
                    DiscoveredService(
                        service_name=service_name,
                        service_type=service_type,
                        endpoints=endpoints,
                        host=pod_ip,
                        metadata=metadata,
                        discovery_source="kubernetes",
                    )
                )
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "Error scanning pod %s: %s", getattr(pod.metadata, "name", "?"), exc
                )
                continue

        return discovered
