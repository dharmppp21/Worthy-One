"""Global exception handling for SignalForge.

In production, internal errors should not leak stack traces to clients.
This module provides a safe exception handler that logs the full error
server-side and returns a generic message to the client.

In development, the original error detail is preserved for debugging.
"""

import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import config

logger = logging.getLogger("app.errors")


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle HTTP exceptions (including our own HTTPException and FastAPI's)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors (e.g. missing required fields)."""
    # In development, show the actual validation errors
    if config.is_development():
        # errors() may contain non-JSON-serializable objects (e.g. ValueError)
        # Convert to a safe JSON representation
        def _safe_error(err):
            safe = {
                "type": err.get("type"),
                "loc": err.get("loc"),
                "msg": err.get("msg"),
                "input": str(err.get("input")) if err.get("input") is not None else None,
            }
            return safe

        detail = [_safe_error(e) for e in exc.errors()]
    else:
        detail = "Invalid request. Please check your input."
    return JSONResponse(
        status_code=422,
        content={"detail": detail},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions. Never leak internal details to clients."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception(
        "Unhandled exception",
        extra={"request_id": request_id, "path": str(request.url), "method": request.method},
    )

    if config.is_development():
        detail = f"Internal server error: {type(exc).__name__}: {str(exc)}"
    else:
        detail = "An unexpected error occurred. Please try again later."

    return JSONResponse(
        status_code=500,
        content={"detail": detail},
    )


def register_exception_handlers(app) -> None:
    """Register all exception handlers on the FastAPI app."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
