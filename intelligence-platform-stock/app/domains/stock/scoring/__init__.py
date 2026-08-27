"""
Stock domain scoring subpackage.

Exposes the ScoringStrategy protocol adapter (used by the core intelligence
pipeline via ``DomainModule.get_scoring_strategy()``) alongside the
domain-specific scoring engines (investment scoring, backtesting, risk, ...).
"""

from app.domains.stock.scoring.scoring_strategy import InvestmentScoringStrategy

__all__ = [
    "InvestmentScoringStrategy",
]
