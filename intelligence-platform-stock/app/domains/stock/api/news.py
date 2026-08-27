"""
News API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.news import CompanyNews, News
from app.domains.stock.schemas.news import NewsListResponse, NewsResponse

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/", response_model=NewsListResponse)
async def list_news(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List news, optionally filtered by ticker."""
    query = select(News)
    count_query = select(func.count(News.id))

    if ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        query = (
            select(News)
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company.id)
        )
        count_query = (
            select(func.count(News.id))
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company.id)
        )

    query = query.order_by(desc(News.published_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    news_items = result.scalars().all()

    total = (await db.execute(count_query)).scalar() or 0

    return NewsListResponse(
        news=[NewsResponse.model_validate(n) for n in news_items],
        total=total,
    )


@router.get("/{news_id}", response_model=NewsResponse)
async def get_news(news_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single news item."""
    result = await db.execute(select(News).where(News.id == news_id))
    news = result.scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=404, detail="News not found")
    return NewsResponse.model_validate(news)