"""API key authentication and tenant isolation for SignalForge.

Keys are configured out-of-band (``SIGNALFORGE_API_KEYS`` env var, parsed in
config) rather than hardcoded, and compared in constant time so a wrong key
cannot be distinguished from a valid one by response timing. Production-grade
systems would layer JWT/OAuth2 or an API gateway on top; this is the baseline.
"""

import hmac

from fastapi import Header, HTTPException, status

from app.config import config


def _lookup_tenant(api_key: str) -> str | None:
    """Return the tenant for an API key, or None. Constant-time comparison.

    Compares against every configured key (no early exit) with
    hmac.compare_digest, so neither a wrong key's bytes nor its position leaks
    through timing.
    """
    matched: str | None = None
    for key, tenant in config.API_KEYS.items():
        if hmac.compare_digest(api_key, key):
            matched = tenant
    return matched


def get_current_tenant(x_api_key: str = Header(default="", alias="X-API-Key")) -> str:
    """Extract tenant_id from the X-API-Key header.

    Raises HTTP 401 if the key is missing or invalid.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    tenant_id = _lookup_tenant(x_api_key)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return tenant_id


def get_current_tenant_optional(x_api_key: str = Header(default="", alias="X-API-Key")) -> str:
    """Extract tenant_id from the X-API-Key header. Returns default tenant if missing.

    Used for health check and other public endpoints.
    """
    if not x_api_key:
        return "default"
    return _lookup_tenant(x_api_key) or "default"
