from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text, func

from app.database import SessionLocal
from app.models import IncidentModel, RunbookModel, TelemetryEventModel
from app.redis_client import redis_window
from app.schemas import (
    EventType,
    Incident,
    IncidentStatus,
    IncidentTimelineEntry,
    Runbook,
    ServiceGraphEdge,
    ServiceGraphNode,
    ServiceGraphResponse,
    TelemetryEvent,
)


def _pgvector_available(session) -> bool:
    """Check if pgvector extension is available in the current database."""
    try:
        result = session.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar()
        return bool(result)
    except Exception:
        return False


class DatabaseStore:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def _to_event(self, row: TelemetryEventModel) -> TelemetryEvent:
        return TelemetryEvent(
            event_id=row.event_id,
            tenant_id=row.tenant_id,
            service_name=row.service_name,
            event_type=EventType(row.event_type),
            timestamp=row.timestamp,
            name=row.name,
            trace_id=row.trace_id,
            value=row.value,
            severity=row.severity,
            message=row.message,
            attributes=row.attributes or {},
        )

    def _to_incident(self, row: IncidentModel) -> Incident:
        timeline = [
            IncidentTimelineEntry(**entry)
            for entry in (row.timeline or [])
        ]
        return Incident(
            id=row.id,
            tenant_id=row.tenant_id,
            service_name=row.service_name,
            title=row.title,
            severity=row.severity,
            status=IncidentStatus(row.status),
            summary=row.summary,
            evidence=row.evidence or [],
            timeline=timeline,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def add_event(self, event: TelemetryEvent) -> bool:
        with self._session_factory() as session:
            existing = session.get(TelemetryEventModel, event.event_id)
            if existing is not None:
                return False

            db_event = TelemetryEventModel(
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                service_name=event.service_name,
                event_type=event.event_type.value,
                timestamp=event.timestamp,
                name=event.name,
                trace_id=event.trace_id,
                value=event.value,
                severity=event.severity,
                message=event.message,
                attributes=event.attributes,
            )
            session.add(db_event)
            session.commit()

            # Push to Redis hot operational state for fast rolling windows
            redis_window.add_event(
                event.tenant_id,
                event.service_name,
                event.model_dump(mode="json"),
            )
            return True

    def get_recent_events(self, tenant_id: str, service_name: str) -> list[TelemetryEvent]:
        # Try Redis hot state first for fast rolling windows
        redis_events = redis_window.get_recent_events(tenant_id, service_name)
        if redis_events:
            return [
                TelemetryEvent.model_validate(e)
                for e in redis_events
            ]

        # Fallback to PostgreSQL durable storage
        with self._session_factory() as session:
            rows = (
                session.query(TelemetryEventModel)
                .filter_by(tenant_id=tenant_id, service_name=service_name)
                .order_by(TelemetryEventModel.timestamp.desc())
                .limit(500)
                .all()
            )
            return [self._to_event(r) for r in reversed(rows)]

    def add_incident(self, incident: Incident) -> bool:
        with self._session_factory() as session:
            existing = (
                session.query(IncidentModel)
                .filter_by(tenant_id=incident.tenant_id, service_name=incident.service_name)
                .filter(IncidentModel.status != "resolved")
                .first()
            )
            if existing is not None:
                return False

            db_incident = IncidentModel(
                id=incident.id,
                tenant_id=incident.tenant_id,
                service_name=incident.service_name,
                title=incident.title,
                severity=incident.severity,
                status=incident.status.value,
                summary=incident.summary,
                evidence=incident.evidence,
                timeline=[e.model_dump(mode="json") for e in incident.timeline],
                created_at=incident.created_at,
                updated_at=incident.updated_at,
            )
            session.add(db_incident)
            session.commit()
            return True

    def get_incident(self, incident_id: str, tenant_id: str | None = None) -> Incident | None:
        with self._session_factory() as session:
            row = session.get(IncidentModel, incident_id)
            if row is None:
                return None
            if tenant_id is not None and row.tenant_id != tenant_id:
                return None
            return self._to_incident(row)

    def update_incident_status(
        self,
        incident_id: str,
        status: IncidentStatus,
        timeline_entry: IncidentTimelineEntry,
    ) -> Incident | None:
        with self._session_factory() as session:
            row = session.get(IncidentModel, incident_id)
            if row is None:
                return None

            row.status = status.value
            row.updated_at = timeline_entry.timestamp
            current_timeline = list(row.timeline or [])
            current_timeline.append(timeline_entry.model_dump(mode="json"))
            row.timeline = current_timeline
            session.commit()

            return self._to_incident(row)

    def list_incidents(self, tenant_id: str | None = None) -> list[Incident]:
        with self._session_factory() as session:
            query = session.query(IncidentModel)
            if tenant_id is not None:
                query = query.filter_by(tenant_id=tenant_id)
            rows = (
                query.order_by(IncidentModel.created_at.desc())
                .all()
            )
            return [self._to_incident(r) for r in rows]

    def list_events(self, tenant_id: str | None = None, limit: int = 50) -> list[TelemetryEvent]:
        with self._session_factory() as session:
            query = session.query(TelemetryEventModel)
            if tenant_id is not None:
                query = query.filter_by(tenant_id=tenant_id)
            rows = (
                query.order_by(TelemetryEventModel.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [self._to_event(r) for r in reversed(rows)]

    def reset(self) -> None:
        with self._session_factory() as session:
            session.execute(text("DELETE FROM telemetry_events"))
            session.execute(text("DELETE FROM incidents"))
            session.execute(text("DELETE FROM runbooks"))
            session.commit()
        # Also clear Redis hot operational state
        redis_window.reset()

    def get_recent_deployments(
        self, tenant_id: str, service_name: str, window_minutes: int = 30
    ) -> list[TelemetryEvent]:
        """Return deployment events for a service within the last N minutes.

        This is used for change-based root cause analysis: when an incident
        is created, we check if a deployment happened recently on the same service.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        with self._session_factory() as session:
            rows = (
                session.query(TelemetryEventModel)
                .filter_by(tenant_id=tenant_id, service_name=service_name, event_type="deployment")
                .filter(TelemetryEventModel.timestamp >= cutoff)
                .order_by(TelemetryEventModel.timestamp.desc())
                .all()
            )
            return [self._to_event(r) for r in rows]

    def get_service_graph(self, tenant_id: str | None = None) -> ServiceGraphResponse:
        """Extract service dependency edges from trace events with name='service_call'."""
        with self._session_factory() as session:
            query = session.query(TelemetryEventModel).filter_by(event_type="trace", name="service_call")
            if tenant_id is not None:
                query = query.filter_by(tenant_id=tenant_id)
            rows = query.all()

            # Build edge counts from caller -> callee
            edge_counts: dict[tuple[str, str], int] = {}
            nodes: set[str] = set()

            for row in rows:
                attrs = row.attributes or {}
                caller = attrs.get("caller")
                callee = attrs.get("callee")
                if caller and callee:
                    key = (caller, callee)
                    edge_counts[key] = edge_counts.get(key, 0) + 1
                    nodes.add(caller)
                    nodes.add(callee)

            graph_nodes = [ServiceGraphNode(id=s, label=s) for s in sorted(nodes)]
            graph_edges = [
                ServiceGraphEdge(
                    source=source,
                    target=target,
                    label="calls",
                    count=count,
                )
                for (source, target), count in edge_counts.items()
            ]

            return ServiceGraphResponse(nodes=graph_nodes, edges=graph_edges)

    # ─────────── Runbook CRUD ───────────

    def _to_runbook(self, row: RunbookModel) -> Runbook:
        return Runbook(
            id=row.id,
            tenant_id=row.tenant_id,
            service_name=row.service_name,
            title=row.title,
            description=row.description,
            steps=row.steps or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create_runbook(self, runbook: Runbook) -> bool:
        with self._session_factory() as session:
            existing = session.get(RunbookModel, runbook.id)
            if existing is not None:
                return False

            db_runbook = RunbookModel(
                id=runbook.id,
                tenant_id=runbook.tenant_id,
                service_name=runbook.service_name,
                title=runbook.title,
                description=runbook.description,
                steps=runbook.steps,
                created_at=runbook.created_at,
                updated_at=runbook.updated_at,
            )
            session.add(db_runbook)
            session.commit()
            return True

    def get_runbook(self, runbook_id: str, tenant_id: str | None = None) -> Runbook | None:
        with self._session_factory() as session:
            row = session.get(RunbookModel, runbook_id)
            if row is None:
                return None
            if tenant_id is not None and row.tenant_id != tenant_id:
                return None
            return self._to_runbook(row)

    def list_runbooks(self, tenant_id: str | None = None, service_name: str | None = None) -> list[Runbook]:
        with self._session_factory() as session:
            query = session.query(RunbookModel)
            if tenant_id is not None:
                query = query.filter_by(tenant_id=tenant_id)
            if service_name is not None:
                query = query.filter_by(service_name=service_name)
            rows = query.order_by(RunbookModel.created_at.desc()).all()
            return [self._to_runbook(r) for r in rows]

    def update_runbook(self, runbook_id: str, title: str | None, description: str | None, steps: list[str] | None, tenant_id: str | None = None) -> Runbook | None:
        with self._session_factory() as session:
            row = session.get(RunbookModel, runbook_id)
            if row is None:
                return None
            if tenant_id is not None and row.tenant_id != tenant_id:
                return None

            if title is not None:
                row.title = title
            if description is not None:
                row.description = description
            if steps is not None:
                row.steps = steps
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._to_runbook(row)

    def delete_runbook(self, runbook_id: str, tenant_id: str | None = None) -> bool:
        with self._session_factory() as session:
            row = session.get(RunbookModel, runbook_id)
            if row is None:
                return False
            if tenant_id is not None and row.tenant_id != tenant_id:
                return False
            session.delete(row)
            session.commit()
            return True

    def search_incidents(self, query: str, tenant_id: str | None = None) -> list[Incident]:
        """Keyword search over incident title, summary, and service_name."""
        pattern = f"%{query}%"
        with self._session_factory() as session:
            q = session.query(IncidentModel).filter(
                (IncidentModel.title.ilike(pattern))
                | (IncidentModel.summary.ilike(pattern))
                | (IncidentModel.service_name.ilike(pattern))
            )
            if tenant_id is not None:
                q = q.filter_by(tenant_id=tenant_id)
            rows = (
                q.order_by(IncidentModel.created_at.desc())
                .limit(50)
                .all()
            )
            return [self._to_incident(r) for r in rows]

    def search_runbooks(self, query: str, tenant_id: str | None = None) -> list[Runbook]:
        """Keyword search over runbook title, description, and service_name."""
        pattern = f"%{query}%"
        with self._session_factory() as session:
            q = session.query(RunbookModel).filter(
                (RunbookModel.title.ilike(pattern))
                | (RunbookModel.description.ilike(pattern))
                | (RunbookModel.service_name.ilike(pattern))
            )
            if tenant_id is not None:
                q = q.filter_by(tenant_id=tenant_id)
            rows = (
                q.order_by(RunbookModel.created_at.desc())
                .limit(50)
                .all()
            )
            return [self._to_runbook(r) for r in rows]

    # ─────────── Semantic Search (pgvector) ───────────

    def _has_embeddings_table(self, session) -> bool:
        """Check if the embeddings table exists (PostgreSQL + pgvector only)."""
        try:
            session.execute(text("SELECT 1 FROM embeddings LIMIT 1"))
            return True
        except Exception:
            return False

    def store_embedding(self, entity_type: str, entity_id: str, embedding: list[float]) -> bool:
        """Store an embedding vector for an incident or runbook."""
        with self._session_factory() as session:
            if not self._has_embeddings_table(session):
                return False
            try:
                session.execute(
                    text("""
                        INSERT INTO embeddings (id, entity_type, entity_id, embedding, created_at)
                        VALUES (:id, :entity_type, :entity_id, :embedding, :created_at)
                        ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            created_at = EXCLUDED.created_at
                    """),
                    {
                        "id": str(uuid4()),
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "embedding": str(embedding),
                        "created_at": datetime.now(timezone.utc),
                    },
                )
                session.commit()
                return True
            except Exception:
                return False

    def semantic_search(
        self, query_embedding: list[float], entity_type: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Find similar incidents/runbooks by cosine similarity using pgvector.

        Returns list of {entity_type, entity_id, similarity} dicts.
        Falls back to empty list if pgvector is not available.
        """
        with self._session_factory() as session:
            if not self._has_embeddings_table(session):
                return []
            try:
                embedding_str = str(query_embedding)
                sql = """
                    SELECT entity_type, entity_id,
                           1 - (embedding <=> :embedding) AS similarity
                    FROM embeddings
                    WHERE embedding IS NOT NULL
                """
                params: dict = {"embedding": embedding_str}
                if entity_type:
                    sql += " AND entity_type = :entity_type"
                    params["entity_type"] = entity_type
                sql += " ORDER BY embedding <=> :embedding LIMIT :limit"
                params["limit"] = limit

                rows = session.execute(text(sql), params).all()
                return [
                    {"entity_type": r[0], "entity_id": r[1], "similarity": r[2]}
                    for r in rows
                ]
            except Exception:
                return []

    def get_runbook_for_service(self, tenant_id: str, service_name: str) -> Runbook | None:
        """Return the most recent runbook for a specific service."""
        with self._session_factory() as session:
            row = (
                session.query(RunbookModel)
                .filter_by(tenant_id=tenant_id, service_name=service_name)
                .order_by(RunbookModel.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return self._to_runbook(row)

    # ─────────── Root Cause Evidence Gathering ───────────

    def get_recent_error_logs(
        self, tenant_id: str, service_name: str, window_minutes: int = 30
    ) -> list[TelemetryEvent]:
        """Return recent error/critical log events for a service."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        with self._session_factory() as session:
            rows = (
                session.query(TelemetryEventModel)
                .filter_by(
                    tenant_id=tenant_id,
                    service_name=service_name,
                    event_type="log",
                )
                .filter(TelemetryEventModel.timestamp >= cutoff)
                .filter(TelemetryEventModel.severity.in_(["error", "critical"]))
                .order_by(TelemetryEventModel.timestamp.desc())
                .limit(100)
                .all()
            )
            return [self._to_event(r) for r in rows]

    def get_recent_trace_failures(
        self, tenant_id: str, service_name: str, window_minutes: int = 30
    ) -> list[TelemetryEvent]:
        """Return recent trace events where this service is the caller and status is failure."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        with self._session_factory() as session:
            rows = (
                session.query(TelemetryEventModel)
                .filter_by(
                    tenant_id=tenant_id,
                    event_type="trace",
                    name="service_call",
                )
                .filter(TelemetryEventModel.timestamp >= cutoff)
                .order_by(TelemetryEventModel.timestamp.desc())
                .limit(200)
                .all()
            )
            # Filter in Python for caller match and failure status
            results = []
            for row in rows:
                attrs = row.attributes or {}
                if attrs.get("caller") == service_name:
                    status = attrs.get("status", "unknown")
                    if status in ("failure", "error", "timeout"):
                        results.append(self._to_event(row))
            return results

    def get_callees(self, service_name: str) -> list[str]:
        """Return list of services called by the given service."""
        with self._session_factory() as session:
            rows = (
                session.query(TelemetryEventModel)
                .filter_by(event_type="trace", name="service_call")
                .all()
            )
            callees = set()
            for row in rows:
                attrs = row.attributes or {}
                if attrs.get("caller") == service_name:
                    callee = attrs.get("callee")
                    if callee:
                        callees.add(callee)
            return sorted(callees)

    def get_downstream_incidents(
        self, tenant_id: str, service_names: list[str], window_minutes: int = 30
    ) -> list[Incident]:
        """Return open incidents for downstream services within a time window."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        with self._session_factory() as session:
            rows = (
                session.query(IncidentModel)
                .filter(IncidentModel.tenant_id == tenant_id)
                .filter(IncidentModel.service_name.in_(service_names))
                .filter(IncidentModel.status != "resolved")
                .filter(IncidentModel.created_at >= cutoff)
                .order_by(IncidentModel.created_at.desc())
                .all()
            )
            return [self._to_incident(r) for r in rows]


store = DatabaseStore(SessionLocal)
