"""Network-based dependency detection scanner using psutil."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.dependencies.models import ServiceDependency
from app.discovery.registry import ServiceRegistry

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

logger = logging.getLogger(__name__)

# Port -> dependency_type inference
_PORT_TYPE_MAP = {
    5432: "database", 3306: "database", 27017: "database",
    6379: "cache", 11211: "cache",
    9092: "message_queue",
    80: "http", 443: "http", 8080: "http", 3000: "http",
    50051: "grpc",
}


def _infer_dependency_type(port: int) -> str:
    """Infer dependency type from remote port number."""
    return _PORT_TYPE_MAP.get(port, "unknown")


class NetworkConnectionScanner:
    """Scans active network connections to infer service dependencies."""

    def __init__(self, registry: ServiceRegistry) -> None:
        """
        Args:
            registry: ServiceRegistry for looking up services by PID or endpoint.
        """
        self._registry = registry

    async def scan(self) -> List[ServiceDependency]:
        """Scan ESTABLISHED network connections and return inferred dependencies."""
        if psutil is None:
            logger.warning("psutil is not installed; network scan skipped.")
            return []

        try:
            connections = psutil.net_connections(kind="inet")
        except PermissionError as exc:
            logger.warning("Permission denied scanning network connections: %s", exc)
            return []
        except Exception as exc:  # pragma: no cover
            logger.error("Unexpected error scanning connections: %s", exc)
            return []

        # Group by (source_service_id, target_endpoint)
        grouped: Dict[Tuple[str, Tuple[str, int]], int] = defaultdict(int)

        for conn in connections:
            if conn.status != psutil.CONN_ESTABLISHED:
                continue
            if not conn.raddr:
                continue

            remote_ip = conn.raddr.ip
            remote_port = conn.raddr.port

            # Find source service by PID
            source_service = self._find_service_by_pid(conn.pid)
            if not source_service:
                continue

            # Find target service by endpoint
            target_service = self._find_service_by_endpoint(remote_ip, remote_port)
            if not target_service:
                # Create an inferred placeholder
                target_service = self._create_inferred_service(remote_ip, remote_port)

            key = (source_service.service_id, (remote_ip, remote_port))
            grouped[key] += 1

        # Build ServiceDependency objects from grouped data
        dependencies: List[ServiceDependency] = []
        seen_pairs: set = set()

        for (source_id, (remote_ip, remote_port)), count in grouped.items():
            pair = (source_id, remote_ip, remote_port)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            dep_type = _infer_dependency_type(remote_port)

            # Try to find the actual target service_id for known services
            target_service = self._find_service_by_endpoint(remote_ip, remote_port)
            target_id = target_service.service_id if target_service else self._inferred_service_id(remote_ip, remote_port)

            confidence = 0.8 if target_service else 0.3

            dependencies.append(
                ServiceDependency(
                    source_service_id=source_id,
                    target_service_id=target_id,
                    dependency_type=dep_type,
                    connection_count=count,
                    last_seen_at=datetime.now(timezone.utc),
                    confidence_score=confidence,
                    discovery_sources=["network"],
                )
            )

        return dependencies

    def _find_service_by_pid(self, pid: Optional[int]) -> Optional[Any]:
        """Look up a service in the registry by matching PID in metadata."""
        if pid is None:
            return None
        for svc in self._registry.list_services(active_only=True):
            if svc.metadata.get("pid") == pid:
                return svc
        return None

    def _find_service_by_endpoint(self, ip: str, port: int) -> Optional[Any]:
        """Look up a service in the registry by matching IP:port in endpoints."""
        target = f"tcp://{ip}:{port}"
        for svc in self._registry.list_services(active_only=True):
            for ep in svc.endpoints:
                if ep == target:
                    return svc
            # Also check host:port match
            if svc.host == ip:
                for ep in svc.endpoints:
                    try:
                        ep_port = int(ep.split(":")[-1])
                        if ep_port == port:
                            return svc
                    except (ValueError, IndexError):
                        continue
        return None

    def _inferred_service_id(self, ip: str, port: int) -> str:
        """Generate a deterministic service_id for an inferred service."""
        return f"inferred-{ip.replace('.', '-')}-{port}"

    def _create_inferred_service(self, ip: str, port: int) -> Any:
        """Create a placeholder DiscoveredService for an inferred target."""
        from app.discovery.models import DiscoveredService

        dep_type = _infer_dependency_type(port)
        return DiscoveredService(
            service_id=self._inferred_service_id(ip, port),
            service_name=f"inferred-{dep_type}-{ip}-{port}",
            service_type=dep_type,
            endpoints=[f"tcp://{ip}:{port}"],
            host=ip,
            metadata={"inferred": True, "port": port},
            discovery_source="inferred",
        )
