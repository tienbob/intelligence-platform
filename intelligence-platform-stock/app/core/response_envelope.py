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
import json

from starlette.types import ASGIApp, Scope, Receive, Send, Message

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


class ResponseEnvelopeMiddleware:
    """Wrap JSON at the public ASGI boundary; pass other streams through."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or _is_excluded(scope["path"]):
            return await self.app(scope, receive, send)

        started = time.monotonic()
        response_start = None
        chunks = []
        wrap = False

        async def envelope_send(message: Message):
            nonlocal response_start, wrap
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                wrap = (
                    b"application/json" in headers.get(b"content-type", b"").lower()
                    and b"content-encoding" not in headers
                    and message["status"] not in {204, 304}
                    and scope["method"] != "HEAD"
                )
                if wrap:
                    response_start = message
                else:
                    await send(message)
                return
            if message["type"] != "http.response.body" or not wrap:
                await send(message)
                return

            chunks.append(message.get("body", b""))
            if message.get("more_body", False):
                return
            body = b"".join(chunks)
            try:
                original = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                # Malformed or empty upstream JSON must remain byte-for-byte
                # intact, rather than returning an already-consumed iterator.
                await send(response_start)
                await send({**message, "body": body})
                return

            meta = {
                "request_id": get_request_id(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": settings.APP_VERSION,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            }
            status = response_start["status"]
            if status >= 400:
                detail = original.get("detail", "An error occurred") if isinstance(original, dict) else original
                if isinstance(detail, list):
                    detail = "; ".join(d.get("msg", str(d)) if isinstance(d, dict) else str(d) for d in detail)
                wrapped = {"error": {"code": str(status), "message": str(detail)}, "meta": meta}
            else:
                wrapped = {"data": original, "meta": meta}
            body = json.dumps(wrapped, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            # Preserve duplicate headers such as Set-Cookie. Validators refer
            # to the original representation and must not survive rewriting.
            headers = [(key, value) for key, value in response_start.get("headers", [])
                       if key.lower() not in {b"content-length", b"etag", b"content-md5"}]
            headers.append((b"content-length", str(len(body)).encode()))
            await send({**response_start, "headers": headers})
            await send({**message, "body": body})

        await self.app(scope, receive, envelope_send)
