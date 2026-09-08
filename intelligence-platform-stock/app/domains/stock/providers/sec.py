"""
SEC EDGAR provider — primary source for US public-company filings.

Provides:
    - 10-K, 10-Q, 8-K filings
    - XBRL financial facts
    - Company submissions
    - Insider filings

SEC APIs do not require API keys, but a descriptive User-Agent is mandatory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.providers.base import FundamentalDataProvider

logger = get_logger(__name__)
settings = get_stock_config()

# Cache for ticker→CIK resolution
_ticker_to_cik_cache: dict[str, str] = {}


class SECProvider(FundamentalDataProvider):
    """
    SEC EDGAR adapter.

    Source_docs.md §2:
        SEC is the primary source for US public-company filings.
        SEC APIs don't require API keys.
        Submissions API updates in <1 second; XBRL APIs in <1 minute.
    """

    provider_name = "sec"
    base_url = settings.SEC_BASE_URL
    rate_limit_per_sec = 10  # SEC allows 10 req/sec

    def __init__(self, **kwargs: Any):
        # SEC doesn't use API keys, but requires a descriptive User-Agent
        super().__init__(api_key=None, **kwargs)

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": settings.SEC_USER_AGENT,
            "Accept": "application/json",
        }

    def _build_params(self, **kwargs: Any) -> dict[str, Any]:
        # SEC doesn't use API key params
        return {k: v for k, v in kwargs.items() if v is not None}

    # -- Generic Provider Protocol (Section 6) ----------------------

    async def fetch(self, entity_ref) -> list[dict[str, Any]]:
        """Generic fetch -- returns observations with ``kind`` fields."""
        ticker = entity_ref.entity_id
        results: list[dict[str, Any]] = []

        try:
            income = await self.get_income_statement(ticker)
            results.append({"kind": "financials", "data": income})
        except Exception:
            logger.warning("SEC get_income_statement failed for %s", ticker, exc_info=True)

        try:
            balance = await self.get_balance_sheet(ticker)
            results.append({"kind": "balance_sheet", "data": balance})
        except Exception:
            logger.warning("SEC get_balance_sheet failed for %s", ticker, exc_info=True)

        try:
            cash = await self.get_cash_flow(ticker)
            results.append({"kind": "cash_flow", "data": cash})
        except Exception:
            logger.warning("SEC get_cash_flow failed for %s", ticker, exc_info=True)

        return results


    # ── Company / CIK resolution ─────────────────────────────────

    async def _resolve_ticker_to_cik(self, ticker: str) -> str:
        """
        Resolve ticker symbol to CIK using SEC company tickers index.
        
        Caches results to minimize API calls.
        """
        ticker_upper = ticker.upper()
        if ticker_upper in _ticker_to_cik_cache:
            return _ticker_to_cik_cache[ticker_upper]

        # SEC provides a company tickers JSON at /files/company/tickers.json
        import httpx
        client = await self._get_client()
        response = await client.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=self._get_headers(),
        )
        response.raise_for_status()
        tickers_data = response.json()
        
        # Find matching ticker (case-insensitive)
        cik = None
        for key, company in tickers_data.items():
            if isinstance(company, dict) and company.get("ticker", "").upper() == ticker_upper:
                cik = str(company.get("cik_str", "")).zfill(10)
                break
        
        if not cik:
            raise ValueError(f"Could not resolve ticker {ticker} to CIK")
        
        _ticker_to_cik_cache[ticker_upper] = cik
        return cik

    async def get_company_submissions(self, cik: str) -> dict[str, Any]:
        """
        Get all filings for a company by CIK.

        Endpoint: /submissions/CIK{cik}.json
        """
        # Pad CIK to 10 digits
        cik_padded = str(cik).zfill(10)
        data = await self._request(
            "GET",
            f"/submissions/CIK{cik_padded}.json",
            params=self._build_params(),
        )
        return data

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        """
        Get XBRL company facts (all financial data points).

        Endpoint: /api/xbrl/companyfacts/CIK{cik}.json
        """
        cik_padded = str(cik).zfill(10)
        data = await self._request(
            "GET",
            f"/api/xbrl/companyfacts/CIK{cik_padded}.json",
            params=self._build_params(),
        )
        return data

    async def get_company_concept(
        self, cik: str, taxonomy: str, concept: str
    ) -> dict[str, Any]:
        """
        Get a specific XBRL concept (e.g., us-gaap:Revenues).

        Endpoint: /api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json
        """
        cik_padded = str(cik).zfill(10)
        return await self._request(
            "GET",
            f"/api/xbrl/companyconcept/CIK{cik_padded}/{taxonomy}/{concept}.json",
            params=self._build_params(),
        )

    async def get_filings(
        self,
        cik: str | None = None,
        form_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Search EDGAR full-text search API.

        Endpoint: https://efts.sec.gov/LATEST/search-index?q=...
        """
        params = self._build_params(
            q=f"formType:{form_type}" if form_type else "",
            dateRange=(",".join([
                start_date.strftime("%Y-%m-%d") if start_date else "",
                end_date.strftime("%Y-%m-%d") if end_date else "",
            ])),
        )
        if cik:
            params["ciks"] = str(cik).zfill(10)
        params["limit"] = limit

        # Use the full-text search base URL
        import httpx
        client = await self._get_client()
        # Override base URL for this search
        response = await client.get(
            "https://efts.sec.gov/LATEST/search-index",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    # ── FundamentalDataProvider interface ────────────────────────

    async def get_income_statement(self, ticker: str) -> list[dict[str, Any]]:
        """
        Extract income-statement data from XBRL company facts.

        SEC stores raw XBRL facts; we extract the relevant us-gaap concepts.
        """
        cik = await self._resolve_ticker_to_cik(ticker)
        facts = await self.get_company_facts(cik)
        us_gaap = facts.get("facts", {}).get("us-gaap", {})

        income_concepts = {
            "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
            "gross_profit": ["GrossProfit"],
            "operating_income": ["OperatingIncomeLoss"],
            "net_income": ["NetIncomeLoss"],
            "eps": ["EarningsPerShareBasic"],
        }

        # ``start``/``end`` carry the XBRL reporting window. Duration facts
        # (income, cash flow) report BOTH a ~3-month quarterly window and a
        # ~6-month year-to-date window inside the same (fy, fp, form) group,
        # so downstream selection needs the window to tell them apart.
        results: list[dict[str, Any]] = []
        for concept_name, aliases in income_concepts.items():
            for alias in aliases:
                if alias in us_gaap:
                    units = us_gaap[alias].get("units", {})
                    for unit, data_points in units.items():
                        for dp in data_points:
                            if dp.get("form") in ("10-K", "10-Q"):
                                results.append({
                                    "concept": concept_name,
                                    "value": dp.get("val"),
                                    "period": dp.get("fp"),
                                    "fiscal_year": dp.get("fy"),
                                    "form": dp.get("form"),
                                    "filed": dp.get("filed"),
                                    "start": dp.get("start"),
                                    "end": dp.get("end"),
                                    "unit": unit,
                                    "source": "SEC",
                                })
                    break  # Use first matching alias
        return results

    async def get_balance_sheet(self, ticker: str) -> list[dict[str, Any]]:
        """Extract balance-sheet data from XBRL company facts."""
        cik = await self._resolve_ticker_to_cik(ticker)
        facts = await self.get_company_facts(cik)
        us_gaap = facts.get("facts", {}).get("us-gaap", {})

        balance_concepts = {
            "total_assets": ["Assets"],
            "total_liabilities": ["Liabilities"],
            # IMPORTANT: prefer the COMBINED long+short-term concept first.
            # LongTermDebt is a component of debt, not "total debt" — using
            # it whenever Apple (or another filer) also reports the combined
            # concept made the RAG/alignment path report a different number
            # than FMP's combined totalDebt for the same quarter.
            "total_debt": ["DebtLongtermAndShorttermCombined", "LongTermDebt"],
            "cash": ["CashAndCashEquivalentsAtCarryingValue"],
            "shareholders_equity": ["StockholdersEquity"],
        }

        # Instant facts: ``start`` is emitted as None (XBRL instants carry
        # only ``end``); duration-aware selection never applies here.
        results: list[dict[str, Any]] = []
        for concept_name, aliases in balance_concepts.items():
            for alias in aliases:
                if alias in us_gaap:
                    units = us_gaap[alias].get("units", {})
                    for unit, data_points in units.items():
                        for dp in data_points:
                            if dp.get("form") in ("10-K", "10-Q"):
                                results.append({
                                    "concept": concept_name,
                                    "value": dp.get("val"),
                                    "period": dp.get("fp"),
                                    "fiscal_year": dp.get("fy"),
                                    "form": dp.get("form"),
                                    "filed": dp.get("filed"),
                                    "start": dp.get("start"),
                                    "end": dp.get("end"),
                                    "unit": unit,
                                    "source": "SEC",
                                })
                    break
        return results

    async def get_cash_flow(self, ticker: str) -> list[dict[str, Any]]:
        """Extract cash-flow data from XBRL company facts."""
        cik = await self._resolve_ticker_to_cik(ticker)
        facts = await self.get_company_facts(cik)
        us_gaap = facts.get("facts", {}).get("us-gaap", {})

        cashflow_concepts = {
            "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
            "capital_expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
            "free_cash_flow": ["FreeCashFlow"],
        }

        results: list[dict[str, Any]] = []
        for concept_name, aliases in cashflow_concepts.items():
            for alias in aliases:
                if alias in us_gaap:
                    units = us_gaap[alias].get("units", {})
                    for unit, data_points in units.items():
                        for dp in data_points:
                            if dp.get("form") in ("10-K", "10-Q"):
                                results.append({
                                    "concept": concept_name,
                                    "value": dp.get("val"),
                                    "period": dp.get("fp"),
                                    "fiscal_year": dp.get("fy"),
                                    "form": dp.get("form"),
                                    "filed": dp.get("filed"),
                                    "start": dp.get("start"),
                                    "end": dp.get("end"),
                                    "unit": unit,
                                    "source": "SEC",
                                })
                    break
        return results