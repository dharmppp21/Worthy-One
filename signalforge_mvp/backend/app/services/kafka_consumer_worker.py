"""Kafka consumer worker for event-driven telemetry processing.

Runs as a background thread. Consumes telemetry events from Kafka,
processes them via EventProcessor (DB write, Redis hot state, anomaly
detection, incident creation), with retries and dead-letter handling
for failed events.

Why this architecture matters for production:
- Backpressure: if processing is slow, the consumer lag grows. The API
  stays fast because it only publishes. Kafka acts as a buffer.
- Horizontal scaling: run N worker processes with the same group_id.
  Kafka partitions are rebalanced across them automatically.
- Fault tolerance: if a worker dies, another consumer in the group
  picks up its partitions. No events are lost (assuming retention).
"""

import json
import logging
import threading
import time
from typing import Any

from app.kafka_client import KAFKA_BROKERS, TELEMETRY_TOPIC, kafka_client
from app.schemas import TelemetryEvent
from app.services.event_processor import event_processor

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0  # seconds


def _process_event(raw_event: dict[str, Any]) -> bool:
    """Process a single telemetry event via the worker-owned pipeline.

    Returns True on success, False on failure.
    """
    try:
        event = TelemetryEvent(**raw_event)
        result = event_processor.process(event)
        return result["accepted"]
    except Exception as exc:
        logger.warning(f"Failed to process event {raw_event.get('event_id', 'unknown')}: {exc}")
        return False


def _consume_with_retries(raw_event: dict[str, Any]) -> bool:
    """Consume an event with exponential backoff retries.

    Returns True if the event was processed successfully.
    If all retries fail, sends the event to the dead-letter topic.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        if _process_event(raw_event):
            return True
        delay = BASE_RETRY_DELAY * (2 ** (attempt - 1))
        logger.warning(
            f"Retry {attempt}/{MAX_RETRIES} for event {raw_event.get('event_id', 'unknown')} "
            f"after {delay}s"
        )
        time.sleep(delay)

    # All retries exhausted — send to dead letter
    reason = f"Failed after {MAX_RETRIES} retries"
    kafka_client.publish_to_dead_letter(raw_event, reason)
    logger.error(f"Event sent to dead-letter topic: {raw_event.get('event_id', 'unknown')}")
    return False


def run_consumer_worker() -> None:
    """Run the Kafka consumer worker in a loop.

    Consumes from the telemetry_events topic and processes each event
    with retry logic and dead-letter handling.
    """
    if not kafka_client.is_available():
        logger.info("Kafka is not available. Consumer worker not starting.")
        return

    consumer = kafka_client.create_consumer()
    if consumer is None:
        logger.warning("Could not create Kafka consumer. Worker not starting.")
        return

    logger.info(f"Kafka consumer started: brokers={KAFKA_BROKERS}, topic={TELEMETRY_TOPIC}")

    try:
        for message in consumer:
            raw_event = message.value
            if not isinstance(raw_event, dict):
                logger.warning(f"Invalid message format, expected dict: {type(raw_event)}")
                continue
            _consume_with_retries(raw_event)
    except Exception as exc:
        logger.error(f"Consumer worker encountered an error: {exc}")
    finally:
        consumer.close()
        logger.info("Kafka consumer closed.")


def start_consumer_worker() -> None:
    """Start the consumer worker in a background thread."""
    if not kafka_client.is_available():
        logger.info("Kafka unavailable. Skipping consumer worker startup.")
        return

    thread = threading.Thread(target=run_consumer_worker, name="kafka-consumer", daemon=True)
    thread.start()
    logger.info("Kafka consumer worker started in background thread.")
