"""OTLP/HTTP trace receiver -> existing telemetry pipeline.

Builds a real OTLP protobuf export (the exact bytes an OpenTelemetry SDK sends)
and verifies SERVER spans drive incidents and CLIENT spans record dependencies.
"""

import time

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


def _span(i, name, kind, status_code, latency_ms, extra=None, span_status=None, status_message="", end_ns=None):
    attrs = [_kv("http.response.status_code", int_value=status_code)]
    if extra:
        attrs.extend(extra)
    # Default to the fixed 2023 start; end_ns=now() is for time-windowed assertions.
    if end_ns is None:
        start, end = _START_NS, _START_NS + int(latency_ms * 1_000_000)
    else:
        start, end = end_ns - int(latency_ms * 1_000_000), end_ns
    return Span(
        trace_id=i.to_bytes(16, "big"),
        span_id=i.to_bytes(8, "big"),
        name=name,
        kind=kind,
        start_time_unix_nano=start,
        end_time_unix_nano=end,
        attributes=attrs,
        status=Status(
            code=span_status if span_status is not None else Status.STATUS_CODE_UNSET,
            message=status_message,
        ),
    )


def _export(service_name, spans, version=None):
    attrs = [_kv("service.name", string_value=service_name)]
    if version is not None:
        attrs.append(_kv("service.version", string_value=version))
    return ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=Resource(attributes=attrs),
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


def test_otlp_error_span_records_error_log(client, reset_store):
    # A failed span becomes an error log — the symptom density root-cause scores.
    span = _span(
        1, "POST /charge", Span.SPAN_KIND_SERVER, 500, 2000,
        span_status=Status.STATUS_CODE_ERROR, status_message="charge failed",
        end_ns=time.time_ns(),
    )
    resp = client.post("/v1/traces", content=_export("payment-service", [span]), headers=OTLP_HEADERS)
    assert resp.status_code == 200

    errors = store.get_recent_error_logs("demo-company", "payment-service")
    assert len(errors) == 1
    assert errors[0].severity == "error"
    assert errors[0].message == "charge failed"


def test_otlp_service_version_change_records_deployment(client, reset_store):
    def healthy(i):
        return _span(i, "GET /healthz", Span.SPAN_KIND_SERVER, 200, 10)

    def versions():
        deploys = store.get_recent_deployments("demo-company", "payment-service", window_minutes=1440)
        return [d.attributes["version"] for d in deploys]  # newest first

    # First sighting of v1 -> one deployment recorded.
    client.post("/v1/traces", content=_export("payment-service", [healthy(1)], version="1"), headers=OTLP_HEADERS)
    assert versions() == ["1"]

    # Same version again -> no new deployment.
    client.post("/v1/traces", content=_export("payment-service", [healthy(2)], version="1"), headers=OTLP_HEADERS)
    assert versions() == ["1"]

    # A new version -> a second deployment (the bad-deploy signal).
    client.post("/v1/traces", content=_export("payment-service", [healthy(3)], version="2"), headers=OTLP_HEADERS)
    assert versions() == ["2", "1"]


def test_otlp_enrichment_lights_up_root_cause_and_remediation(client, reset_store):
    """The payoff: a bad-deploy OTLP export feeds deployment + error-log signals,
    so root-cause scores those dimensions and remediation proposes a rollback."""
    from app.remediation import propose_rollback
    from app.root_cause_engine import rank_root_causes

    now = time.time_ns()
    # v1: healthy baseline (records the prior known-good deployment).
    client.post(
        "/v1/traces",
        content=_export("payment-service", [_span(1, "GET /healthz", Span.SPAN_KIND_SERVER, 200, 10, end_ns=now)], version="1"),
        headers=OTLP_HEADERS,
    )
    # v2: a bad deploy — 20 failing requests open an incident.
    bad = [
        _span(i, "POST /charge", Span.SPAN_KIND_SERVER, 500, 2000,
              span_status=Status.STATUS_CODE_ERROR, status_message="charge failed", end_ns=now)
        for i in range(10, 30)
    ]
    client.post("/v1/traces", content=_export("payment-service", bad, version="2"), headers=OTLP_HEADERS)

    incidents = store.list_incidents(tenant_id="demo-company")
    assert len(incidents) == 1

    # Remediation now proposes a concrete rollback v2 -> v1.
    proposal = propose_rollback(incidents[0])
    assert proposal.action == "rollback"
    assert proposal.from_version == "2"
    assert proposal.to_version == "1"

    # Root-cause now has real evidence in the deployment and logs dimensions.
    top = rank_root_causes("payment-service", tenant_id="demo-company").hypotheses[0]
    scores = {e.type: e.score for e in top.evidence}
    assert scores["deployment"] > 0
    assert scores["logs"] > 0


def test_otlp_requires_api_key():
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as no_auth:
        resp = no_auth.post("/v1/traces", content=_export("x", []), headers=OTLP_HEADERS)
    assert resp.status_code == 401
