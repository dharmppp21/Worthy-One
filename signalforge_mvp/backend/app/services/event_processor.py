"""EventProcessor — worker-owned telemetry pipeline.

The API does NOT call this directly. It publishes to the stream (Kafka or
in-memory queue) and returns immediately. Workers consume the stream and
run this pipeline.

This decoupling gives two key production properties:

1. Backpressure: if workers are slow, the queue grows. The API stays fast.
   Consumers pull at their own pace; the producer never blocks.

2. Horizontal scaling: run N worker processes on separate machines. They all
   consume from the same topic with the same group_id. Kafka rebalances
   partitions across workers automatically. More workers = more throughput.

Pipeline stages:
  1. Persist to DB (durable source of truth) + Redis hot state
  2. Anomaly detection on rolling window
  3. Incident creation if anomaly detected
"""

from app.anomaly import analyze_service_window
from app.incident_engine import maybe_create_incident
from app.schemas import TelemetryEvent
from app.storage import store


class EventProcessor:
    """Owns the full telemetry event processing pipeline.

    The worker calls this. The API only publishes to the stream.
    """

    def process(self, event: TelemetryEvent) -> dict:
        """Process a single event end-to-end.

        Returns a dict with:
            accepted: bool
            duplicate: bool
            event_id: str
        """
        # Stage 1: Durable storage + hot operational state
        # store.add_event writes to PostgreSQL AND pushes to Redis rolling window.
        stored = store.add_event(event)
        if not stored:
            return {"accepted": True, "duplicate": True, "event_id": event.event_id}

        # Stage 2: Anomaly detection on rolling window
        # get_recent_events reads from Redis first (O(1), sub-ms) then falls
        # back to PostgreSQL if Redis is unavailable.
        recent_events = store.get_recent_events(event.tenant_id, event.service_name)
        anomaly = analyze_service_window(recent_events)

        # Stage 3: Incident creation if anomaly detected
        # maybe_create_incident checks for duplicates, builds timeline evidence,
        # stores embeddings, and broadcasts via WebSocket.
        maybe_create_incident(event, anomaly, recent_events)

        return {"accepted": True, "duplicate": False, "event_id": event.event_id}


event_processor = EventProcessor()
