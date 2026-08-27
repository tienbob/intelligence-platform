"""
Provider factory (Sections 6, 60).

Centralizes provider instantiation, capability registration, and fallback
chains so the application never directly depends on one provider.

Section 60 — No Single Provider Dependency:
    The application should remain functional if one provider fails.
    Massive unavailable → Fallback market provider → Continue
    But record: data_source = fallback, and reduce confidence if appropriate.

Architecture (Section 6):
    Provider Interface (abstract capabilities)
        ↓
    Concrete Providers registered by capability
        ↓
    Fallback chains by capability
        ↓
    Normalized Model returned to application
"""

from __future__ import annotations

from typing import Any, Type, TypeVar

from app.core.logging import get_logger
from app.domains.stock.providers.base import (
    AlternativeDataProvider,
    FundamentalDataProvider,
    MacroDataProvider,
    MarketDataProvider,
    NewsProvider,
    ProviderError,
)
from app.domains.stock.providers.finnhub import FinnhubProvider
from app.domains.stock.providers.fmp import FMPProvider
from app.domains.stock.providers.fred import FREDProvider
from app.domains.stock.providers.massive import MassiveProvider
from app.domains.stock.providers.sec import SECProvider

logger = get_logger(__name__)

T = TypeVar("T")

# Capability → list of provider classes in priority order (highest first)
# Section 60: Primary source → Official source → Verified provider → Secondary provider
DEFAULT_PROVIDER_CHAINS: dict[type, list[type]] = {
    MarketDataProvider: [MassiveProvider, FMPProvider, FinnhubProvider],
    FundamentalDataProvider: [FMPProvider, SECProvider, MassiveProvider],
    NewsProvider: [MassiveProvider, FinnhubProvider],
    MacroDataProvider: [FREDProvider],
    AlternativeDataProvider: [FinnhubProvider],
}

# Method-specific fallback chains (issue #8)
METHOD_FALLBACK_CHAINS: dict[tuple[type, str], list[type]] = {
    (MarketDataProvider, "get_quote"): [MassiveProvider, FMPProvider, FinnhubProvider],
    (MarketDataProvider, "get_historical_prices"): [MassiveProvider, FMPProvider, FinnhubProvider],
    (MarketDataProvider, "get_market_movers"): [MassiveProvider, FMPProvider],
    (FundamentalDataProvider, "get_income_statement"): [FMPProvider, SECProvider, MassiveProvider],
    (FundamentalDataProvider, "get_balance_sheet"): [FMPProvider, SECProvider, MassiveProvider],
    (FundamentalDataProvider, "get_cash_flow"): [FMPProvider, SECProvider, MassiveProvider],
    (NewsProvider, "search_news"): [MassiveProvider, FinnhubProvider],
    (NewsProvider, "get_company_news"): [MassiveProvider, FinnhubProvider],
}


class ProviderRegistry:
    """
    Registry mapping interface types to ordered provider implementations.

    The application resolves a provider capability through the registry,
    which manages primary/fallback chains transparently.
    """

    def __init__(self, chains: dict[type, list[type]] | None = None):
        self._chains: dict[type, list[type]] = chains or DEFAULT_PROVIDER_CHAINS
        self._instances: dict[tuple[type, type], Any] = {}

    def register_chain(self, interface: type, provider_classes: list[type]) -> None:
        """Register or replace a provider chain for an interface."""
        self._chains[interface] = provider_classes

    def get_provider_chain(self, interface: type) -> list[type]:
        """Return the provider classes implementing an interface, in priority order."""
        return self._chains.get(interface, [])

    async def close(self) -> None:
        """Close all provider instances."""
        for instance in set(self._instances.values()):
            close_method = getattr(instance, "close", None)
            if close_method:
                await close_method()
        self._instances.clear()


class ProviderFactory:
    """
    Creates and resolves providers with automatic fallback.

    Usage:
        factory = ProviderFactory()

        # Get the primary market-data provider
        provider = await factory.get(MarketDataProvider)

        # Resolve a call across the provider chain (section 60):
        # tries Massive, falls back to FMP, then Finnhub.
        result = await factory.execute(MarketDataProvider, "get_quote", "AAPL")
    """

    def __init__(self, registry: ProviderRegistry | None = None):
        self.registry = registry or ProviderRegistry()
        self._fallback_counts: dict[tuple[type, type], int] = {}

    async def get(self, interface: type) -> Any:
        """Return the primary provider instance for an interface."""
        chain = self.registry.get_provider_chain(interface)
        if not chain:
            raise ProviderError("factory", f"No provider registered for {interface.__name__}")

        provider_cls = chain[0]
        return self._get_instance(interface, provider_cls)

    def _get_instance(self, interface: type, provider_cls: type) -> Any:
        """Get-or-create a provider instance for an interface.capability."""
        key = (interface, provider_cls)
        if key not in self.registry._instances:
            # Instantiate with no args — providers read API keys from settings
            instance = provider_cls()
            self.registry._instances[key] = instance
            logger.info("Created provider instance: %s for %s", provider_cls.__name__, interface.__name__)
        return self.registry._instances[key]

    async def execute(
        self,
        interface: type,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a method across the provider chain with automatic failover.

        Tries each provider in priority order. If the primary fails, falls
        back to the next provider (Section 60) and records the fallback.

        Args:
            interface: The capability interface (e.g. MarketDataProvider)
            method_name: Method to call (e.g. "get_quote", "get_historical_prices")
            *args, **kwargs: Passed to the provider method

        Returns:
            The result from the first successful provider.

        Raises:
            ProviderError: If all providers in the chain fail.
        """
        # Check for method-specific fallback chain (issue #8)
        method_key = (interface, method_name)
        if method_key in METHOD_FALLBACK_CHAINS:
            chain = METHOD_FALLBACK_CHAINS[method_key]
        else:
            chain = self.registry.get_provider_chain(interface)

        if not chain:
            raise ProviderError("factory", f"No provider registered for {interface.__name__}")

        last_error: Exception | None = None
        used_fallback = False

        for idx, provider_cls in enumerate(chain):
            provider = self._get_instance(interface, provider_cls)

            # Skip providers that don't implement the method
            method = getattr(provider, method_name, None)
            if method is None or not callable(method):
                continue

            try:
                result = await method(*args, **kwargs)

                # Record fallback use for confidence adjustment (Section 60)
                if idx > 0:
                    self._record_fallback(interface, provider_cls)
                    logger.warning(
                        "Used fallback provider %s for %s.%s",
                        provider_cls.__name__,
                        interface.__name__,
                        method_name,
                    )

                # Attach provider info to dict results
                if isinstance(result, dict):
                    result.setdefault("_provider", provider.provider_name)

                return result

            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "Provider %s failed for %s.%s: %s — trying next provider",
                    provider_cls.__name__,
                    interface.__name__,
                    method_name,
                    exc,
                )

        raise ProviderError(
            "factory",
            f"All providers failed for {interface.__name__}.{method_name}: {last_error}",
        )

    def _record_fallback(self, interface: type, provider_cls: type) -> None:
        """Record fallback use for observability / confidence scoring."""
        key = (interface, provider_cls)
        self._fallback_counts[key] = self._fallback_counts.get(key, 0) + 1

    def get_fallback_stats(self) -> dict[str, int]:
        """Return fallback usage statistics for observability."""
        return {
            f"{interface.__name__}→{cls.__name__}": count
            for (interface, cls), count in self._fallback_counts.items()
        }

    def was_fallback_used(self) -> bool:
        """Whether any fallback provider was used (for confidence adjustment)."""
        return bool(self._fallback_counts)


# Module-level singleton factory
_default_factory = ProviderFactory()


def get_provider_factory() -> ProviderFactory:
    """Return the global provider factory instance."""
    return _default_factory


async def get_provider(interface: type) -> Any:
    """Get the primary provider for an interface (dependency-friendly)."""
    return await _default_factory.get(interface)


async def execute_provider(interface: type, method: str, *args: Any, **kwargs: Any) -> Any:
    """Execute a provider method with automatic fallback."""
    return await _default_factory.execute(interface, method, *args, **kwargs)