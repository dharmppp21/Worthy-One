"""Health, liveness, and readiness probes for orchestration."""

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.routers import health


def test_liveness_is_always_200():
    resp = TestClient(fastapi_app).get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_readiness_ok_when_db_up():
    resp = TestClient(fastapi_app).get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_readiness_returns_503_when_db_down(monkeypatch):
    monkeypatch.setattr(health, "_db_ok", lambda: False)
    resp = TestClient(fastapi_app).get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_health_reports_dependency_status():
    resp = TestClient(fastapi_app).get("/health")
    assert resp.status_code == 200
    assert "database" in resp.json()["dependencies"]
