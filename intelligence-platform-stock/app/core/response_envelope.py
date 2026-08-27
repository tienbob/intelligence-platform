"""
Response envelope middleware (Architecture §71).

Wraps all API responses in a standard envelope:

    {
        "data": { ... },
        "meta": {
            "request_id": "...",
            "timestamp": "...",
            "version": "..."
        }
    }

Health, metrics, and root endpoints are excluded from wrapping.
Error responses are wrapped in:

    {
        "error": {
            "code": "...",
            "message": "..."
        },
        "meta": { ... }
    }
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.observability import get_request_id

settings = get_settings()

# Paths that should NOT be wrapped in the envelope
_EXCLUDED_PATHS = {
    "/",
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _is_excluded(path: str) -> bool:
    """Check if a path should be excluded from envelope wrapping."""
    # Strip API prefix for comparison
    for excluded in _EXCLUDED_PATHS:
        if path == excluded or path == f"{settings.API_V1_PREFIX}{excluded}":
            return True
    return False


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    """
    Middleware that wraps all API responses in a standard envelope.

    Architecture §71: All API responses use {"data": {...}, "meta": {...}}.
    Error responses use {"error": {"code": ..., "message": ...}, "meta": {...}}.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip excluded paths
        if _is_excluded(request.url.path):
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        # Only wrap JSON responses
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # Read the original response body
        body = b""
        async for chunk in response.__dict__.get("body_iterator", []):
            body += chunk

        if not body:
            return response

        import json

        try:
            original = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return response

        meta = {
            "request_id": get_request_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": settings.APP_VERSION,
            "elapsed_ms": elapsed_ms,
        }

        # Check if this is an error response (status >= 400)
        if response.status_code >= 400:
            # Convert FastAPI's flat {"detail": "..."} to Architecture §71 error format
            detail = original.get("detail", "An error occurred")
            if isinstance(detail, list):
                # FastAPI validation errors
                detail = "; ".join(
                    d.get("msg", str(d)) for d in detail if isinstance(d, dict)
                )
            wrapped = {
                "error": {
                    "code": str(response.status_code),
                    "message": str(detail),
                },
                "meta": meta,
            }
        else:
            wrapped = {
                "data": original,
                "meta": meta,
            }

        # Strip content-length since the wrapped body is larger
        safe_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() != "content-length"
        }
        return JSONResponse(
            content=wrapped,
            status_code=response.status_code,
            headers=safe_headers,
        )
