"""
Intelligence Platform — domain-agnostic application entry point.

The platform auto-discovers domain modules from app/domains/ and wires
them into the FastAPI application. No domain-specific imports needed.

Architecture:
    Core (intelligence/) → Domain Packs (domains/*) → App Wiring (this file)

To add a new domain:
    1. Create app/domains/<name>/ with a manifest.py
    2. Set INTELLIGENCE_DOMAINS=stock,<name> (or omit to enable all)
    3. Restart — the registry auto-discovers it
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.observability import RequestIDMiddleware, get_metrics_snapshot
from app.core.rate_limit_middleware import RateLimitMiddleware
from app.core.redis_cache import get_redis_cache
from app.core.response_envelope import ResponseEnvelopeMiddleware
from app.core.security import IdempotencyReplay
from app.core.versioning import ARCHITECTURE_VERSION, PIPELINE_VERSION
from app.intelligence.registry import get_registry

settings = get_settings()
setup_logging()

# ── Fail-closed production guard (audit S1) ─────────────────────
# In production the internal API must never be reachable with an unset (or
# well-known dev) service key, and user JWTs must never be verified with the
# default secret. Refuse to boot instead of failing open.
_DEV_SERVICE_KEY = "dev-service-key-change-me"
_DEFAULT_JWT_SECRET = "change-me-in-production-change-me-in-production-1234"

if settings.ENVIRONMENT == "production":
    _secret_problems: list[str] = []
    if not settings.INTERNAL_SERVICE_KEY or settings.INTERNAL_SERVICE_KEY == _DEV_SERVICE_KEY:
        _secret_problems.append(
            "INTERNAL_SERVICE_KEY is unset or the known dev default "
            f"({_DEV_SERVICE_KEY}) — the /internal API would be open"
        )
    if settings.AUTH_ENABLED and (
        not settings.JWT_SECRET_KEY or settings.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET
    ):
        _secret_problems.append(
            "AUTH_ENABLED=true but JWT_SECRET_KEY is unset or the known default"
        )
    if _secret_problems:
        raise RuntimeError(
            "Refusing to start with ENVIRONMENT=production: "
            + "; ".join(_secret_problems)
            + ". Set real secrets, or set ENVIRONMENT=development for local development."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    from app.core.logging import get_logger

    logger = get_logger(__name__)

    # Discover all domain modules
    registry = get_registry()
    logger.info(
        "Discovered %d domain(s): %s",
        len(registry.enabled),
        [d.name for d in registry.enabled],
    )

    # Start domain-specific schedulers
    from app.workers.scheduler import create_scheduler

    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))

    from app.core.security import _idempotency_redis

    if get_redis_cache().available:
        logger.info("Redis cache enabled — idempotency is durable across workers")
    else:
        logger.info("Redis unavailable — idempotency uses the in-memory fallback")
    _idempotency_redis()  # warm the idempotency handle early

    yield

    scheduler.shutdown()
    logger.info("Background scheduler stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered domain-agnostic intelligence platform",
    lifespan=lifespan,
)

# ── Middleware ──────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)
# Rate limiting runs INSIDE the envelope middleware (added first → sits
# closer to the app) so its 429 responses get wrapped in the standard
# {"error": ...} shape with Retry-After preserved (audit S03).
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ResponseEnvelopeMiddleware)


# ── Idempotency replay (Architecture §101, audit F04) ───────────
# A replay returns the ORIGINAL status + payload — re-wrapped by the envelope
# middleware as {"data": ...} — plus the replay headers, so a retry is
# indistinguishable from the first response instead of becoming an error body.
@app.exception_handler(IdempotencyReplay)
async def _idempotency_replay_handler(_request: Request, exc: IdempotencyReplay):
    return JSONResponse(
        content=exc.body,
        status_code=exc.status_code,
        headers={"Idempotency-Key": exc.key, "Idempotency-Replayed": "true"},
    )

# ── Domain Routes (auto-discovered) ─────────────────────────────
#
# Contract: Each domain router MUST declare its own prefix as
# ``APIRouter(prefix="/<domain_name>")``. The application mounts
# every domain under ``/api/v1``, producing final paths like:
#
#     /api/v1/stock/health
#     /api/v1/hr/health
#     /api/v1/example/health
#
# This keeps prefix ownership in the domain (where it belongs) and
# avoids collisions between domains.

logger = get_logger(__name__)
registry = get_registry()
for domain in registry.enabled:
    try:
        router = domain.get_api_router()
        app.include_router(router, prefix=f"/api/v1")
        logger.info("Mounted domain '%s' at /api/v1%s", domain.name, router.prefix)
    except Exception as exc:
        logger.error("Failed to mount domain '%s': %s", domain.name, exc)

# ── Internal API (Rails→Python gateway) ─────────────────────────
# Mounted at /internal — only reachable on the private Docker network.
# Authenticated via X-Service-Key header. Domains expose their internal
# routers through the DomainModule contract; core never imports domain
# code directly.
for domain in registry.enabled:
    get_internal_router = getattr(domain, "get_internal_router", None)
    if get_internal_router is None:
        continue
    try:
        router = get_internal_router()
        if router is not None:
            app.include_router(router, prefix="/internal")
            logger.info(
                "Mounted internal router for domain '%s' at /internal%s",
                domain.name,
                router.prefix,
            )
    except Exception as exc:
        logger.error(
            "Failed to mount internal router for domain '%s': %s",
            domain.name,
            exc,
        )

# ── Platform Routes ─────────────────────────────────────────────


@app.get("/")
async def root():
    """Root endpoint with platform info."""
    return {
        "name": settings.APP_NAME,
        "application_version": settings.APP_VERSION,
        "architecture_version": ARCHITECTURE_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "domains": [d.name for d in registry.enabled],
        "docs": "/docs",
    }


@app.get("/health/live")
async def health_live():
    """Liveness check."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(response: Response):
    """Readiness check — database and required services available."""
    from app.core.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "degraded"
        response.status_code = 503

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
    }


@app.get("/health")
async def health():
    """Health check endpoint (backward compatible)."""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics_endpoint(request: Request):
    """Metrics snapshot (key-gated outside development).

    Labels are route-templated so no resource ids leak (audit S02), but the
    snapshot still exposes traffic patterns — outside development it requires
    the internal service key, and nginx no longer proxies this path at all
    (audit S02 remainder).
    """
    if settings.ENVIRONMENT == "production":
        expected = settings.INTERNAL_SERVICE_KEY or settings.APP_API_KEY
        provided = request.headers.get("X-Service-Key") or request.headers.get("X-API-Key")
        if not expected or not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Metrics require the internal service key")
    return get_metrics_snapshot()


@app.get("/domains")
async def list_domains():
    """List all discovered domains and their status."""
    return {
        "domains": [
            {
                "name": d.name,
                "domain_version": d.version,
                "enabled": True,
            }
            for d in registry.enabled
        ],
        "total": len(registry.enabled),
    }