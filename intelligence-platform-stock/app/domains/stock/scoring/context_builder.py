"""
Context builder for LLM research (Section 29).

The LLM should receive a structured context:
    Market Snapshot + Technical Snapshot + Fundamental Snapshot
    + Macro Snapshot + News Snapshot + Event Snapshot
    + Historical Similar Events → Context Builder → LLM
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.analysis import AnomalyScore, RiskMetric, TechnicalIndicator
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.financial import FinancialMetric, FinancialStatement
from app.domains.stock.models.news import News
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.scoring.evidence import EvidenceAttributor
from app.domains.stock.scoring.macro_analysis import MacroAnalysisEngine
from app.domains.stock.scoring.rag import RAGService
from sqlalchemy import desc, select

logger = get_logger(__name__)


def market_window_stats(
    latest_close: float | None,
    highs: list[float | None],
    lows: list[float | None],
) -> tuple[float | None, float | None]:
    """(high, low) over the trailing window INCLUDING the latest bar.

    Contract: the window includes the latest observation, so the returned
    high is always >= latest_close and the low always <= latest_close
    (whenever latest_close is a positive number). Non-positive highs/lows
    are treated as unavailable — quote-based ingestion can fabricate 0.0
    for missing OHLC fields, which previously allowed
    ``price_high_30d < latest_price`` (an impossible state).
    """
    valid_highs = [h for h in highs if h is not None and h > 0]
    valid_lows = [v for v in lows if v is not None and v > 0]
    if latest_close is not None and latest_close > 0:
        valid_highs.append(latest_close)
        valid_lows.append(latest_close)
    high = max(valid_highs) if valid_highs else None
    low = min(valid_lows) if valid_lows else None
    return high, low


class ContextBuilder:
    """
    Builds structured context for the LLM research analyst.

    Section 29: The LLM should receive a structured context, not raw data.
    """

    def __init__(self, session: AsyncSession, rag_service: RAGService | None = None):
        self.session = session
        self.rag = rag_service or RAGService(session)
        self.macro_engine = MacroAnalysisEngine(session)

    async def build_market_snapshot(self, company_id: int) -> dict[str, Any]:
        """Build market data snapshot."""
        result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id == company_id)
            .where(StockPrice.interval == "1d")
            .order_by(desc(StockPrice.timestamp))
            .limit(30)
        )
        prices = list(result.scalars().all())

        if not prices:
            return {}

        latest = prices[0]
        prev = prices[1] if len(prices) > 1 else None

        valid_volumes = [
            p.volume for p in prices if p.volume is not None and p.volume > 0
        ]
        high_30d, low_30d = market_window_stats(
            latest.close, [p.high for p in prices], [p.low for p in prices]
        )
        return {
            "latest_price": latest.close,
            "latest_volume": valid_volumes[0] if valid_volumes else None,
            "latest_date": latest.timestamp.isoformat(),
            "price_change_1d": ((latest.close - prev.close) / prev.close) if prev and prev.close else None,
            "price_high_30d": high_30d,
            "price_low_30d": low_30d,
            "avg_volume_30d": sum(valid_volumes) / len(valid_volumes) if valid_volumes else None,
        }

    async def build_technical_snapshot(self, company_id: int) -> dict[str, Any]:
        """Build technical indicator snapshot."""
        result = await self.session.execute(
            select(TechnicalIndicator)
            .where(TechnicalIndicator.company_id == company_id)
            .order_by(desc(TechnicalIndicator.timestamp))
            .limit(1)
        )
        ti = result.scalar_one_or_none()
        if not ti:
            return {}

        return {
            "sma_20": ti.sma_20,
            "sma_50": ti.sma_50,
            "sma_200": ti.sma_200,
            "rsi_14": ti.rsi_14,
            "macd": ti.macd,
            "macd_signal": ti.macd_signal,
            "atr": ti.atr,
            "bollinger_upper": ti.bollinger_upper,
            "bollinger_lower": ti.bollinger_lower,
            "volatility_30d": ti.volatility_30d,
            "momentum": ti.momentum,
            "drawdown": ti.drawdown,
        }

    async def build_fundamental_snapshot(self, company_id: int) -> dict[str, Any]:
        """Build fundamental data snapshot."""
        # Latest metrics
        metrics_result = await self.session.execute(
            select(FinancialMetric)
            .where(FinancialMetric.company_id == company_id)
            .order_by(desc(FinancialMetric.timestamp))
            .limit(1)
        )
        metrics = metrics_result.scalar_one_or_none()

        # Latest statements
        stmt_result = await self.session.execute(
            select(FinancialStatement)
            .where(FinancialStatement.company_id == company_id)
            .order_by(desc(FinancialStatement.period))
            .limit(4)
        )
        statements = list(stmt_result.scalars().all())
        latest_statement = statements[0] if statements else None
        derived_metrics = {}
        if latest_statement and latest_statement.revenue:
            if latest_statement.net_income is not None:
                derived_metrics["net_margin"] = (
                    latest_statement.net_income / latest_statement.revenue
                )
            if latest_statement.gross_profit is not None:
                derived_metrics["gross_margin"] = (
                    latest_statement.gross_profit / latest_statement.revenue
                )

        return {
            "metrics": {
                "pe_ratio": metrics.pe_ratio if metrics else None,
                "roe": metrics.roe if metrics else None,
                "roa": metrics.roa if metrics else None,
                "gross_margin": metrics.gross_margin if metrics else None,
                "operating_margin": metrics.operating_margin if metrics else None,
                "net_margin": metrics.net_margin if metrics else None,
                "debt_equity": metrics.debt_equity if metrics else None,
                "revenue_growth": metrics.revenue_growth if metrics else None,
                "earnings_growth": metrics.earnings_growth if metrics else None,
                "fcf_growth": metrics.fcf_growth if metrics else None,
            } if metrics else derived_metrics,
            "latest_statement": {
                "period": latest_statement.period if latest_statement else None,
                "revenue": latest_statement.revenue if latest_statement else None,
                "net_income": latest_statement.net_income if latest_statement else None,
                "free_cash_flow": latest_statement.free_cash_flow if latest_statement else None,
                "total_debt": latest_statement.total_debt if latest_statement else None,
                "source": getattr(latest_statement, "source", None) if latest_statement else None,
            } if statements else {},
        }

    async def build_news_snapshot(self, company_id: int, limit: int = 10) -> dict[str, Any]:
        """Build recent news snapshot."""
        from app.domains.stock.models.news import CompanyNews
        from app.domains.stock.models.company import Company

        result = await self.session.execute(
            select(News)
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company_id)
            .order_by(desc(News.published_at))
            .limit(limit * 5)
        )
        news_items = result.scalars().all()
        company = await self.session.get(Company, company_id)
        ticker = company.ticker.upper() if company else ""
        company_name = (company.name or "").lower() if company else ""
        company_token = company_name.replace(" inc.", "").split()[0] if company_name else ""
        news_items = [
            item for item in news_items
            if ticker in (item.title or "").upper()
            or (company_token and company_token in (item.title or "").lower())
        ]

        news_items = news_items[:limit]
        return {
            "recent_news": [
                {
                    "title": n.title,
                    "source": n.source,
                    "published_at": n.published_at.isoformat(),
                    "sentiment": n.sentiment,
                    "summary": n.summary,
                }
                for n in news_items
            ],
            "news_count": len(news_items),
        }

    async def build_event_snapshot(self, company_id: int, limit: int = 10) -> dict[str, Any]:
        """Build recent events snapshot."""
        result = await self.session.execute(
            select(MarketEvent)
            .where(MarketEvent.company_id == company_id)
            .order_by(desc(MarketEvent.event_date))
            .limit(limit)
        )
        events = result.scalars().all()

        return {
            "recent_events": [
                {
                    "type": e.event_type,
                    "date": e.event_date.isoformat(),
                    "impact": e.impact,
                    "description": e.description,
                    "confidence": e.confidence,
                }
                for e in events
            ],
            "event_count": len(events),
        }

    async def build_risk_snapshot(self, company_id: int) -> dict[str, Any]:
        """Build risk metrics snapshot."""
        result = await self.session.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company_id)
            .order_by(desc(RiskMetric.timestamp))
            .limit(1)
        )
        risk = result.scalar_one_or_none()
        if not risk:
            return {}

        return {
            "risk_score": risk.risk_score,
            "volatility": risk.volatility,
            "max_drawdown": risk.max_drawdown,
            "event_risk": risk.event_risk,
            "fundamental_risk": risk.fundamental_risk,
            "confidence": risk.confidence,
        }

    async def build_anomaly_snapshot(self, company_id: int) -> dict[str, Any]:
        """Build anomaly detection snapshot."""
        result = await self.session.execute(
            select(AnomalyScore)
            .where(AnomalyScore.company_id == company_id)
            .order_by(desc(AnomalyScore.timestamp))
            .limit(1)
        )
        anomaly = result.scalar_one_or_none()
        if not anomaly:
            return {}

        return {
            "overall_score": anomaly.overall_score,
            "triggered": anomaly.triggered,
            "price_change_score": anomaly.price_change_score,
            "volume_score": anomaly.volume_score,
            "volatility_score": anomaly.volatility_score,
        }

    async def build_full_context(
        self,
        company: Company,
        include_news: bool = True,
        include_fundamentals: bool = True,
        include_technical: bool = True,
        include_macro: bool = True,
    ) -> dict[str, Any]:
        """
        Build the complete structured context for LLM analysis.

        Section 29:
            Market Snapshot + Technical Snapshot + Fundamental Snapshot
            + Macro Snapshot + News Snapshot + Event Snapshot
            + Historical Similar Events
        """
        context: dict[str, Any] = {
            "company": {
                "ticker": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "industry": company.industry,
                "market_cap": company.market_cap,
            },
        }

        # Market snapshot
        context["market_snapshot"] = await self.build_market_snapshot(company.id)

        # Technical snapshot
        if include_technical:
            context["technical_snapshot"] = await self.build_technical_snapshot(company.id)
            context["anomaly_snapshot"] = await self.build_anomaly_snapshot(company.id)

        # Fundamental snapshot
        if include_fundamentals:
            context["fundamental_snapshot"] = await self.build_fundamental_snapshot(company.id)

        # News snapshot
        if include_news:
            context["news_snapshot"] = await self.build_news_snapshot(company.id)
            context["event_snapshot"] = await self.build_event_snapshot(company.id)

        # Macro snapshot
        if include_macro:
            context["macro_snapshot"] = await self.macro_engine.get_macro_snapshot()

        # Risk snapshot
        context["risk_snapshot"] = await self.build_risk_snapshot(company.id)

        # RAG: Historical similar events
        rag_context = await self.rag.retrieve_context(
            f"Analysis of {company.ticker} {company.name}",
            company_id=company.id,
        )
        context["rag_context"] = rag_context

        logger.info("Built full context for %s", company.ticker)
        return context