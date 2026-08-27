"""
SQLAlchemy ORM models.

Layers (Section 7):
    RAW → CANONICAL → DERIVED → AI
"""

from app.domains.stock.models.alert import Alert
from app.domains.stock.models.backtest import (
    BacktestAIEvaluation,
    BacktestBenchmark,
    BacktestResult,
    BacktestRun,
    BacktestScoreEvaluation,
    BacktestSnapshot,
    BacktestTrade,
)
from app.domains.stock.models.analysis import (
    Analysis,
    AnalysisSource,
    AnomalyScore,
    Embedding,
    InvestmentScore,
    RiskMetric,
    TechnicalIndicator,
)
from app.domains.stock.models.company import Company
from app.domains.stock.models.event import EventPriceCorrelation, MarketEvent
from app.domains.stock.models.financial import FinancialMetric, FinancialStatement
from app.domains.stock.models.macro import EconomicIndicator
from app.domains.stock.models.news import CompanyNews, News
from app.domains.stock.models.raw import RawMacroData, RawMarketData, RawNews, RawSecFiling
from app.domains.stock.models.stock_price import StockPrice

__all__ = [
    # Canonical
    "Company",
    "StockPrice",
    "FinancialStatement",
    "FinancialMetric",
    "News",
    "CompanyNews",
    "MarketEvent",
    "EventPriceCorrelation",
    "EconomicIndicator",
    # Derived
    "TechnicalIndicator",
    "AnomalyScore",
    "RiskMetric",
    # AI
    "Embedding",
    "Analysis",
    "InvestmentScore",
    "AnalysisSource",
    # Raw
    "RawMarketData",
    "RawSecFiling",
    "RawNews",
    "RawMacroData",
    # Alerts
    "Alert",
    # Backtesting (Phase 9)
    "BacktestRun",
    "BacktestSnapshot",
    "BacktestResult",
    "BacktestTrade",
    "BacktestBenchmark",
    "BacktestScoreEvaluation",
    "BacktestAIEvaluation",
]