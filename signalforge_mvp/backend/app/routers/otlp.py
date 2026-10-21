"""OTLP/HTTP trace receiver.

Accepts OpenTelemetry traces exported by any OTel SDK at the standard
``POST /v1/traces`` endpoint (protobuf) and maps spans into SignalForge's
existing telemetry pipeline:

  * SERVER spans -> metric/http_request events (drive anomaly + incidents)
  * CLIENT spans -> trace/service_call events  (drive the dependency graph)
  * error spans (status=ERROR) -> log events   (drive error-log root-cause scoring)
  * a changed service.version -> deployment event (drives deployment root-cause
    and the rollback remediation proposal)

This is the real-telemetry path that replaces the traffic simulator: instrument
a service with the OTel SDK, point ``OTEL_EXPORTER_OTLP_ENDPOINT`` at this
backend, send ``x-api-key`` in ``OTEL_EXPORTER_OTLP_HEADERS``, and its live
requests become SignalForge events.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth import get_current_tenant
from app.middleware.rate_limit import rate_limit_dependency
from app.schemas import EventType, TelemetryEvent
from app.services.event_processor import event_processor
from app.storage import store

try:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    _OTLP_AVAILABLE = True
except ImportError:  # pragma: no cover - dep is in requirements
    _OTLP_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(tags=["otlp"])

# opentelemetry.proto SpanKind / StatusCode enum values (avoid importing the
# proto enums so this module imports even if the dep is missing).
_SPAN_KIND_SERVER = 2
_SPAN_KIND_CLIENT = 3
_STATUS_CODE_ERROR = 2

# Span attribute keys that name the thing a CLIENT span is calling.
_CALLEE_KEYS = ("peer.service", "server.address", "net.peer.name", "http.host", "db.system")
# Span attribute keys carrying the HTTP status code (new and legacy semconv).
_STATUS_KEYS = ("http.response.status_code", "http.status_code")
# How far back to look for the last-recorded version when detecting a new deploy.
_DEPLOY_LOOKBACK_MINUTES = 24 * 60


def _anyvalue(value) -> Any:
    """Unwrap an OTLP AnyValue to a Python scalar."""
    for field in ("string_value", "int_value", "double_value", "bool_value"):
        if value.HasField(field):
            return getattr(value, field)
    return None


def _attrs(key_values) -> dict:
    return {kv.key: _anyvalue(kv.value) for kv in key_values}


def _callee(attrs: dict) -> str | None:
    for key in _CALLEE_KEYS:
        if attrs.get(key):
            return str(attrs[key])
    return None


def _status_code(attrs: dict, span) -> int:
    """Best-effort HTTP status for a span, clamped to the valid 100-599 range."""
    for key in _STATUS_KEYS:
        if key in attrs:
            try:
                code = int(attrs[key])
                if 100 <= code <= 599:
                    return code
            except (TypeError, ValueError):
                pass
    # No usable HTTP status: infer from the span's own status.
    return 500 if span.status.code == _STATUS_CODE_ERROR else 200


def _duration_ms(span) -> float:
    if span.end_time_unix_nano and span.start_time_unix_nano:
        return max(0.0, (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000)
    return 0.0


def _error_message(span) -> str:
    """A human-readable error message for a failed span.

    Prefers the span's status message, then an attached OTel exception event,
    then the span name — always non-empty (log events require a message).
    """
    if span.status.message:
        return str(span.status.message)
    for event in span.events:
        if event.name == "exception":
            ex = _attrs(event.attributes)
            msg, typ = ex.get("exception.message"), ex.get("exception.type")
            if msg and typ:
                return f"{typ}: {msg}"
            if msg:
                return str(msg)
    return f"Error in span '{span.name}'"


def _map_span(span, service_name: str, tenant_id: str) -> list[TelemetryEvent]:
    """Map one span to zero or more TelemetryEvents. Never raises."""
    attrs = _attrs(span.attributes)
    trace_hex = span.trace_id.hex()
    base_id = f"otlp-{trace_hex}-{span.span_id.hex()}"
    ts = (
        datetime.fromtimestamp(span.end_time_unix_nano / 1e9, tz=timezone.utc)
        if span.end_time_unix_nano
        else datetime.now(timezone.utc)
    )
    events: list[TelemetryEvent] = []
    try:
        if span.kind == _SPAN_KIND_SERVER:
            events.append(
                TelemetryEvent(
                    event_id=f"{base_id}-req",
                    tenant_id=tenant_id,
                    service_name=service_name,
                    event_type=EventType.metric,
                    timestamp=ts,
                    name="http_request",
                    value=1,
                    trace_id=trace_hex,
                    attributes={
                        "status_code": _status_code(attrs, span),
                        "latency_ms": _duration_ms(span),
                        "endpoint": attrs.get("http.route") or attrs.get("url.path") or span.name,
                    },
                )
            )
        elif span.kind == _SPAN_KIND_CLIENT:
            callee = _callee(attrs)
            if callee:
                events.append(
                    TelemetryEvent(
                        event_id=f"{base_id}-call",
                        tenant_id=tenant_id,
                        service_name=service_name,
                        event_type=EventType.trace,
                        timestamp=ts,
                        name="service_call",
                        trace_id=trace_hex,
                        attributes={
                            "caller": service_name,
                            "callee": callee,
                            "status_code": _status_code(attrs, span),
                            "latency_ms": _duration_ms(span),
                        },
                    )
                )

        # Any failed span also becomes an error log — this is the symptom
        # density the root-cause engine's error-log dimension scores on.
        if span.status.code == _STATUS_CODE_ERROR:
            events.append(
                TelemetryEvent(
                    event_id=f"{base_id}-log",
                    tenant_id=tenant_id,
                    service_name=service_name,
                    event_type=EventType.log,
                    timestamp=ts,
                    name="span_error",
                    severity="error",
                    message=_error_message(span),
                    trace_id=trace_hex,
                    attributes={"span_name": span.name},
                )
            )
    except Exception as exc:  # a malformed span must not fail the whole export
        logger.warning("Skipped unmappable span %s: %s", base_id, exc)
    return events


def _deployment_event_if_changed(
    tenant_id: str, service_name: str, version: str
) -> TelemetryEvent | None:
    """Emit a deployment event when a service's reported version changes.

    OTel carries the running build as the ``service.version`` resource
    attribute. When it differs from the latest deployment we've recorded, that's
    a new rollout — the exact signal the deployment root-cause dimension and the
    rollback remediation proposal key off.
    """
    # ponytail: compares against the stored latest; concurrent exports of the
    # same new version could each emit one. Harmless dup for a demo; single-flight
    # per service if it ever matters.
    recent = store.get_recent_deployments(tenant_id, service_name, window_minutes=_DEPLOY_LOOKBACK_MINUTES)
    if recent and str(recent[0].attributes.get("version")) == version:
        return None  # unchanged — no new deploy
    now = datetime.now(timezone.utc)
    return TelemetryEvent(
        event_id=f"otlp-deploy-{service_name}-{version}-{int(now.timestamp() * 1000)}",
        tenant_id=tenant_id,
        service_name=service_name,
        event_type=EventType.deployment,
        timestamp=now,
        name="service_deployed",
        attributes={"version": version, "source": "otlp"},
    )


def _map_to_events(req, tenant_id: str) -> list[TelemetryEvent]:
    events: list[TelemetryEvent] = []
    seen_deploys: set[tuple[str, str]] = set()
    for resource_spans in req.resource_spans:
        res_attrs = _attrs(resource_spans.resource.attributes)
        service_name = str(res_attrs.get("service.name") or "unknown-service")

        version = res_attrs.get("service.version")
        if version is not None and (service_name, str(version)) not in seen_deploys:
            seen_deploys.add((service_name, str(version)))
            deploy = _deployment_event_if_changed(tenant_id, service_name, str(version))
            if deploy is not None:
                events.append(deploy)

        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                events.extend(_map_span(span, service_name, tenant_id))
    return events


@router.post("/v1/traces", dependencies=[Depends(rate_limit_dependency)])
async def receive_traces(
    request: Request, tenant_id: str = Depends(get_current_tenant)
) -> Response:
    """Receive an OTLP/HTTP protobuf trace export and ingest the mapped events."""
    if not _OTLP_AVAILABLE:
        return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

    body = await request.body()
    try:
        export = ExportTraceServiceRequest.FromString(body)
    except Exception as exc:
        logger.warning("Failed to parse OTLP trace export: %s", exc)
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    events = _map_to_events(export, tenant_id)
    for event in events:
        event_processor.process(event)

    logger.info("OTLP /v1/traces: ingested %d events for tenant %s", len(events), tenant_id)
    # Empty 200 body is accepted by OTLP/HTTP exporters on success.
    return Response(status_code=status.HTTP_200_OK)
