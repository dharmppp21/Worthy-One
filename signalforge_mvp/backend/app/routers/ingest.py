from fastapi import APIRouter, Depends, status

from app.auth import get_current_tenant
from app.kafka_client import kafka_client
from app.middleware.rate_limit import rate_limit_dependency
from app.schemas import IngestResponse, TelemetryEvent
from app.services.event_processor import event_processor
from app.logging_config import get_logger

logger = get_logger("app.routers.ingest")

router = APIRouter(tags=["telemetry"])


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    dependencies=[Depends(rate_limit_dependency)],
)
def ingest_event(event: TelemetryEvent, tenant_id: str = Depends(get_current_tenant)) -> IngestResponse:
    """Accept a telemetry event and enqueue it for asynchronous processing.

    When the stream is available, the event is published immediately and
    returned with mode="async". The worker processor handles DB write,
    Redis hot state, anomaly detection, and incident creation.

    When the stream is unavailable, the event is processed synchronously
    as a fallback with mode="sync".
    """
    # Enforce tenant isolation: override the payload tenant_id with the
    # authenticated tenant. This prevents cross-tenant data injection.
    event.tenant_id = tenant_id

    logger.info(
        "event ingested",
        extra={"event_id": event.event_id, "tenant_id": tenant_id, "service_name": event.service_name},
    )

    # Async path: publish to stream and return immediately (202 Accepted)
    if kafka_client.is_available():
        event_dict = event.model_dump(mode="json")
        sent = kafka_client.publish_event(event_dict)
        if sent:
            logger.info(
                "event published to kafka",
                extra={"event_id": event.event_id},
            )
            return IngestResponse(
                accepted=True,
                event_id=event.event_id,
                duplicate=False,
                mode="async",
            )
        logger.warning(
            "kafka publish failed, falling back to sync",
            extra={"event_id": event.event_id},
        )

    # Fallback: synchronous inline processing
    result = event_processor.process(event)
    logger.info(
        "event processed synchronously",
        extra={"event_id": event.event_id, "duplicate": result["duplicate"]},
    )
    return IngestResponse(
        accepted=result["accepted"],
        event_id=result["event_id"],
        duplicate=result["duplicate"],
        mode="sync",
    )
