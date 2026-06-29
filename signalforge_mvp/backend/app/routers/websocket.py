"""WebSocket endpoint for real-time incident updates.

Clients connect to /ws/incidents and receive JSON messages when:
- A new incident is created
- An incident status is updated

Redis pub/sub is used as the message bus so multiple backend workers
can broadcast to all connected clients.
"""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.redis_client import redis_pubsub

router = APIRouter()

# In-memory connection manager for this process
class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected WebSocket clients."""
        dead = []
        for conn in self._connections:
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        # Clean up dead connections
        for conn in dead:
            self.disconnect(conn)


manager = ConnectionManager()


@router.websocket("/ws/incidents")
async def websocket_incidents(websocket: WebSocket) -> None:
    """WebSocket endpoint for live incident updates.

    Clients receive JSON messages with:
    - type: "incident_created" | "incident_updated"
    - incident: the incident data
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for client pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_incident_event(event_type: str, incident_data: dict[str, Any]) -> None:
    """Broadcast an incident event to all WebSocket clients.

    Also publishes to Redis pub/sub so other backend workers can
    broadcast to their own connected clients.
    """
    message = {"type": event_type, "incident": incident_data}
    # Broadcast to local clients
    await manager.broadcast(message)
    # Publish to Redis for other workers
    redis_pubsub.publish_incident_event(message)
