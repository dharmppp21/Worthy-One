#!/usr/bin/env python3
"""Load test orchestrator for SignalForge.

Starts the backend, runs a burst of requests, measures throughput,
API latency per endpoint, and incident detection delay, then prints
a structured report.

Usage:
    cd signalforge_mvp/backend
    .venv\\Scripts\\python.exe tests\\load\\run_load_tests.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE = "http://127.0.0.1:8000"
HEALTH_URL = f"{API_BASE}/health"
INGEST_URL = f"{API_BASE}/ingest"
INCIDENTS_URL = f"{API_BASE}/incidents"
EVENTS_URL = f"{API_BASE}/events"
GRAPH_URL = f"{API_BASE}/graph"
SEARCH_URL = f"{API_BASE}/search?q=checkout"
RUNBOOKS_URL = f"{API_BASE}/runbooks"

# Wipe the SQLite database so tests start fresh
DB_PATH = Path(__file__).parent.parent.parent / "signforge.db"


def _start_backend():
    """Start uvicorn in a subprocess and return the process handle."""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
    env["REDIS_URL"] = "redis://localhost:12345/0"  # dummy, gracefully degrades
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=Path(__file__).parent.parent.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def _wait_for_server(timeout: float = 30.0) -> bool:
    """Poll health endpoint until server is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(HEALTH_URL, timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _stop_backend(proc: subprocess.Popen):
    """Gracefully terminate the backend process."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _make_event(event_id: str, service_name: str, status_code: int, latency_ms: int) -> dict:
    return {
        "event_id": event_id,
        "tenant_id": "demo-company",
        "service_name": service_name,
        "event_type": "metric",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": "http_request",
        "value": 1,
        "attributes": {
            "status_code": status_code,
            "latency_ms": latency_ms,
            "endpoint": "/api/checkout",
        },
    }


# ─────────────────── Tests ───────────────────


def test_throughput(duration: float = 10.0, concurrency: int = 20) -> dict:
    """Fire ingest requests concurrently and measure throughput."""
    start = time.time()
    results = {"ok": 0, "error": 0, "latencies": []}
    seq = 0

    def _fire():
        nonlocal seq
        seq += 1
        t0 = time.time()
        try:
            resp = requests.post(INGEST_URL, json=_make_event(f"load-{seq:08d}", "checkout-service", 200, 100), timeout=5)
            dt = time.time() - t0
            if resp.status_code in (200, 202):
                results["ok"] += 1
                results["latencies"].append(dt * 1000)
            else:
                results["error"] += 1
        except Exception:
            results["error"] += 1

    # Fire as fast as possible for the duration
    while time.time() - start < duration:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(_fire) for _ in range(concurrency)]
            for _ in as_completed(futures):
                pass

    elapsed = time.time() - start
    latencies = results["latencies"]
    if not latencies:
        return {"rps": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "errors": results["error"]}

    latencies.sort()
    n = len(latencies)
    return {
        "rps": round(n / elapsed, 1),
        "avg_ms": round(sum(latencies) / n, 2),
        "p50_ms": round(latencies[int(n * 0.5)], 2),
        "p95_ms": round(latencies[int(n * 0.95)], 2),
        "p99_ms": round(latencies[int(n * 0.99)], 2),
        "errors": results["error"],
        "total": n,
    }


def test_api_latency() -> dict:
    """Measure latency for each read endpoint."""
    endpoints = {
        "GET /health": HEALTH_URL,
        "GET /incidents": INCIDENTS_URL,
        "GET /events": EVENTS_URL,
        "GET /graph": GRAPH_URL,
        "GET /search?q=checkout": SEARCH_URL,
        "GET /runbooks": RUNBOOKS_URL,
    }
    results = {}
    for name, url in endpoints.items():
        times = []
        for _ in range(10):
            t0 = time.time()
            try:
                resp = requests.get(url, timeout=5)
                dt = time.time() - t0
                if resp.status_code == 200:
                    times.append(dt * 1000)
            except Exception:
                pass
        if times:
            times.sort()
            results[name] = {
                "avg_ms": round(sum(times) / len(times), 2),
                "p50_ms": round(times[len(times) // 2], 2),
                "p95_ms": round(times[int(len(times) * 0.95)], 2),
            }
        else:
            results[name] = {"error": "all requests failed"}
    return results


def test_incident_detection_delay() -> dict:
    """Measure how long from first bad event to incident creation."""
    # Send a burst of 20 bad events to trigger an incident
    service_name = "latency-test-service"
    start_time = time.time()

    for i in range(20):
        requests.post(
            INGEST_URL,
            json=_make_event(f"delay-{i:04d}", service_name, 500, 2000),
            timeout=5,
        )

    # Poll incidents until one appears for our service
    poll_start = time.time()
    max_wait = 10.0
    found = False
    while time.time() - poll_start < max_wait:
        resp = requests.get(INCIDENTS_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            for inc in data.get("incidents", []):
                if inc["service_name"] == service_name:
                    found = True
                    break
        if found:
            break
        time.sleep(0.1)

    detection_time = time.time() - start_time
    return {
        "detected": found,
        "delay_ms": round(detection_time * 1000, 2),
        "events_to_trigger": 20,
    }


def test_concurrent_ingest_throughput() -> dict:
    """Fire a fixed number of requests with high concurrency and measure."""
    total_requests = 1000
    concurrency = 50
    start = time.time()
    results = {"ok": 0, "error": 0, "latencies": []}
    seq = 0

    def _fire():
        nonlocal seq
        seq += 1
        t0 = time.time()
        try:
            resp = requests.post(INGEST_URL, json=_make_event(f"burst-{seq:08d}", "checkout-service", 200, 100), timeout=5)
            dt = time.time() - t0
            if resp.status_code in (200, 202):
                results["ok"] += 1
                results["latencies"].append(dt * 1000)
            else:
                results["error"] += 1
        except Exception:
            results["error"] += 1

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_fire) for _ in range(total_requests)]
        for _ in as_completed(futures):
            pass

    elapsed = time.time() - start
    latencies = results["latencies"]
    if not latencies:
        return {"rps": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "errors": results["error"]}

    latencies.sort()
    n = len(latencies)
    return {
        "rps": round(n / elapsed, 1),
        "avg_ms": round(sum(latencies) / n, 2),
        "p50_ms": round(latencies[int(n * 0.5)], 2),
        "p95_ms": round(latencies[int(n * 0.95)], 2),
        "p99_ms": round(latencies[int(n * 0.99)], 2),
        "errors": results["error"],
        "total": n,
    }


def main():
    # Clean up old DB
    if DB_PATH.exists():
        DB_PATH.unlink()

    print("=" * 60)
    print("SignalForge Load Test")
    print("=" * 60)

    print("\n[1/4] Starting backend...")
    proc = _start_backend()
    if not _wait_for_server(timeout=15):
        print("ERROR: Backend did not start within 15 seconds.")
        _stop_backend(proc)
        sys.exit(1)
    print("Backend ready at", API_BASE)

    try:
        print("\n[2/4] Measuring API latency (read endpoints)...")
        latency_results = test_api_latency()
        for name, stats in latency_results.items():
            if "error" in stats:
                print(f"  {name}: {stats['error']}")
            else:
                print(f"  {name}: avg={stats['avg_ms']}ms p50={stats['p50_ms']}ms p95={stats['p95_ms']}ms")

        print("\n[3/4] Measuring ingest throughput (10s burst, 20 concurrent)...")
        throughput_results = test_throughput(duration=10.0, concurrency=20)
        print(f"  Requests: {throughput_results['total']}")
        print(f"  RPS: {throughput_results['rps']}")
        print(f"  Avg latency: {throughput_results['avg_ms']}ms")
        print(f"  P50 latency: {throughput_results['p50_ms']}ms")
        print(f"  P95 latency: {throughput_results['p95_ms']}ms")
        print(f"  P99 latency: {throughput_results['p99_ms']}ms")
        print(f"  Errors: {throughput_results['errors']}")

        print("\n[4/4] Measuring incident detection delay (20 bad events)...")
        delay_results = test_incident_detection_delay()
        if delay_results["detected"]:
            print(f"  Incident detected in {delay_results['delay_ms']}ms")
            print(f"  Events to trigger: {delay_results['events_to_trigger']}")
        else:
            print("  WARNING: Incident was NOT detected within 10s")

        print("\n[5/4] Fixed-count concurrent ingest (1000 requests, 50 workers)...")
        burst_results = test_concurrent_ingest_throughput()
        print(f"  Requests: {burst_results['total']}")
        print(f"  RPS: {burst_results['rps']}")
        print(f"  Avg latency: {burst_results['avg_ms']}ms")
        print(f"  P50 latency: {burst_results['p50_ms']}ms")
        print(f"  P95 latency: {burst_results['p95_ms']}ms")
        print(f"  P99 latency: {burst_results['p99_ms']}ms")
        print(f"  Errors: {burst_results['errors']}")

        # Write JSON report
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_latency_ms": latency_results,
            "ingest_throughput_10s": throughput_results,
            "incident_detection_delay_ms": delay_results,
            "concurrent_ingest_1000": burst_results,
        }
        report_path = Path(__file__).parent / "load_test_results.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: load_test_results.json")

    finally:
        print("\n[Done] Stopping backend...")
        _stop_backend(proc)
        time.sleep(1)
        if DB_PATH.exists():
            try:
                DB_PATH.unlink()
            except PermissionError:
                print(f"  Note: Could not delete {DB_PATH.name} (still in use by backend)")
                pass

    print("\n" + "=" * 60)
    print("Load test complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
