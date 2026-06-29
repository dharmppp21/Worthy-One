"""In-memory rate limiting for SignalForge.

Uses a simple sliding window per client IP. For production, replace with
Redis-backed rate limiting (e.g. slowapi + redis) to work across multiple
backend instances.
"""

import time
from collections import defaultdict
from fastapi import Request, HTTPException, status

from app.config import config


class _SlidingWindow:
    """Simple in-memory sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self._window_seconds

        # Clean old requests for this key
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= self._max_requests:
            return False

        self._requests[key].append(now)
        return True

    def reset(self) -> None:
        self._requests.clear()


_rate_limiter = _SlidingWindow(
    max_requests=config.RATE_LIMIT_RPS,
    window_seconds=config.RATE_LIMIT_WINDOW_SECONDS,
)


def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency that applies rate limiting by client IP.

    Raises HTTP 429 Too Many Requests if the limit is exceeded.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down your requests.",
        )


def reset_rate_limiter() -> None:
    """Reset the rate limiter state. Useful for testing."""
    _rate_limiter.reset()
