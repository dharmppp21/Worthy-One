"""WebSocket endpoint for real-time discovery events.

Clients connect to /ws/discovery and receive JSON messages when:
- A new service is discovered
- A service is removed (stale)
- A service health status changes
- A new dependency is detected
- A dependency is removed
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect, status

from app.auth import get_current_tenant_optional
from app.discovery.dependencies.models import ServiceDependency
from app.discovery.models import DiscoveredService

router = APIRouter()


class DiscoveryEventPublisher:
    """Singleton publisher that maintains WebSocket connections and broadcasts
    discovery events to all connected clients.
    """

    _instance: Optional["DiscoveryEventPublisher"] = None

    def __new__(cls) -> "DiscoveryEventPublisher":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self._health_cache: Dict[str, str] = {}  # service_id -> last known status

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept a new WebSocket connection if under the limit.

        Returns:
            True if connected, False if rejected (too many clients).
        """
        async with self._lock:
            if len(self._connections) >= 100:
                return False
            await websocket.accept()
            self._connections.append(websocket)
            return True

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected client."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a JSON message to all connected clients."""
        dead: List[WebSocket] = []
        async with self._lock:
            conns = list(self._connections)
        for conn in conns:
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        # Clean up dead connections
        async with self._lock:
            for conn in dead:
                if conn in self._connections:
                    self._connections.remove(conn)

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    async def publish_service_discovered(self, service: DiscoveredService) -> None:
        await self.broadcast({
            "event_type": "service_discovered",
            "service": json.loads(service.model_dump_json()),
            "timestamp": service.last_seen_at.isoformat(),
        })

    async def publish_service_removed(self, service_id: str, service_name: str) -> None:
        await self.broadcast({
            "event_type": "service_removed",
            "service_id": service_id,
            "service_name": service_name,
            "timestamp": "",
        })
        # Remove from health cache
        self._health_cache.pop(service_id, None)

    async def publish_health_changed(
        self, service_id: str, service_name: str, old_status: str, new_status: str
    ) -> None:
        if old_status == new_status:
            return
        await self.broadcast({
            "event_type": "service_health_changed",
            "service_id": service_id,
            "service_name": service_name,
            "old_status": old_status,
            "new_status": new_status,
            "timestamp": "",
        })
        self._health_cache[service_id] = new_status

    async def publish_dependency_detected(self, dep: ServiceDependency) -> None:
        await self.broadcast({
            "event_type": "dependency_detected",
            "dependency": json.loads(dep.model_dump_json()),
            "timestamp": dep.last_seen_at.isoformat() if dep.last_seen_at else "",
        })

    async def publish_dependency_removed(self, source_id: str, target_id: str) -> None:
        await self.broadcast({
            "event_type": "dependency_removed",
            "source_id": source_id,
            "target_id": target_id,
            "timestamp": "",
        })

    # ------------------------------------------------------------------
    # Health tracking
    # ------------------------------------------------------------------

    def track_health(self, service_id: str, status: str) -> bool:
        """Track health status and return True if it changed."""
        old = self._health_cache.get(service_id)
        if old != status:
            self._health_cache[service_id] = status
            return True
        return False

    def get_cached_health(self, service_id: str) -> Optional[str]:
        return self._health_cache.get(service_id)


# Singleton instance
publisher = DiscoveryEventPublisher()


@router.websocket("/ws/discovery")
async def websocket_discovery(websocket: WebSocket) -> None:
    """WebSocket endpoint for live discovery events.

    On connection, sends the current discovered services and dependency graph.
    Then listens for client pings and broadcasts events as they happen.
    """
    # Extract optional API key from query param or header for tenant isolation
    api_key = websocket.query_params.get("api_key", "")
    if not api_key:
        api_key = websocket.headers.get("X-API-Key", "")

    tenant_id = get_current_tenant_optional(api_key)

    connected = await publisher.connect(websocket)
    if not connected:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        # Send initial handshake so the client knows the connection is alive.
        await websocket.send_json({
            "event_type": "connected",
            "tenant_id": tenant_id,
            "message": "Discovery event stream connected. Subscribe to events.",
        })

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await publisher.disconnect(websocket)


async def broadcast_discovery_event(event_type: str, payload: dict[str, Any]) -> None:
    """Convenience wrapper for broadcasting raw events."""
    await publisher.broadcast({"event_type": event_type, **payload})
