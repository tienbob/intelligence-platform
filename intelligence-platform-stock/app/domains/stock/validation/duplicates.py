"""
Duplicate detection (Section 13).

Checks for duplicate records before canonical storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.financial import FinancialStatement
from app.domains.stock.models.macro import EconomicIndicator
from app.domains.stock.models.news import News
from app.domains.stock.models.stock_price import StockPrice

logger = get_logger(__name__)


async def is_duplicate_stock_price(
    session: AsyncSession, company_id: int, timestamp: datetime, interval: str
) -> bool:
    """Check if a stock price record already exists."""
    result = await session.execute(
        select(StockPrice.id).where(
            StockPrice.company_id == company_id,
            StockPrice.timestamp == timestamp,
            StockPrice.interval == interval,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def is_duplicate_news(session: AsyncSession, content_hash: str) -> bool:
    """Check if a news item already exists by content hash."""
    result = await session.execute(
        select(News.id).where(News.content_hash == content_hash).limit(1)
    )
    return result.scalar_one_or_none() is not None


def compute_news_hash(
    title: str,
    url: str | None = None,
    published_at: str | None = None,
    external_id: str | None = None,
    source: str | None = None,
) -> str:
    """Compute a canonical SHA256 hash for a news item.

    Dedup strategy:
      1. If a stable provider `external_id` exists, hash on that
         (normalized title as a fallback sanity component).
      2. Otherwise hash on `title|published_at` — deliberately
         excluding the URL so the same syndicated article reached via
         different URLs collapses to one record.

    `published_at` should be a canonical ISO string (UTC) when available.
    """
    if external_id and source:
        content = f"{source}|{external_id}|{(title or '').strip().lower()}"
    else:
        content = f"{(title or '').strip().lower()}|{published_at or ''}"
    return hashlib.sha256(content.encode()).hexdigest()


async def is_duplicate_financial(
    session: AsyncSession, company_id: int, period: str
) -> bool:
    """Check if a financial statement already exists."""
    result = await session.execute(
        select(FinancialStatement.id).where(
            FinancialStatement.company_id == company_id,
            FinancialStatement.period == period,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def is_duplicate_indicator(
    session: AsyncSession, indicator: str, timestamp: datetime
) -> bool:
    """Check if an economic indicator data point already exists."""
    result = await session.execute(
        select(EconomicIndicator.id).where(
            EconomicIndicator.indicator == indicator,
            EconomicIndicator.timestamp == timestamp,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None