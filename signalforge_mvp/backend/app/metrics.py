"""Prometheus metrics for the SignalForge backend (self-observability).

Exposes RED metrics — request Rate, Errors, Duration — for every endpoint plus
a couple of domain counters, scraped at ``GET /metrics``. Request labels use the
matched route template (e.g. ``/incidents/{incident_id}``), never the raw path,
so incident/service ids can't explode label cardinality.

ponytail: ``/metrics`` is unauthenticated per Prometheus convention; restrict it
at the network layer (NetworkPolicy / scrape-only ingress) in production.
"""

import time

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HTTP_REQUESTS = Counter(
    "signalforge_http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "signalforge_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)

# Domain counters — what the platform is actually doing.
INCIDENTS_CREATED = Counter(
    "signalforge_incidents_created_total",
    "Incidents opened, by severity.",
    ["severity"],
)
EVENTS_INGESTED = Counter(
    "signalforge_events_ingested_total",
    "Telemetry events accepted into the pipeline, by type.",
    ["event_type"],
)

_METRICS_PATH = "/metrics"


class MetricsMiddleware:
    """Record request count and latency per route template, method, and status."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == _METRICS_PATH:
            await self._app(scope, receive, send)
            return

        status = {"code": 500}  # default if the app errors before responding

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        start = time.perf_counter()
        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            # Routing runs inside the app, so scope["route"] is set by now.
            route = scope.get("route")
            path = getattr(route, "path", None) or "__unmatched__"
            method = scope.get("method", "UNKNOWN")
            HTTP_LATENCY.labels(method, path).observe(elapsed)
            HTTP_REQUESTS.labels(method, path, str(status["code"])).inc()


router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
