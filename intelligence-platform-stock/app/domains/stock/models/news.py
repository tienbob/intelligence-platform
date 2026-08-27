"""
News and company-news models (Section 15).

News is stored once (deduplicated by ``content_hash``) and linked to
companies through the ``company_news`` join table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin


class News(Base, TimestampMixin):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="en")
    content_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    # News impact model (Section 25)
    sentiment: Mapped[float | None] = mapped_column(Float)  # -1 .. 1
    relevance_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    credibility_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    magnitude_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    impact_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    confidence_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    # Phase 4: materiality & effective weight (Sections 45-46)
    materiality_score: Mapped[float | None] = mapped_column(Float)  # 0 .. 1
    effective_weight: Mapped[float | None] = mapped_column(Float)  # 0 .. 1

    def __repr__(self) -> str:
        return f"<News(id={self.id}, title={self.title[:50]!r})>"


class CompanyNews(Base, TimestampMixin):
    """Join table linking news to the companies they mention."""

    __tablename__ = "company_news"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    news_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news.id"), nullable=False, index=True
    )
    relevance_score: Mapped[float | None] = mapped_column(Float)
    # Phase 4: extraction metadata (Section 24)
    extraction_method: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Float)  # 0 .. 1

    __table_args__ = (
        Index("ix_company_news_company_news", "company_id", "news_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<CompanyNews(company_id={self.company_id}, news_id={self.news_id})>"