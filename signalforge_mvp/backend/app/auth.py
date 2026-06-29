"""Simple API key authentication and tenant isolation for SignalForge.

Production-grade systems use JWT tokens, OAuth2, or API gateways.
For this MVP, we use a simple API key header (X-API-Key) that maps to a tenant.
This gives a clear enterprise security story while keeping the demo lightweight.
"""

from fastapi import Header, HTTPException, status

# Map API keys to tenant IDs. In production, this would be a database lookup.
API_KEY_TENANTS: dict[str, str] = {
    "sf-api-key-demo": "demo-company",
    "sf-test-key": "demo-company",
}


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
    tenant_id = API_KEY_TENANTS.get(x_api_key)
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
    return API_KEY_TENANTS.get(x_api_key, "default")
