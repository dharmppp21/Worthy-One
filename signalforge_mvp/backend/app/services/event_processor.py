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
  1. Service correlation (if service_name not provided or unknown)
  2. Persist to DB (durable source of truth) + Redis hot state
  3. Anomaly detection on rolling window
  4. Incident creation if anomaly detected
"""

import logging
from typing import Optional, Set

from app.anomaly import analyze_service_window
from app.discovery.correlation import EventServiceCorrelator
from app.incident_engine import maybe_create_incident
from app.schemas import CorrelationMetadata, TelemetryEvent
from app.storage import store

logger = logging.getLogger(__name__)


class EventProcessor:
    """Owns the full telemetry event processing pipeline.

    The worker calls this. The API only publishes to the stream.
    """

    def __init__(self, correlator: Optional[EventServiceCorrelator] = None) -> None:
        """
        Args:
            correlator: Optional EventServiceCorrelator for auto-matching
                events to discovered services. If None, no correlation is attempted.
        """
        self._correlator = correlator
        self._known_service_names: Set[str] = set()

    def set_correlator(self, correlator: Optional[EventServiceCorrelator]) -> None:
        """Set or update the correlator after initialization."""
        self._correlator = correlator

    def process(self, event: TelemetryEvent) -> dict:
        """Process a single event end-to-end.

        Returns a dict with:
            accepted: bool
            duplicate: bool
            event_id: str
        """
        # Stage 0: Service correlation (if needed)
        if self._correlator is not None:
            self._correlate_event(event)

        # Stage 1: Durable storage + hot operational state
        stored = store.add_event(event)
        if not stored:
            return {"accepted": True, "duplicate": True, "event_id": event.event_id}

        # Stage 2: Anomaly detection on rolling window
        recent_events = store.get_recent_events(event.tenant_id, event.service_name)
        anomaly = analyze_service_window(recent_events)

        # Stage 3: Incident creation if anomaly detected
        maybe_create_incident(event, anomaly, recent_events)

        return {"accepted": True, "duplicate": False, "event_id": event.event_id}

    def _correlate_event(self, event: TelemetryEvent) -> None:
        """Attempt to correlate the event to a discovered service.

        If correlation succeeds, updates event.service_name and event.tenant_id.
        If correlation fails, marks event as uncorrelated.
        """
        # Check if service_name is already known
        if event.service_name and event.service_name.lower() in self._known_service_names:
            event.correlation_metadata = CorrelationMetadata(
                strategy="exact_name", confidence=1.0, candidate_count=1
            )
            return

        # Attempt correlation
        result = self._correlator.correlate(event)

        event.correlation_metadata = CorrelationMetadata(
            strategy=result.strategy,
            confidence=result.confidence,
            matched_field=result.matched_field,
            candidate_count=result.candidate_count,
        )

        if result.service_name:
            event.service_name = result.service_name
            if result.tenant_id:
                event.tenant_id = result.tenant_id
            logger.info(
                "Correlated event %s to service %s via %s (confidence=%.2f)",
                event.event_id,
                result.service_name,
                result.strategy,
                result.confidence,
            )
            if result.confidence < 0.5:
                logger.warning(
                    "Low correlation confidence for event %s: strategy=%s confidence=%.2f",
                    event.event_id,
                    result.strategy,
                    result.confidence,
                )
        else:
            event.uncorrelated = True
            logger.warning(
                "Failed to correlate event %s to any known service",
                event.event_id,
            )


event_processor = EventProcessor(correlator=None)
