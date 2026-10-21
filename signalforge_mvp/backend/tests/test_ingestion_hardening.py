"""Phase 5 ingestion hardening: request body-size cap + OTLP rate limiting."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.middleware import rate_limit
from app.middleware.body_size import MaxBodySizeMiddleware


def test_body_size_middleware_rejects_oversized():
    app = FastAPI()
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=10)

    @app.post("/x")
    async def x() -> dict:
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/x", content=b"0123456789AB").status_code == 413  # 12 > 10
    assert client.post("/x", content=b"hi").status_code == 200            # 2 <= 10


def test_body_size_guard_is_wired_into_app():
    assert any(m.cls is MaxBodySizeMiddleware for m in fastapi_app.user_middleware)


def test_otlp_endpoint_is_rate_limited(client, reset_store, monkeypatch):
    # Force the shared limiter to deny, then the OTLP endpoint must 429 — proving
    # /v1/traces is now covered by the same rate limit as /ingest.
    monkeypatch.setattr(rate_limit._rate_limiter, "_max_requests", 0)
    resp = client.post(
        "/v1/traces", content=b"", headers={"Content-Type": "application/x-protobuf"}
    )
    assert resp.status_code == 429
