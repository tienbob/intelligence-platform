"""
FastAPI dependencies for the provider factory.

Allows the API layer to request a provider capability (interface) without
hard-coding a specific provider implementation.
"""

from __future__ import annotations

from typing import TypeVar

from app.domains.stock.providers import get_provider, get_provider_factory

T = TypeVar("T")


async def get_provider_dep():
    """
    FastAPI dependency that yields the provider factory.

    Usage:
        @router.get("/stocks/{ticker}")
        async def get_quote(ticker: str, factory: ProviderFactory = Depends(get_provider_factory_dep)):
            provider = await factory.get(MarketDataProvider)
            return await provider.get_quote(ticker)
    """
    return get_provider_factory()