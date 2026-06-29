"""Tests for the DiscoveredService Pydantic model."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.discovery.models import DiscoveredService


def test_default_creation():
    """A minimal model should be created with sensible defaults."""
    svc = DiscoveredService(service_name="test-svc", host="127.0.0.1")
    assert svc.service_name == "test-svc"
    assert svc.host == "127.0.0.1"
    assert svc.service_type == "unknown"
    assert svc.endpoints == []
    assert svc.metadata == {}
    assert svc.health_check_url is None
    assert svc.discovery_source == "manual"
    # UUID auto-generated
    assert isinstance(svc.service_id, str)
    assert len(svc.service_id) == 36
    # All datetimes are timezone-aware and in UTC
    assert svc.first_seen_at.tzinfo is not None
    assert svc.last_seen_at.tzinfo is not None
    assert svc.last_heartbeat_at.tzinfo is not None


def test_full_creation():
    """A fully populated model should retain all values."""
    now = datetime.now(timezone.utc)
    svc = DiscoveredService(
        service_id="abc-123",
        service_name="api-gateway",
        service_type="api",
        endpoints=["http://10.0.0.1:8080", "tcp://10.0.0.1:5432"],
        host="10.0.0.1",
        metadata={"version": "1.2.3"},
        health_check_url="http://10.0.0.1:8080/health",
        discovery_source="docker",
        first_seen_at=now,
        last_seen_at=now,
        last_heartbeat_at=now,
    )
    assert svc.service_id == "abc-123"
    assert svc.endpoints == ["http://10.0.0.1:8080", "tcp://10.0.0.1:5432"]
    assert svc.metadata == {"version": "1.2.3"}
    assert svc.health_check_url == "http://10.0.0.1:8080/health"
    assert svc.discovery_source == "docker"


def test_serialization_roundtrip():
    """Model should serialize to JSON and back correctly."""
    svc = DiscoveredService(
        service_name="cache",
        service_type="redis",
        endpoints=["tcp://127.0.0.1:6379"],
        host="127.0.0.1",
        metadata={"cluster": "primary"},
        discovery_source="kubernetes",
    )
    data = json.loads(svc.model_dump_json())
    assert data["service_name"] == "cache"
    assert data["service_type"] == "redis"
    assert data["endpoints"] == ["tcp://127.0.0.1:6379"]
    # JSON-encoded datetime is ISO 8601 with timezone
    assert "T" in data["first_seen_at"]
    assert data["first_seen_at"].endswith("Z") or data["first_seen_at"].endswith("+00:00")

    # Round-trip
    svc2 = DiscoveredService(**data)
    assert svc2.service_name == svc.service_name
    assert svc2.host == svc.host
    assert svc2.first_seen_at.tzinfo is not None


def test_invalid_missing_required():
    """Missing required fields should raise ValidationError."""
    with pytest.raises(ValidationError):
        DiscoveredService(service_name="only-name")

    with pytest.raises(ValidationError):
        DiscoveredService(host="only-host")
