"""Inbound rate-limiting middleware (audit S03).

The sliding-window limiter in ``app.core.rate_limit`` was fully implemented
but never consulted by any route or middleware, and it defaulted to disabled
— so paid-work endpoints accepted unbounded requests. This middleware checks
quota BEFORE the request reaches expensive work.

Scope: the Python side of paid work (analysis creation, portfolio
optimization and backtests). Rails authentication has a separate PostgreSQL
counter budget in AuthThrottle.

Client identity comes from ``get_client_key``, which prefers the gateway's
``X-User-Id`` header, giving each user their own budget rather than one
shared container-IP quota.

Budgets use Redis across processes; paid work returns 503 if Redis is unavailable.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.rate_limit import rate_limit

settings = get_settings()

# Path suffix → (scope, per-minute limit). Suffix matching covers BOTH the
# public (/api/v1/...) and internal (/internal/...) mounts of the same router.
_LIMITED_POST_PATHS: dict[str, tuple[str, int | None]] = {
    "/backtest/runs": ("backtest", settings.RATE_LIMIT_ANALYSIS_PER_MINUTE),
    "/backtest/snapshots": ("snapshots", settings.RATE_LIMIT_ANALYSIS_PER_MINUTE),
    "/analysis/company": ("analysis", settings.RATE_LIMIT_ANALYSIS_PER_MINUTE),
    "/portfolio/optimize": ("portfolio", settings.RATE_LIMIT_PORTFOLIO_PER_MINUTE),
}


def limited_scope_for(method: str, path: str) -> tuple[str, int | None] | None:
    """Return the (scope, limit) to enforce for this request, or None."""
    if method != "POST":
        return None
    path = path.rstrip("/")
    for suffix, scope_and_limit in _LIMITED_POST_PATHS.items():
        if path.endswith(suffix):
            return scope_and_limit
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject over-quota POSTs with 429 + Retry-After before any work starts."""

    async def dispatch(self, request: Request, call_next) -> Response:
        matched = limited_scope_for(request.method, request.url.path)
        if matched is not None:
            scope, limit = matched
            try:
                await rate_limit(request, limit=limit, scope=scope)
            except HTTPException as exc:
                return JSONResponse(
                    {"detail": exc.detail},
                    status_code=exc.status_code,
                    headers=dict(exc.headers or {}),
                )
        return await call_next(request)