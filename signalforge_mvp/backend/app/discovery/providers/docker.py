"""Docker-based service discovery provider using the Docker SDK."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.discovery.base import ServiceDiscoveryProvider
from app.discovery.models import DiscoveredService
from app.discovery.providers.process import _get_service_type_from_port

try:
    import docker
except ImportError:  # pragma: no cover
    docker = None  # type: ignore

logger = logging.getLogger(__name__)

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

# Docker Compose random suffix pattern
_COMPOSE_SUFFIX_RE = re.compile(r"_\d+$")


def _clean_container_name(name: str) -> str:
    """Remove leading slash and Docker Compose suffixes."""
    if name.startswith("/"):
        name = name[1:]
    return _COMPOSE_SUFFIX_RE.sub("", name)


def _get_service_type_from_image(image_name: str) -> Optional[str]:
    """Infer service type from Docker image name."""
    img_lower = image_name.lower()
    for keyword, stype in _IMAGE_TYPE_HINTS.items():
        if keyword in img_lower:
            return stype
    return None


def _build_endpoints_from_ports(ports: Dict[str, Any]) -> List[str]:
    """Build endpoint strings from Docker container port mappings."""
    endpoints: List[str] = []
    for container_port, host_bindings in ports.items():
        if not host_bindings:
            continue
        for binding in host_bindings:
            host_ip = binding.get("HostIp") or "127.0.0.1"
            host_port = binding.get("HostPort")
            if host_port:
                endpoints.append(f"tcp://{host_ip}:{host_port}")
    return endpoints


class DockerDiscoveryProvider(ServiceDiscoveryProvider):
    """Discovers services by scanning local Docker containers."""

    async def health_check(self) -> bool:
        """Verify Docker daemon is reachable by pinging it."""
        if docker is None:
            return False
        try:
            client = docker.from_env()
            return client.ping()
        except Exception as exc:  # pragma: no cover
            logger.debug("Docker health check failed: %s", exc)
            return False

    async def discover(self) -> List[DiscoveredService]:
        """Scan Docker containers and return discovered services."""
        if docker is None:  # pragma: no cover
            logger.warning("docker SDK is not installed; Docker discovery skipped.")
            return []

        try:
            client = docker.from_env()
            containers = client.containers.list()
        except docker.errors.DockerException as exc:
            logger.warning("Docker is not running or not accessible: %s", exc)
            return []
        except Exception as exc:  # pragma: no cover
            logger.error("Unexpected Docker error: %s", exc)
            return []

        discovered: List[DiscoveredService] = []
        seen_keys: set = set()

        for container in containers:
            try:
                attrs = container.attrs
                network_settings = attrs.get("NetworkSettings", {})
                ports = network_settings.get("Ports", {})
                networks = network_settings.get("Networks", {})
                config = attrs.get("Config", {})

                container_name = container.name
                labels = container.labels or {}

                # Determine service name
                service_name = labels.get("app") or labels.get("service.name")
                if not service_name:
                    service_name = _clean_container_name(container_name)

                # Image tag or ID
                image_name = ""
                try:
                    tags = container.image.tags
                    if tags:
                        image_name = tags[0]
                    else:
                        image_name = container.image.id
                except Exception:
                    image_name = attrs.get("Image", "")

                # Build endpoints
                endpoints = _build_endpoints_from_ports(ports)
                if not endpoints:
                    # Fallback: use container IP + exposed ports without host binding
                    for container_port in ports.keys():
                        if container_port.endswith("/tcp"):
                            port_num = container_port.split("/")[0]
                            endpoints.append(f"tcp://127.0.0.1:{port_num}")

                if not endpoints:
                    # Use container IP from network
                    for net_name, net_info in networks.items():
                        ip = net_info.get("IPAddress")
                        if ip:
                            endpoints.append(f"tcp://{ip}:0")
                            break

                host = "127.0.0.1"
                if endpoints:
                    first = endpoints[0]
                    try:
                        host = first.split("://")[1].split(":")[0]
                    except (IndexError, ValueError):
                        pass

                # Determine service type
                service_type = _get_service_type_from_image(image_name)
                if not service_type and endpoints:
                    # Try infer from port numbers
                    for ep in endpoints:
                        try:
                            port = int(ep.split(":")[-1])
                            inferred = _get_service_type_from_port(port)
                            if inferred != "unknown":
                                service_type = inferred
                                break
                        except (ValueError, IndexError):
                            continue
                if not service_type:
                    service_type = "unknown"

                # Metadata
                metadata: Dict[str, Any] = {
                    "container_id": container.short_id,
                    "image": image_name,
                    "status": container.status,
                    "labels": dict(labels),
                    "networks": list(networks.keys()),
                    "command": config.get("Cmd") or [],
                    "created_at": attrs.get("Created"),
                    "pid": attrs.get("State", {}).get("Pid"),
                }
                metadata = {k: v for k, v in metadata.items() if v is not None}

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
                        discovery_source="docker",
                    )
                )
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "Unexpected error scanning container %s: %s",
                    getattr(container, "name", "?"),
                    exc,
                )
                continue

        return discovered
