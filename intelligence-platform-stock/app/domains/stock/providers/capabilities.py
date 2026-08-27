"""
Stock provider capability adapters.

The framework defines WHAT a capability means via the protocols in
``app.intelligence.contracts``; these adapters define HOW each Stock
vendor supplies it. They wrap the existing, production-proven providers
(NEVER rewritten) and expose framework-canonical capability methods.

    Framework capabilities          thin adapters (this module)
        EntityDataProvider ◄──────── CapabilityAdapter.fetch
        TimeSeriesProvider ◄──────── CapabilityAdapter.get_series
        NewsProvider       ◄──────── CapabilityAdapter.search_news / get_company_news
        SearchProvider     ◄──────── SEC adapter search

Vendor responses are NOT reshaped here — the domain normalizer owns that.
These adapters only (a) bridge method signatures, and (b) add the
``health_check`` that the framework's ``CapabilityProvider`` requires but
the legacy vendor classes never implemented.

    Massive  → entity_data, time_series, news
    FMP      → entity_data, time_series
    Finnhub  → entity_data, time_series, news
    SEC      → entity_data, search
    FRED     → time_series
"""

from __future__ import annotations

from typing import Any

from app.domains.stock.providers.base import ProviderError
from app.domains.stock.providers.finnhub import FinnhubProvider
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.providers.fred import FREDProvider
from app.domains.stock.providers.massive import MassiveProvider
from app.domains.stock.providers.sec import SECProvider
from app.shared.entities import EntityRef

# Framework capability → vendor method used to satisfy it.
_FETCH_METHODS = {
    "income_statement": "get_income_statement",
    "balance_sheet": "get_balance_sheet",
    "cash_flow": "get_cash_flow",
    "profile": "get_company_profile",
    "ratios": "get_ratios",
    "enterprise_value": "get_enterprise_value",
}


class CapabilityAdapter:
    """
    Base thin adapter. Subclasses declare the capabilities their vendor
    actually supports via ``framework_capabilities``. Canonical methods
    delegate to the wrapped vendor's existing methods.
    """

    #: names in CAPABILITY_PROTOCOLS that this vendor satisfies
    framework_capabilities: frozenset[str] = frozenset()

    def __init__(self, vendor: Any):
        self.vendor = vendor
        self.provider_name: str = getattr(vendor, "provider_name", "unknown")

    @property
    def capabilities(self) -> set[str]:
        return set(self.framework_capabilities)

    async def health_check(self) -> bool:
        """
        Reachability probe for the framework's ``CapabilityProvider``.

        Legacy Stock providers never implemented this; the adapter treats an
        instantiated, configured vendor as reachable. Override to add a real
        ping without touching the vendor class.
        """
        return True

    def _require(self, *vendor_methods: str) -> None:
        missing = [m for m in vendor_methods if not hasattr(self.vendor, m)]
        if missing:
            raise ProviderError(
                self.provider_name,
                f"vendor does not supply capability method(s): {', '.join(missing)}",
            )
    # ── EntityDataProvider ──────────────────────────────────────

    async def fetch(
        self,
        entity_ref: EntityRef,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Fetch a structured record for an entity by ``kind``."""
        ticker = entity_ref.entity_id
        kind = kwargs.get("kind", "income_statement")
        method = _FETCH_METHODS.get(kind)
        if method is None:
            raise ProviderError(
                self.provider_name, f"unknown entity data kind: {kind!r}"
            )
        self._require(method)
        result = await getattr(self.vendor, method)(ticker)
        return list(result) if isinstance(result, (list, tuple)) else [result]

        # ── TimeSeriesProvider ──────────────────────────────────────

    async def get_series(
        self,
        entity_ref: EntityRef,
        metric: str = "price",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Fetch a time series for an entity, keyed by ``metric``."""
        ticker = entity_ref.entity_id
        if metric in ("price", "prices"):
            self._require("get_historical_prices")
            return await self.vendor.get_historical_prices(
                ticker,
                kwargs.get("start_date"),
                kwargs.get("end_date"),
                kwargs.get("interval", "1d"),
            )
        if metric == "quote":
            self._require("get_quote")
            result = await self.vendor.get_quote(ticker)
            return list(result) if isinstance(result, (list, tuple)) else [result]
        raise ProviderError(
            self.provider_name, f"unsupported time-series metric: {metric!r}"
        )

        # ── NewsProvider ────────────────────────────────────────────

    async def search_news(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self._require("search_news")
        return await self.vendor.search_news(query, **kwargs.get("limit", 50))

    async def get_company_news(
        self, ticker: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        self._require("get_company_news")
        return await self.vendor.get_company_news(ticker, **kwargs.get("limit", 50))


# ── Per-vendor adapters ─────────────────────────────────────────


class MassiveCapabilities(CapabilityAdapter):
    framework_capabilities: frozenset[str] = frozenset(
        {"entity_data", "time_series", "news"}
    )


class FMPCapabilities(CapabilityAdapter):
    framework_capabilities: frozenset[str] = frozenset(
        {"entity_data", "time_series"}
    )


class FinnhubCapabilities(CapabilityAdapter):
    framework_capabilities: frozenset[str] = frozenset(
        {"entity_data", "time_series", "news"}
    )


class SECCapabilities(CapabilityAdapter):
    framework_capabilities: frozenset[str] = frozenset({"entity_data", "search"})

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """SearchProvider: delegate SEC filing search to the vendor."""
        self._require("get_filings")
        return await self.vendor.get_filings(query)


class FREDCapabilities(CapabilityAdapter):
    framework_capabilities: frozenset[str] = frozenset({"time_series"})

    async def get_series(
        self,
        entity_ref: EntityRef,
        metric: str = "gdp",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """FRED supplies indicators, not prices — metric is an indicator id."""
        self._require("get_indicator")
        return await self.vendor.get_indicator(metric)


# ── Catalog + builder ───────────────────────────────────────────

STOCK_CAPABILITY_CATALOG: dict[str, tuple[type, type]] = {
    "massive": (MassiveProvider, MassiveCapabilities),
    "fmp": (FMPProvider, FMPCapabilities),
    "finnhub": (FinnhubProvider, FinnhubCapabilities),
    "sec": (SECProvider, SECCapabilities),
    "fred": (FREDProvider, FREDCapabilities),
}


def build_capability_providers() -> dict[str, CapabilityAdapter]:
    """
    Return a fresh dict of framework-capability providers, one per vendor.

    Adapters are lightweight and stateless; constructing them is cheap
    (vendor clients initialize lazily on first request).
    """
    return {
        name: adapter_cls(vendor_cls())
        for name, (vendor_cls, adapter_cls) in STOCK_CAPABILITY_CATALOG.items()
    }
