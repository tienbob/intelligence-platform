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

SEC XBRL is stored separately as authoritative raw verification data.

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

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.company import Company
from app.domains.stock.models.financial import FinancialStatement
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

    SEC provides authoritative XBRL company facts that are stored
    separately for verification and future reconciliation.

    The canonical FinancialStatement model intentionally stores one
    combined row per company/reporting period rather than separate
    income, balance-sheet, and cash-flow rows.
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
    ) -> None:
        """
        Store raw SEC payload.

        The raw payload is deliberately kept separate from the
        canonical FinancialStatement table because SEC XBRL contains
        substantially more information than the normalized model.
        """

        raw = RawSecFiling(
            provider="SEC",
            endpoint=f"/api/xbrl/companyfacts/CIK{cik}",
            cik=cik,
            filing_type=filing_type,
            retrieved_at=datetime.now(timezone.utc),
            payload=payload,
        )

        self.session.add(raw)

        # Flush so database errors happen here rather than later at
        # an unrelated commit.
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

        The existing database schema intentionally stores all three
        statement categories in a single FinancialStatement row.

        Values are taken from their corresponding source statement:

            income   → income fields
            balance  → balance-sheet fields
            cashflow  → cash-flow fields
        """

        income = income or {}
        balance = balance or {}
        cashflow = cashflow or {}

        # Prefer income metadata, then balance, then cash flow.
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

    async def ingest_fmp_statements(
        self,
        ticker: str,
    ) -> int:
        """
        Ingest and merge FMP income, balance-sheet, and cash-flow data.

        The three provider responses are grouped by reporting period
        and merged into one canonical FinancialStatement row.

        Example:

            Income Q2 2026
            Balance Q2 2026
            Cash Flow Q2 2026

        become:

            FinancialStatement(
                company_id=...,
                period="Q2 2026",
                revenue=...,
                total_assets=...,
                operating_cash_flow=...,
                ...
            )

        Returns the number of newly inserted canonical statement rows.
        """

        try:
            company = await self._get_company(ticker)

            # ----------------------------------------------------------
            # Fetch all three statement families.
            #
            # They are fetched separately because FMP exposes them as
            # separate endpoints.
            # ----------------------------------------------------------

            income_statements = (
                await self.fmp.get_income_statement(ticker)
            )

            balance_statements = (
                await self.fmp.get_balance_sheet(ticker)
            )

            cashflow_statements = (
                await self.fmp.get_cash_flow(ticker)
            )

            # ----------------------------------------------------------
            # Index each statement family by reporting period.
            #
            # This allows:
            #
            #     Q1 → income + balance + cashflow
            #     Q2 → income + balance + cashflow
            #
            # to be merged into a single canonical record.
            # ----------------------------------------------------------

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

            # ----------------------------------------------------------
            # Union of all periods.
            #
            # A provider can occasionally have one statement family
            # missing a period, so do not require all three to exist.
            # ----------------------------------------------------------

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

                # ------------------------------------------------------
                # Validate the merged canonical record.
                # ------------------------------------------------------

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

                # ------------------------------------------------------
                # Normalize dates.
                # ------------------------------------------------------

                filing_date = self._parse_datetime(
                    merged["filing_date"]
                )

                published_at = self._parse_datetime(
                    merged["published_at"]
                )

                retrieved_at = datetime.now(timezone.utc)

                # ------------------------------------------------------
                # Build one canonical FinancialStatement row.
                # ------------------------------------------------------

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

                # ------------------------------------------------------
                # One canonical row per:
                #
                #     company_id + period
                #
                # This matches the existing database schema.
                # ------------------------------------------------------

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

            # ----------------------------------------------------------
            # Commit the complete batch only after all periods have
            # been processed successfully.
            # ----------------------------------------------------------

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
    # SEC XBRL
    # ------------------------------------------------------------------

    async def ingest_sec_facts(
        self,
        cik: str,
        ticker: str | None = None,
    ) -> dict[str, Any]:
        """
        Ingest SEC XBRL company facts.

        SEC data is stored as raw authoritative source data.

        It is intentionally not directly written into
        FinancialStatement yet. A future verification/reconciliation
        layer can compare SEC facts against the normalized FMP data.
        """

        try:
            facts = await self.sec.get_company_facts(cik)

            await self._store_raw_sec(
                cik=cik,
                filing_type="XBRL",
                payload=facts,
            )

            await self.session.commit()

            logger.info(
                "Ingested SEC XBRL facts for CIK %s%s",
                cik,
                f" ({ticker})" if ticker else "",
            )

            return facts

        except ProviderError:
            await self.session.rollback()

            logger.exception(
                "Provider error ingesting SEC facts for CIK %s",
                cik,
            )

            raise

        except Exception:
            await self.session.rollback()

            logger.exception(
                "Unexpected error ingesting SEC facts for CIK %s",
                cik,
            )

            raise

    # ------------------------------------------------------------------
    # Company profile
    # ------------------------------------------------------------------

    async def ingest_company_profile(
        self,
        ticker: str,
    ) -> dict[str, Any]:
        """
        Ingest company profile from FMP and update the Company record.
        """

        try:
            profile = await self.fmp.get_company_profile(
                ticker
            )

            company = await self._get_company(ticker)

            if profile:
                company.name = profile.get(
                    "companyName",
                    company.name,
                )

                company.exchange = profile.get("exchange")
                company.sector = profile.get("sector")
                company.industry = profile.get("industry")
                company.country = profile.get("country")
                company.market_cap = profile.get("mktCap")
                company.description = profile.get("description")
                company.website = profile.get("website")
                company.cik = profile.get("cik")

            await self.session.commit()

            logger.info(
                "Updated company profile for %s",
                ticker,
            )

            return profile

        except ProviderError:
            await self.session.rollback()

            logger.exception(
                "Provider error ingesting profile for %s",
                ticker,
            )

            raise

        except Exception:
            await self.session.rollback()

            logger.exception(
                "Unexpected error ingesting profile for %s",
                ticker,
            )

            raise