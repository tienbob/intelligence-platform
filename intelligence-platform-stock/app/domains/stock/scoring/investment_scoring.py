"""
Investment scoring engine (Section 34).

Investment score is primarily deterministic.

Weights:
    Fundamental       30%
    Valuation         20%
    Growth            15%
    Technical         10%
    Sentiment         10%
    Catalysts         10%
    Risk              -15%

The final score is calculated by Python.
The LLM explains why the score makes sense.

Phase 6 (#159):
    - Score versioning (scoring_model, scoring_version, scoring_weights)
    - Configurable recommendation categories
    - Data quality integration
    - Confidence calculation based on data availability
    - Business rule validation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock.config import get_stock_config
from app.core.database import commit_session
from app.core.logging import get_logger
from app.domains.stock.models.analysis import InvestmentScore, RiskMetric, TechnicalIndicator
from app.domains.stock.models.financial import FinancialMetric, FinancialStatement
from app.domains.stock.models.news import CompanyNews, News
from app.domains.stock.models.stock_price import StockPrice
from app.domains.stock.models.event import MarketEvent

logger = get_logger(__name__)
settings = get_stock_config()

# Current scoring model identifier
SCORING_MODEL = settings.SCORING_MODEL
SCORING_VERSION = settings.SCORING_VERSION


def get_scoring_weights() -> dict[str, float]:
    """Return the current scoring weight configuration."""
    return {
        "fundamental": settings.SCORE_WEIGHT_FUNDAMENTAL,
        "valuation": settings.SCORE_WEIGHT_VALUATION,
        "growth": settings.SCORE_WEIGHT_GROWTH,
        "technical": settings.SCORE_WEIGHT_TECHNICAL,
        "sentiment": settings.SCORE_WEIGHT_SENTIMENT,
        "catalyst": settings.SCORE_WEIGHT_CATALYST,
        "risk": settings.SCORE_WEIGHT_RISK,
    }


def get_data_quality_weights() -> dict[str, float]:
    """Return the current data quality weight configuration."""
    return dict(settings.DATA_QUALITY_WEIGHTS)


def get_strong_recommendation_categories() -> set[str]:
    """
    Return recommendation categories considered 'strong' (threshold >= 70).

    Derived from configurable ``RECOMMENDATION_THRESHOLDS`` so business
    rule validation stays in sync with the configured categories (Section 60).
    """
    return {
        rule["category"] for rule in settings.RECOMMENDATION_THRESHOLDS
        if rule["threshold"] >= 70
    }


class DataQualityEngine:
    """
    Assesses data completeness for scoring inputs (Section 62).

    Each component (price, fundamental, technical, news, events)
    is scored 0..1 based on how much recent data is available.
    """

    # Recency windows for the availability checks
    _FULL_DATA_DAYS = {
        "price": 30,
        "fundamental": 90,
        "technical": 30,
        "news": 7,
        "events": 30,
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _data_available(self, company_id: int, model: type, date_field: str,
                              days: int) -> float:
        """Return a 0..1 completeness score for a given model and recency window."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(model)
            .where(model.company_id == company_id)
            .where(getattr(model, date_field) >= since)
            .limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return 1.0
        # Check if any data exists at all (partial credit)
        result_all = await self.session.execute(
            select(model).where(model.company_id == company_id).limit(1)
        )
        if result_all.scalar_one_or_none() is not None:
            return 0.5
        return 0.0

    @staticmethod
    def financial_completeness(metrics: Any, statement: Any) -> dict[str, Any]:
        """Measure usable scoring fields; alternative valuation ratios are allowed."""
        groups = {
            "fundamental": ("roe", "net_margin", "roa", "debt_equity"),
            "valuation": ("pe_ratio", "ps_ratio", "pb_ratio", "fcf_yield"),
            "growth": ("revenue_growth", "earnings_growth", "fcf_growth"),
        }
        missing, coverage = {}, {}
        for component, fields in groups.items():
            valid = []
            for field in fields:
                value = getattr(metrics, field, None)
                usable = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                if field in ("pe_ratio", "ps_ratio", "pb_ratio"):
                    usable = usable and value > 0
                if usable:
                    valid.append(field)
            missing[component] = [field for field in fields if field not in valid]
            # Any three valuation inputs suffice; P/E is not mandatory.
            required = 3 if component == "valuation" else len(fields)
            coverage[component] = min(1.0, len(valid) / required)
        period = getattr(statement, "period", None)
        try:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(period).date()).days
            freshness = 1.0 if 0 <= age <= 150 else 0.5 if 150 < age <= 400 else 0.0
        except (ValueError, TypeError):
            freshness = 0.0
        return {
            "coverage": coverage,
            "missing_inputs": missing,
            "fallback_components": [name for name, value in coverage.items() if value == 0],
            "reporting_period": period,
            "reporting_freshness": freshness,
            "overall": sum(coverage.values()) / len(coverage) * freshness,
        }

    async def _financial_quality(self, company_id: int) -> dict[str, Any]:
        metrics = (await self.session.execute(
            select(FinancialMetric).where(FinancialMetric.company_id == company_id)
            .order_by(FinancialMetric.timestamp.desc(), FinancialMetric.id.desc()).limit(1)
        )).scalar_one_or_none()
        statement = (await self.session.execute(
            select(FinancialStatement).where(FinancialStatement.company_id == company_id)
            .order_by(FinancialStatement.period.desc(), FinancialStatement.period_type.desc()).limit(1)
        )).scalar_one_or_none()
        quality = self.financial_completeness(metrics, statement)
        timestamp = getattr(metrics, "timestamp", None)
        if timestamp is None:
            quality["overall"] = 0.0
        else:
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp < datetime.now(timezone.utc) - timedelta(days=90):
                quality["overall"] *= 0.5
        return quality

    @staticmethod
    async def _financial_quality_score(quality: dict[str, Any]) -> float:
        return quality["overall"]

    async def assess(self, company_id: int) -> dict[str, Any]:
        """
        Compute data quality scores for each component.

        Returns dict with per-component scores, overall quality score,
        and a recommendation on whether the data is sufficient.
        """
        weights = get_data_quality_weights()

        checks = {
            "price": lambda: self._data_available(
                company_id, StockPrice, "timestamp", self._FULL_DATA_DAYS["price"]),
            "technical": lambda: self._data_available(
                company_id, TechnicalIndicator, "timestamp", self._FULL_DATA_DAYS["technical"]),
        }

        # News check via CompanyNews join
        async def news_check() -> float:
            since = datetime.now(timezone.utc) - timedelta(days=self._FULL_DATA_DAYS["news"])
            result = await self.session.execute(
                select(News)
                .join(CompanyNews, CompanyNews.news_id == News.id)
                .where(CompanyNews.company_id == company_id)
                .where(News.published_at >= since)
                .limit(1)
            )
            if result.scalar_one_or_none() is not None:
                return 1.0
            result_all = await self.session.execute(
                select(News)
                .join(CompanyNews, CompanyNews.news_id == News.id)
                .where(CompanyNews.company_id == company_id)
                .limit(1)
            )
            if result_all.scalar_one_or_none() is not None:
                return 0.5
            return 0.0

        checks["news"] = news_check

        # Events check
        async def events_check() -> float:
            since = datetime.now(timezone.utc) - timedelta(days=self._FULL_DATA_DAYS["events"])
            result = await self.session.execute(
                select(MarketEvent)
                .where(MarketEvent.company_id == company_id)
                .where(MarketEvent.event_date >= since)
                .limit(1)
            )
            if result.scalar_one_or_none() is not None:
                return 1.0
            result_all = await self.session.execute(
                select(MarketEvent)
                .where(MarketEvent.company_id == company_id)
                .limit(1)
            )
            if result_all.scalar_one_or_none() is not None:
                return 0.5
            return 0.0

        checks["events"] = events_check

        financial_quality = await self._financial_quality(company_id)
        checks["fundamental"] = lambda: self._financial_quality_score(financial_quality)

        component_scores: dict[str, float] = {}
        for name, check in checks.items():
            try:
                component_scores[name] = await check()
            except Exception:
                component_scores[name] = 0.0

        # Weighted overall quality
        total_weight = sum(weights.get(name, 0) for name in component_scores)
        overall = sum(
            component_scores[name] * weights.get(name, 0)
            for name in component_scores
        )
        overall_score = overall / total_weight if total_weight > 0 else 0.0

        sufficient = overall_score >= settings.MIN_DATA_QUALITY_FOR_RECOMMENDATION

        return {
            "financial_inputs": financial_quality,
            "overall": round(overall_score, 4),
            "components": component_scores,
            "sufficient": sufficient,
        }


class InvestmentScoringEngine:
    """
    Calculates deterministic investment scores.

    Section 34: Investment score should be primarily deterministic.
    The LLM explains why the score makes sense.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.data_quality = DataQualityEngine(session)

    @staticmethod
    def _bounded_score(value: float) -> float:
        return max(0.0, min(100.0, value)) if math.isfinite(value) else 50.0

    @staticmethod
    def _normalize(value: float | None, min_val: float, max_val: float, invert: bool = False) -> float:
        """Normalize a value to 0-100 scale."""
        if value is None:
            return 50.0  # Neutral if missing
        normalized = (value - min_val) / (max_val - min_val) * 100
        normalized = max(0, min(100, normalized))
        return 100 - normalized if invert else normalized

    async def _score_fundamental(self, company_id: int) -> float:
        """Score fundamental quality (0-100)."""
        result = await self.session.execute(
            select(FinancialMetric)
            .where(FinancialMetric.company_id == company_id)
            .order_by(desc(FinancialMetric.timestamp))
            .limit(1)
        )
        m = result.scalar_one_or_none()
        if not m:
            return 50.0

        scores = []
        # ROE: 0-30% → 0-100
        if m.roe is not None:
            scores.append(min(100, m.roe * 100 / 0.30))
        # Net margin: 0-20% → 0-100
        if m.net_margin is not None:
            scores.append(min(100, m.net_margin * 100 / 0.20))
        # ROA: 0-15% → 0-100
        if m.roa is not None:
            scores.append(min(100, m.roa * 100 / 0.15))
        # Debt/equity: lower is better (invert)
        if m.debt_equity is not None:
            scores.append(self._normalize(m.debt_equity, 0, 2, invert=True))

        return sum(scores) / len(scores) if scores else 50.0

    async def _score_valuation(self, company_id: int) -> float:
        """Score valuation attractiveness (0-100)."""
        result = await self.session.execute(
            select(FinancialMetric)
            .where(FinancialMetric.company_id == company_id)
            .order_by(desc(FinancialMetric.timestamp))
            .limit(1)
        )
        m = result.scalar_one_or_none()
        if not m:
            return 50.0

        scores = []
        # P/E: 5-40 → 100-0 (lower is better)
        if m.pe_ratio is not None and m.pe_ratio > 0:
            scores.append(self._normalize(m.pe_ratio, 5, 40, invert=True))
        # P/S: 0.5-10 → 100-0
        if m.ps_ratio is not None and m.ps_ratio > 0:
            scores.append(self._normalize(m.ps_ratio, 0.5, 10, invert=True))
        # P/B: 0.5-5 → 100-0
        if m.pb_ratio is not None and m.pb_ratio > 0:
            scores.append(self._normalize(m.pb_ratio, 0.5, 5, invert=True))
        # FCF yield: 0-10% → 0-100 (higher is better)
        if m.fcf_yield is not None:
            scores.append(max(0.0, min(100.0, m.fcf_yield * 10)))

        return sum(scores) / len(scores) if scores else 50.0

    async def _score_growth(self, company_id: int) -> float:
        """Score growth metrics (0-100)."""
        result = await self.session.execute(
            select(FinancialMetric)
            .where(FinancialMetric.company_id == company_id)
            .order_by(desc(FinancialMetric.timestamp))
            .limit(1)
        )
        m = result.scalar_one_or_none()
        if not m:
            return 50.0

        scores = []
        # Revenue growth: 0-30% → 0-100
        if m.revenue_growth is not None:
            scores.append(min(100, max(0, m.revenue_growth * 100 / 0.30)))
        # Earnings growth: 0-40% → 0-100
        if m.earnings_growth is not None:
            scores.append(min(100, max(0, m.earnings_growth * 100 / 0.40)))
        # FCF growth: 0-30% → 0-100
        if m.fcf_growth is not None:
            scores.append(min(100, max(0, m.fcf_growth * 100 / 0.30)))

        return sum(scores) / len(scores) if scores else 50.0

    async def _score_technical(self, company_id: int) -> float:
        """Score technical indicators (0-100)."""
        result = await self.session.execute(
            select(TechnicalIndicator)
            .where(TechnicalIndicator.company_id == company_id)
            .order_by(desc(TechnicalIndicator.timestamp))
            .limit(1)
        )
        ti = result.scalar_one_or_none()
        if not ti:
            return 50.0

        scores = []
        # RSI: 40-60 neutral, <30 oversold (good entry), >70 overbought
        if ti.rsi_14 is not None:
            if ti.rsi_14 < 30:
                scores.append(70)  # Oversold — potential buy
            elif ti.rsi_14 > 70:
                scores.append(40)  # Overbought
            else:
                scores.append(55)
        # Momentum: positive is good
        if ti.momentum is not None:
            scores.append(min(100, max(0, 50 + ti.momentum)))
        # Drawdown: less drawdown is better (positive magnitude, e.g. 0.18 for 18%)
        if ti.drawdown is not None:
            scores.append(self._normalize(ti.drawdown, 0, 0.3, invert=True))

        return sum(scores) / len(scores) if scores else 50.0

    async def _score_sentiment(self, company_id: int) -> float:
        """Score news sentiment (0-100)."""
        since = datetime.now(timezone.utc) - timedelta(days=7)
        result = await self.session.execute(
            select(News)
            .join(CompanyNews, CompanyNews.news_id == News.id)
            .where(CompanyNews.company_id == company_id)
            .where(News.published_at >= since)
        )
        news_items = result.scalars().all()

        if not news_items:
            return 50.0

        sentiments = [n.sentiment for n in news_items if n.sentiment is not None]
        if not sentiments:
            return 50.0

        avg_sentiment = sum(sentiments) / len(sentiments)
        # -1 to 1 → 0 to 100
        return (avg_sentiment + 1) * 50

    async def _score_catalyst(self, company_id: int) -> float:
        """Score catalysts from recent events (0-100)."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        result = await self.session.execute(
            select(MarketEvent)
            .where(MarketEvent.company_id == company_id)
            .where(MarketEvent.event_date >= since)
        )
        events = result.scalars().all()

        if not events:
            return 50.0

        positive = sum(1 for e in events if e.impact == "positive")
        negative = sum(1 for e in events if e.impact == "negative")

        # More positive events = higher score
        score = 50 + (positive - negative) * 10
        return max(0, min(100, score))

    async def _score_risk(self, company_id: int) -> float:
        """Get risk score (0-100, higher = riskier)."""
        result = await self.session.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company_id)
            .order_by(desc(RiskMetric.timestamp))
            .limit(1)
        )
        risk = result.scalar_one_or_none()
        if risk and risk.risk_score is not None:
            return risk.risk_score
        return 50.0

    async def _score_volatility(self, company_id: int) -> float | None:
        """Get volatility from RiskMetric (0-1 scale, lower = less risky)."""
        result = await self.session.execute(
            select(RiskMetric)
            .where(RiskMetric.company_id == company_id)
            .order_by(desc(RiskMetric.timestamp))
            .limit(1)
        )
        risk = result.scalar_one_or_none()
        if risk and risk.volatility is not None:
            return risk.volatility
        return None

    async def _score_market_regime(self, company_id: int) -> str | None:
        """
        Get the current market regime (Section 41).

        Returns the regime string or None if unavailable.
        This is a deterministic pre-LLM signal.
        """
        from app.domains.stock.scoring.macro_analysis import MacroAnalysisEngine

        macro = MacroAnalysisEngine(self.session)
        snapshot = await macro.get_macro_snapshot()
        return snapshot.get("economic_regime")

    async def _assess_data_quality(self, company_id: int) -> dict[str, Any]:
        """
        Assess data quality for scoring inputs (Section 62).

        Returns quality scores per component and an overall quality score.
        """
        return await self.data_quality.assess(company_id)

    @staticmethod
    def _compute_confidence(
        data_quality: dict[str, Any],
        data_quality_available: bool,
    ) -> float:
        """
        Compute explicit confidence based on data availability and quality
        (Section 61).

        Confidence ≠ Investment Score.  It reflects how much evidence
        backs the recommendation.
        """
        if data_quality_available:
            # Base on data quality score
            quality = data_quality.get("overall", 0.0)
            sufficient = data_quality.get("sufficient", False)
            if sufficient:
                # Map quality to 0.5..1.0 range
                financial = data_quality.get("financial_inputs", {})
                # Neutral fallback scores must never imply strong evidence.
                ceiling = 0.5 if financial.get("fallback_components") else 0.95
                return round(min(ceiling, quality), 4)
            else:
                # Insufficient data — lower confidence
                return round(min(0.5, quality), 4)
        # Fallback
        return settings.BASE_CONFIDENCE

    @staticmethod
    def _recommendation_from_thresholds(overall_score: float) -> str:
        """
        Map an overall score to a recommendation category using
        configurable thresholds (Section 60).

        Thresholds are evaluated top-to-bottom; first match wins.
        """
        for rule in settings.RECOMMENDATION_THRESHOLDS:
            if overall_score >= rule["threshold"]:
                return rule["category"]
        return "AVOID"

    @staticmethod
    def _validate_business_rules(
        scores: dict[str, float],
        overall: float,
        recommendation: str,
        confidence: float,
        data_quality: dict[str, Any],
    ) -> list[str]:
        """
        Validate end-to-end risk and score outputs against business rules
        (Section 60).

        Returns a list of validation issues (empty = all valid).
        """
        issues: list[str] = []

        # Rule 1: Overall score must be 0-100
        if not (0 <= overall <= 100):
            issues.append(f"overall_score {overall} out of bounds [0, 100]")

        # Rule 2: All component scores must be 0-100
        for name, value in scores.items():
            if not (0 <= value <= 100):
                issues.append(f"{name} score {value} out of bounds [0, 100]")

        # Rule 3: Confidence must be 0-1
        if not (0 <= confidence <= 1):
            issues.append(f"confidence {confidence} out of bounds [0, 1]")

        # Rule 4: Recommendation consistency — high overall shouldn't pair
        # with low confidence without sufficient data warning
        if overall >= 70 and confidence < 0.5:
            issues.append("High overall score with low confidence without data quality warning")

        # Rule 5: If data quality is insufficient, recommendation should not
        # be a strong buy.  Strong categories are derived from configurable
        # thresholds (>= 70) rather than hardcoded.
        if not data_quality.get("sufficient", True) and recommendation in get_strong_recommendation_categories():
            issues.append(
                f"Recommendation '{recommendation}' issued with insufficient data quality"
            )

        # Rule 6: Risk score should not exceed overall score meaningfully
        risk = scores.get("risk", 0)
        if risk > overall + 50:
            issues.append(
                f"Risk score {risk} is disproportionately high vs overall {overall}"
            )

        if issues:
            logger.warning("Business rule validation issues: %s", issues)
        return issues

    async def calculate_score(self, company_id: int) -> InvestmentScore:
        """
        Calculate the full investment score.

        Section 34:
            Fundamental 30% + Valuation 20% + Growth 15% + Technical 10%
            + Sentiment 10% + Catalysts 10% - Risk 15%

        Phase 6:
            - Score versioning (scoring_model, scoring_version, scoring_weights)
            - Configurable recommendation categories
            - Data quality integration
            - Explicit confidence calculation
            - Business rule validation
        """
        # Phase 6: Data quality assessment
        try:
            data_quality_result = await self._assess_data_quality(company_id)
            data_quality_available = True
        except Exception:
            logger.warning("Data quality assessment failed for company_id=%d", company_id)
            data_quality_result = {"overall": 0.0, "sufficient": False, "components": {}}
            data_quality_available = False

        # Phase 6: Pre-LLM scoring signals (deterministic)
        volatility = await self._score_volatility(company_id)
        market_regime = await self._score_market_regime(company_id)

        fundamental = await self._score_fundamental(company_id)
        valuation = await self._score_valuation(company_id)
        growth = await self._score_growth(company_id)
        technical = await self._score_technical(company_id)
        sentiment = await self._score_sentiment(company_id)
        catalyst = await self._score_catalyst(company_id)
        risk = await self._score_risk(company_id)

        fundamental, valuation, growth, technical, sentiment, catalyst, risk = (
            self._bounded_score(value) for value in
            (fundamental, valuation, growth, technical, sentiment, catalyst, risk)
        )

        # Risk is a penalty, not a weighted component.
        # Positive weights sum to 0.95; risk subtracts up to 0.15.
        # Raw range is [-15, 95] — this is intentional: risk can push the
        # score below zero (clamped), and a perfect score with zero risk
        # would reach 95 (not 100, because some risk always exists).
        overall = (
            fundamental * settings.SCORE_WEIGHT_FUNDAMENTAL
            + valuation * settings.SCORE_WEIGHT_VALUATION
            + growth * settings.SCORE_WEIGHT_GROWTH
            + technical * settings.SCORE_WEIGHT_TECHNICAL
            + sentiment * settings.SCORE_WEIGHT_SENTIMENT
            + catalyst * settings.SCORE_WEIGHT_CATALYST
            - risk * settings.SCORE_WEIGHT_RISK
        )
        overall = max(0.0, min(100.0, overall))

        # Phase 6: Configurable recommendation thresholds
        recommendation = self._recommendation_from_thresholds(overall)

        # Phase 6: Explicit confidence calculation based on data availability
        confidence = self._compute_confidence(
            data_quality_result, data_quality_available
        )

        # Market regime risk adjustment (Section 41): risk-off regimes reduce
        # confidence on the recommendation.
        if market_regime in ("contraction_risk", "high_volatility"):
            confidence = max(0.0, min(1.0, confidence - 0.05))

        # Phase 6: Score versioning
        scores = {
            "fundamental": fundamental,
            "valuation": valuation,
            "growth": growth,
            "technical": technical,
            "sentiment": sentiment,
            "catalyst": catalyst,
            "risk": risk,
        }

        # Phase 6: Business rule validation
        validation_issues = self._validate_business_rules(
            scores, overall, recommendation, confidence, data_quality_result
        )

        score = InvestmentScore(
            company_id=company_id,
            timestamp=datetime.now(timezone.utc),
            fundamental_score=fundamental,
            valuation_score=valuation,
            growth_score=growth,
            technical_score=technical,
            sentiment_score=sentiment,
            catalyst_score=catalyst,
            risk_score=risk,
            overall_score=overall,
            confidence=confidence,
            recommendation=recommendation,
            # Phase 6: versioned scoring metadata
            scoring_model=SCORING_MODEL,
            scoring_version=SCORING_VERSION,
            scoring_weights=get_scoring_weights(),
        )
        self.session.add(score)

        # Phase 6: Persist data quality and validation info as metadata
        if hasattr(score, "data_quality_score"):
            score.data_quality_score = data_quality_result["overall"]
        if hasattr(score, "validation_issues"):
            score.validation_issues = {"issues": validation_issues, "data_quality": data_quality_result}

        await commit_session(self.session)

        logger.info(
            "Investment score for company_id=%d: %.1f (%s) [model=%s v%s]",
            company_id, overall, recommendation, SCORING_MODEL, SCORING_VERSION,
        )
        return score

    async def get_latest_score(self, company_id: int) -> InvestmentScore | None:
        """Get the most recent investment score."""
        result = await self.session.execute(
            select(InvestmentScore)
            .where(InvestmentScore.company_id == company_id)
            .order_by(desc(InvestmentScore.timestamp))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def get_recommendation_categories() -> list[str]:
        """
        Return the configured recommendation categories (Section 60).
        """
        return [rule["category"] for rule in settings.RECOMMENDATION_THRESHOLDS]
