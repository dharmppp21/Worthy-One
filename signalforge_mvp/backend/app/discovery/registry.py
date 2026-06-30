"""
Service registry: persists discovered services to PostgreSQL and caches them in memory.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .models import DiscoveredService
from app.models import DiscoveredServiceDB

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """
    Registry that stores discovered services in a relational database
    and keeps an in-memory cache for fast lookups.
    """

    def __init__(self, db_session: Session) -> None:
        """
        Args:
            db_session: SQLAlchemy ORM session.
        """
        self._db: Session = db_session
        # In-memory cache keyed by service_id. Synced with DB on every read.
        self._cache: Dict[str, DiscoveredService] = {}

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _to_db(self, service: DiscoveredService) -> DiscoveredServiceDB:
        """Convert a Pydantic model to an ORM instance."""
        return DiscoveredServiceDB(
            id=service.service_id,
            service_id=service.service_id,
            service_name=service.service_name,
            service_type=service.service_type,
            endpoints=service.endpoints,
            host=service.host,
            metadata_=service.metadata,
            health_check_url=service.health_check_url,
            health_status=service.health_status,
            discovery_source=service.discovery_source,
            is_active=True,
            first_seen_at=service.first_seen_at,
            last_seen_at=service.last_seen_at,
            last_heartbeat_at=service.last_heartbeat_at,
        )

    @staticmethod
    def _to_model(db_obj: DiscoveredServiceDB) -> DiscoveredService:
        """Convert an ORM instance to a Pydantic model."""

        def ensure_utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        return DiscoveredService(
            service_id=db_obj.service_id,
            service_name=db_obj.service_name,
            service_type=db_obj.service_type,
            endpoints=db_obj.endpoints or [],
            host=db_obj.host,
            metadata=db_obj.metadata_ or {},
            health_check_url=db_obj.health_check_url,
            health_status=db_obj.health_status,
            discovery_source=db_obj.discovery_source,
            first_seen_at=ensure_utc(db_obj.first_seen_at),
            last_seen_at=ensure_utc(db_obj.last_seen_at),
            last_heartbeat_at=ensure_utc(db_obj.last_heartbeat_at),
        )

    def _refresh_cache(self) -> None:
        """Load all active services from DB into the cache."""
        self._cache = {}
        for db_obj in self._db.query(DiscoveredServiceDB).filter_by(is_active=True).all():
            self._cache[db_obj.service_id] = self._to_model(db_obj)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_service(self, service: DiscoveredService) -> tuple[str, bool]:
        """
        Register or update a service.

        Deduplication is based on (service_name, host). If a matching record
        exists, it is updated; otherwise a new row is inserted.

        Args:
            service: The service to register.

        Returns:
            Tuple of (service_id, is_new) where is_new is True if the service
            was just created.
        """
        now = datetime.now(timezone.utc)
        existing = (
            self._db.query(DiscoveredServiceDB)
            .filter_by(service_name=service.service_name, host=service.host)
            .first()
        )

        is_new = False
        if existing:
            # Update existing record
            existing.service_type = service.service_type
            existing.endpoints = service.endpoints
            existing.metadata_ = service.metadata
            existing.health_check_url = service.health_check_url
            existing.discovery_source = service.discovery_source
            existing.is_active = True
            existing.last_seen_at = now
            existing.last_heartbeat_at = now
            self._db.commit()
            self._db.refresh(existing)
            service_id = existing.service_id
        else:
            # Insert new record
            db_obj = self._to_db(service)
            db_obj.first_seen_at = now
            db_obj.last_seen_at = now
            db_obj.last_heartbeat_at = now
            self._db.add(db_obj)
            self._db.commit()
            self._db.refresh(db_obj)
            service_id = db_obj.service_id
            is_new = True

        # Sync cache
        self._cache[service_id] = self._to_model(
            self._db.query(DiscoveredServiceDB).filter_by(service_id=service_id).first()
        )
        return service_id, is_new

    def get_service(self, service_id: str) -> Optional[DiscoveredService]:
        """
        Retrieve a single service by ID.

        Args:
            service_id: The service UUID.

        Returns:
            The matching DiscoveredService or None.
        """
        self._refresh_cache()
        return self._cache.get(service_id)

    def list_services(
        self,
        tenant_id: Optional[str] = None,
        active_only: bool = True,
    ) -> List[DiscoveredService]:
        """
        List services, optionally filtered by tenant and active status.

        Args:
            tenant_id: Optional tenant filter.
            active_only: If True, only return services with is_active=True.

        Returns:
            A list of DiscoveredService objects.
        """
        query = self._db.query(DiscoveredServiceDB)
        if active_only:
            query = query.filter_by(is_active=True)
        if tenant_id is not None:
            query = query.filter_by(tenant_id=tenant_id)

        services = [self._to_model(db_obj) for db_obj in query.all()]
        # Rebuild cache from this result set
        self._cache = {s.service_id: s for s in services}
        return services

    def update_health_status(self, service_id: str, health_status: str) -> None:
        """
        Update the health status of a service.

        Args:
            service_id: The service UUID.
            health_status: The new health status string.

        Raises:
            ValueError: If the service is not found.
        """
        db_obj = self._db.query(DiscoveredServiceDB).filter_by(service_id=service_id).first()
        if not db_obj:
            raise ValueError(f"Service with id={service_id} not found")

        db_obj.health_status = health_status
        db_obj.last_seen_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(db_obj)

        self._cache[service_id] = self._to_model(db_obj)

    def update_heartbeat(self, service_id: str) -> None:
        """
        Update the heartbeat timestamp for a service.

        Args:
            service_id: The service UUID.

        Raises:
            ValueError: If the service is not found.
        """
        db_obj = self._db.query(DiscoveredServiceDB).filter_by(service_id=service_id).first()
        if not db_obj:
            raise ValueError(f"Service with id={service_id} not found")

        now = datetime.now(timezone.utc)
        db_obj.last_heartbeat_at = now
        db_obj.last_seen_at = now
        db_obj.is_active = True
        self._db.commit()
        self._db.refresh(db_obj)

        self._cache[service_id] = self._to_model(db_obj)

    def remove_stale_services(self, timeout_seconds: int = 120) -> list[tuple[str, str]]:
        """
        Remove services whose last heartbeat is older than ``timeout_seconds``.

        Args:
            timeout_seconds: Staleness threshold in seconds.

        Returns:
            List of (service_id, service_name) tuples for services marked inactive.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=timeout_seconds)

        stale = (
            self._db.query(DiscoveredServiceDB)
            .filter(DiscoveredServiceDB.last_heartbeat_at < cutoff)
            .filter(DiscoveredServiceDB.is_active.is_(True))
            .all()
        )

        removed: list[tuple[str, str]] = []
        for db_obj in stale:
            db_obj.is_active = False
            removed.append((db_obj.service_id, db_obj.service_name))
            self._cache.pop(db_obj.service_id, None)

        self._db.commit()
        return removed
