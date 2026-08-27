"""Regression tests for score-evaluation forward-return horizons."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.domains.stock.scoring.backtest import _forward_return_at_horizon


def test_unelapsed_horizons_return_none_instead_of_same_stale_return():
    score_date = datetime(2026, 8, 1, tzinfo=timezone.utc)
    timestamps = [score_date, score_date + timedelta(days=20)]
    prices = [SimpleNamespace(close=100.0), SimpleNamespace(close=110.0)]

    returns = [
        _forward_return_at_horizon(
            timestamps, prices, 0, score_date + timedelta(days=days)
        )
        for days in (30, 91, 182)
    ]

    assert returns == [None, None, None]


def test_elapsed_horizon_uses_price_near_target():
    score_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [score_date, score_date + timedelta(days=29)]
    prices = [SimpleNamespace(close=100.0), SimpleNamespace(close=112.0)]

    result = _forward_return_at_horizon(
        timestamps, prices, 0, score_date + timedelta(days=30)
    )

    assert result == 0.12
