"""Shared readers for persisted Stock snapshots used by both analysis engines."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.analysis import AnomalyScore, RiskMetric, TechnicalIndicator
from app.domains.stock.models.event import MarketEvent
from app.domains.stock.models.financial import FinancialMetric, FinancialStatement
from app.domains.stock.models.news import News
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.scoring.macro_analysis import MacroAnalysisEngine
from sqlalchemy import desc, select

logger = get_logger(__name__)


class StockSnapshotReader:
    def __init__(self, session: AsyncSession):
        self.session = session
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

        return {
            "latest_price": latest.close,
            "latest_volume": latest.volume,
            "latest_date": latest.timestamp.isoformat(),
            "price_change_1d": ((latest.close - prev.close) / prev.close) if prev and prev.close else None,
            "price_high_30d": max(p.high for p in prices),
            "price_low_30d": min(p.low for p in prices),
            "avg_volume_30d": sum(p.volume for p in prices) / len(prices),
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
            .order_by(desc(FinancialStatement.period), desc(FinancialStatement.period_type))
            .limit(4)
        )
        statements = list(stmt_result.scalars().all())

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
            } if metrics else {},
            "latest_statement": {
                "period": statements[0].period if statements else None,
                "revenue": statements[0].revenue if statements else None,
                "net_income": statements[0].net_income if statements else None,
                "free_cash_flow": statements[0].free_cash_flow if statements else None,
                "total_debt": statements[0].total_debt if statements else None,
                "source": getattr(statements[0], "source", None) if statements else None,
            } if statements else {},
        }

    async def build_news_snapshot(self, company_id: int, limit: int = 10) -> dict[str, Any]:
        """Build recent news snapshot."""
        from app.domains.stock.models.news import CompanyNews

        result = await self.session.execute(
            select(News)
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company_id)
            .order_by(desc(News.published_at))
            .limit(limit)
        )
        news_items = result.scalars().all()

        return {
            "recent_news": [
                {
                    "id": n.id,
                    "source_id": f"snapshot_news_{n.id}",
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
