"""Shared fixtures for all integration tests.

Provides DB, registry, discovery engine, and common cleanup so each test file
can focus on its own assertions.
"""
from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.discovery.engine import DiscoveryEngine
from app.discovery.providers.docker import DockerDiscoveryProvider
from app.discovery.providers.kubernetes import KubernetesDiscoveryProvider
from app.discovery.providers.process import ProcessDiscoveryProvider
from app.discovery.registry import ServiceRegistry
from tests.integration.docker_mocks import build_mock_docker_client, make_all_containers


@pytest.fixture(scope="module")
def setup_db():
    """Ensure tables are created for the module."""
    init_db()


@pytest.fixture
def db_session(setup_db) -> Generator[Session, None, None]:
    """Fresh DB session per test."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def registry(db_session: Session) -> ServiceRegistry:
    """Registry backed by a fresh DB session."""
    return ServiceRegistry(db_session=db_session)


@pytest.fixture
def discovery_engine(registry: ServiceRegistry) -> DiscoveryEngine:
    """Engine wired to the registry."""
    return DiscoveryEngine(registry=registry)


@pytest.fixture
def docker_provider() -> DockerDiscoveryProvider:
    """Docker provider (will be mocked by fixtures)."""
    return DockerDiscoveryProvider()


@pytest.fixture
def k8s_provider() -> KubernetesDiscoveryProvider:
    """Kubernetes provider with no namespace filter (will be mocked)."""
    return KubernetesDiscoveryProvider(namespace=None)


@pytest.fixture
def process_provider() -> ProcessDiscoveryProvider:
    """Process provider (will be mocked by fixtures)."""
    return ProcessDiscoveryProvider()


@pytest.fixture
def mock_docker_client():
    """Context manager that patches docker.from_env() with 5 fake containers."""
    containers = make_all_containers()
    mock_client = build_mock_docker_client(containers)

    with patch("docker.from_env", return_value=mock_client):
        yield mock_client


@pytest.fixture(autouse=True)
def cleanup_registry(db_session: Session) -> Generator[None, None, None]:
    """After each test, mark all discovered services inactive so the next test starts fresh."""
    yield
    from app.models import DiscoveredServiceDB
    db_session.query(DiscoveredServiceDB).update({"is_active": False})
    db_session.commit()
