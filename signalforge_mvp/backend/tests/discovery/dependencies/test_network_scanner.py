"""Tests for the NetworkConnectionScanner and DependencyRegistry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
from app.discovery.dependencies.network_scanner import (
    NetworkConnectionScanner,
    _infer_dependency_type,
)
from app.discovery.dependencies.registry import DependencyRegistry
from app.discovery.models import DiscoveredService
from app.discovery.registry import ServiceRegistry


# ------------------------------------------------------------------
# Helper function tests
# ------------------------------------------------------------------

def test_infer_dependency_type():
    assert _infer_dependency_type(5432) == "database"
    assert _infer_dependency_type(6379) == "cache"
    assert _infer_dependency_type(9092) == "message_queue"
    assert _infer_dependency_type(80) == "http"
    assert _infer_dependency_type(50051) == "grpc"
    assert _infer_dependency_type(99999) == "unknown"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
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
    return ServiceRegistry(db_session=db_session)


@pytest.fixture
def dep_registry(db_session):
    return DependencyRegistry(db_session=db_session)


@pytest.fixture
def scanner(registry):
    return NetworkConnectionScanner(registry=registry)


# ------------------------------------------------------------------
# NetworkConnectionScanner tests
# ------------------------------------------------------------------

def _make_mock_connection(pid, laddr_ip, laddr_port, raddr_ip, raddr_port, status="ESTABLISHED"):
    """Build a mock psutil connection object."""
    conn = MagicMock()
    conn.pid = pid
    conn.laddr = MagicMock()
    conn.laddr.ip = laddr_ip
    conn.laddr.port = laddr_port
    conn.raddr = MagicMock()
    conn.raddr.ip = raddr_ip
    conn.raddr.port = raddr_port
    conn.status = status
    return conn


@pytest.mark.asyncio
async def test_scan_no_psutil(scanner):
    with patch("app.discovery.dependencies.network_scanner.psutil", None):
        result = await scanner.scan()
    assert result == []


@pytest.mark.asyncio
async def test_scan_permission_error(scanner):
    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(side_effect=PermissionError("access denied"))
        result = await scanner.scan()
    assert result == []


@pytest.mark.asyncio
async def test_scan_no_connections(scanner, registry):
    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()
    assert result == []


@pytest.mark.asyncio
async def test_scan_finds_dependency(scanner, registry):
    """A process with PID 1234 connects to a known service on port 5432."""
    svc_source = DiscoveredService(
        service_name="web-api",
        host="127.0.0.1",
        endpoints=["tcp://127.0.0.1:8080"],
        metadata={"pid": 1234},
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="postgres",
        host="10.0.0.5",
        endpoints=["tcp://10.0.0.5:5432"],
        metadata={"pid": 5678},
        discovery_source="process",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    conn = _make_mock_connection(1234, "127.0.0.1", 45678, "10.0.0.5", 5432)

    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[conn])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()

    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_source.service_id
    assert dep.target_service_id == svc_target.service_id
    assert dep.dependency_type == "database"
    assert dep.connection_count == 1
    assert dep.confidence_score == 0.8
    assert dep.discovery_sources == ["network"]


@pytest.mark.asyncio
async def test_scan_skips_listen_connections(scanner, registry):
    """LISTEN connections should be skipped."""
    svc = DiscoveredService(
        service_name="api",
        host="127.0.0.1",
        endpoints=["tcp://127.0.0.1:8080"],
        metadata={"pid": 1234},
        discovery_source="process",
    )
    registry.register_service(svc)

    conn = _make_mock_connection(1234, "0.0.0.0", 8080, None, None, status="LISTEN")
    conn.raddr = None

    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[conn])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()

    assert result == []


@pytest.mark.asyncio
async def test_scan_inferred_service(scanner, registry):
    """If remote endpoint is not in registry, create inferred service with low confidence."""
    svc_source = DiscoveredService(
        service_name="worker",
        host="127.0.0.1",
        endpoints=["tcp://127.0.0.1:5000"],
        metadata={"pid": 9999},
        discovery_source="process",
    )
    registry.register_service(svc_source)

    conn = _make_mock_connection(9999, "127.0.0.1", 56789, "10.0.0.10", 6379)

    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[conn])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()

    assert len(result) == 1
    dep = result[0]
    assert dep.source_service_id == svc_source.service_id
    assert dep.dependency_type == "cache"
    assert dep.confidence_score == 0.3
    assert dep.target_service_id.startswith("inferred-")


@pytest.mark.asyncio
async def test_scan_deduplicates_connections(scanner, registry):
    """Multiple connections between same source/target should be counted."""
    svc_source = DiscoveredService(
        service_name="api",
        host="127.0.0.1",
        endpoints=["tcp://127.0.0.1:8080"],
        metadata={"pid": 1111},
        discovery_source="process",
    )
    svc_target = DiscoveredService(
        service_name="redis",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:6379"],
        metadata={"pid": 2222},
        discovery_source="process",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_target)

    conn1 = _make_mock_connection(1111, "127.0.0.1", 45000, "10.0.0.2", 6379)
    conn2 = _make_mock_connection(1111, "127.0.0.1", 45001, "10.0.0.2", 6379)

    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[conn1, conn2])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()

    assert len(result) == 1
    assert result[0].connection_count == 2


@pytest.mark.asyncio
async def test_scan_ignores_unknown_source_pid(scanner, registry):
    """If the local process PID is not in registry, skip it."""
    conn = _make_mock_connection(7777, "127.0.0.1", 45678, "10.0.0.5", 5432)

    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[conn])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()

    assert result == []


@pytest.mark.asyncio
async def test_scan_multiple_different_targets(scanner, registry):
    """One source connecting to multiple targets creates multiple dependencies."""
    svc_source = DiscoveredService(
        service_name="api",
        host="127.0.0.1",
        endpoints=["tcp://127.0.0.1:8080"],
        metadata={"pid": 3333},
        discovery_source="process",
    )
    svc_db = DiscoveredService(
        service_name="postgres",
        host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:5432"],
        metadata={"pid": 4444},
        discovery_source="process",
    )
    svc_cache = DiscoveredService(
        service_name="redis",
        host="10.0.0.2",
        endpoints=["tcp://10.0.0.2:6379"],
        metadata={"pid": 5555},
        discovery_source="process",
    )
    registry.register_service(svc_source)
    registry.register_service(svc_db)
    registry.register_service(svc_cache)

    conn1 = _make_mock_connection(3333, "127.0.0.1", 46000, "10.0.0.1", 5432)
    conn2 = _make_mock_connection(3333, "127.0.0.1", 46001, "10.0.0.2", 6379)

    with patch("app.discovery.dependencies.network_scanner.psutil") as mock_psutil:
        mock_psutil.net_connections = MagicMock(return_value=[conn1, conn2])
        mock_psutil.CONN_ESTABLISHED = "ESTABLISHED"
        result = await scanner.scan()

    assert len(result) == 2
    types = {d.dependency_type for d in result}
    assert types == {"database", "cache"}


# ------------------------------------------------------------------
# DependencyRegistry tests
# ------------------------------------------------------------------

def test_store_dependency_new(dep_registry, db_session):
    dep = ServiceDependency(
        source_service_id="svc-a",
        target_service_id="svc-b",
        dependency_type="http",
        connection_count=3,
        confidence_score=0.8,
        discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep)

    stored = dep_registry.get_all_dependencies()
    assert len(stored) == 1
    assert stored[0].source_service_id == "svc-a"
    assert stored[0].target_service_id == "svc-b"
    assert stored[0].connection_count == 3
    assert stored[0].confidence_score == 0.8


def test_store_dependency_upsert(dep_registry, db_session):
    dep1 = ServiceDependency(
        source_service_id="svc-a",
        target_service_id="svc-b",
        dependency_type="http",
        connection_count=1,
        confidence_score=0.5,
        discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep1)

    dep2 = ServiceDependency(
        source_service_id="svc-a",
        target_service_id="svc-b",
        dependency_type="http",
        connection_count=5,
        confidence_score=0.9,
        discovery_sources=["network", "manual"],
    )
    dep_registry.store_dependency(dep2)

    stored = dep_registry.get_all_dependencies()
    assert len(stored) == 1
    assert stored[0].connection_count == 5
    assert stored[0].confidence_score == 0.9
    # Discovery sources should be deduplicated union
    assert set(stored[0].discovery_sources) == {"network", "manual"}


def test_get_dependencies_filter(dep_registry, db_session):
    dep1 = ServiceDependency(
        source_service_id="svc-a", target_service_id="svc-b",
        dependency_type="http", confidence_score=0.8,
        discovery_sources=["network"],
    )
    dep2 = ServiceDependency(
        source_service_id="svc-c", target_service_id="svc-d",
        dependency_type="database", confidence_score=0.3,
        discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep1)
    dep_registry.store_dependency(dep2)

    by_source = dep_registry.get_dependencies(source_id="svc-a")
    assert len(by_source) == 1
    assert by_source[0].target_service_id == "svc-b"

    by_target = dep_registry.get_dependencies(target_id="svc-d")
    assert len(by_target) == 1
    assert by_target[0].source_service_id == "svc-c"

    high_conf = dep_registry.get_dependencies(min_confidence=0.5)
    assert len(high_conf) == 1
    assert high_conf[0].confidence_score == 0.8


def test_remove_stale_dependencies(dep_registry, db_session):
    now = datetime.now(timezone.utc)
    old = now - timedelta(seconds=600)

    fresh_dep = ServiceDependency(
        source_service_id="svc-a", target_service_id="svc-b",
        dependency_type="http", last_seen_at=now,
        discovery_sources=["network"],
    )
    stale_dep = ServiceDependency(
        source_service_id="svc-c", target_service_id="svc-d",
        dependency_type="database", last_seen_at=old,
        discovery_sources=["network"],
    )
    dep_registry.store_dependency(fresh_dep)
    dep_registry.store_dependency(stale_dep)

    # Manually backdate the stale one in DB
    from app.models import ServiceDependencyDB
    db_obj = db_session.query(ServiceDependencyDB).filter_by(
        source_service_id="svc-c", target_service_id="svc-d"
    ).first()
    db_obj.last_seen_at = old
    db_session.commit()

    removed = dep_registry.remove_stale_dependencies(timeout_seconds=300)
    assert removed == 1

    remaining = dep_registry.get_all_dependencies()
    assert len(remaining) == 1
    assert remaining[0].source_service_id == "svc-a"


def test_get_dependency_graph(dep_registry, db_session):
    dep = ServiceDependency(
        source_service_id="svc-a", target_service_id="svc-b",
        dependency_type="http", confidence_score=0.9,
        discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep)

    svc_a = DiscoveredService(
        service_name="api", host="127.0.0.1",
        endpoints=["tcp://127.0.0.1:8080"],
    )
    svc_b = DiscoveredService(
        service_name="db", host="10.0.0.1",
        endpoints=["tcp://10.0.0.1:5432"],
    )

    graph = dep_registry.get_dependency_graph([svc_a, svc_b])
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.edges[0].source_service_id == "svc-a"


def test_cache_syncs_on_write(dep_registry, db_session):
    dep = ServiceDependency(
        source_service_id="svc-a", target_service_id="svc-b",
        dependency_type="http", discovery_sources=["network"],
    )
    dep_registry.store_dependency(dep)

    # Direct DB update should reflect after cache refresh
    from app.models import ServiceDependencyDB
    db_obj = db_session.query(ServiceDependencyDB).filter_by(
        source_service_id="svc-a", target_service_id="svc-b"
    ).first()
    db_obj.connection_count = 99
    db_session.commit()

    # get_dependencies should refresh cache
    deps = dep_registry.get_dependencies(source_id="svc-a")
    assert deps[0].connection_count == 99


# ------------------------------------------------------------------
# DependencyGraph tests
# ------------------------------------------------------------------

def test_get_upstream_downstream():
    edges = [
        ServiceDependency(source_service_id="a", target_service_id="b", dependency_type="http"),
        ServiceDependency(source_service_id="c", target_service_id="b", dependency_type="http"),
        ServiceDependency(source_service_id="b", target_service_id="d", dependency_type="database"),
    ]
    graph = DependencyGraph(edges=edges)

    upstream = graph.get_upstream("b")
    assert len(upstream) == 2
    assert {e.source_service_id for e in upstream} == {"a", "c"}

    downstream = graph.get_downstream("b")
    assert len(downstream) == 1
    assert downstream[0].target_service_id == "d"


def test_get_critical_path():
    edges = [
        ServiceDependency(source_service_id="a", target_service_id="b", dependency_type="http"),
        ServiceDependency(source_service_id="b", target_service_id="c", dependency_type="http"),
        ServiceDependency(source_service_id="c", target_service_id="d", dependency_type="database"),
        ServiceDependency(source_service_id="a", target_service_id="e", dependency_type="http"),
    ]
    graph = DependencyGraph(edges=edges)

    path = graph.get_critical_path("a", "d")
    assert len(path) == 3
    assert path[0].target_service_id == "b"
    assert path[1].target_service_id == "c"
    assert path[2].target_service_id == "d"


def test_get_critical_path_same_source_target():
    graph = DependencyGraph(edges=[])
    assert graph.get_critical_path("a", "a") == []


def test_get_critical_path_no_path():
    edges = [
        ServiceDependency(source_service_id="a", target_service_id="b", dependency_type="http"),
    ]
    graph = DependencyGraph(edges=edges)
    assert graph.get_critical_path("a", "z") == []


def test_service_dependency_confidence_validator():
    """Confidence score must be between 0.0 and 1.0."""
    with pytest.raises(ValueError):
        ServiceDependency(
            source_service_id="a", target_service_id="b",
            confidence_score=1.5,
        )

    with pytest.raises(ValueError):
        ServiceDependency(
            source_service_id="a", target_service_id="b",
            confidence_score=-0.1,
        )

    # Valid edge cases
    dep = ServiceDependency(
        source_service_id="a", target_service_id="b",
        confidence_score=0.0,
    )
    assert dep.confidence_score == 0.0

    dep = ServiceDependency(
        source_service_id="a", target_service_id="b",
        confidence_score=1.0,
    )
    assert dep.confidence_score == 1.0
