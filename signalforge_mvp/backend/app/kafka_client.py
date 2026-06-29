"""Kafka client for event-driven telemetry ingestion.

Produces telemetry events to the `telemetry_events` topic.
If Kafka is unavailable, falls back to synchronous processing.

Consumer worker runs in a background thread and processes events
from the topic, with retries and dead-letter handling.
"""

import json
import threading
import time
from typing import Any

from app.config import config

KAFKA_BROKERS = config.KAFKA_BROKERS
TELEMETRY_TOPIC = "telemetry_events"
DEAD_LETTER_TOPIC = "telemetry_events_dead_letter"


class KafkaClient:
    """Kafka producer and consumer for telemetry events."""

    def __init__(self) -> None:
        self._producer: Any | None = None
        self._consumer: Any | None = None
        self._available = False
        self._init()

    def _init(self) -> None:
        try:
            from kafka import KafkaProducer, KafkaConsumer
            self._producer = KafkaProducer(
                bootstrap_servers=KAFKA_BROKERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=3,
                retry_backoff_ms=1000,
            )
            # Test connectivity by sending a metadata request
            self._producer._wait_on_metadata(TELEMETRY_TOPIC)
            self._available = True
        except Exception as exc:
            self._available = False
            self._producer = None

    def is_available(self) -> bool:
        return self._available

    def publish_event(self, event: dict[str, Any]) -> bool:
        """Publish a telemetry event to the Kafka topic.

        Returns True if the event was sent successfully.
        """
        if not self._available or self._producer is None:
            return False
        try:
            future = self._producer.send(TELEMETRY_TOPIC, value=event)
            future.get(timeout=5)  # Wait for confirmation
            return True
        except Exception:
            return False

    def create_consumer(self, group_id: str = "signforge-consumer") -> Any | None:
        """Create a KafkaConsumer for the telemetry topic.

        Returns None if Kafka is unavailable.
        """
        if not self._available:
            return None
        try:
            from kafka import KafkaConsumer
            return KafkaConsumer(
                TELEMETRY_TOPIC,
                bootstrap_servers=KAFKA_BROKERS,
                group_id=group_id,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
        except Exception:
            return None

    def publish_to_dead_letter(self, event: dict[str, Any], reason: str) -> bool:
        """Publish a failed event to the dead-letter topic."""
        if not self._available or self._producer is None:
            return False
        try:
            dl_message = {
                "original_event": event,
                "failure_reason": reason,
                "failed_at": time.time(),
            }
            future = self._producer.send(DEAD_LETTER_TOPIC, value=dl_message)
            future.get(timeout=5)
            return True
        except Exception:
            return False


kafka_client = KafkaClient()
