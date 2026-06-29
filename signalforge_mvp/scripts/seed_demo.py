"""Seed demo data for SignalForge.

Generates a complete, deterministic demo story that demonstrates the full
product: healthy traffic, bad deployment, cascading failure, incident creation,
structured evidence, service graph, runbook retrieval, and AI triage.

Usage:
    cd signalforge_mvp/backend
    .venv/Scripts/python.exe ../scripts/seed_demo.py

What it creates:
- Phase 1: 20 healthy metric events across all 5 services (200ms, 200 OK)
- Phase 2: Deployment event for notification-service v2.1.0
- Phase 3: 20 bad metric events for notification-service (500, 2000ms)
- Phase 4: 10 bad trace events showing checkout-service -> notification-service failures
- Phase 5: 10 bad metric events for checkout-service (500, 2200ms)
- Phase 6: Error log events for the failing services
- Phase 7: A runbook for notification-service
- Phase 8: A runbook for checkout-service

Result: One incident for notification-service (critical) with deployment
correlation, anomaly evidence, and cascading impact. One incident for
checkout-service (warning) with trace evidence showing dependency failure.
"""

import os
import sys

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import datetime, timezone
from uuid import uuid4

from app.schemas import TelemetryEvent, Runbook
from app.services.event_processor import event_processor
from app.storage import store
from app.database import init_db


TENANT_ID = "demo-company"
API_KEY = "sf-api-key-demo"
SERVICES = [
    "checkout-service",
    "payment-service",
    "inventory-service",
    "fraud-service",
    "notification-service",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event_id(prefix: str, seq: int) -> str:
    return f"demo-{prefix}-{seq:03d}"


def build_event(
    event_id: str,
    service_name: str,
    event_type: str,
    name: str,
    status_code: int = 200,
    latency_ms: int = 200,
    trace_id: str | None = None,
    endpoint: str | None = None,
    **attrs,
) -> TelemetryEvent:
    if endpoint is None:
        endpoints = {
            "checkout-service": "/api/checkout",
            "payment-service": "/api/charge",
            "inventory-service": "/api/reserve",
            "fraud-service": "/api/validate",
            "notification-service": "/api/notify",
        }
        endpoint = endpoints.get(service_name, "/demo")

    attributes = {"status_code": status_code, "latency_ms": latency_ms, "endpoint": endpoint}
    attributes.update(attrs)

    if trace_id is None:
        trace_id = f"trace-{event_id}"

    return TelemetryEvent(
        event_id=event_id,
        tenant_id=TENANT_ID,
        service_name=service_name,
        event_type=event_type,
        timestamp=now_iso(),
        name=name,
        trace_id=trace_id,
        value=1,
        attributes=attributes,
    )


def seed():
    print("=" * 60)
    print("SignalForge Demo Seed Data")
    print("=" * 60)
    print()

    # Initialize database (creates tables if not present)
    init_db()

    # Reset any existing data for a clean demo
    store.reset()
    print("Database reset for clean demo.")
    print()

    # ── Phase 1: Healthy traffic (events 001-020) ──
    print("Phase 1: Healthy traffic (20 events)")
    print("  All services responding with 200ms latency, 200 OK status.")
    for i in range(1, 21):
        service = SERVICES[i % len(SERVICES)]
        event = build_event(
            make_event_id("metric", i),
            service,
            "metric",
            "http_request",
            status_code=200,
            latency_ms=200,
        )
        result = event_processor.process(event)
        if not result["duplicate"]:
            print(f"  [{i:3d}] {service:20s} 200 OK  200ms")
    print()

    # ── Phase 2: Bad deployment (event 021) ──
    print("Phase 2: Bad deployment")
    print("  notification-service v2.1.0 deployed with a bug.")
    deploy_event = TelemetryEvent(
        event_id=make_event_id("deploy", 1),
        tenant_id=TENANT_ID,
        service_name="notification-service",
        event_type="deployment",
        timestamp=now_iso(),
        name="service_deployed",
        attributes={"version": "v2.1.0", "deployed_by": "seed_demo"},
    )
    event_processor.process(deploy_event)
    print("  [021] notification-service deployed v2.1.0")
    print()

    # ── Phase 3: notification-service fails (events 022-041) ──
    print("Phase 3: notification-service failure (20 events)")
    print("  500 errors, 2000-2500ms latency. 20% error rate will trigger incident.")
    for i in range(22, 42):
        event = build_event(
            make_event_id("metric", i),
            "notification-service",
            "metric",
            "http_request",
            status_code=500,
            latency_ms=2000 + (i % 500),
        )
        result = event_processor.process(event)
        if not result["duplicate"]:
            print(f"  [{i:3d}] notification-service 500 ERR {2000 + (i % 500)}ms")
    print()

    # ── Phase 4: Trace events showing checkout -> notification failure ──
    print("Phase 4: Service dependency traces (10 events)")
    print("  checkout-service calls notification-service and gets 500 errors.")
    for i in range(42, 52):
        trace_id = f"trace-checkout-{i:03d}"
        event = build_event(
            make_event_id("trace", i),
            "checkout-service",
            "trace",
            "service_call",
            trace_id=trace_id,
            caller="checkout-service",
            callee="notification-service",
            status_code=500,
            latency_ms=2500,
        )
        event_processor.process(event)
        print(f"  [{i:3d}] checkout-service -> notification-service 500 ERR 2500ms")
    print()

    # ── Phase 5: checkout-service starts failing (events 052-061) ──
    print("Phase 5: checkout-service cascading failure (10 events)")
    print("  checkout-service depends on notification. Now it also fails.")
    for i in range(52, 62):
        event = build_event(
            make_event_id("metric", i),
            "checkout-service",
            "metric",
            "http_request",
            status_code=500,
            latency_ms=2200,
        )
        result = event_processor.process(event)
        if not result["duplicate"]:
            print(f"  [{i:3d}] checkout-service 500 ERR 2200ms")
    print()

    # ── Phase 6: Log events for error visibility ──
    print("Phase 6: Error log events")
    print("  Application logs showing the actual error messages.")
    for i in range(62, 67):
        service = "notification-service" if i < 65 else "checkout-service"
        event = TelemetryEvent(
            event_id=make_event_id("log", i),
            tenant_id=TENANT_ID,
            service_name=service,
            event_type="log",
            timestamp=now_iso(),
            name="application_log",
            trace_id=f"trace-log-{i:03d}",
            severity="error",
            message=f"{service} connection pool exhausted after deployment v2.1.0",
            attributes={"logger": "seed_demo"},
        )
        event_processor.process(event)
        print(f"  [{i:3d}] {service} log: connection pool exhausted")
    print()

    # ── Phase 7: Runbooks ──
    print("Phase 7: Creating runbooks")
    runbook_checkout = store.create_runbook(
        Runbook(
            id="rb-checkout-001",
            tenant_id=TENANT_ID,
            service_name="checkout-service",
            title="Checkout Service Incident Playbook",
            description="Steps to follow when checkout-service fails or times out.",
            steps=[
                "Check notification-service health (checkout depends on it)",
                "Verify payment-service connectivity",
                "Check Redis connection pool status",
                "If p95 latency > 2000ms, scale horizontally",
                "Escalate to SRE if error rate > 50% after 5 minutes",
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    print(f"  Created runbook for checkout-service: rb-checkout-001")

    runbook_notification = store.create_runbook(
        Runbook(
            id="rb-notification-001",
            tenant_id=TENANT_ID,
            service_name="notification-service",
            title="Notification Service Recovery Playbook",
            description="Steps to recover notification-service after failures or deployments.",
            steps=[
                "Check deployment history for recent changes",
                "Verify database connection pool settings",
                "Restart notification-service pods if connection pool is exhausted",
                "Check downstream queue depth (Kafka/SQS)",
                "If rolling back, use version tag from last known good deployment",
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    print(f"  Created runbook for notification-service: rb-notification-001")
    print()

    # ── Summary ──
    print("=" * 60)
    print("Demo seed complete!")
    print("=" * 60)
    print()

    # Count what we created
    incidents = store.list_incidents(tenant_id=TENANT_ID)
    events = store.list_events(tenant_id=TENANT_ID)
    runbooks = store.list_runbooks(tenant_id=TENANT_ID)
    deployments = store.get_recent_deployments(tenant_id=TENANT_ID, service_name="notification-service")

    print(f"Events created:   {len(events)}")
    print(f"Incidents created: {len(incidents)}")
    print(f"Runbooks created:  {len(runbooks)}")
    print(f"Deployments:       {len(deployments)}")
    print()

    if incidents:
        print("Incidents:")
        for inc in incidents:
            print(f"  - {inc.id}: {inc.service_name}")
            print(f"    Status: {inc.status}")
            print(f"    Severity: {inc.severity}")
            print(f"    Timeline entries: {len(inc.timeline)}")
            if inc.timeline:
                for entry in inc.timeline:
                    print(f"      [{entry.timestamp}] {entry.actor}: {entry.message}")
            print()

    print()
    print("Next steps:")
    print("  1. Start the backend: cd backend && uvicorn app.main:app --reload")
    print("  2. Open the dashboard: http://localhost:5173")
    print("  3. Or query the API directly:")
    print(f"     curl -H 'X-API-Key: {API_KEY}' http://localhost:8000/incidents")
    print(f"     curl -H 'X-API-Key: {API_KEY}' http://localhost:8000/graph")
    print(f"     curl -H 'X-API-Key: {API_KEY}' http://localhost:8000/runbooks")
    print()
    print("Demo narrative to tell:")
    print('  "Our monitoring detected notification-service failing after')
    print('   deployment v2.1.0. The anomaly engine flagged critical severity')
    print('   with 100% error rate and 2000ms+ latency. The incident engine')
    print('   created an incident with structured evidence including the')
    print('   deployment correlation. The service graph shows checkout-service')
    print('   depends on notification-service, explaining the cascading failure.')
    print('   The runbook suggests checking the connection pool and rolling back')
    print('   to the last known good version."')
    print()


if __name__ == "__main__":
    seed()
