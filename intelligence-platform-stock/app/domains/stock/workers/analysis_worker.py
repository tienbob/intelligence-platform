"""
Analysis worker (Section 41).

Daily: Recalculate investment scores
On-demand: Full AI research analysis with evidence attribution
"""

from __future__ import annotations

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.domains.stock.models.analysis import Analysis
from app.domains.stock.models.company import Company
from app.domains.stock.scoring.analysis_validator import AnalysisValidationError
from app.domains.stock.scoring.context_builder import ContextBuilder
from app.domains.stock.scoring.evidence import EvidenceAttributor
from app.domains.stock.scoring.llm import LLMService
from app.domains.stock.scoring.investment_scoring import InvestmentScoringEngine
from app.domains.stock.services.company_analysis import (
    CompanyAnalysisService,
    execute_company_analysis,
)
from app.domains.stock.scoring.risk import RiskEngine
from app.domains.stock.scoring.technical_analysis import TechnicalAnalysisEngine
from sqlalchemy import select

logger = get_logger(__name__)


async def recalculate_scores() -> None:
    """Recalculate investment scores for all tracked companies."""
    async with async_session_factory() as session:
        result = await session.execute(select(Company).limit(100))
        companies = result.scalars().all()

        scoring = InvestmentScoringEngine(session)
        for company in companies:
            try:
                await scoring.calculate_score(company.id)
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

    Thin entry-point wrapper: all contract-producing steps (context, LLM,
    validation, deterministic scoring, persistence of the canonical Analysis
    contract) live in ``CompanyAnalysisService`` — shared with the API path.

    This variant runs without progress reporting (``on_stage=None``) and
    creates one complete row at the end. Callers today: Gate 3's legacy
    oracle and batch contexts. See docs/PLAN_ANALYSIS_CONTRACT.md.
    """
    async with async_session_factory() as session:
        company = await session.get(Company, company_id)
        if not company:
            logger.error("Company not found: %d", company_id)
            return None

        try:
            service = CompanyAnalysisService(
                session,
                context_builder=ContextBuilder(session),
                llm_service=LLMService(),
                evidence_attributor_factory=EvidenceAttributor,
                scoring_engine_factory=lambda s: InvestmentScoringEngine(s),
            )
            result = await execute_company_analysis(
                session, company, legacy_service=service
            )
            return result.analysis

        except AnalysisValidationError as exc:
            logger.error("Analysis validation failed for %s: %s", company.ticker, exc)
            return None
        except Exception as exc:
            logger.error("Analysis failed for %s: %s", company.ticker, exc)
            return None

