"""
Technical analysis engine (Section 19).

Deterministic calculation of technical indicators using pandas/numpy.
The LLM must NOT calculate these values itself.

Indicators:
    SMA, EMA, RSI, MACD, ATR, Bollinger Bands, VWAP,
    Volatility, Momentum, Drawdown, Volume Anomaly
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.stock.models.analysis import TechnicalIndicator
from app.domains.stock.models.stock_price import StockPrice
from app.core.database import commit_session

logger = get_logger(__name__)


class TechnicalAnalysisEngine:
    """
    Calculates technical indicators from historical price data.

    All calculations are deterministic — no LLM involvement.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _load_price_dataframe(
        self, company_id: int, days: int = 365
    ) -> pd.DataFrame:
        """Load the most recent ``days`` of historical prices into a DataFrame.

        Prices are returned in ascending chronological order so that
        ``tail(window)`` in the indicator helpers refers to the most recent
        observations.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id == company_id)
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp >= since)
            .order_by(StockPrice.timestamp)
        )
        prices = result.scalars().all()

        if not prices:
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "timestamp": p.timestamp,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "adjusted_close": p.adjusted_close or p.close,
                    "volume": p.volume,
                }
                for p in prices
            ]
        )
        df.set_index("timestamp", inplace=True)
        return df

    # ── Technical indicators ──────────────────────────────────────

    @staticmethod
    def sma(data: pd.Series, window: int) -> float | None:
        """Simple Moving Average."""
        if len(data) < window:
            return None
        return float(data.tail(window).mean())

    @staticmethod
    def ema(data: pd.Series, window: int) -> float | None:
        """Exponential Moving Average."""
        if len(data) < window:
            return None
        return float(data.ewm(span=window, adjust=False).mean().iloc[-1])

    @staticmethod
    def rsi(data: pd.Series, window: int = 14) -> float | None:
        """Relative Strength Index."""
        if len(data) < window + 1:
            return None
        delta = data.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1 / window, min_periods=window).mean()
        avg_loss = loss.ewm(alpha=1 / window, min_periods=window).mean()
        rs = avg_gain / avg_loss
        rsi_val = 100 - (100 / (1 + rs))
        return float(rsi_val.iloc[-1])

    @staticmethod
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float | None, float | None]:
        """MACD line and signal line."""
        if len(data) < slow:
            return None, None
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> float | None:
        """Average True Range."""
        if len(close) < window + 1:
            return None
        tr = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return float(tr.rolling(window=window).mean().iloc[-1])

    @staticmethod
    def bollinger_bands(data: pd.Series, window: int = 20, num_std: float = 2.0) -> tuple[float | None, float | None]:
        """Bollinger Bands (upper, lower)."""
        if len(data) < window:
            return None, None
        sma = data.rolling(window=window).mean()
        std = data.rolling(window=window).std()
        upper = sma + num_std * std
        lower = sma - num_std * std
        return float(upper.iloc[-1]), float(lower.iloc[-1])

    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> float | None:
        """Volume Weighted Average Price."""
        if len(close) == 0 or volume.sum() == 0:
            return None
        typical_price = (high + low + close) / 3
        return float((typical_price * volume).sum() / volume.sum())

    @staticmethod
    def volatility(data: pd.Series, window: int = 30) -> float | None:
        """Annualized volatility (30-day)."""
        if len(data) < window + 1:
            return None
        returns = data.pct_change().dropna()
        if len(returns) < window:
            return None
        daily_vol = returns.tail(window).std()
        return float(daily_vol * np.sqrt(252))

    @staticmethod
    def momentum(data: pd.Series, window: int = 10) -> float | None:
        """Price momentum (rate of change over window)."""
        if len(data) < window + 1:
            return None
        return float((data.iloc[-1] - data.iloc[-1 - window]) / data.iloc[-1 - window] * 100)

    @staticmethod
    def max_drawdown(data: pd.Series) -> float | None:
        """Maximum drawdown over the period (positive magnitude, e.g. 0.18 for 18%)."""
        if len(data) < 2:
            return None
        running_max = data.cummax()
        drawdown = (data - running_max) / running_max
        return float(abs(drawdown.min()))

    @staticmethod
    def volume_anomaly(volume: pd.Series, window: int = 20) -> float | None:
        """Volume anomaly score (current vs average)."""
        if len(volume) < window + 1:
            return None
        avg_vol = volume.tail(window).mean()
        current_vol = volume.iloc[-1]
        if avg_vol == 0:
            return None
        return float((current_vol - avg_vol) / avg_vol * 100)

    # ── Full calculation ──────────────────────────────────────────

    async def calculate_indicators(self, company_id: int) -> TechnicalIndicator | None:
        """
        Calculate all technical indicators for a company and store in DB.

        Returns the TechnicalIndicator record, or None if insufficient data.
        """
        df = await self._load_price_dataframe(company_id)
        if df.empty or len(df) < 20:
            logger.warning("Insufficient price data for company_id=%d", company_id)
            return None

        close = df["adjusted_close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        macd_line, macd_signal = self.macd(close)
        bb_upper, bb_lower = self.bollinger_bands(close)

        indicator = TechnicalIndicator(
            company_id=company_id,
            timestamp=datetime.now(timezone.utc),
            sma_20=self.sma(close, 20),
            sma_50=self.sma(close, 50),
            sma_200=self.sma(close, 200),
            ema_20=self.ema(close, 20),
            rsi_14=self.rsi(close, 14),
            macd=macd_line,
            macd_signal=macd_signal,
            atr=self.atr(high, low, close),
            bollinger_upper=bb_upper,
            bollinger_lower=bb_lower,
            vwap=self.vwap(high, low, close, volume),
            volatility_30d=self.volatility(close, 30),
            momentum=self.momentum(close, 10),
            drawdown=self.max_drawdown(close),
        )

        self.session.add(indicator)
        await commit_session(self.session)
        logger.info("Calculated technical indicators for company_id=%d", company_id)
        return indicator

    async def get_latest_indicators(self, company_id: int) -> TechnicalIndicator | None:
        """Get the most recent technical indicators for a company."""
        result = await self.session.execute(
            select(TechnicalIndicator)
            .where(TechnicalIndicator.company_id == company_id)
            .order_by(desc(TechnicalIndicator.timestamp))
            .limit(1)
        )
        return result.scalar_one_or_none()