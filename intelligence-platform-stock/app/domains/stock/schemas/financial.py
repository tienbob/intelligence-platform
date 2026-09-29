"""
Pydantic schemas for financial statement and metric API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FinancialStatementResponse(BaseModel):
    """Lean statement row — only columns rendered by the FE table."""

    id: int
    period: str
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    free_cash_flow: Optional[float] = None

    model_config = {"from_attributes": True}


class FinancialMetricResponse(BaseModel):
    """Lean metric set — every field rendered by CompanyDetail."""

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
    fcf_yield: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    fcf_growth: Optional[float] = None

    model_config = {"from_attributes": True}


class TechnicalIndicatorResponse(BaseModel):
    """Lean indicator set — every field rendered by CompanyDetail."""

    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    atr: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    volatility_30d: Optional[float] = None
    momentum: Optional[float] = None
    drawdown: Optional[float] = None

    model_config = {"from_attributes": True}