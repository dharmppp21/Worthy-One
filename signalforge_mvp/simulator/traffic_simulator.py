import random
import time
from datetime import datetime, timezone
from uuid import uuid4

import requests


API_URL = "http://127.0.0.1:8000/ingest"
TENANT_ID = "demo-company"


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


def send_event(payload: dict) -> None:
    response = requests.post(API_URL, json=payload, timeout=5)
    response.raise_for_status()


def send_trace_event(trace_id: str, caller: str, callee: str, status_code: int, latency_ms: int) -> None:
    payload = {
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
    send_event(payload)


def send_request_event(
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

    payload = {
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
    send_event(payload)

    if status_code >= 500:
        send_log_event(
            service_name=service_name,
            trace_id=trace_id,
            message=f"{service_name} returned status {status_code} from {endpoint}",
            severity="error",
        )
    elif latency_ms >= 1500:
        send_log_event(
            service_name=service_name,
            trace_id=trace_id,
            message=f"{service_name} request to {endpoint} timed out after {latency_ms}ms",
            severity="warning",
        )

    return trace_id


def send_log_event(service_name: str, trace_id: str, message: str, severity: str) -> None:
    payload = {
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
    send_event(payload)


def send_deployment_event(service_name: str, version: str) -> None:
    payload = {
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
    send_event(payload)


# Phase 1: Normal traffic across all services
def normal_traffic() -> None:
    service_name = random.choice(SERVICES)
    status_code = 200 if random.random() > 0.02 else 500
    latency_ms = random.randint(80, 250)
    trace_id = send_request_event(service_name, status_code, latency_ms)

    # Emit trace events for service dependencies
    callees = DEPENDENCIES.get(service_name, [])
    for callee in callees:
        callee_latency = random.randint(40, 120)
        send_trace_event(trace_id, service_name, callee, 200, callee_latency)


# Phase 2: Bad notification-service deployment (cascading failure)
def bad_notification_traffic() -> None:
    """notification-service is failing after bad deploy — timeouts and 500s."""
    status_code = 500 if random.random() < 0.40 else 200
    # Simulate timeouts: high latency even on 200s
    latency_ms = random.randint(2000, 4500) if status_code == 500 else random.randint(1200, 2500)
    send_request_event("notification-service", status_code, latency_ms)


def bad_checkout_traffic() -> None:
    """checkout-service starts failing because it depends on notification-service."""
    status_code = 500 if random.random() < 0.30 else 200
    latency_ms = random.randint(1500, 3000) if status_code == 500 else random.randint(400, 1200)
    trace_id = send_request_event("checkout-service", status_code, latency_ms)

    # checkout still calls payment and inventory normally-ish
    send_trace_event(trace_id, "checkout-service", "payment-service", 200, random.randint(80, 200))
    send_trace_event(trace_id, "checkout-service", "inventory-service", 200, random.randint(60, 150))
    # But notification call fails/times out
    send_trace_event(trace_id, "checkout-service", "notification-service", 500, random.randint(2000, 4000))


def degraded_payment_traffic() -> None:
    """payment-service is slightly degraded but not failing."""
    status_code = 200 if random.random() > 0.10 else 500
    latency_ms = random.randint(300, 800)
    trace_id = send_request_event("payment-service", status_code, latency_ms)
    send_trace_event(trace_id, "payment-service", "fraud-service", 200, random.randint(80, 200))


def normal_other_services() -> None:
    """inventory and fraud stay healthy."""
    service_name = random.choice(["inventory-service", "fraud-service"])
    status_code = 200 if random.random() > 0.02 else 500
    latency_ms = random.randint(80, 200)
    send_request_event(service_name, status_code, latency_ms)


if __name__ == "__main__":
    print("=" * 60)
    print("SignalForge Traffic Simulator")
    print("=" * 60)
    print("Services:", ", ".join(SERVICES))
    print()
    print("Phase 1: Normal traffic (events 0-49)")
    print("  All services healthy. Low latency. Few random errors.")
    print()
    print("Phase 2: Bad deploy (event 50)")
    print("  notification-service v42 deployed.")
    print()
    print("Phase 3: Cascading failure (events 50-99)")
    print("  notification-service timeouts and 500s.")
    print("  checkout-service fails because it depends on notification.")
    print("  payment-service slightly degraded.")
    print("  inventory and fraud stay healthy.")
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    count = 0
    deployment_sent = False

    try:
        while True:
            if count < 50:
                # Phase 1: Normal traffic
                normal_traffic()
            else:
                if not deployment_sent:
                    print(f"[{count}] Simulating bad deployment: notification-service v42")
                    send_deployment_event("notification-service", "v42")
                    deployment_sent = True
                    print(f"[{count}] Starting cascading failure scenario...")

                # Phase 3: Cascading failure mix
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
            time.sleep(0.25)

    except KeyboardInterrupt:
        print(f"\n\nSimulator stopped after {count} events.")
