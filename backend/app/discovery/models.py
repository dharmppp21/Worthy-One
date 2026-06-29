"""
Pydantic models for service discovery.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


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
        discovery_source: Origin of discovery (e.g. 'docker', 'kubernetes', 'manual').
        first_seen_at: UTC timestamp when first discovered.
        last_seen_at: UTC timestamp of most recent discovery.
        last_heartbeat_at: UTC timestamp of last known heartbeat.
    """

    model_config = ConfigDict(
        populate_by_name=True,
    )

    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    service_name: str
    service_type: str = Field(default="unknown")
    endpoints: List[str] = Field(default_factory=list)
    host: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    health_check_url: Optional[str] = None
    discovery_source: str = Field(default="manual")
    first_seen_at: datetime = Field(default_factory=_utc_now)
    last_seen_at: datetime = Field(default_factory=_utc_now)
    last_heartbeat_at: datetime = Field(default_factory=_utc_now)
