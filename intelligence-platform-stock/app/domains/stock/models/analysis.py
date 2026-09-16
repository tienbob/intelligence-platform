"""
Derived and AI-layer models (Sections 15).

* ``TechnicalIndicator`` — SMA, EMA, RSI, MACD, etc. (derived)
* ``AnomalyScore`` — market anomaly detection results (derived)
* ``Embedding`` — pgvector embeddings for RAG (AI)
* ``Analysis`` — full AI analysis with LLM output (AI)
* ``InvestmentThesis`` — persisted investment theses (AI)
* ``InvestmentScore`` — deterministic investment scores (AI)
* ``AnalysisSource`` — source-backed AI claims (AI)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector
from pgvector.utils import Vector as PgVector

from app.core.config import get_settings
from app.core.database import Base
from app.domains.stock.models.base import TimestampMixin

settings = get_settings()


class AsyncVector(Vector):
    """
    pgvector Vector type that passes values through to asyncpg's binary codec.

    The stock ``Vector.bind_processor`` serializes the value to a text string
    (``"[0.1, 0.2, ...]"``) before asyncpg sees it.  asyncpg's registered
    binary codec (``register_vector``) then fails to encode that string as a
    vector ("could not convert string to float").  This subclass overrides the
    bind processor to return a ``pgvector.Vector`` object unchanged, so the
    asyncpg binary codec receives the correct type.
    """

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if not isinstance(value, PgVector):
                value = PgVector(value)
            return value

        return process


# ── Derived layer ────────────────────────────────────────────────


class TechnicalIndicator(Base, TimestampMixin):
    __tablename__ = "technical_indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    sma_20: Mapped[float | None] = mapped_column(Float)
    sma_50: Mapped[float | None] = mapped_column(Float)
    sma_200: Mapped[float | None] = mapped_column(Float)
    ema_20: Mapped[float | None] = mapped_column(Float)
    rsi_14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    atr: Mapped[float | None] = mapped_column(Float)
    bollinger_upper: Mapped[float | None] = mapped_column(Float)
    bollinger_lower: Mapped[float | None] = mapped_column(Float)
    vwap: Mapped[float | None] = mapped_column(Float)
    volatility_30d: Mapped[float | None] = mapped_column(Float)
    momentum: Mapped[float | None] = mapped_column(Float)
    drawdown: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_technical_indicators_company_ts", "company_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<TechnicalIndicator(company_id={self.company_id}, ts={self.timestamp})>"


class AnomalyScore(Base, TimestampMixin):
    __tablename__ = "anomaly_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    price_change_score: Mapped[float | None] = mapped_column(Float)
    volume_score: Mapped[float | None] = mapped_column(Float)
    volatility_score: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    triggered: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        Index("ix_anomaly_scores_company_ts", "company_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AnomalyScore(company_id={self.company_id}, score={self.overall_score})>"


class RiskMetric(Base, TimestampMixin):
    """Risk metrics calculated by the risk engine (Section 33)."""

    __tablename__ = "risk_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    risk_score: Mapped[float | None] = mapped_column(Float)
    volatility: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    value_at_risk: Mapped[float | None] = mapped_column(Float)
    liquidity_score: Mapped[float | None] = mapped_column(Float)
    fundamental_risk: Mapped[float | None] = mapped_column(Float)
    event_risk: Mapped[float | None] = mapped_column(Float)
    concentration_risk: Mapped[float | None] = mapped_column(Float)
    sector_risk: Mapped[float | None] = mapped_column(Float)
    correlation_risk: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_risk_metrics_company_ts", "company_id", "timestamp"),
    )


# ── AI layer ─────────────────────────────────────────────────────


class Embedding(Base, TimestampMixin):
    """pgvector embedding for RAG retrieval (Section 28)."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # pgvector column — matches migrations/versions/0002_embedding_vector.py
    embedding: Mapped[list[float] | None] = mapped_column(
        AsyncVector(settings.EMBEDDING_DIMENSIONS), nullable=True
    )
    embedding_model: Mapped[str] = mapped_column(String(100), default="text-embedding-3-small")
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    def __repr__(self) -> str:
        return f"<Embedding(entity_type={self.entity_type!r}, entity_id={self.entity_id})>"


class Analysis(Base, TimestampMixin):
    """Full AI analysis record (Section 15, 31).

    Ownership: ``user_id`` mirrors Rails ``users.id`` (no FK — users table is
    Rails-owned). ``NULL`` = system/scheduler row, visible to everyone.
    Market-data tables stay global; only this user-action table is scoped.
    """

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(20), default="1.0")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed

    # Snapshots
    market_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fundamental_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    technical_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    news_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    macro_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    risk_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # LLM output
    llm_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Scores
    investment_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)

    # Observability (Section 57)
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    llm_tokens_used: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:
        return f"<Analysis(analysis_id={self.analysis_id!r}, status={self.status!r})>"


class InvestmentScore(Base, TimestampMixin):
    """Deterministic investment score (Section 34)."""

    __tablename__ = "investment_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("companies.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    fundamental_score: Mapped[float | None] = mapped_column(Float)
    valuation_score: Mapped[float | None] = mapped_column(Float)
    growth_score: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float | None] = mapped_column(Float)
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    catalyst_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(20))

    # Phase 6: Score versioning (Section 59)
    scoring_model: Mapped[str | None] = mapped_column(String(50), default="investment_score_v1")
    scoring_version: Mapped[str | None] = mapped_column(String(20), default="1.0")
    scoring_weights: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Phase 6: Data quality (Section 62) and validation metadata
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    validation_issues: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    __table_args__ = (
        Index("ix_investment_scores_company_ts", "company_id", "timestamp"),
    )


class AnalysisSource(Base, TimestampMixin):
    """Source-backed AI claims (Section 32)."""

    __tablename__ = "analysis_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analyses.id"), nullable=False, index=True
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50))
    source_name: Mapped[str] = mapped_column(String(100))
    metric: Mapped[str | None] = mapped_column(String(100))
    value: Mapped[float | None] = mapped_column(Float)
    period: Mapped[str | None] = mapped_column(String(20))

    def __repr__(self) -> str:
        return f"<AnalysisSource(claim={self.claim[:50]!r})>"