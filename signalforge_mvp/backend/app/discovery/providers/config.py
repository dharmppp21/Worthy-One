"""Config-based service discovery provider (JSON/YAML from env or file)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from app.discovery.base import ServiceDiscoveryProvider
from app.discovery.models import DiscoveredService

logger = logging.getLogger(__name__)


def _load_yaml(data: str) -> Any:
    """Load YAML string if pyyaml is available."""
    try:
        import yaml

        return yaml.safe_load(data)
    except ImportError:
        raise ImportError("pyyaml is not installed; cannot parse YAML config")


class ConfigDiscoveryProvider(ServiceDiscoveryProvider):
    """Discovers services from a JSON/YAML config source."""

    def __init__(
        self,
        env_var: str = "SIGNALFORGE_SERVICES",
        file_env_var: str = "SIGNALFORGE_SERVICES_CONFIG",
    ) -> None:
        """
        Args:
            env_var: Environment variable containing JSON service list.
            file_env_var: Environment variable with path to a JSON/YAML config file.
        """
        self._env_var = env_var
        self._file_env_var = file_env_var

    async def health_check(self) -> bool:
        """Always returns True — config provider is passive."""
        return True

    async def discover(self) -> List[DiscoveredService]:
        """Read services from environment variable or config file."""
        raw_data = self._load_data()
        if not raw_data:
            return []

        discovered: List[DiscoveredService] = []
        for item in raw_data:
            try:
                name = item.get("name")
                if not name:
                    continue
                endpoints = item.get("endpoints", [])
                host = item.get("host") or "127.0.0.1"
                if endpoints and host == "127.0.0.1":
                    # Try to extract host from first endpoint
                    try:
                        host = endpoints[0].split("://")[1].split(":")[0]
                    except (IndexError, ValueError):
                        pass

                metadata = dict(item.get("metadata", {}))
                metadata["discovery_source"] = "config"

                discovered.append(
                    DiscoveredService(
                        service_name=name,
                        service_type=item.get("type", "unknown"),
                        endpoints=endpoints,
                        host=host,
                        metadata=metadata,
                        discovery_source="config",
                    )
                )
            except Exception as exc:
                logger.warning("Invalid config entry: %s", exc)
                continue

        return discovered

    def _load_data(self) -> List[Dict[str, Any]]:
        """Load raw data from env var or file. Returns list of dicts."""
        # Check env var first
        env_value = os.environ.get(self._env_var)
        if env_value:
            try:
                return json.loads(env_value)
            except json.JSONDecodeError as exc:
                # Try YAML
                try:
                    return _load_yaml(env_value)
                except Exception:
                    logger.warning("Failed to parse %s: %s", self._env_var, exc)
                    return []

        # Check file path
        file_path = os.environ.get(self._file_env_var)
        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if file_path.endswith((".yaml", ".yml")):
                    return _load_yaml(content)
                return json.loads(content)
            except Exception as exc:
                logger.warning("Failed to read config file %s: %s", file_path, exc)
                return []

        return []
