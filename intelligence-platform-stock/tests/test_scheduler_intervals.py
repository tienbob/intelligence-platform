"""Scheduler cadences must be sourced from StockConfig (improvement plan I3).

Regression guard for the config-drift finding: manifest.py previously
hardcoded intervals (5/10/15/60/1440) while the .env keys claimed otherwise,
so operator edits silently did nothing. These tests fail if the wiring is
removed or a cadence is misconfigured.
"""

from types import SimpleNamespace

import pytest

from app.domains.stock import manifest
from app.domains.stock.config import get_stock_config


def _tasks():
    return manifest.DOMAIN.get_intelligence_tasks()


def test_task_names_are_unique():
    names = [t.name for t in _tasks()]
    assert len(names) == len(set(names))


def test_all_intervals_positive():
    assert all(t.interval_minutes > 0 for t in _tasks())


def test_intervals_match_stock_config():
    """Wired keys must mirror StockConfig — hours fields are × 60."""
    cfg = get_stock_config()
    by_name = {t.name: t.interval_minutes for t in _tasks()}
    assert by_name["Update market data"] == cfg.MARKET_DATA_UPDATE_INTERVAL_MIN
    assert by_name["Process news"] == cfg.NEWS_PROCESSING_INTERVAL_MIN
    assert by_name["Detect anomalies"] == cfg.ANOMALY_DETECTION_INTERVAL_MIN
    assert by_name["Analyze events"] == cfg.EVENT_ANALYSIS_INTERVAL_HR * 60
    assert by_name["Recalculate scores"] == cfg.SCORE_RECALCULATION_INTERVAL_HR * 60
    assert by_name["Ingest fundamentals"] == cfg.FUNDAMENTALS_UPDATE_INTERVAL_HR * 60


def test_non_positive_interval_fails_loudly(monkeypatch):
    """A misconfigured key must abort task registration, not silently skip."""
    bad = SimpleNamespace(
        MARKET_DATA_UPDATE_INTERVAL_MIN=0,
        NEWS_PROCESSING_INTERVAL_MIN=10,
        ANOMALY_DETECTION_INTERVAL_MIN=15,
        EVENT_ANALYSIS_INTERVAL_HR=1,
        FUNDAMENTALS_UPDATE_INTERVAL_HR=24,
        SCORE_RECALCULATION_INTERVAL_HR=24,
    )
    # The manifest imports get_stock_config at call time, so patching the
    # source module attribute is seen by the next call.
    monkeypatch.setattr(
        "app.domains.stock.config.get_stock_config", lambda: bad
    )
    with pytest.raises(ValueError, match="Non-positive"):
        manifest.DOMAIN.get_intelligence_tasks()
