from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, JSON, String
from sqlalchemy.orm import declarative_base

from app.database import Base


class TelemetryEventModel(Base):
    __tablename__ = "telemetry_events"

    event_id = Column(String(128), primary_key=True)
    tenant_id = Column(String(128), nullable=False)
    service_name = Column(String(128), nullable=False)
    event_type = Column(String(32), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    trace_id = Column(String(128), nullable=True)
    value = Column(Float, nullable=True)
    severity = Column(String(32), nullable=True)
    message = Column(String(1024), nullable=True)
    attributes = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("idx_events_tenant_service_ts", "tenant_id", "service_name", "timestamp"),
        Index("idx_events_event_type", "event_type"),
    )


class IncidentModel(Base):
    __tablename__ = "incidents"

    id = Column(String(128), primary_key=True)
    tenant_id = Column(String(128), nullable=False)
    service_name = Column(String(128), nullable=False)
    title = Column(String(512), nullable=False)
    severity = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    summary = Column(String(1024), nullable=False)
    evidence = Column(JSON, nullable=False, default=list)
    timeline = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_incidents_tenant_service", "tenant_id", "service_name"),
        Index("idx_incidents_status", "status"),
    )


class RunbookModel(Base):
    __tablename__ = "runbooks"

    id = Column(String(128), primary_key=True)
    tenant_id = Column(String(128), nullable=False)
    service_name = Column(String(128), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(String(2048), nullable=False)
    steps = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_runbooks_tenant_service", "tenant_id", "service_name"),
    )
