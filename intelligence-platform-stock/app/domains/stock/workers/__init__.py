"""
Stock domain background workers.

Each worker module exposes async functions that are called by the scheduler.
"""

from app.domains.stock.workers.analysis_worker import recalculate_scores
from app.domains.stock.workers.analysis_worker import update_derived_metrics
from app.domains.stock.workers.backtest_worker import create_daily_snapshot
from app.domains.stock.workers.backtest_worker import run_scheduled_backtests
from app.domains.stock.workers.event_worker import analyze_events
from app.domains.stock.workers.event_worker import detect_anomalies
from app.domains.stock.workers.ingestion_worker import ingest_fundamentals
from app.domains.stock.workers.ingestion_worker import ingest_macro_indicators
from app.domains.stock.workers.ingestion_worker import ingest_sec_filings
from app.domains.stock.workers.embedding_worker import ingest_rag_embeddings
from app.domains.stock.workers.news_worker import process_news
from app.domains.stock.workers.market_worker import update_market_data

__all__ = [
    "analyze_events",
    "create_daily_snapshot",
    "detect_anomalies",
    "ingest_fundamentals",
    "ingest_macro_indicators",
    "ingest_rag_embeddings",
    "ingest_sec_filings",
    "process_news",
    "recalculate_scores",
    "run_scheduled_backtests",
    "update_derived_metrics",
    "update_market_data",
]