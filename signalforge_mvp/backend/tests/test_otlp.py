"""OTLP/HTTP trace receiver -> existing telemetry pipeline.

Builds a real OTLP protobuf export (the exact bytes an OpenTelemetry SDK sends)
and verifies SERVER spans drive incidents and CLIENT spans record dependencies.
"""

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span,
    Status,
)

from app.storage import store

OTLP_HEADERS = {"Content-Type": "application/x-protobuf"}
_START_NS = 1_700_000_000_000_000_000


def _kv(key, **value):
    return KeyValue(key=key, value=AnyValue(**value))


def _span(i, name, kind, status_code, latency_ms, extra=None):
    attrs = [_kv("http.response.status_code", int_value=status_code)]
    if extra:
        attrs.extend(extra)
    return Span(
        trace_id=i.to_bytes(16, "big"),
        span_id=i.to_bytes(8, "big"),
        name=name,
        kind=kind,
        start_time_unix_nano=_START_NS,
        end_time_unix_nano=_START_NS + int(latency_ms * 1_000_000),
        attributes=attrs,
        status=Status(code=Status.STATUS_CODE_UNSET),
    )


def _export(service_name, spans):
    return ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=Resource(
                    attributes=[_kv("service.name", string_value=service_name)]
                ),
                scope_spans=[ScopeSpans(spans=spans)],
            )
        ]
    ).SerializeToString()


def test_otlp_server_spans_create_incident(client, reset_store):
    # 20 failing requests (HTTP 500, 2000ms) breach the anomaly thresholds.
    spans = [_span(i, "POST /charge", Span.SPAN_KIND_SERVER, 500, 2000) for i in range(20)]
    resp = client.post("/v1/traces", content=_export("payment-service", spans), headers=OTLP_HEADERS)
    assert resp.status_code == 200

    incidents = store.list_incidents(tenant_id="demo-company")
    assert len(incidents) == 1
    assert incidents[0].service_name == "payment-service"


def test_otlp_healthy_server_spans_create_no_incident(client, reset_store):
    spans = [_span(i, "POST /charge", Span.SPAN_KIND_SERVER, 200, 40) for i in range(20)]
    resp = client.post("/v1/traces", content=_export("payment-service", spans), headers=OTLP_HEADERS)
    assert resp.status_code == 200
    assert store.list_incidents(tenant_id="demo-company") == []


def test_otlp_client_span_records_dependency(client, reset_store):
    span = _span(
        1, "POST payment", Span.SPAN_KIND_CLIENT, 200, 50,
        extra=[_kv("peer.service", string_value="payment-service")],
    )
    resp = client.post("/v1/traces", content=_export("checkout-service", [span]), headers=OTLP_HEADERS)
    assert resp.status_code == 200

    calls = [e for e in store.list_events(tenant_id="demo-company") if e.name == "service_call"]
    assert len(calls) == 1
    assert calls[0].attributes["caller"] == "checkout-service"
    assert calls[0].attributes["callee"] == "payment-service"


def test_otlp_requires_api_key():
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as no_auth:
        resp = no_auth.post("/v1/traces", content=_export("x", []), headers=OTLP_HEADERS)
    assert resp.status_code == 401
