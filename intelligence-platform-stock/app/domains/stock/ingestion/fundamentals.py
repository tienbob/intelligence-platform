"""
Fundamentals data ingestion (Section 16).

Pipeline:

    FMP Income Statement ─┐
    FMP Balance Sheet ────┼→ Merge by reporting period
    FMP Cash Flow ────────┘
                              ↓
                         Validate
                              ↓
                    Canonical FinancialStatement
                              ↓
                         PostgreSQL

SEC XBRL is stored in two forms:

    1. RawSecFiling
       Complete authoritative SEC companyfacts payload.

    2. SecFiling
       Human-readable filing-period chunks derived from XBRL,
       used by the RAG / embedding pipeline.

Canonical model:

    One FinancialStatement row per:

        (company_id, period)

The canonical row combines:

    Income statement:
        revenue
        gross_profit
        operating_income
        net_income
        eps

    Balance sheet:
        total_assets
        total_liabilities
        total_debt
        cash
        shareholders_equity

    Cash flow:
        operating_cash_flow
        capital_expenditure
        free_cash_flow
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from app.domains.stock.models.company import Company
from app.domains.stock.models.financial import (
    FinancialStatement,
    SecFiling,
)
from app.domains.stock.models.raw import RawSecFiling

from app.domains.stock.normalization.companies import EntityResolver

from app.domains.stock.providers import (
    FMPProvider,
    ProviderError,
    SECProvider,
)

from app.domains.stock.validation.schema import (
    validate_financial_statement,
)

logger = get_logger(__name__)


class FundamentalsIngestion:
    """
    Ingest financial data from FMP and SEC.

    FMP provides normalized financial statement data.

    SEC provides authoritative XBRL company facts that are:

        - preserved completely in RawSecFiling
        - transformed into SecFiling RAG chunks

    The canonical FinancialStatement model stores one combined row
    per company/reporting period.
    """

    def __init__(
        self,
        session: AsyncSession,
        fmp_provider: FMPProvider | None = None,
        sec_provider: SECProvider | None = None,
    ):
        self.session = session
        self.fmp = fmp_provider or FMPProvider()
        self.sec = sec_provider or SECProvider()
        self._entity_resolver = EntityResolver(session)

    # ------------------------------------------------------------------
    # Company resolution
    # ------------------------------------------------------------------

    async def _get_company(self, ticker: str) -> Company:
        """
        Resolve ticker to a company using the entity resolver.
        """
        return await self._entity_resolver.resolve_or_create(
            ticker=ticker
        )

    # ------------------------------------------------------------------
    # SEC raw storage
    # ------------------------------------------------------------------

    async def _store_raw_sec(
        self,
        cik: str,
        filing_type: str,
        payload: dict[str, Any],
        ticker: str | None = None,
    ) -> None:
        """
        Store the complete raw SEC provider response.

        The raw payload is deliberately kept separate from the
        canonical FinancialStatement and SecFiling tables.
        """
        raw = RawSecFiling(
            provider="SEC",
            endpoint=f"/api/xbrl/companyfacts/CIK{cik}",
            cik=cik,
            ticker=ticker or "",
            filing_type=filing_type,
            retrieved_at=datetime.now(timezone.utc),
            payload=payload,
        )

        self.session.add(raw)

        # Flush so database errors happen here rather than at an
        # unrelated commit.
        await self.session.flush()

    # ------------------------------------------------------------------
    # Datetime normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_datetime(
        value: str | datetime | None,
    ) -> datetime | None:
        """
        Normalize provider timestamps to timezone-aware UTC datetimes.

        Handles:

            None
            datetime
            ISO-8601 strings
            timestamps with Z
            naive timestamps
        """
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)

            return value.astimezone(timezone.utc)

        if not isinstance(value, str) or not value.strip():
            return None

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            logger.warning(
                "Unable to parse datetime value from %r",
                value,
            )
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # Statement normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_statement_period(
        income: dict[str, Any] | None,
        balance: dict[str, Any] | None,
        cashflow: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Merge the three FMP statement types into one canonical record.
        """
        income = income or {}
        balance = balance or {}
        cashflow = cashflow or {}

        period_type = (
            income.get("period_type")
            or balance.get("period_type")
            or cashflow.get("period_type")
            or "quarterly"
        )

        currency = (
            income.get("currency")
            or balance.get("currency")
            or cashflow.get("currency")
            or "USD"
        )

        filed_date = (
            income.get("filed_date")
            or balance.get("filed_date")
            or cashflow.get("filed_date")
        )

        published_at = (
            income.get("published_at")
            or balance.get("published_at")
            or cashflow.get("published_at")
            or filed_date
        )

        source_id = (
            income.get("source_id")
            or balance.get("source_id")
            or cashflow.get("source_id")
        )

        return {
            # Common metadata
            "period_type": period_type,
            "currency": currency,

            # Income statement
            "revenue": income.get("revenue"),
            "gross_profit": income.get("gross_profit"),
            "operating_income": income.get("operating_income"),
            "net_income": income.get("net_income"),
            "eps": income.get("eps"),

            # Balance sheet
            "total_assets": balance.get("total_assets"),
            "total_liabilities": balance.get(
                "total_liabilities"
            ),
            "total_debt": balance.get("total_debt"),
            "cash": balance.get("cash"),
            "shareholders_equity": balance.get(
                "shareholders_equity"
            ),

            # Cash flow
            "operating_cash_flow": cashflow.get(
                "operating_cash_flow"
            ),
            "capital_expenditure": cashflow.get(
                "capital_expenditure"
            ),
            "free_cash_flow": cashflow.get(
                "free_cash_flow"
            ),

            # Metadata
            "filing_date": filed_date,
            "published_at": published_at,
            "source_id": source_id,
        }

    # ------------------------------------------------------------------
    # FMP financial statements
    # ------------------------------------------------------------------

    async def ingest_company_profile(
        self,
        ticker: str,
    ) -> Company:
        """
        Ingest and apply the FMP company profile to the canonical company row.

        Fills name, exchange, sector, industry, market cap, description,
        website, country, and identifier columns (CIK/ISIN/CUSIP). This is
        the step that turns a bare auto-ingested stub (created by the price
        ingestion with ``name == ticker``) into a fully-populated company.
        """
        profile = await self.fmp.get_company_profile(ticker)

        if not profile:
            logger.info("FMP returned no profile for %s; skipping", ticker)
            return await self._get_company(ticker)

        company = await self._get_company(ticker)

        # Map FMP profile fields → canonical Company columns. FMP has used
        # both ``marketCap`` and ``mktCap`` across API revisions, so accept
        # either.
        name = profile.get("companyName") or profile.get("name")
        exchange = (
            profile.get("exchange")
            or profile.get("exchangeShortName")
        )
        sector = profile.get("sector")
        industry = profile.get("industry")
        market_cap = (
            profile.get("marketCap")
            or profile.get("mktCap")
        )
        description = profile.get("description")
        website = profile.get("website")
        country = profile.get("country")
        isin = profile.get("isin")
        cusip = profile.get("cusip")
        cik = profile.get("cik")

        updated = False

        # Replace the ticker-fallback name whenever a real company name is
        # available. ``resolve_or_create`` only fills a name when it is
        # empty, which never triggers for a stub whose name is the ticker.
        if name and (not company.name or company.name == company.ticker):
            company.name = name
            updated = True

        def _set_if_missing(attr: str, value: Any) -> None:
            nonlocal updated
            if value and not getattr(company, attr, None):
                setattr(company, attr, value)
                updated = True

        _set_if_missing("exchange", exchange)
        _set_if_missing("sector", sector)
        _set_if_missing("industry", industry)
        _set_if_missing("market_cap", market_cap)
        _set_if_missing("description", description)
        _set_if_missing("website", website)
        _set_if_missing("country", country)
        _set_if_missing("isin", isin)
        _set_if_missing("cusip", cusip)

        if cik and not company.cik:
            company.cik = str(cik).strip().zfill(10)
            updated = True

        if updated:
            await self.session.commit()
            logger.info(
                "Updated company profile for %s (%s)",
                ticker,
                company.name,
            )
        else:
            logger.info(
                "Company profile for %s already complete",
                ticker,
            )

        return company

    async def ingest_fmp_statements(
        self,
        ticker: str,
    ) -> int:
        """
        Ingest and merge FMP income, balance-sheet, and cash-flow data.

        Returns the number of newly inserted canonical statement rows.
        """
        try:
            company = await self._get_company(ticker)

            income_statements = (
                await self.fmp.get_income_statement(ticker)
            )

            balance_statements = (
                await self.fmp.get_balance_sheet(ticker)
            )

            cashflow_statements = (
                await self.fmp.get_cash_flow(ticker)
            )

            income_by_period: dict[str, dict[str, Any]] = {
                stmt["period"]: stmt
                for stmt in income_statements
                if stmt.get("period")
            }

            balance_by_period: dict[str, dict[str, Any]] = {
                stmt["period"]: stmt
                for stmt in balance_statements
                if stmt.get("period")
            }

            cashflow_by_period: dict[str, dict[str, Any]] = {
                stmt["period"]: stmt
                for stmt in cashflow_statements
                if stmt.get("period")
            }

            periods = (
                set(income_by_period)
                | set(balance_by_period)
                | set(cashflow_by_period)
            )

            count = 0

            for period in sorted(periods):
                income = income_by_period.get(period)
                balance = balance_by_period.get(period)
                cashflow = cashflow_by_period.get(period)

                merged = self._merge_statement_period(
                    income=income,
                    balance=balance,
                    cashflow=cashflow,
                )

                validation_data = {
                    "ticker": ticker,
                    "period": period,
                    "period_type": merged["period_type"],
                    "currency": merged["currency"],
                    "revenue": merged["revenue"],
                    "gross_profit": merged["gross_profit"],
                    "operating_income": merged[
                        "operating_income"
                    ],
                    "net_income": merged["net_income"],
                    "eps": merged["eps"],
                    "total_assets": merged["total_assets"],
                    "total_liabilities": merged[
                        "total_liabilities"
                    ],
                    "total_debt": merged["total_debt"],
                    "cash": merged["cash"],
                    "source": "FMP",
                }

                validation_result = validate_financial_statement(
                    validation_data
                )

                if not validation_result:
                    logger.warning(
                        "Skipping invalid financial statement for "
                        "%s period %s: %s",
                        ticker,
                        period,
                        validation_result.errors,
                    )
                    continue

                filing_date = self._parse_datetime(
                    merged["filing_date"]
                )

                published_at = self._parse_datetime(
                    merged["published_at"]
                )

                retrieved_at = datetime.now(timezone.utc)

                values = {
                    "company_id": company.id,
                    "period": period,
                    "period_type": merged["period_type"],
                    "currency": merged["currency"],

                    # Income
                    "revenue": merged["revenue"],
                    "gross_profit": merged["gross_profit"],
                    "operating_income": merged[
                        "operating_income"
                    ],
                    "net_income": merged["net_income"],
                    "eps": merged["eps"],

                    # Balance sheet
                    "total_assets": merged["total_assets"],
                    "total_liabilities": merged[
                        "total_liabilities"
                    ],
                    "total_debt": merged["total_debt"],
                    "cash": merged["cash"],
                    "shareholders_equity": merged[
                        "shareholders_equity"
                    ],

                    # Cash flow
                    "operating_cash_flow": merged[
                        "operating_cash_flow"
                    ],
                    "capital_expenditure": merged[
                        "capital_expenditure"
                    ],
                    "free_cash_flow": merged[
                        "free_cash_flow"
                    ],

                    # Metadata
                    "filing_date": filing_date,
                    "source": "FMP",
                    "source_id": merged["source_id"],
                    "retrieved_at": retrieved_at,
                    "published_at": published_at,
                    "data_version": "1.0",
                }

                insert_stmt = (
                    insert(FinancialStatement)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=[
                            "company_id",
                            "period",
                        ]
                    )
                )

                result = await self.session.execute(
                    insert_stmt
                )

                if result.rowcount == 0:
                    logger.debug(
                        "Skipping duplicate financial statement "
                        "for %s period %s",
                        ticker,
                        period,
                    )
                    continue

                count += 1

            await self.session.commit()

            logger.info(
                "Ingested %d financial statement periods for %s "
                "(income=%d, balance=%d, cashflow=%d)",
                count,
                ticker,
                len(income_by_period),
                len(balance_by_period),
                len(cashflow_by_period),
            )

            return count

        except ProviderError:
            await self.session.rollback()

            logger.exception(
                "Provider error ingesting FMP statements for %s",
                ticker,
            )

            raise

        except Exception:
            await self.session.rollback()

            logger.exception(
                "Unexpected error ingesting FMP statements for %s",
                ticker,
            )

            raise

    # ------------------------------------------------------------------
    # SEC filing chunk construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filing_chunks(
        company_id: int,
        cik: str,
        ticker: str | None,
        facts: dict[str, Any],
    ) -> list[SecFiling]:
        """
        Convert SEC companyfacts XBRL data into human-readable
        filing-period chunks for RAG.

        SEC companyfacts has the general structure:

            {
                "entityName": "...",
                "facts": {
                    "us-gaap": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {
                            "label": "...",
                            "units": {
                                "USD": [
                                    {
                                        "fy": 2026,
                                        "fp": "Q2",
                                        "form": "10-Q",
                                        "filed": "2026-05-..."
                                        "start": "...",
                                        "end": "...",
                                        "val": ...
                                    }
                                ]
                            }
                        }
                    }
                }
            }

        We group XBRL facts by:

            fiscal year + fiscal period + form

        and produce one SecFiling chunk per group.

        This deliberately uses companyfacts rather than attempting to
        download the full filing HTML. The resulting content is
        authoritative SEC-derived financial context suitable for the
        current RAG pipeline.
        """
        facts_root = facts.get("facts") or {}

        if not isinstance(facts_root, dict):
            logger.warning(
                "SEC facts payload has invalid 'facts' structure "
                "for %s",
                ticker or cik,
            )
            return []

        grouped: dict[
            tuple[str, str, str],
            list[dict[str, Any]],
        ] = defaultdict(list)

        # --------------------------------------------------------------
        # Extract us-gaap facts.
        # --------------------------------------------------------------

        for namespace, namespace_facts in facts_root.items():
            if not isinstance(namespace_facts, dict):
                continue

            for concept, concept_data in namespace_facts.items():
                if not isinstance(concept_data, dict):
                    continue

                label = (
                    concept_data.get("label")
                    or concept_data.get("description")
                    or concept
                )

                units = concept_data.get("units") or {}

                if not isinstance(units, dict):
                    continue

                for unit_name, observations in units.items():
                    if not isinstance(observations, list):
                        continue

                    for observation in observations:
                        if not isinstance(observation, dict):
                            continue

                        form = observation.get("form")

                        # Companyfacts contains many observation types.
                        # Only filing-backed observations are useful here.
                        if not form:
                            continue

                        fiscal_year = observation.get("fy")

                        if fiscal_year is None:
                            continue

                        fiscal_period = (
                            observation.get("fp")
                            or "FY"
                        )

                        filed = observation.get("filed")

                        key = (
                            str(fiscal_year),
                            str(fiscal_period),
                            str(form),
                        )

                        grouped[key].append(
                            {
                                "namespace": namespace,
                                "concept": concept,
                                "label": label,
                                "unit": unit_name,
                                "value": observation.get("val"),
                                "start": observation.get("start"),
                                "end": observation.get("end"),
                                "filed": filed,
                                "accn": observation.get("accn"),
                                "frame": observation.get("frame"),
                                "form": form,
                            }
                        )

        chunks: list[SecFiling] = []

        # --------------------------------------------------------------
        # Build one RAG document per filing period.
        # --------------------------------------------------------------

        for (
            fiscal_year,
            fiscal_period,
            form,
        ), observations in grouped.items():

            if not observations:
                continue

            # Prefer the most recently filed observation for each
            # concept/unit combination.
            latest_by_concept: dict[
                tuple[str, str],
                dict[str, Any],
            ] = {}

            for observation in observations:
                concept_key = (
                    observation["concept"],
                    observation["unit"],
                )

                existing = latest_by_concept.get(concept_key)

                if existing is None:
                    latest_by_concept[concept_key] = observation
                    continue

                existing_filed = existing.get("filed") or ""
                current_filed = observation.get("filed") or ""

                if current_filed >= existing_filed:
                    latest_by_concept[concept_key] = observation

            selected = list(latest_by_concept.values())

            # Stable ordering gives deterministic content and therefore
            # deterministic embeddings.
            selected.sort(
                key=lambda item: (
                    str(item.get("label") or ""),
                    str(item.get("concept") or ""),
                    str(item.get("unit") or ""),
                )
            )

            filed_dates = [
                item.get("filed")
                for item in selected
                if item.get("filed")
            ]

            latest_filed = None

            if filed_dates:
                latest_filed = max(filed_dates)

            filed_date = FundamentalsIngestion._parse_datetime(
                latest_filed
            )

            # ----------------------------------------------------------
            # Human-readable RAG content.
            # ----------------------------------------------------------

            lines = [
                f"SEC filing data for {ticker or 'UNKNOWN'}",
                f"CIK: {cik}",
                f"Form: {form}",
                f"Fiscal year: {fiscal_year}",
                f"Fiscal period: {fiscal_period}",
            ]

            if filed_date:
                lines.append(
                    f"Filed date: {filed_date.date().isoformat()}"
                )

            lines.append("")
            lines.append("SEC XBRL financial facts:")

            for observation in selected:
                label = (
                    observation.get("label")
                    or observation.get("concept")
                    or "Unknown fact"
                )

                value = observation.get("value")
                unit = observation.get("unit") or ""

                start = observation.get("start")
                end = observation.get("end")

                concept = observation.get("concept") or ""

                if start and end:
                    period_text = (
                        f"{start} to {end}"
                    )
                elif end:
                    period_text = str(end)
                else:
                    period_text = ""

                value_text = (
                    str(value)
                    if value is not None
                    else "N/A"
                )

                line = (
                    f"- {label}: {value_text} {unit}"
                )

                if period_text:
                    line += f" ({period_text})"

                if concept:
                    line += f" [XBRL: {concept}]"

                lines.append(line)

            content = "\n".join(lines)

            chunks.append(
                SecFiling(
                    company_id=company_id,
                    cik=cik,
                    filing_type="XBRL",
                    fiscal_year=str(fiscal_year),
                    period=str(fiscal_period),
                    form=str(form),
                    filed_date=filed_date,
                    content=content,
                    source="SEC",
                )
            )

        logger.debug(
            "Prepared %d SEC filing chunks for %s",
            len(chunks),
            ticker or cik,
        )

        return chunks

    # ------------------------------------------------------------------
    # SEC XBRL
    # ------------------------------------------------------------------

    async def ingest_sec_facts(
        self,
        cik: str,
        ticker: str | None = None,
        company_id: int | None = None,
    ) -> None:
        """Ingest SEC company facts and optionally build RAG filing chunks."""

        cik = str(cik).strip().zfill(10)

        try:
            facts = await self.sec.get_company_facts(cik)

        except ProviderError as exc:
            # Some instruments have a CIK but do not expose an SEC
            # Company Facts dataset. Treat 404 as a normal skip.
            if "HTTP 404" in str(exc):
                logger.info(
                    "SEC Company Facts unavailable for %s (CIK %s); skipping",
                    ticker or "unknown ticker",
                    cik,
                )
                return

            logger.exception(
                "Provider error ingesting SEC facts for CIK %s",
                cik,
            )
            raise

        if not facts:
            logger.info(
                "SEC returned no company facts for %s (CIK %s); skipping",
                ticker or "unknown ticker",
                cik,
            )
            return

        # Store complete authoritative SEC payload.
        # _store_raw_sec() constructs the endpoint internally.
        await self._store_raw_sec(
            cik=cik,
            ticker=ticker,
            filing_type="companyfacts",
            payload=facts,
        )

        # Build SEC filing chunks for RAG.
        if company_id is not None:
            filings = self._build_filing_chunks(
                company_id=company_id,
                cik=cik,
                ticker=ticker,
                facts=facts,
            )

            if filings:
                for filing in filings:
                    stmt = (
                        insert(SecFiling)
                        .values(
                            company_id=filing.company_id,
                            cik=filing.cik,
                            filing_type=filing.filing_type,
                            fiscal_year=filing.fiscal_year,
                            period=filing.period,
                            form=filing.form,
                            filed_date=filing.filed_date,
                            content=filing.content,
                            source=filing.source,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                "company_id",
                                "fiscal_year",
                                "period",
                                "form",
                            ]
                        )
                    )

                    await self.session.execute(stmt)

                await self.session.commit()

                logger.info(
                    "Stored %d SEC filing chunks for %s",
                    len(filings),
                    ticker or cik,
                )
            else:
                logger.info(
                    "No SEC filing chunks generated for %s",
                    ticker or cik,
                )
