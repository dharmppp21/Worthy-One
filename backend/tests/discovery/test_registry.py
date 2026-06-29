"""Tests for the ServiceRegistry CRUD and caching logic."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry
from app.models import DiscoveredServiceDB


@pytest.fixture(scope="function")
def db_session():
    """Create an in-memory SQLite DB and yield a session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def registry(db_session):
    """Fresh ServiceRegistry backed by a SQLite session."""
    return ServiceRegistry(db_session=db_session)


# ------------------------------------------------------------------
# Basic CRUD
# ------------------------------------------------------------------

def test_register_new_service(registry, db_session):
    """register_service should insert a new record and return its ID."""
    svc = DiscoveredService(service_name="web", host="10.0.0.1")
    sid = registry.register_service(svc)
    assert sid is not None
    assert len(sid) == 36  # UUID length

    # Verify DB state
    db_obj = db_session.query(DiscoveredServiceDB).filter_by(service_id=sid).first()
    assert db_obj is not None
    assert db_obj.service_name == "web"
    assert db_obj.host == "10.0.0.1"
    assert db_obj.is_active is True


def test_register_existing_service_updates(registry, db_session):
    """Registering the same (service_name, host) should update, not duplicate."""
    svc1 = DiscoveredService(
        service_name="api", host="10.0.0.2", service_type="http", endpoints=["http://10.0.0.2:80"]
    )
    sid1 = registry.register_service(svc1)

    svc2 = DiscoveredService(
        service_name="api", host="10.0.0.2", service_type="grpc", endpoints=["grpc://10.0.0.2:50051"]
    )
    sid2 = registry.register_service(svc2)

    assert sid1 == sid2, "Same (name, host) should produce the same service_id"

    # DB should have only one row
    count = db_session.query(DiscoveredServiceDB).filter_by(service_name="api", host="10.0.0.2").count()
    assert count == 1

    db_obj = db_session.query(DiscoveredServiceDB).filter_by(service_id=sid1).first()
    assert db_obj.service_type == "grpc"
    assert db_obj.endpoints == ["grpc://10.0.0.2:50051"]


def test_get_service(registry):
    """get_service should return the correct service or None."""
    svc = DiscoveredService(service_name="db", host="10.0.0.3")
    sid = registry.register_service(svc)

    fetched = registry.get_service(sid)
    assert fetched is not None
    assert fetched.service_name == "db"
    assert fetched.host == "10.0.0.3"

    assert registry.get_service("non-existent-id") is None


def test_list_services(registry, db_session):
    """list_services should return all active services by default."""
    svc_a = DiscoveredService(service_name="svc-a", host="10.0.0.4")
    svc_b = DiscoveredService(service_name="svc-b", host="10.0.0.5")
    registry.register_service(svc_a)
    registry.register_service(svc_b)

    all_active = registry.list_services()
    assert len(all_active) == 2

    # Mark one inactive manually
    db_obj = db_session.query(DiscoveredServiceDB).filter_by(service_name="svc-a").first()
    db_obj.is_active = False
    db_session.commit()

    active_only = registry.list_services(active_only=True)
    assert len(active_only) == 1
    assert active_only[0].service_name == "svc-b"

    all_including_inactive = registry.list_services(active_only=False)
    assert len(all_including_inactive) == 2


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------

def test_update_heartbeat(registry):
    """update_heartbeat should refresh timestamps."""
    svc = DiscoveredService(service_name="worker", host="10.0.0.6")
    sid = registry.register_service(svc)

    # Small sleep to ensure timestamp changes
    time.sleep(0.01)
    registry.update_heartbeat(sid)

    fetched = registry.get_service(sid)
    assert fetched.last_heartbeat_at > svc.last_heartbeat_at


def test_update_heartbeat_not_found(registry):
    """update_heartbeat on a missing service should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        registry.update_heartbeat("missing-id")


# ------------------------------------------------------------------
# Stale removal
# ------------------------------------------------------------------

def test_remove_stale_services(registry, db_session):
    """remove_stale_services should mark old services inactive."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(seconds=300)

    svc = DiscoveredService(service_name="stale", host="10.0.0.7")
    sid = registry.register_service(svc)

    # Manually backdate the heartbeat
    db_obj = db_session.query(DiscoveredServiceDB).filter_by(service_id=sid).first()
    db_obj.last_heartbeat_at = old
    db_obj.last_seen_at = old
    db_session.commit()

    removed = registry.remove_stale_services(timeout_seconds=120)
    assert removed == 1

    db_obj = db_session.query(DiscoveredServiceDB).filter_by(service_id=sid).first()
    assert db_obj.is_active is False

    # Cache should no longer contain the stale service
    assert registry.get_service(sid) is None


def test_remove_stale_services_none(registry):
    """remove_stale_services should return 0 when nothing is stale."""
    svc = DiscoveredService(service_name="fresh", host="10.0.0.8")
    registry.register_service(svc)

    removed = registry.remove_stale_services(timeout_seconds=120)
    assert removed == 0

    active = registry.list_services(active_only=True)
    assert len(active) == 1


# ------------------------------------------------------------------
# Cache consistency
# ------------------------------------------------------------------

def test_cache_syncs_on_read(registry, db_session):
    """Modifying the DB directly should reflect in cache after a read."""
    svc = DiscoveredService(service_name="cache-test", host="10.0.0.9")
    sid = registry.register_service(svc)

    # Direct DB update
    db_obj = db_session.query(DiscoveredServiceDB).filter_by(service_id=sid).first()
    db_obj.service_name = "cache-test-renamed"
    db_session.commit()

    # Cache should be stale until we call a read method that refreshes
    fetched = registry.get_service(sid)
    assert fetched.service_name == "cache-test-renamed"
