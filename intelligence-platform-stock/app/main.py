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

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.observability import RequestIDMiddleware, get_metrics_snapshot
from app.core.response_envelope import ResponseEnvelopeMiddleware
from app.core.versioning import ARCHITECTURE_VERSION, PIPELINE_VERSION
from app.intelligence.registry import get_registry

settings = get_settings()
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    from app.core.logging import get_logger

    logger = get_logger(__name__)

    # Fail loud if the configured EMBEDDING_DIMENSIONS doesn't match the DB's
    # `embeddings.embedding` vector width (see database.verify_embedding_dimensions).
    try:
        from app.core.database import verify_embedding_dimensions

        await verify_embedding_dimensions()
    except RuntimeError:
        raise  # dimension mismatch between config and schema — fatal
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Embedding-dimension pre-flight skipped: %s", exc)


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
app.add_middleware(ResponseEnvelopeMiddleware)

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
async def health_ready():
    """Readiness check — database and required services available."""
    from app.core.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "degraded"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
    }


@app.get("/health")
async def health():
    """Health check endpoint (backward compatible)."""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics_endpoint():
    """Metrics endpoint."""
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