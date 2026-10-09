"""
Provider abstraction layer.

The application must not directly depend on one provider (Section 6).
All providers are accessed through abstract interfaces.

Provider registry:
    Massive  → MarketDataProvider, NewsProvider, FundamentalDataProvider
    SEC      → FundamentalDataProvider
    FRED     → MacroDataProvider
    FMP      → FundamentalDataProvider, MarketDataProvider
    Finnhub  → AlternativeDataProvider, NewsProvider, MarketDataProvider
"""

from app.domains.stock.providers.base import (
    AlternativeDataProvider,
    CircuitBreaker,
    CircuitBreakerOpenError,
    DataFreshness,
    FundamentalDataProvider,
    MacroDataProvider,
    MarketDataProvider,
    NewsProvider,
    ProviderError,
    RateLimitError,
)
from app.domains.stock.providers.factory import (
    DEFAULT_PROVIDER_CHAINS,
    ProviderFactory,
    ProviderRegistry,
    execute_provider,
    get_provider,
    get_provider_factory,
)
from app.domains.stock.providers.finnhub import FinnhubProvider
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.providers.fred import FREDProvider
from app.domains.stock.providers.twelve_data import TwelveDataProvider
from app.domains.stock.providers.massive import MassiveProvider
from app.domains.stock.providers.normalized import (
    NormalizedEconomicIndicator,
    NormalizedFinancialStatement,
    NormalizedInsiderTransaction,
    NormalizedInstitutionalOwnership,
    NormalizedMarketMover,
    NormalizedMarketMovers,
    NormalizedNews,
    NormalizedPriceHistory,
    NormalizedPricePoint,
    NormalizedQuote,
)
from app.domains.stock.providers.sec import SECProvider

__all__ = [
    # Interfaces
    "MarketDataProvider",
    "FundamentalDataProvider",
    "NewsProvider",
    "MacroDataProvider",
    "AlternativeDataProvider",
    # Concrete providers
    "TwelveDataProvider",
    "MassiveProvider",
    "SECProvider",
    "FREDProvider",
    "FMPProvider",
    "FinnhubProvider",
    # Factory / registry
    "ProviderFactory",
    "ProviderRegistry",
    "DEFAULT_PROVIDER_CHAINS",
    "get_provider_factory",
    "get_provider",
    "execute_provider",
    # Normalized models
    "NormalizedQuote",
    "NormalizedPricePoint",
    "NormalizedPriceHistory",
    "NormalizedMarketMover",
    "NormalizedMarketMovers",
    "NormalizedNews",
    "NormalizedFinancialStatement",
    "NormalizedEconomicIndicator",
    "NormalizedInsiderTransaction",
    "NormalizedInstitutionalOwnership",
    # Errors / utilities
    "ProviderError",
    "RateLimitError",
    "CircuitBreakerOpenError",
    "CircuitBreaker",
    "DataFreshness",
]