"""Locust load tests for SignalForge API.

Usage:
    # Run headless and get stats to stdout
    locust -f backend/tests/load/locustfile.py --host http://127.0.0.1:8000 --headless -u 50 -r 10 --run-time 60s --csv=load_test_results

    # Run with web UI for manual exploration
    locust -f backend/tests/load/locustfile.py --host http://127.0.0.1:8000

Environment variables:
    LOCUST_HOST (default: http://127.0.0.1:8000)
"""

import os
import random
from datetime import datetime, timezone

from locust import HttpUser, between, task

API_HOST = os.environ.get("LOCUST_HOST", "http://127.0.0.1:8000")


def _event_id(prefix: str, seq: int) -> str:
    return f"locust-{prefix}-{seq:08d}"


class TelemetryUser(HttpUser):
    """Simulates services sending telemetry events."""

    wait_time = between(0.05, 0.2)  # 5–20 events per second per user
    host = API_HOST

    def on_start(self):
        self._seq = 0

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return _event_id(prefix, self._seq)

    @task(10)
    def ingest_healthy_metric(self):
        """Ingest a normal HTTP request metric."""
        self.client.post(
            "/ingest",
            json={
                "event_id": self._next_id("metric-ok"),
                "tenant_id": "demo-company",
                "service_name": random.choice(["checkout-service", "payment-service", "inventory-service"]),
                "event_type": "metric",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "http_request",
                "value": 1,
                "attributes": {
                    "status_code": 200,
                    "latency_ms": random.randint(50, 300),
                    "endpoint": "/api/health",
                },
            },
        )

    @task(3)
    def ingest_error_metric(self):
        """Ingest a failing HTTP request metric (triggers anomaly detection)."""
        self.client.post(
            "/ingest",
            json={
                "event_id": self._next_id("metric-err"),
                "tenant_id": "demo-company",
                "service_name": "checkout-service",
                "event_type": "metric",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "http_request",
                "value": 1,
                "attributes": {
                    "status_code": 500,
                    "latency_ms": random.randint(1500, 3000),
                    "endpoint": "/api/checkout",
                },
            },
        )

    @task(2)
    def ingest_trace(self):
        """Ingest a service trace event (builds the graph)."""
        services = ["checkout-service", "payment-service", "inventory-service", "fraud-service", "notification-service"]
        caller, callee = random.sample(services, 2)
        self.client.post(
            "/ingest",
            json={
                "event_id": self._next_id("trace"),
                "tenant_id": "demo-company",
                "service_name": caller,
                "event_type": "trace",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "service_call",
                "trace_id": self._next_id("traceid"),
                "attributes": {
                    "caller": caller,
                    "callee": callee,
                    "status": "success",
                },
            },
        )

    @task(1)
    def ingest_log(self):
        """Ingest a log event."""
        self.client.post(
            "/ingest",
            json={
                "event_id": self._next_id("log"),
                "tenant_id": "demo-company",
                "service_name": "checkout-service",
                "event_type": "log",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "name": "error",
                "severity": "error",
                "message": "Connection timeout to payment gateway",
                "attributes": {
                    "endpoint": "/api/checkout",
                },
            },
        )

    @task(1)
    def get_incidents(self):
        """Poll the incidents list."""
        self.client.get("/incidents")

    @task(1)
    def get_events(self):
        """Poll the events list."""
        self.client.get("/events")

    @task(1)
    def get_graph(self):
        """Poll the service graph."""
        self.client.get("/graph")

    @task(1)
    def get_health(self):
        """Poll the health endpoint."""
        self.client.get("/health")

    @task(1)
    def search(self):
        """Search the knowledge base."""
        self.client.get("/search?q=checkout", name="/search?q=checkout")

    @task(1)
    def get_runbooks(self):
        """List runbooks."""
        self.client.get("/runbooks")


class ReadOnlyUser(HttpUser):
    """Simulates dashboard users polling data."""

    wait_time = between(1, 3)
    host = API_HOST
    weight = 1

    @task(3)
    def get_incidents(self):
        self.client.get("/incidents")

    @task(2)
    def get_events(self):
        self.client.get("/events")

    @task(1)
    def get_graph(self):
        self.client.get("/graph")

    @task(1)
    def get_health(self):
        self.client.get("/health")
