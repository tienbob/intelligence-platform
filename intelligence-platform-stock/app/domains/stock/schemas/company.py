"""
Pydantic schemas for company API responses.

Lean: only fields rendered by the FE tables (Companies list, Search results).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CompanyResponse(BaseModel):
    """Lean company row — only fields rendered by the FE tables."""

    id: int
    ticker: str
    name: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None

    model_config = {"from_attributes": True}


class CompanyListResponse(BaseModel):
    companies: list[CompanyResponse]