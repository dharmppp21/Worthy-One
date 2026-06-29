import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:12345/0")  # Dummy URL for tests — Redis gracefully degrades

import pytest
from fastapi.testclient import TestClient
from app.database import init_db
from app.main import app as fastapi_app
from app.middleware.rate_limit import reset_rate_limiter
from app.storage import store


API_KEY_HEADERS = {"X-API-Key": "sf-test-key"}


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    init_db()


@pytest.fixture
def reset_store():
    """Reset database, Redis state, and rate limiter before each test."""
    store.reset()
    reset_rate_limiter()
    yield
    store.reset()
    reset_rate_limiter()


@pytest.fixture
def client():
    """FastAPI TestClient for integration testing."""
    with TestClient(fastapi_app) as c:
        c.headers.update(API_KEY_HEADERS)
        yield c


@pytest.fixture
def auth_client():
    """Authenticated FastAPI TestClient with API key header."""
    with TestClient(fastapi_app, headers=API_KEY_HEADERS) as c:
        yield c
