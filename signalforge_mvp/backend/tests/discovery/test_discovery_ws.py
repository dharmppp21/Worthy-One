"""Tests for the discovery WebSocket endpoint and event publisher."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.discovery.models import DiscoveredService
from app.discovery.dependencies.models import ServiceDependency
from app.routers.discovery_ws import (
    DiscoveryEventPublisher,
    publisher,
    websocket_discovery,
)


@pytest.fixture(autouse=True)
def reset_publisher():
    """Reset the singleton publisher state before each test."""
    old_connections = list(publisher._connections)
    old_health = dict(publisher._health_cache)
    publisher._connections = []
    publisher._health_cache = {}
    yield
    publisher._connections = old_connections
    publisher._health_cache = old_health


class TestDiscoveryEventPublisher:
    """Unit tests for the DiscoveryEventPublisher singleton."""

    def test_singleton_identity(self):
        """The publisher should be a singleton."""
        p1 = DiscoveryEventPublisher()
        p2 = DiscoveryEventPublisher()
        assert p1 is p2

    def test_track_health_returns_true_on_change(self):
        """track_health should return True when status changes."""
        publisher._health_cache = {}
        assert publisher.track_health("svc-1", "up") is True
        assert publisher.track_health("svc-1", "up") is False
        assert publisher.track_health("svc-1", "down") is True

    def test_get_cached_health(self):
        """get_cached_health should return the last known status."""
        publisher._health_cache = {"svc-1": "up"}
        assert publisher.get_cached_health("svc-1") == "up"
        assert publisher.get_cached_health("missing") is None

    @pytest.mark.asyncio
    async def test_publish_service_discovered(self):
        """Publishing service_discovered should send JSON to connected clients."""
        mock_ws = AsyncMock()
        publisher._connections = [mock_ws]

        svc = DiscoveredService(service_name="web", host="10.0.0.1")
        await publisher.publish_service_discovered(svc)

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["event_type"] == "service_discovered"
        assert call_args["service"]["service_name"] == "web"

    @pytest.mark.asyncio
    async def test_publish_service_removed(self):
        """Publishing service_removed should send JSON to connected clients."""
        mock_ws = AsyncMock()
        publisher._connections = [mock_ws]

        await publisher.publish_service_removed("id-1", "web")

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["event_type"] == "service_removed"
        assert call_args["service_id"] == "id-1"
        assert call_args["service_name"] == "web"

    @pytest.mark.asyncio
    async def test_publish_health_changed(self):
        """Publishing health_changed should send JSON to connected clients."""
        mock_ws = AsyncMock()
        publisher._connections = [mock_ws]

        await publisher.publish_health_changed("id-1", "web", "up", "down")

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["event_type"] == "service_health_changed"
        assert call_args["old_status"] == "up"
        assert call_args["new_status"] == "down"

    @pytest.mark.asyncio
    async def test_publish_dependency_detected(self):
        """Publishing dependency_detected should send JSON to connected clients."""
        mock_ws = AsyncMock()
        publisher._connections = [mock_ws]

        dep = ServiceDependency(
            source_service_id="a",
            target_service_id="b",
            dependency_type="network",
            connection_count=5,
            confidence_score=0.9,
        )
        await publisher.publish_dependency_detected(dep)

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["event_type"] == "dependency_detected"
        assert call_args["dependency"]["source_service_id"] == "a"

    @pytest.mark.asyncio
    async def test_publish_dependency_removed(self):
        """Publishing dependency_removed should send JSON to connected clients."""
        mock_ws = AsyncMock()
        publisher._connections = [mock_ws]

        await publisher.publish_dependency_removed("a", "b")

        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["event_type"] == "dependency_removed"
        assert call_args["source_id"] == "a"
        assert call_args["target_id"] == "b"

    @pytest.mark.asyncio
    async def test_connection_limit(self):
        """Only 100 connections should be accepted."""
        for _ in range(100):
            mock_ws = AsyncMock()
            result = await publisher.connect(mock_ws)
            assert result is True

        # The 101st connection should be rejected
        mock_ws = AsyncMock()
        result = await publisher.connect(mock_ws)
        assert result is False

        assert len(publisher._connections) == 100

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self):
        """disconnect should remove the websocket from connections."""
        mock_ws = AsyncMock()
        await publisher.connect(mock_ws)
        assert len(publisher._connections) == 1

        await publisher.disconnect(mock_ws)
        assert len(publisher._connections) == 0


class TestDiscoveryWebSocketAuth:
    """Tests for WebSocket auth via query param and header."""

    def test_ws_with_api_key_query_param(self, client: TestClient):
        """Connection with valid api_key query param should succeed."""
        with client.websocket_connect("/ws/discovery?api_key=sf-api-key-demo") as ws:
            msg = ws.receive_json()
            assert msg["event_type"] == "connected"
            assert msg["tenant_id"] == "demo-company"

    def test_ws_without_api_key(self):
        """Connection without API key should use default tenant."""
        from app.main import app
        with TestClient(app) as c:
            with c.websocket_connect("/ws/discovery") as ws:
                msg = ws.receive_json()
                assert msg["event_type"] == "connected"
                assert msg["tenant_id"] == "default"

    def test_ws_ping_pong(self, client: TestClient):
        """Client should be able to send ping and receive pong."""
        with client.websocket_connect("/ws/discovery") as ws:
            ws.receive_json()  # handshake
            ws.send_text("ping")
            assert ws.receive_text() == "pong"

    def test_ws_connection_limit(self, client: TestClient):
        """Only 100 connections should be accepted."""
        sockets = []
        for _ in range(100):
            ws = client.websocket_connect("/ws/discovery")
            ws.__enter__()
            ws.receive_json()  # handshake
            sockets.append(ws)

        # The 101st connection should be rejected
        with pytest.raises(Exception):
            ws = client.websocket_connect("/ws/discovery")
            ws.__enter__()

        # Clean up
        for ws in sockets:
            ws.__exit__(None, None, None)
