"""API key authentication + tenant isolation.

Integration tests exercise the real HTTP auth path; the unit tests below cover
the config-driven key map, constant-time lookup, and production fail-closed.
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.config import _parse_api_keys
from app.main import app as fastapi_app


def test_missing_api_key_returns_401():
    """Requests without X-API-Key header should return 401 Unauthorized."""
    client = TestClient(fastapi_app)
    resp = client.get("/incidents")
    assert resp.status_code == 401
    assert "Missing X-API-Key header" in resp.json()["detail"]


def test_invalid_api_key_returns_401():
    """Requests with an invalid X-API-Key should return 401 Unauthorized."""
    client = TestClient(fastapi_app, headers={"X-API-Key": "bad-key"})
    resp = client.get("/incidents")
    assert resp.status_code == 401
    assert "Invalid API key" in resp.json()["detail"]


def test_valid_api_key_returns_data(client, reset_store):
    """Requests with a valid test API key should succeed."""
    resp = client.get("/incidents")
    assert resp.status_code == 200
    assert "count" in resp.json()


def test_tenant_isolation_prevents_cross_tenant_access(monkeypatch, reset_store):
    """A key maps to exactly its tenant; a different tenant's key sees its own scope."""
    monkeypatch.setattr(auth.config, "API_KEYS", {"key-a": "tenant-a", "key-b": "tenant-b"})
    assert auth.get_current_tenant(x_api_key="key-a") == "tenant-a"
    assert auth.get_current_tenant(x_api_key="key-b") == "tenant-b"


# ─── Unit tests: config-driven keys + constant-time lookup ───

def test_parse_api_keys_ignores_malformed_entries():
    parsed = _parse_api_keys("k1:t1, k2:t2 ,nocolon,:,x:")
    assert parsed == {"k1": "t1", "k2": "t2"}


def test_valid_key_resolves_tenant(monkeypatch):
    monkeypatch.setattr(auth.config, "API_KEYS", {"abc": "acme"})
    assert auth.get_current_tenant(x_api_key="abc") == "acme"


def test_missing_key_is_401():
    with pytest.raises(HTTPException) as exc:
        auth.get_current_tenant(x_api_key="")
    assert exc.value.status_code == 401


def test_invalid_key_is_401(monkeypatch):
    monkeypatch.setattr(auth.config, "API_KEYS", {"abc": "acme"})
    with pytest.raises(HTTPException) as exc:
        auth.get_current_tenant(x_api_key="wrong")
    assert exc.value.status_code == 401


def test_empty_key_map_fails_closed(monkeypatch):
    # Production with SIGNALFORGE_API_KEYS unset -> no keys -> everything 401.
    monkeypatch.setattr(auth.config, "API_KEYS", {})
    with pytest.raises(HTTPException) as exc:
        auth.get_current_tenant(x_api_key="sf-api-key-demo")
    assert exc.value.status_code == 401


def test_optional_tenant_defaults_without_key():
    assert auth.get_current_tenant_optional(x_api_key="") == "default"
