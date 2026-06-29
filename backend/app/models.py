"""
Database models for the application.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

# Use JSONB for PostgreSQL; fallback JSON for SQLite tests.
try:
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover
    JSON = JSONB  # type: ignore[misc]

Base = declarative_base()


class DiscoveredServiceDB(Base):
    """SQLAlchemy ORM model for discovered services."""

    __tablename__ = "discovered_services"

    id = Column(String, primary_key=True)
    service_id = Column(String, unique=True, index=True, nullable=False)
    service_name = Column(String, index=True, nullable=False)
    service_type = Column(String, nullable=False, default="unknown")
    endpoints = Column(JSON, default=list)
    host = Column(String, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    health_check_url = Column(String, nullable=True)
    discovery_source = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=False)
    tenant_id = Column(String, index=True, nullable=True)

    __table_args__ = (
        Index("idx_service_name_host", "service_name", "host"),
    )
