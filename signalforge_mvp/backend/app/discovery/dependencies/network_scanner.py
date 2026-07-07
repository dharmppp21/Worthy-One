"""Network-based dependency detection scanner using psutil."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.dependencies.base import BaseDependencyAnalyzer
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.registry import ServiceRegistry

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

logger = logging.getLogger(__name__)

# Ephemeral port range — outbound client connections, not server services
_EPHEMERAL_PORT_MIN = 49152

# Common browser / system process names to skip as sources
_BROWSER_PROCESSES = frozenset({
    "chrome", "firefox", "msedge", "safari", "opera", "brave",
    "discord", "spotify", "steam", "epicgameslauncher",
    "code", "cursor", "warp", "terminal", "windowsterminal",
})

# Well-known external/cloud IPs to skip
_EXTERNAL_IP_PREFIXES = (
    "8.8.8.", "8.8.4.",       # Google DNS
    "1.1.1.", "1.0.0.",       # Cloudflare DNS
    "208.67.",                  # OpenDNS
    "9.9.9.",                   # Quad9
    "142.250.", "172.217.",    # Google
    "13.107.", "20.190.",      # Microsoft
    "31.13.", "157.240.",      # Facebook/Meta
    "104.16.", "104.17.",      # Cloudflare
)

# Port -> dependency_type inference
_PORT_TYPE_MAP = {
    5432: "database",
    3306: "database",
    27017: "database",
    6379: "cache",
    11211: "cache",
    9092: "message_queue",
    80: "http",
    443: "http",
    8080: "http",
    3000: "http",
    50051: "grpc",
}


def _is_ephemeral_connection(conn) -> bool:
    """Return True if this looks like an ephemeral outbound connection."""
    if conn.laddr and conn.laddr.port >= _EPHEMERAL_PORT_MIN:
        return True
    if conn.raddr and conn.raddr.port >= _EPHEMERAL_PORT_MIN:
        return True
    return False


def _is_external_target(ip: str) -> bool:
    """Return True if target IP is a known external/cloud service."""
    if ip in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "::"):
        return False
    if ip.startswith("10.") or ip.startswith("192.168."):
        return False
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            if 16 <= second <= 31:
                return False
        except (ValueError, IndexError):
            pass
    for prefix in _EXTERNAL_IP_PREFIXES:
        if ip.startswith(prefix):
            return True
    return False


def _is_browser_process(name: str) -> bool:
    """Return True if process name looks like a browser or desktop app."""
    name_clean = name.lower()
    if name_clean.endswith(".exe"):
        name_clean = name_clean[:-4]
    return name_clean in _BROWSER_PROCESSES or any(b in name_clean for b in _BROWSER_PROCESSES)


def _infer_dependency_type(port: int) -> str:
    """Infer dependency type from remote port number."""
    return _PORT_TYPE_MAP.get(port, "unknown")


class NetworkConnectionScanner(BaseDependencyAnalyzer):
    """Scans active network connections to infer service dependencies."""

    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry

    async def analyze(self) -> List[ServiceDependency]:
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

            # Skip ephemeral outbound connections (browser, apps)
            if _is_ephemeral_connection(conn):
                continue

            # Skip external/cloud targets (DNS, Google, etc.)
            if _is_external_target(remote_ip):
                continue

            # Skip browser/desktop app sources
            proc_name = ""
            try:
                if conn.pid:
                    proc = psutil.Process(conn.pid)
                    proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            if _is_browser_process(proc_name):
                continue

            # Find source service by PID (primary) or local endpoint (fallback)
            source_service = self._find_service_by_pid(conn.pid)
            if not source_service and conn.laddr:
                source_service = self._find_service_by_endpoint(
                    conn.laddr.ip, conn.laddr.port
                )

            # Only create edges if we know BOTH source AND target
            target_service = self._find_service_by_endpoint(remote_ip, remote_port)
            if not source_service or not target_service:
                continue

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

            target_service = self._find_service_by_endpoint(remote_ip, remote_port)
            if not target_service:
                continue  # Should not happen since we filtered above

            dependencies.append(
                ServiceDependency(
                    source_service_id=source_id,
                    target_service_id=target_service.service_id,
                    dependency_type=dep_type,
                    connection_count=count,
                    last_seen_at=datetime.now(timezone.utc),
                    confidence_score=0.8,
                    discovery_sources=["network"],
                )
            )

        logger.info(
            "NetworkConnectionScanner: %d connections scanned, %d real dependencies found",
            len(connections),
            len(dependencies),
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
