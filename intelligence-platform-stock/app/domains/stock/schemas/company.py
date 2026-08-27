"""
Pydantic schemas for company API responses.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CompanyBase(BaseModel):
    ticker: str
    name: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    market_cap: Optional[float] = None
    description: Optional[str] = None
    website: Optional[str] = None

    model_config = {"from_attributes": True}


class CompanyResponse(CompanyBase):
    id: int
    isin: Optional[str] = None
    cik: Optional[str] = None
    cusip: Optional[str] = None


class CompanyListResponse(BaseModel):
    companies: list[CompanyResponse]
    total: int