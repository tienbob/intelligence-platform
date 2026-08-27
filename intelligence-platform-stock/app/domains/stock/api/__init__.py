"""
Stock domain API router.

The router is mounted by main.py under the domain's prefix (e.g., /api/v1/stock/...).
"""

from __future__ import annotations

from fastapi import APIRouter

stock_router = APIRouter(prefix="/stock", tags=["stock"])


@stock_router.get("/health")
async def stock_domain_health():
    """Health check for the stock domain."""
    return {
        "domain": "stock",
        "version": "1.0",
        "status": "operational",
    }


@stock_router.get("/companies")
async def list_companies():
    """List tracked companies."""
    return {"companies": [], "note": "Endpoint not yet migrated"}


@stock_router.get("/companies/{ticker}")
async def get_company(ticker: str):
    """Get company details."""
    return {"ticker": ticker, "note": "Endpoint not yet migrated"}


@stock_router.post("/analysis")
async def create_analysis():
    """Create a company analysis job."""
    return {"status": "not_implemented", "note": "Endpoint not yet migrated"}


@stock_router.get("/analysis/{analysis_id}")
async def get_analysis(analysis_id: str):
    """Get analysis results."""
    return {"analysis_id": analysis_id, "status": "not_implemented", "note": "Endpoint not yet migrated"}