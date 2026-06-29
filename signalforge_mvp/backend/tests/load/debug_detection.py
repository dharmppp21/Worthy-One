import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_BASE = "http://127.0.0.1:8000"
DB_PATH = Path(__file__).parent.parent.parent / "signforge.db"


def _start_backend():
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
    env["REDIS_URL"] = "redis://localhost:12345/0"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=Path(__file__).parent.parent.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def _wait_for_server(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{API_BASE}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _stop_backend(proc: subprocess.Popen):
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


if __name__ == "__main__":
    if DB_PATH.exists():
        DB_PATH.unlink()

    proc = _start_backend()
    if not _wait_for_server():
        print("Backend failed to start")
        _stop_backend(proc)
        sys.exit(1)

    try:
        service = "debug-service"
        print(f"Sending 20 bad events to {service}...")
        for i in range(20):
            resp = requests.post(
                f"{API_BASE}/ingest",
                json=_make_event(f"debug-{i:04d}", service, 500, 2000),
                timeout=5,
            )
            print(f"  Event {i}: status={resp.status_code}, body={resp.text[:100]}")

        print("Checking incidents...")
        for _ in range(20):
            resp = requests.get(f"{API_BASE}/incidents", timeout=5)
            data = resp.json()
            found = any(inc["service_name"] == service for inc in data.get("incidents", []))
            if found:
                print(f"  Incident found! Count={data['count']}")
                break
            time.sleep(0.5)
        else:
            print("  No incident detected within 10s")
            print(f"  All incidents: {data}")
    finally:
        _stop_backend(proc)
        time.sleep(1)
        if DB_PATH.exists():
            try:
                DB_PATH.unlink()
            except PermissionError:
                pass
