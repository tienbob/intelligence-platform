"""
Observability (Phase 8, Sections 91-94).

Implements:
- Request ID propagation middleware
- Metrics collection (in-memory counters/histograms)
- Structured logging with request context
- Health check endpoints
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

# Context variable for request ID propagation
request_id_var: ContextVar[str] = ContextVar("request_id", default="unknown")


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_var.get()


class MetricsRegistry:
    """
    In-memory metrics registry.

    Tracks:
    - Request counts by endpoint/status
    - Request latency histograms
    - Error rates
    - Provider call counts
    """

    def __init__(self):
        self._request_counts: dict[str, int] = defaultdict(int)
        self._request_latencies: dict[str, list[float]] = defaultdict(list)
        self._error_counts: dict[str, int] = defaultdict(int)
        self._provider_calls: dict[str, int] = defaultdict(int)
        self._provider_errors: dict[str, int] = defaultdict(int)
        self._llm_calls: int = 0
        self._llm_tokens: int = 0

    def record_request(self, endpoint: str, status_code: int, latency_ms: float) -> None:
        """Record a request with its status and latency."""
        key = f"{endpoint}:{status_code}"
        self._request_counts[key] += 1
        self._request_latencies[endpoint].append(latency_ms)
        if status_code >= 500:
            self._error_counts[endpoint] += 1

    def record_provider_call(self, provider: str, success: bool = True) -> None:
        """Record a provider API call."""
        self._provider_calls[provider] += 1
        if not success:
            self._provider_errors[provider] += 1

    def record_llm_call(self, tokens: int = 0) -> None:
        """Record an LLM call and token usage."""
        self._llm_calls += 1
        self._llm_tokens += tokens

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all metrics."""
        return {
            "requests": dict(self._request_counts),
            "errors": dict(self._error_counts),
            "provider_calls": dict(self._provider_calls),
            "provider_errors": dict(self._provider_errors),
            "llm_calls": self._llm_calls,
            "llm_tokens": self._llm_tokens,
            "avg_latency_ms": {
                endpoint: sum(lats) / len(lats) if lats else 0
                for endpoint, lats in self._request_latencies.items()
            },
        }


# Global metrics registry
metrics = MetricsRegistry()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that assigns and propagates a request ID.

    Uses the client-supplied X-Request-ID if present, otherwise generates one.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get(settings.REQUEST_ID_HEADER) or str(uuid.uuid4())
        request_id_var.set(request_id)

        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Record error metrics even on unhandled exceptions
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record_request(request.url.path, 500, latency_ms)
            raise

        latency_ms = (time.monotonic() - start) * 1000
        metrics.record_request(request.url.path, response.status_code, latency_ms)

        response.headers[settings.REQUEST_ID_HEADER] = request_id
        return response


def get_metrics_snapshot() -> dict[str, Any]:
    """Return the current metrics snapshot."""
    return metrics.snapshot()