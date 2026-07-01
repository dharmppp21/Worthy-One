"""Process-based service discovery provider using psutil."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.discovery.base import ServiceDiscoveryProvider
from app.discovery.models import DiscoveredService

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

logger = logging.getLogger(__name__)

# System processes to skip
_SYSTEM_BLOCKLIST = frozenset(
    {
        "system",
        "kernel",
        "svchost",
        "services",
        "wininit",
        "winlogon",
        "csrss",
        "lsass",
        "smss",
        "crss",
        "registry",
        "fontdrvhost",
        "idle",
        "system idle process",
        "conhost",
        "dwm",
        "explorer",
        "taskhost",
        "runtimebroker",
        "searchindexer",
        "spoolsv",
        "wlanext",
        "audiodg",
        "mpnotify",
        "mscorsvw",
        "ngen",
        "sihost",
        "shell experiences host",
        "backgroundtaskhost",
        "securityhealthservice",
        "wudfhost",
        "psvc",
        "mpuxsrv",
    }
)

# Known port -> service_type mapping
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

# Executable name keywords -> service_name hint
_EXE_NAME_HINTS = {
    "nginx": "nginx",
    "postgres": "postgres",
    "python": "python-app",
    "node": "node-app",
    "java": "java-app",
    "redis-server": "redis",
    "redis": "redis",
    "mongod": "mongodb",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "kafka": "kafka",
    "zookeeper": "zookeeper",
    "elasticsearch": "elasticsearch",
    "kibana": "kibana",
    "go": "go-app",
    "dotnet": "dotnet-app",
}


def _get_service_name_from_exe(exe_path: Optional[str], fallback_name: str) -> str:
    """Map executable path/name to a clean service name."""
    if exe_path:
        base = os.path.basename(exe_path).lower()
        # Remove extension on Windows
        base = os.path.splitext(base)[0]
        for keyword, hint in _EXE_NAME_HINTS.items():
            if keyword in base:
                return hint
        return base
    return fallback_name


def _get_service_type_from_port(port: int) -> str:
    """Infer service type from listening port."""
    return _PORT_TYPE_MAP.get(port, "unknown")


def _is_system_process(name: str) -> bool:
    """Return True if the process name is a known system process."""
    name_clean = name.lower()
    # Strip Windows .exe extension for lookup
    if name_clean.endswith(".exe"):
        name_clean = name_clean[:-4]
    return name_clean in _SYSTEM_BLOCKLIST


class ProcessDiscoveryProvider(ServiceDiscoveryProvider):
    """Discovers services by scanning local process listening ports."""

    async def health_check(self) -> bool:
        """Verify psutil is available and process_iter works."""
        if psutil is None:
            return False
        try:
            # Try to iterate processes once
            for p in psutil.process_iter(attrs=["name"]):
                break
            return True
        except (PermissionError, Exception) as exc:
            logger.debug("psutil health check failed: %s", exc)
            return False

    async def discover(self) -> List[DiscoveredService]:
        """Scan local processes and return services with listening ports."""
        if psutil is None:  # pragma: no cover
            logger.warning("psutil is not installed; process discovery skipped.")
            return []

        discovered: List[DiscoveredService] = []
        seen_keys: set = set()

        for proc in psutil.process_iter(
            attrs=[
                "pid",
                "name",
                "exe",
                "cmdline",
                "username",
                "create_time",
                "cpu_percent",
                "memory_percent",
            ]
        ):
            try:
                info = proc.info
                proc_name = (info.get("name") or "").lower()

                if _is_system_process(proc_name):
                    continue

                exe = info.get("exe")
                service_name = _get_service_name_from_exe(exe, proc_name)
                if not service_name:
                    continue

                # Gather connections
                connections = proc.connections(kind="inet")
                listening_addrs: List[Tuple[str, int]] = []
                for conn in connections:
                    if conn.status != psutil.CONN_LISTEN:
                        continue
                    addr = conn.laddr
                    if addr:
                        ip = addr.ip or "127.0.0.1"
                        port = addr.port
                        if (ip, port) not in listening_addrs:
                            listening_addrs.append((ip, port))

                if not listening_addrs:
                    continue

                # Determine service type from the first listening port
                first_port = listening_addrs[0][1]
                service_type = _get_service_type_from_port(first_port)

                endpoints = [f"tcp://{ip}:{port}" for ip, port in listening_addrs]
                host = listening_addrs[0][0]

                # Build metadata
                metadata: Dict[str, Any] = {
                    "pid": info.get("pid"),
                    "exe": exe,
                    "cmdline": info.get("cmdline") or [],
                    "username": info.get("username"),
                    "create_time": (
                        datetime.fromtimestamp(
                            info["create_time"], tz=timezone.utc
                        ).isoformat()
                        if info.get("create_time")
                        else None
                    ),
                    "cpu_percent": info.get("cpu_percent"),
                    "memory_percent": info.get("memory_percent"),
                }

                # Remove None values
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
                        discovery_source="process",
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError):
                continue
            except Exception as exc:  # pragma: no cover
                logger.debug(
                    "Unexpected error scanning process %s: %s",
                    proc.info.get("pid", "?"),
                    exc,
                )
                continue

        return discovered
