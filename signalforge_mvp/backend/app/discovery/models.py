"""
Pydantic models for service discovery.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class ProbeStatus(str, Enum):
    """Health probe status enum."""
    up = "up"
    down = "down"
    unknown = "unknown"


class ProbeType(str, Enum):
    """Health probe type enum."""
    http = "http"
    tcp = "tcp"


class HealthProbeResult(BaseModel):
    """Result of a single health probe attempt."""

    model_config = ConfigDict(populate_by_name=True)

    service_id: str
    status: ProbeStatus
    probe_type: ProbeType
    endpoint: Optional[str] = None
    response_time_ms: Optional[float] = None
    response_status_code: Optional[int] = None
    response_body_preview: Optional[str] = Field(default=None, max_length=200)
    error_message: Optional[str] = None
    probed_at: datetime = Field(default_factory=_utc_now)


class DiscoveredService(BaseModel):
    """
    Represents a service discovered by a discovery provider.

    Fields:
        service_id: Unique identifier (UUID), auto-generated.
        service_name: Human-readable service name.
        service_type: Service category (e.g. 'api', 'database', 'cache').
        endpoints: List of URIs exposed by the service.
        host: IP address or hostname of the service.
        metadata: Open-ended key-value metadata.
        health_check_url: Optional URL to check service health.
        health_status: Optional health status from probing.
        discovery_source: Origin of discovery (e.g. 'docker', 'kubernetes', 'manual').
        first_seen_at: UTC timestamp when first discovered.
        last_seen_at: UTC timestamp of most recent discovery.
        last_heartbeat_at: UTC timestamp of last known heartbeat.
    """

    model_config = ConfigDict(populate_by_name=True)

    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    service_name: str
    service_type: str = Field(default="unknown")
    endpoints: List[str] = Field(default_factory=list)
    host: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    health_check_url: Optional[str] = None
    health_status: Optional[str] = Field(default=None)
    discovery_source: str = Field(default="manual")
    first_seen_at: datetime = Field(default_factory=_utc_now)
    last_seen_at: datetime = Field(default_factory=_utc_now)
    last_heartbeat_at: datetime = Field(default_factory=_utc_now)
