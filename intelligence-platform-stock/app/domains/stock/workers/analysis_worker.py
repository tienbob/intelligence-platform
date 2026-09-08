"""
Analysis worker (Section 41).

Daily: Recalculate investment scores
On-demand: Full AI research analysis with evidence attribution

Gate 6.2: Worker delegates analysis execution to the framework path.
No legacy orchestration remains — scheduling, ticker selection, batching,
retries, and per-ticker isolation live here; analysis execution is
delegated to execute_company_analysis() which routes through the framework.
"""

from __future__ import annotations

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.models.analysis import Analysis
from app.domains.stock.models.company import Company
from app.domains.stock.scoring.analysis_validator import AnalysisValidationError
from app.domains.stock.services.company_analysis import execute_company_analysis
from app.domains.stock.scoring.risk import RiskEngine
from app.domains.stock.scoring.technical_analysis import TechnicalAnalysisEngine
from app.domains.stock.scoring.investment_scoring import InvestmentScoringEngine
from sqlalchemy import select

logger = get_logger(__name__)


async def recalculate_scores() -> None:
    """Recalculate investment scores for all tracked companies."""
    async with async_session_factory() as session:
        result = await session.execute(select(Company).limit(100))
        companies = result.scalars().all()

        scoring = InvestmentScoringEngine(session)

        # Pass the canonical fundamental snapshot so sub-scores are computed
        # from real data. Without it, _score_fundamental_snapshot() /
        # _score_growth_snapshot() silently return the 50.0 neutral
        # placeholder whenever the FinancialMetric rows lag, persisting
        # hardcoded-looking sub-scores that later become the "latest" score.
        from app.domains.stock.scoring.context_builder import ContextBuilder

        builder = ContextBuilder(session)

        for company in companies:
            try:
                snapshot = await builder.build_fundamental_snapshot(
                    company.id
                )
                await scoring.calculate_score(
                    company.id,
                    context={"fundamental_snapshot": snapshot},
                )
            except Exception as exc:
                logger.error("Failed to recalculate score for %s: %s", company.ticker, exc)

        logger.info("Score recalculation complete for %d companies", len(companies))


async def update_derived_metrics() -> None:
    """Update technical indicators and risk metrics for all companies."""
    async with async_session_factory() as session:
        result = await session.execute(select(Company).limit(100))
        companies = result.scalars().all()

        technical = TechnicalAnalysisEngine(session)
        risk = RiskEngine(session)

        for company in companies:
            try:
                await technical.calculate_indicators(company.id)
                await risk.calculate_risk(company.id)
            except Exception as exc:
                logger.error("Failed to update metrics for %s: %s", company.ticker, exc)

        logger.info("Derived metrics update complete for %d companies", len(companies))


async def run_company_analysis(company_id: int) -> Analysis | None:
    """
    Run full AI research analysis for a company.

    Gate 6.2: Worker delegates analysis execution to the framework path.
    No legacy orchestration remains — this is a thin wrapper that owns only
    worker-specific concerns (row lifecycle, error isolation). Analysis
    execution is delegated to execute_company_analysis() which routes
    through the framework per the ANALYSIS_ENGINE flag.

    See docs/PLAN_ANALYSIS_CONTRACT.md.
    """
    async with async_session_factory() as session:
        company = await session.get(Company, company_id)
        if not company:
            logger.error("Company not found: %d", company_id)
            return None

        try:
            result = await execute_company_analysis(
                session, company
            )
            return result.analysis

        except AnalysisValidationError as exc:
            logger.error("Analysis validation failed for %s: %s", company.ticker, exc)
            return None
        except Exception as exc:
            logger.error("Analysis failed for %s: %s", company.ticker, exc)
            return None

