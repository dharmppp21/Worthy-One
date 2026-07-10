"""SignalForge traffic simulator.

Streams a realistic microservice incident scenario into the backend
``/ingest`` endpoint so the dashboard, incident engine, root-cause analysis
and trace-derived dependency graph have live data to show.

The scenario runs in two phases:

* **Phase 1 — healthy traffic.** ``NORMAL_EVENTS`` events of normal traffic
  across a five-service e-commerce app (checkout -> payment/inventory/
  notification, payment -> fraud). Low latency, the odd random error.
* **Phase 2 — cascading failure.** A bad ``notification-service`` deploy is
  emitted, then notification starts timing out and returning 500s; checkout
  fails because it depends on notification; payment degrades; inventory and
  fraud stay healthy.

Everything is configurable via environment variables so the same image works
both locally (against ``127.0.0.1``) and inside docker-compose (against the
``backend`` service):

======================  ============================================  ==========================
Variable                Meaning                                       Default
======================  ============================================  ==========================
``API_URL``             Full ingest URL                               ``http://127.0.0.1:8000/ingest``
``API_KEY``             ``X-API-Key`` header value                    ``sf-api-key-demo``
``TENANT_ID``           Tenant the events belong to                   ``demo-company``
``EVENT_INTERVAL``      Seconds to sleep between events               ``0.25``
``NORMAL_EVENTS``       Healthy events before the bad deploy          ``50``
``TOTAL_EVENTS``        Stop after this many events (0 = run forever) ``0``
======================  ============================================  ==========================
"""

from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import requests


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000/ingest")
API_KEY = os.environ.get("API_KEY", "sf-api-key-demo")
TENANT_ID = os.environ.get("TENANT_ID", "demo-company")
EVENT_INTERVAL = _env_float("EVENT_INTERVAL", 0.25)
NORMAL_EVENTS = _env_int("NORMAL_EVENTS", 50)
TOTAL_EVENTS = _env_int("TOTAL_EVENTS", 0)


# Services in the microservice e-commerce app
SERVICES = [
    "checkout-service",
    "payment-service",
    "inventory-service",
    "fraud-service",
    "notification-service",
]

# Service dependency graph (caller -> callee)
DEPENDENCIES = {
    "checkout-service": ["payment-service", "inventory-service", "notification-service"],
    "payment-service": ["fraud-service"],
}

# Realistic endpoints per service
ENDPOINTS = {
    "checkout-service": "/api/checkout",
    "payment-service": "/api/charge",
    "inventory-service": "/api/reserve",
    "fraud-service": "/api/validate",
    "notification-service": "/api/notify",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_event_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


# ---------------------------------------------------------------------------
# Payload builders — pure functions returning the /ingest event body. Kept
# free of I/O so they can be validated against the backend schema in tests.
# ---------------------------------------------------------------------------
def build_request_payload(
    service_name: str,
    status_code: int,
    latency_ms: int,
    trace_id: str,
    endpoint: str,
) -> dict:
    return {
        "event_id": new_event_id("metric"),
        "tenant_id": TENANT_ID,
        "service_name": service_name,
        "event_type": "metric",
        "timestamp": now_iso(),
        "name": "http_request",
        "trace_id": trace_id,
        "value": 1,
        "attributes": {
            "status_code": status_code,
            "latency_ms": latency_ms,
            "endpoint": endpoint,
        },
    }


def build_trace_payload(
    trace_id: str, caller: str, callee: str, status_code: int, latency_ms: int
) -> dict:
    return {
        "event_id": new_event_id("trace"),
        "tenant_id": TENANT_ID,
        "service_name": caller,
        "event_type": "trace",
        "timestamp": now_iso(),
        "name": "service_call",
        "trace_id": trace_id,
        "attributes": {
            "caller": caller,
            "callee": callee,
            "status_code": status_code,
            "latency_ms": latency_ms,
        },
    }


def build_log_payload(service_name: str, trace_id: str, message: str, severity: str) -> dict:
    return {
        "event_id": new_event_id("log"),
        "tenant_id": TENANT_ID,
        "service_name": service_name,
        "event_type": "log",
        "timestamp": now_iso(),
        "name": "application_log",
        "trace_id": trace_id,
        "severity": severity,
        "message": message,
        "attributes": {
            "logger": "traffic_simulator",
        },
    }


def build_deployment_payload(service_name: str, version: str) -> dict:
    return {
        "event_id": new_event_id("deployment"),
        "tenant_id": TENANT_ID,
        "service_name": service_name,
        "event_type": "deployment",
        "timestamp": now_iso(),
        "name": "service_deployed",
        "attributes": {
            "version": version,
            "deployed_by": "simulator",
        },
    }


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def post_event(payload: dict) -> bool:
    """POST a single event. Never raises — a transient failure logs and the
    demo keeps going rather than crashing the whole run."""
    headers = {"X-API-Key": API_KEY}
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"  ! failed to send {payload.get('event_type')} event: {exc}")
        return False


def wait_for_backend(retries: int = 60, delay: float = 2.0) -> bool:
    """Block until the backend health endpoint responds, so the simulator can
    start alongside the backend under docker-compose without a race."""
    parts = urlsplit(API_URL)
    health_url = urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))
    for attempt in range(1, retries + 1):
        try:
            if requests.get(health_url, timeout=3).ok:
                return True
        except requests.RequestException:
            pass
        print(f"  waiting for backend at {health_url} ({attempt}/{retries})...")
        time.sleep(delay)
    return False


# ---------------------------------------------------------------------------
# Emitters — build a payload, send it, and send any derived follow-up events.
# ---------------------------------------------------------------------------
def emit_request(
    service_name: str,
    status_code: int,
    latency_ms: int,
    trace_id: str | None = None,
    endpoint: str | None = None,
) -> str:
    if trace_id is None:
        trace_id = f"trace-{uuid4()}"
    if endpoint is None:
        endpoint = ENDPOINTS.get(service_name, "/demo")

    post_event(build_request_payload(service_name, status_code, latency_ms, trace_id, endpoint))

    if status_code >= 500:
        post_event(
            build_log_payload(
                service_name,
                trace_id,
                f"{service_name} returned status {status_code} from {endpoint}",
                "error",
            )
        )
    elif latency_ms >= 1500:
        post_event(
            build_log_payload(
                service_name,
                trace_id,
                f"{service_name} request to {endpoint} timed out after {latency_ms}ms",
                "warning",
            )
        )

    return trace_id


def emit_trace(trace_id: str, caller: str, callee: str, status_code: int, latency_ms: int) -> None:
    post_event(build_trace_payload(trace_id, caller, callee, status_code, latency_ms))


def emit_deployment(service_name: str, version: str) -> None:
    post_event(build_deployment_payload(service_name, version))


# ---------------------------------------------------------------------------
# Scenario phases
# ---------------------------------------------------------------------------
def normal_traffic() -> None:
    """Phase 1: healthy traffic across all services."""
    service_name = random.choice(SERVICES)
    status_code = 200 if random.random() > 0.02 else 500
    latency_ms = random.randint(80, 250)
    trace_id = emit_request(service_name, status_code, latency_ms)

    for callee in DEPENDENCIES.get(service_name, []):
        emit_trace(trace_id, service_name, callee, 200, random.randint(40, 120))


def bad_notification_traffic() -> None:
    """notification-service is failing after a bad deploy — timeouts and 500s."""
    status_code = 500 if random.random() < 0.40 else 200
    latency_ms = random.randint(2000, 4500) if status_code == 500 else random.randint(1200, 2500)
    emit_request("notification-service", status_code, latency_ms)


def bad_checkout_traffic() -> None:
    """checkout-service starts failing because it depends on notification-service."""
    status_code = 500 if random.random() < 0.30 else 200
    latency_ms = random.randint(1500, 3000) if status_code == 500 else random.randint(400, 1200)
    trace_id = emit_request("checkout-service", status_code, latency_ms)

    emit_trace(trace_id, "checkout-service", "payment-service", 200, random.randint(80, 200))
    emit_trace(trace_id, "checkout-service", "inventory-service", 200, random.randint(60, 150))
    # The notification call fails/times out — this is the cascade.
    emit_trace(trace_id, "checkout-service", "notification-service", 500, random.randint(2000, 4000))


def degraded_payment_traffic() -> None:
    """payment-service is slightly degraded but not failing."""
    status_code = 200 if random.random() > 0.10 else 500
    latency_ms = random.randint(300, 800)
    trace_id = emit_request("payment-service", status_code, latency_ms)
    emit_trace(trace_id, "payment-service", "fraud-service", 200, random.randint(80, 200))


def normal_other_services() -> None:
    """inventory and fraud stay healthy."""
    service_name = random.choice(["inventory-service", "fraud-service"])
    status_code = 200 if random.random() > 0.02 else 500
    latency_ms = random.randint(80, 200)
    emit_request(service_name, status_code, latency_ms)


def run() -> None:
    print("=" * 60)
    print("SignalForge Traffic Simulator")
    print("=" * 60)
    print("Target:  ", API_URL)
    print("Tenant:  ", TENANT_ID)
    print("Services:", ", ".join(SERVICES))
    print("Config:   NORMAL_EVENTS={} TOTAL_EVENTS={} EVENT_INTERVAL={}s".format(
        NORMAL_EVENTS, TOTAL_EVENTS or "∞", EVENT_INTERVAL
    ))
    print()
    print(f"Phase 1: Normal traffic (events 0-{NORMAL_EVENTS - 1})")
    print("Phase 2: Bad notification-service deploy at event", NORMAL_EVENTS)
    print("Phase 3: Cascading failure (notification -> checkout, payment degraded)")
    print("Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    if not wait_for_backend():
        print("Backend never became reachable — giving up.")
        return

    count = 0
    deployment_sent = False

    try:
        while TOTAL_EVENTS <= 0 or count < TOTAL_EVENTS:
            if count < NORMAL_EVENTS:
                normal_traffic()
            else:
                if not deployment_sent:
                    print(f"[{count}] Simulating bad deployment: notification-service v42")
                    emit_deployment("notification-service", "v42")
                    deployment_sent = True
                    print(f"[{count}] Starting cascading failure scenario...")

                # notification-service is the root cause
                bad_notification_traffic()
                # checkout-service is affected (calls notification)
                if random.random() < 0.6:
                    bad_checkout_traffic()
                # payment-service is slightly degraded
                if random.random() < 0.4:
                    degraded_payment_traffic()
                # inventory and fraud stay mostly healthy
                if random.random() < 0.3:
                    normal_other_services()

            count += 1
            time.sleep(EVENT_INTERVAL)
    except KeyboardInterrupt:
        pass

    print(f"\nSimulator stopped after {count} events.")


if __name__ == "__main__":
    run()
