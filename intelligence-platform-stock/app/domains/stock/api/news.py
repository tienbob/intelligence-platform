"""
News API endpoints.

Access-scoping (docs/TABLE_OWNERSHIP.md): when the gateway forwards
``X-User-Id``, news is only shown for companies linked to that user via
``user_companies``. Unscoped (anonymous/system) requests see everything.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.company import Company
from app.domains.stock.models.news import CompanyNews, News
from app.domains.stock.schemas.news import NewsListResponse, NewsResponse
from app.shared.identity import (
    company_is_scoped,
    requester_scope,
    scoped_where,
)

router = APIRouter(prefix="/news", tags=["news"])


def _dedupe_news(items: list[News]) -> list[News]:
    """Collapse duplicate News rows from the CompanyNews join back to one per news id.

    A news item linked to multiple companies in a user's scope will otherwise
    come back once per matching company link.
    """
    seen: dict[int, News] = {}
    for item in items:
        if item.id not in seen:
            seen[item.id] = item
    return list(seen.values())


@router.get("/", response_model=NewsListResponse)
async def list_news(
    request: Request,
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List news, optionally filtered by ticker — scoped per requesting user."""
    scope = await requester_scope(request, db)

    query = select(News)
    count_query = select(func.count(func.distinct(News.id)))

    if ticker:
        company_result = await db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        company = company_result.scalar_one_or_none()
        if not company or not company_is_scoped(company.id, scope):
            raise HTTPException(status_code=404, detail=f"Company {ticker} not found")
        query = (
            select(News)
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company.id)
        )
        count_query = (
            select(func.count(func.distinct(News.id)))
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company.id)
        )
    elif scope is not None:
        # No ticker but a real user: only news linked to their granted companies.
        query = select(News).join(CompanyNews, CompanyNews.news_id == News.id)
        query = scoped_where(query, CompanyNews.company_id, scope)
        count_query = select(func.count(func.distinct(News.id))).join(
            CompanyNews, CompanyNews.news_id == News.id
        )
        count_query = scoped_where(count_query, CompanyNews.company_id, scope)

    query = query.order_by(desc(News.published_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    news_items = _dedupe_news(result.scalars().all())

    total = (await db.execute(count_query)).scalar() or 0

    return NewsListResponse(
        news=[NewsResponse.model_validate(n) for n in news_items],
        total=total,
    )


@router.get("/{news_id}", response_model=NewsResponse)
async def get_news(
    news_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a single news item — scoped to the requesting user's companies."""
    result = await db.execute(select(News).where(News.id == news_id))
    news = result.scalar_one_or_none()
    if not news:
        raise HTTPException(status_code=404, detail="News not found")

    scope = await requester_scope(request, db)
    if scope is not None:
        links = await db.execute(
            select(CompanyNews.company_id).where(CompanyNews.news_id == news.id)
        )
        linked = {row[0] for row in links.all()}
        if not (linked & scope):
            raise HTTPException(status_code=404, detail="News not found")

    return NewsResponse.model_validate(news)