"""
Company normalization and entity resolution (Section 14).

Different providers may represent the same company differently:
    Apple Inc. / Apple / AAPL / NASDAQ:AAPL / AAPL.US

All should resolve to a single company_id.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.company import Company

logger = get_logger(__name__)


def normalize_ticker(raw_ticker: str) -> str:
    """
    Normalize a ticker symbol.

    Examples:
        NASDAQ:AAPL → AAPL
        AAPL.US     → AAPL
        aapl        → AAPL
    """
    # Remove exchange prefix (NASDAQ:AAPL → AAPL)
    ticker = raw_ticker.split(":")[-1]
    # Remove country suffix (AAPL.US → AAPL)
    ticker = ticker.split(".")[0]
    return ticker.strip().upper()


def normalize_company_name(name: str) -> str:
    """Normalize a company name for comparison."""
    name = name.strip()
    # Remove common suffixes
    suffixes = ["Inc.", "Inc", "Corp.", "Corp", "Ltd.", "Ltd", "Co.", "Co"]
    for suffix in suffixes:
        if name.endswith(f" {suffix}"):
            name = name[: -len(suffix)].strip()
    return name.lower()


# Canonical instrument types (docs/PLAN_INSTRUMENT_TYPE.md).
INSTRUMENT_TYPE_COMMON_STOCK = "common_stock"
INSTRUMENT_TYPE_ETF = "etf"
INSTRUMENT_TYPE_MUTUAL_FUND = "mutual_fund"
INSTRUMENT_TYPE_UNKNOWN = "unknown"


def classify_instrument(profile: dict[str, Any] | None) -> str:
    """
    Map a provider company profile to a canonical ``instrument_type``.

    Returns ``unknown`` when the profile is missing, and otherwise relies on
    the provider's explicit instrument flags. It never defaults a *present*
    profile to ``common_stock`` just because classification failed — the
    only thing it asserts is whether the provider tagged it as an ETF or a
    mutual fund. ADRs are intentionally left as ``common_stock`` (an ADR is
    a foreign company's listed equity, not a fund).

    FMP contract (verified 2026-09-08 against the FMP changelog):
        ``isEtf``  → exchange-traded fund
        ``isFund`` → mutual fund
        ``isAdr``  → depositary receipt (still a stock for analysis purposes)
    """
    if not profile:
        return INSTRUMENT_TYPE_UNKNOWN

    if profile.get("isEtf"):
        return INSTRUMENT_TYPE_ETF

    if profile.get("isFund"):
        return INSTRUMENT_TYPE_MUTUAL_FUND

    return INSTRUMENT_TYPE_COMMON_STOCK


def is_company_analysis_target(
    instrument_type: str | None,
) -> bool:
    """
    Whether an entity should flow through company-style fundamentals/analysis.

    ETFs, mutual funds, and unclassified entities are tracked (prices/news)
    but excluded from company analysis — an ETF has no XBRL financial
    statements or income statement in the company sense.
    """
    return instrument_type == INSTRUMENT_TYPE_COMMON_STOCK


class EntityResolver:
    """
    Resolves different provider representations to a canonical company.

    Section 14: Entity Resolution
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve(
        self,
        ticker: str | None = None,
        name: str | None = None,
        cik: str | None = None,
        isin: str | None = None,
        cusip: str | None = None,
    ) -> Company | None:
        """Resolve identifiers to an existing company record."""
        conditions = []
        if ticker:
            conditions.append(Company.ticker == normalize_ticker(ticker))
        if cik:
            conditions.append(Company.cik == str(cik).zfill(10))
        if isin:
            conditions.append(Company.isin == isin.upper())
        if cusip:
            conditions.append(Company.cusip == cusip.upper())

        if not conditions:
            return None

        result = await self.session.execute(
            select(Company).where(or_(*conditions)).limit(1)
        )
        return result.scalar_one_or_none()

    async def resolve_or_create(
        self,
        ticker: str,
        name: str | None = None,
        **kwargs: Any,
    ) -> Company:
        """Resolve a company or create a new record."""
        normalized_ticker = normalize_ticker(ticker)

        company = await self.resolve(ticker=normalized_ticker, **kwargs)
        if company:
            # Update missing fields
            updated = False
            if name and not company.name:
                company.name = name
                updated = True
            for key in ("cik", "isin", "cusip", "exchange", "sector", "industry"):
                val = kwargs.get(key)
                if val and not getattr(company, key, None):
                    setattr(company, key, val)
                    updated = True
            if updated:
                await self.session.flush()
            return company

        # Create new
        company = Company(
            ticker=normalized_ticker,
            name=name or normalized_ticker,
            cik=kwargs.get("cik"),
            isin=kwargs.get("isin"),
            cusip=kwargs.get("cusip"),
            exchange=kwargs.get("exchange"),
            sector=kwargs.get("sector"),
            industry=kwargs.get("industry"),
        )
        self.session.add(company)
        await self.session.flush()
        logger.info("Created new company: %s", normalized_ticker)
        return company


# ── Framework integration ───────────────────────────────────────
#
# Register Stock's identifier semantics with the canonical framework
# entity-resolution service. This is the general → domain consumption
# pattern: the framework owns resolution mechanics; Stock owns what a
# ticker looks like. Idempotent (registering twice is harmless).

def _register_stock_normalizer() -> None:
    try:
        from app.intelligence.entity_resolution import register_normalizer

        register_normalizer("stock", normalize_ticker, entity_type="company")
    except Exception as exc:  # pragma: no cover — defensive; never block import
        logger.warning("Could not register stock normalizer with framework: %s", exc)


_register_stock_normalizer()