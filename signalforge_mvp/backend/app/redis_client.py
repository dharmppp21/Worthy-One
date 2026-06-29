import json
import threading

import redis

from app.config import config


REDIS_URL = config.REDIS_URL
REDIS_WINDOW_SIZE = 50  # Keep last N events per service for rolling window
REDIS_KEY_TTL = 3600  # 1 hour TTL for auto-cleanup

INCIDENT_PUBSUB_CHANNEL = "incident_events"


def _redis_key(tenant_id: str, service_name: str) -> str:
    """Build the Redis key for a tenant/service event window."""
    return f"events:{tenant_id}:{service_name}"


class RedisWindowStore:
    """Hot operational state: rolling windows of recent events per service.

    PostgreSQL remains the durable source of truth.
    Redis only holds the latest N events for fast anomaly detection.
    If Redis is unavailable, the system falls back to PostgreSQL.
    """

    def __init__(self, redis_url: str) -> None:
        try:
            self._client = redis.Redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
            self._available = True
        except Exception:
            self._client = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def add_event(self, tenant_id: str, service_name: str, event_data: dict) -> None:
        """Push an event into the rolling window for a service."""
        if not self._available:
            return

        key = _redis_key(tenant_id, service_name)
        # LPUSH adds to the front (most recent first)
        self._client.lpush(key, json.dumps(event_data))
        # LTRIM keeps only the last N items
        self._client.ltrim(key, 0, REDIS_WINDOW_SIZE - 1)
        # Set TTL for auto-cleanup
        self._client.expire(key, REDIS_KEY_TTL)

    def get_recent_events(self, tenant_id: str, service_name: str) -> list[dict]:
        """Return the latest N events from the rolling window."""
        if not self._available:
            return []

        key = _redis_key(tenant_id, service_name)
        raw_events = self._client.lrange(key, 0, REDIS_WINDOW_SIZE - 1)
        # LRANGE returns from index 0 (most recent) — reverse to chronological order
        events = []
        for raw in reversed(raw_events):
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return events

    def reset(self, tenant_id: str | None = None) -> None:
        """Clear rolling windows. If tenant_id is None, clear all."""
        if not self._available:
            return

        if tenant_id is None:
            # Find all keys matching the pattern and delete them
            keys = self._client.scan_iter(match="events:*:*")
            for key in keys:
                self._client.delete(key)
        else:
            keys = self._client.scan_iter(match=f"events:{tenant_id}:*")
            for key in keys:
                self._client.delete(key)


class RedisPubSub:
    """Redis pub/sub for broadcasting incident events across backend workers.

    Each backend worker process has its own WebSocket connections.
    When an incident is created or updated, the event is published to Redis
    so all workers can broadcast to their own clients.
    """

    def __init__(self, redis_url: str) -> None:
        try:
            self._client = redis.Redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
            self._available = True
        except redis.ConnectionError:
            self._client = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def publish_incident_event(self, message: dict) -> None:
        """Publish an incident event to the Redis pub/sub channel."""
        if not self._available:
            return
        try:
            self._client.publish(INCIDENT_PUBSUB_CHANNEL, json.dumps(message))
        except Exception:
            pass

    def start_subscriber(self, callback) -> None:
        """Start a background thread that listens for incident events.

        The callback receives the parsed message dict.
        """
        if not self._available:
            return

        def _listen():
            try:
                pubsub = self._client.pubsub()
                pubsub.subscribe(INCIDENT_PUBSUB_CHANNEL)
                for msg in pubsub.listen():
                    if msg["type"] == "message":
                        try:
                            data = json.loads(msg["data"])
                            callback(data)
                        except Exception:
                            pass
            except Exception:
                pass

        thread = threading.Thread(target=_listen, daemon=True)
        thread.start()


redis_window = RedisWindowStore(REDIS_URL)
redis_pubsub = RedisPubSub(REDIS_URL)
