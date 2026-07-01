"""Dependency registry: persists service dependencies to PostgreSQL and caches them."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.discovery.dependencies.models import DependencyGraph, ServiceDependency
from app.discovery.models import DiscoveredService
from app.models import ServiceDependencyDB

logger = logging.getLogger(__name__)


class DependencyRegistry:
    """Registry that stores service dependencies in a relational database
    and keeps an in-memory cache for fast graph queries.
    """

    def __init__(self, db_session: Session) -> None:
        """
        Args:
            db_session: SQLAlchemy ORM session.
        """
        self._db: Session = db_session
        self._cache: Dict[str, ServiceDependency] = {}

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _to_db(self, dep: ServiceDependency) -> ServiceDependencyDB:
        """Convert a Pydantic model to an ORM instance."""
        return ServiceDependencyDB(
            id=str(uuid.uuid4()),
            source_service_id=dep.source_service_id,
            target_service_id=dep.target_service_id,
            dependency_type=dep.dependency_type,
            connection_count=dep.connection_count,
            avg_latency_ms=dep.avg_latency_ms,
            error_rate=dep.error_rate,
            last_seen_at=dep.last_seen_at,
            confidence_score=dep.confidence_score,
            discovery_sources=dep.discovery_sources,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _to_model(db_obj: ServiceDependencyDB) -> ServiceDependency:
        """Convert an ORM instance to a Pydantic model."""

        def _ensure_utc(dt: datetime) -> datetime:
            """Ensure a datetime is timezone-aware UTC."""
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        return ServiceDependency(
            source_service_id=db_obj.source_service_id,
            target_service_id=db_obj.target_service_id,
            dependency_type=db_obj.dependency_type,
            connection_count=db_obj.connection_count or 1,
            avg_latency_ms=db_obj.avg_latency_ms,
            error_rate=db_obj.error_rate,
            last_seen_at=_ensure_utc(db_obj.last_seen_at),
            confidence_score=db_obj.confidence_score or 0.5,
            discovery_sources=db_obj.discovery_sources or [],
        )

    def _sync_cache(self, dep: ServiceDependency) -> None:
        """Upsert a dependency into the in-memory cache."""
        key = f"{dep.source_service_id}::{dep.target_service_id}"
        self._cache[key] = dep

    def _refresh_cache(self) -> None:
        """Load all dependencies from DB into the cache."""
        self._cache = {}
        for db_obj in self._db.query(ServiceDependencyDB).all():
            key = f"{db_obj.source_service_id}::{db_obj.target_service_id}"
            self._cache[key] = self._to_model(db_obj)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_dependency(self, dep: ServiceDependency) -> bool:
        """Upsert a dependency based on (source_service_id, target_service_id).

        Returns:
            True if the dependency was newly created, False if it was updated.
        """
        key = f"{dep.source_service_id}::{dep.target_service_id}"
        existing = (
            self._db.query(ServiceDependencyDB)
            .filter_by(
                source_service_id=dep.source_service_id,
                target_service_id=dep.target_service_id,
            )
            .first()
        )

        is_new = False
        now = datetime.now(timezone.utc)
        if existing:
            existing.connection_count = dep.connection_count
            existing.dependency_type = dep.dependency_type
            existing.confidence_score = dep.confidence_score
            existing.last_seen_at = dep.last_seen_at
            existing.updated_at = now
            existing.discovery_sources = list(
                set((existing.discovery_sources or []) + dep.discovery_sources)
            )
            if dep.avg_latency_ms is not None:
                existing.avg_latency_ms = dep.avg_latency_ms
            if dep.error_rate is not None:
                existing.error_rate = dep.error_rate
            self._db.commit()
            self._db.refresh(existing)
        else:
            db_obj = self._to_db(dep)
            db_obj.created_at = now
            db_obj.updated_at = now
            self._db.add(db_obj)
            self._db.commit()
            self._db.refresh(db_obj)
            is_new = True

        self._cache[key] = self._to_model(
            self._db.query(ServiceDependencyDB)
            .filter_by(
                source_service_id=dep.source_service_id,
                target_service_id=dep.target_service_id,
            )
            .first()
        )
        return is_new

    def get_dependencies(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> List[ServiceDependency]:
        """Get dependencies with optional filtering."""
        query = self._db.query(ServiceDependencyDB)
        if source_id is not None:
            query = query.filter_by(source_service_id=source_id)
        if target_id is not None:
            query = query.filter_by(target_service_id=target_id)

        deps = [self._to_model(db_obj) for db_obj in query.all()]
        deps = [d for d in deps if d.confidence_score >= min_confidence]

        # Sync cache
        for d in deps:
            self._cache[f"{d.source_service_id}::{d.target_service_id}"] = d
        return deps

    def get_all_dependencies(self) -> List[ServiceDependency]:
        """Return all stored dependencies."""
        return self.get_dependencies()

    def get_dependency_graph(
        self, services: List[DiscoveredService]
    ) -> DependencyGraph:
        """Build a DependencyGraph from all dependencies and the given service nodes."""
        edges = self.get_all_dependencies()
        return DependencyGraph(nodes=services, edges=edges)

    def remove_stale_dependencies(self, timeout_seconds: int = 300) -> int:
        """Remove dependencies whose last_seen_at is older than timeout_seconds."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=timeout_seconds)

        stale = (
            self._db.query(ServiceDependencyDB)
            .filter(ServiceDependencyDB.last_seen_at < cutoff)
            .all()
        )

        count = 0
        for db_obj in stale:
            key = f"{db_obj.source_service_id}::{db_obj.target_service_id}"
            self._cache.pop(key, None)
            self._db.delete(db_obj)
            count += 1

        self._db.commit()
        return count
