"""Risk tiers for endpoints.

Every route under /api/* declares a tier. It is exposed in the OpenAPI schema as
`x-risk-tier` so anything sitting in front of this API (a gateway, an agent's
tool list) can read it without importing this package.
"""
from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    CRITICAL = "critical"


def tier(t: Tier) -> dict:
    """Return the `openapi_extra` payload that tags a route with a tier."""
    return {"x-risk-tier": str(t)}


def route_tier(route) -> Tier | None:
    extra = getattr(route, "openapi_extra", None) or {}
    value = extra.get("x-risk-tier")
    return Tier(value) if value else None
