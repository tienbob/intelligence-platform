import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.domains.stock.ingestion.market import MarketDataIngestion
from app.domains.stock.providers.base import ProviderError
from app.domains.stock.providers.massive import MassiveProvider
from app.domains.stock.providers.fmp import FMPProvider


def test_empty_connection_error_preserves_tls_cause():
    async def check():
        provider = MassiveProvider(api_key="test")
        error = httpx.ConnectError("")
        error.__cause__ = OSError("TLS handshake failed")
        provider._get_client = AsyncMock(
            return_value=type("Client", (), {"request": AsyncMock(side_effect=error)})()
        )
        with pytest.raises(ProviderError) as caught:
            await provider._request("GET", "/test", max_retries=0, use_cache=False)
        assert "ConnectError" in str(caught.value)
        assert "TLS handshake failed" in str(caught.value)
        assert provider.base_url in str(caught.value)

    asyncio.run(check())


def test_connection_failure_uses_configured_fallback():
    async def check():
        primary = MassiveProvider(api_key="test")
        fallback = FMPProvider(api_key="test")
        primary.get_historical_prices = AsyncMock(
            side_effect=ProviderError("massive", "TLS handshake failed")
        )
        fallback.get_historical_prices = AsyncMock(return_value=[{"close": 100}])
        market = MarketDataIngestion(None, provider=primary, fallback=fallback)
        now = datetime.now(timezone.utc)
        prices, actual = await market._get_historical_prices_with_fallback(
            "AAPL", now, now, "1d"
        )
        assert prices == [{"close": 100}]
        assert actual is fallback
        assert market.provider is primary
        fallback.get_historical_prices.assert_awaited_once_with("AAPL", now, now, "1d")

    asyncio.run(check())
