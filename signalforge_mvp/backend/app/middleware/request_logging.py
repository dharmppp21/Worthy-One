"""Request logging middleware for SignalForge.

Logs every request with structured fields (method, path, status_code, duration_ms).
Also assigns a request_id for tracing requests through logs.
"""

import logging
import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every request and response with structured fields."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)

        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "endpoint": str(request.url.path),
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else "unknown",
            },
        )
        response.headers["X-Request-Id"] = request_id
        return response
