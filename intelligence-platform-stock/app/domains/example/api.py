"""Example domain API router — minimal endpoints for platform validation."""

from __future__ import annotations

from fastapi import APIRouter

example_router = APIRouter(prefix="/example", tags=["example"])


@example_router.get("/health")
async def example_health():
    return {"domain": "example", "version": "1.0", "status": "operational"}


@example_router.get("/products/{product_id}")
async def get_product(product_id: str):
    return {
        "product_id": product_id,
        "name": product_id,
        "price": 99.99,
        "quality_score": 85,
        "demand_score": 72,
    }