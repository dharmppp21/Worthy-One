"""Sample service instrumented with OpenTelemetry.

Exports real OTLP traces to the SignalForge backend's ``/v1/traces`` endpoint,
so its live requests show up as metrics, incidents and dependencies. This is
the real-telemetry replacement for the traffic simulator — nothing is faked;
these are genuine OTel SDK spans from a running FastAPI app.

Run (see README.md for the full walkthrough):

    pip install -r requirements.txt
    set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000
    set OTEL_EXPORTER_OTLP_HEADERS=x-api-key=sf-api-key-demo
    set OTEL_SERVICE_NAME=payment-service
    uvicorn main:app --port 8090

Flip BROKEN=1 to simulate a bad deploy (500s + high latency) and watch an
incident open in SignalForge after ~20 requests.
"""

import os
import random
import time

import httpx
from fastapi import FastAPI, Response

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "payment-service")
PAYMENT_URL = os.environ.get("PAYMENT_URL")  # optional downstream dependency
BROKEN = os.environ.get("BROKEN", "0") == "1"

# OpenTelemetry wiring: export OTLP/HTTP to the SignalForge backend. The
# exporter reads OTEL_EXPORTER_OTLP_ENDPOINT / _HEADERS from the environment and
# posts protobuf to {endpoint}/v1/traces.
_provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(_provider)

app = FastAPI(title=f"{SERVICE_NAME} (OTel sample)")
FastAPIInstrumentor.instrument_app(app)   # SERVER spans for every request
HTTPXClientInstrumentor().instrument()    # CLIENT spans for outbound calls


@app.get("/charge")
def charge():
    """One unit of work. Healthy by default; 500 + slow when BROKEN=1."""
    if BROKEN:
        time.sleep(random.uniform(1.5, 3.0))
        return Response(status_code=500, content="charge failed")

    time.sleep(random.uniform(0.02, 0.12))
    # Optionally call a downstream dependency to produce a service_call edge.
    if PAYMENT_URL:
        try:
            httpx.get(PAYMENT_URL, timeout=2.0)
        except httpx.HTTPError:
            pass
    return {"status": "charged"}


@app.get("/healthz")
def healthz():
    return {"ok": True}
