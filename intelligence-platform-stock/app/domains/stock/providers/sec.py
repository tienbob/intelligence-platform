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
from app.domains.stock.providers.base import FundamentalDataProvider, ProviderError

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
        try:
            response = await client.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            tickers_data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(self.provider_name, "Unable to resolve SEC ticker index") from exc
        
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
            "total_debt": ["LongTermDebt", "DebtLongtermAndShorttermCombined"],
            "cash": ["CashAndCashEquivalentsAtCarryingValue"],
            "shareholders_equity": ["StockholdersEquity"],
        }

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
                                    "unit": unit,
                                    "source": "SEC",
                                })
                    break
        return results
    async def get_normalized_statements(self, ticker: str) -> list[dict[str, Any]]:
        """Canonical USD statements; omit YTD durations rather than label them quarters."""
        cik = await self._resolve_ticker_to_cik(ticker)
        facts = await self.get_company_facts(cik)
        return self.normalize_statements(facts)

    @staticmethod
    def normalize_statements(facts: dict[str, Any]) -> list[dict[str, Any]]:
        concepts = {
            'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'],
            'gross_profit': ['GrossProfit'], 'operating_income': ['OperatingIncomeLoss'],
            'net_income': ['NetIncomeLoss'], 'eps': ['EarningsPerShareBasic'],
            'total_assets': ['Assets'], 'total_liabilities': ['Liabilities'],
            'total_debt': ['DebtLongtermAndShorttermCombined', 'LongTermDebt'],
            'cash': ['CashAndCashEquivalentsAtCarryingValue'],
            'shareholders_equity': ['StockholdersEquity'],
            'operating_cash_flow': ['NetCashProvidedByUsedInOperatingActivities'],
            'capital_expenditure': ['PaymentsToAcquirePropertyPlantAndEquipment'],
        }
        gaap = facts.get('facts', {}).get('us-gaap', {})
        durations, instants = {}, {}
        for field, aliases in concepts.items():
            unit = 'USD/shares' if field == 'eps' else 'USD'
            points = next((gaap[a].get('units', {}).get(unit, []) for a in aliases if gaap.get(a, {}).get('units', {}).get(unit)), [])
            for point in sorted(points, key=lambda p: p.get('filed', '')):
                if point.get('form') not in ('10-K', '10-Q') or not point.get('end'):
                    continue
                end = point['end']
                if not point.get('start'):
                    instants.setdefault(end, {})[field] = point.get('val')
                    continue
                days = (datetime.fromisoformat(end) - datetime.fromisoformat(point['start'])).days
                kind = 'quarterly' if 70 <= days <= 110 else 'annual' if 330 <= days <= 380 else None
                if kind is None:
                    continue
                row = durations.setdefault((end, kind), {'period': end, 'period_type': kind, 'currency': 'USD', 'source': 'SEC'})
                row[field] = point.get('val')
                row['filed_date'] = max(row.get('filed_date', ''), point.get('filed', ''))
                row['source_id'] = point.get('accn')
        for (end, kind), row in durations.items():
            row.update(instants.get(end, {}))
            if row.get('capital_expenditure') is not None:
                row['capital_expenditure'] = -abs(row['capital_expenditure'])
            if row.get('operating_cash_flow') is not None and row.get('capital_expenditure') is not None:
                row['free_cash_flow'] = row['operating_cash_flow'] + row['capital_expenditure']
        return sorted(durations.values(), key=lambda r: (r['period'], r['period_type']))
