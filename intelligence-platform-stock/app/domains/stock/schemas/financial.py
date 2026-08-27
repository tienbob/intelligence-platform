"""
Pydantic schemas for financial statement and metric API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FinancialStatementResponse(BaseModel):
    id: int
    company_id: int
    period: str
    period_type: str
    currency: str
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    shareholders_equity: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None
    free_cash_flow: Optional[float] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    filing_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FinancialMetricResponse(BaseModel):
    id: int
    company_id: int
    timestamp: datetime
    pe_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    debt_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    fcf_yield: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    fcf_growth: Optional[float] = None

    model_config = {"from_attributes": True}


class TechnicalIndicatorResponse(BaseModel):
    id: int
    company_id: int
    timestamp: datetime
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_20: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    atr: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    vwap: Optional[float] = None
    volatility_30d: Optional[float] = None
    momentum: Optional[float] = None
    drawdown: Optional[float] = None

    model_config = {"from_attributes": True}