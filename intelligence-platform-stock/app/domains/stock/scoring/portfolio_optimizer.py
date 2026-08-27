"""
Portfolio optimizer (Sections 36–39).

The highest-scoring stocks should not automatically receive the highest allocations.

The optimizer considers:
    Investment Score, Risk, Volatility, Correlation,
    Sector Exposure, Position Size, Liquidity, Cash Reserve,
    User Risk Profile, Investment Horizon

Objective (Section 38):
    maximize:
        Expected Return
        - λ * Portfolio Risk
        - Concentration Penalty
        - Liquidity Penalty
    Subject to:
        sum(weights) <= 1
        weight_i <= max_position_weight
        sector_weight <= max_sector_weight
        cash >= minimum_cash

Accounting invariant (always holds):
    cash_reserve + allocated_capital + unallocated_capital = total_capital
    allocated_capital = sum(allocation.amount)
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize

from app.domains.stock.config import get_stock_config
from app.core.logging import get_logger
from app.domains.stock.schemas.portfolio import (
    PortfolioAllocation,
    PortfolioDataQuality,
    PortfolioMetrics,
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
    PortfolioRiskMetrics,
)

logger = get_logger(__name__)
settings = get_stock_config()


class PortfolioOptimizer:
    """
    Optimizes capital allocation across investment opportunities.

    Section 36: Good company ≠ automatically good portfolio allocation.
    """

    # Risk profile → risk aversion lambda
    RISK_AVERSION = {
        "conservative": 3.0,
        "moderate": 1.5,
        "aggressive": 0.5,
    }

    # Diversification component weights (Phase A v1)
    DIVERSIFICATION_WEIGHTS = {
        "holding_distribution": 0.40,
        "sector": 0.30,
        "holding_count": 0.20,
        "correlation": 0.10,
    }

    def __init__(self):
        pass

    def _build_covariance_matrix(
        self,
        volatilities: np.ndarray,
        historical_returns: list[list[float]] | None = None,
    ) -> np.ndarray:
        """
        Build a covariance matrix from volatilities and (optionally) historical returns.

        Phase 7: Correlation-aware covariance. When historical returns are
        provided, compute the empirical correlation matrix and scale by
        volatilities. Otherwise fall back to a diagonal (identity) matrix.
        """
        n = len(volatilities)
        if historical_returns is not None and len(historical_returns) >= 2:
            # historical_returns: list of n series, each with m observations
            arr = np.array(historical_returns, dtype=float)
            if arr.ndim == 2 and arr.shape[0] == n and arr.shape[1] >= 2:
                # Compute correlation matrix from returns
                corr = np.corrcoef(arr)
                # Handle NaN (e.g., constant series) — fall back to identity
                corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
                np.fill_diagonal(corr, 1.0)
                return np.outer(volatilities, volatilities) * corr

        # Fallback: diagonal correlation (identity)
        corr_matrix = np.eye(n)
        return np.outer(volatilities, volatilities) * corr_matrix

    @staticmethod
    def _diversification_score(
        weights: np.ndarray,
        sectors: list[str],
        correlation_available: bool = False,
    ) -> float:
        """
        Compute a transparent diversification score (0-100).

        Phase A v1 formula:
            40% Holding Distribution (Herfindahl on invested weights)
            30% Sector Diversification
            20% Holding Count
            10% Correlation Adjustment (only if correlation data is available)

        A single-asset portfolio scores low regardless of how small the
        position is relative to total cash — diversification is measured on
        the *invested* allocation, not the cash buffer.
        """
        # Only consider invested positions (weight > 0)
        invested_mask = weights > 0
        invested_weights = weights[invested_mask]
        invested_sectors = [s for s, m in zip(sectors, invested_mask) if m]

        if len(invested_weights) == 0:
            return 0.0

        # Normalize invested weights to sum to 1 (diversification is about
        # the invested allocation, not the cash buffer).
        total = invested_weights.sum()
        if total <= 0:
            return 0.0
        norm_weights = invested_weights / total

        # 1. Holding distribution (Herfindahl inverse): 1 - sum(w^2)
        #    Single asset -> 0, many equal assets -> high.
        herfindahl = float(np.sum(norm_weights ** 2))
        holding_dist = 1.0 - herfindahl  # 0..1

        # 2. Sector diversification: 1 - sum(sector_weight^2)
        sector_weights: dict[str, float] = {}
        for sector, w in zip(invested_sectors, norm_weights):
            sector_weights[sector] = sector_weights.get(sector, 0.0) + w
        sector_conc = sum(w ** 2 for w in sector_weights.values())
        sector_div = 1.0 - sector_conc  # 0..1

        # 3. Holding count: scale 1..10 holdings to 0..1
        count = len(invested_weights)
        count_score = min(1.0, count / 10.0)

        # 4. Correlation adjustment (only if available)
        if correlation_available:
            # Placeholder: if correlation data were available, penalize high
            # average pairwise correlation. For now, neutral (0.5).
            corr_score = 0.5
        else:
            # Not available — normalize the remaining components instead.
            corr_score = None

        # Combine
        weights_map = PortfolioOptimizer.DIVERSIFICATION_WEIGHTS
        if corr_score is None:
            # Renormalize the available components to sum to 1.0
            available_weight = (
                weights_map["holding_distribution"]
                + weights_map["sector"]
                + weights_map["holding_count"]
            )
            score = (
                weights_map["holding_distribution"] * holding_dist
                + weights_map["sector"] * sector_div
                + weights_map["holding_count"] * count_score
            ) / available_weight
        else:
            score = (
                weights_map["holding_distribution"] * holding_dist
                + weights_map["sector"] * sector_div
                + weights_map["holding_count"] * count_score
                + weights_map["correlation"] * corr_score
            )

        return round(max(0.0, min(100.0, score * 100.0)), 2)

    def optimize(
        self,
        opportunities: list[dict[str, Any]],
        request: PortfolioOptimizeRequest,
        historical_returns: list[list[float]] | None = None,
    ) -> PortfolioOptimizeResponse:
        """
        Optimize portfolio allocation.

        Args:
            opportunities: List of opportunities with score, risk_score, volatility, sector
            request: Optimization parameters
            historical_returns: Optional list of per-ticker return series for
                correlation-aware covariance (Phase 7).
        """
        # Deduplicate opportunities by ticker (defensive). Some callers may pass
        # duplicate tickers if they don't dedupe score rows; without this the
        # optimizer would emit duplicate allocation rows for the same ticker.
        seen: set[str] = set()
        unique_opportunities: list[dict[str, Any]] = []
        for opp in opportunities:
            ticker = (opp.get("ticker") or "").upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                unique_opportunities.append(opp)
        opportunities = unique_opportunities

        if not opportunities:
            return PortfolioOptimizeResponse(
                capital=request.capital,
                cash_reserve=request.cash_reserve,
                investable_capital=request.capital - request.cash_reserve,
                allocated_capital=0.0,
                unallocated_capital=request.capital - request.cash_reserve,
                allocation=[],
                portfolio=PortfolioMetrics(
                    weighted_investment_score=0.0,
                    diversification_score=0.0,
                    risk=PortfolioRiskMetrics(),
                    data_quality=PortfolioDataQuality(
                        risk_metrics_available=False,
                        reason="no opportunities available",
                    ),
                ),
                explanation="No opportunities available for allocation.",
            )

        n = len(opportunities)
        investable = request.capital - request.cash_reserve

        # Extract scores and risks
        scores = np.array([opp.get("score", 50) for opp in opportunities])
        risks = np.array([opp.get("risk_score", 50) for opp in opportunities])
        volatilities = np.array([opp.get("volatility", 0.25) for opp in opportunities])
        sectors = [opp.get("sector", "Unknown") for opp in opportunities]
        tickers = [opp.get("ticker", f"UNK_{i}") for i, opp in enumerate(opportunities)]

        correlation_available = historical_returns is not None and len(historical_returns) >= 2

        # Score-based allocation: higher score + lower risk → higher weight.
        # Investment scores are ordinal rankings, not expected-return forecasts.
        # We allocate proportionally to (score / risk) rather than feeding
        # fake expected returns into a mean-variance optimizer.
        # Risk aversion from user profile scales the risk penalty.
        lambda_risk = self.RISK_AVERSION.get(request.risk_profile, 1.5)
        attractiveness = scores / (1.0 + lambda_risk * risks / 100.0)
        # Floor at zero so negative attractiveness doesn't produce negative weights
        attractiveness = np.maximum(attractiveness, 0.0)

        total_attr = attractiveness.sum()
        if total_attr <= 0:
            weights = np.zeros(n)
        else:
            weights = attractiveness / total_attr

        # Apply position-size cap
        weights = np.minimum(weights, request.max_position_weight)

        # Apply sector limits
        weights = self._apply_sector_limits(weights, sectors, request.max_sector_weight)

        # Do NOT renormalize to sum=1.0. The inequality constraint
        # (sum(weights) <= 1) intentionally allows unallocated cash when
        # n * max_position_weight < 1.0. Renormalizing would violate the
        # max_position_weight bounds and defeat the cash-reserve intent.
        # Weights are already within [0, max_position_weight] and sum <= 1.

        # Build allocation with explicit weight semantics
        allocation = []
        for i in range(n):
            if weights[i] <= 0.001:
                continue
            amount = float(weights[i] * investable)
            allocation.append(
                PortfolioAllocation(
                    ticker=tickers[i],
                    amount=amount,
                    investable_weight=float(weights[i]),
                    portfolio_weight=float(amount / request.capital) if request.capital else 0.0,
                )
            )

        # Sort by investable weight descending
        allocation.sort(key=lambda a: a.investable_weight, reverse=True)

        # Accounting invariant
        allocated_capital = sum(a.amount for a in allocation)
        unallocated_capital = investable - allocated_capital

        # Portfolio metrics
        # Build covariance for risk calculation (diagonal fallback since we
        # no longer run a mean-variance optimizer that requires it).
        cov_matrix = self._build_covariance_matrix(volatilities, historical_returns)
        portfolio_risk = float(np.sqrt(weights @ cov_matrix @ weights))
        # Volatility = annualized std of the invested portfolio (approx from cov)
        volatility = portfolio_risk
        # Max drawdown / beta / sharpe require historical returns data.
        # Return None (not 0.0) when unavailable — 0.0 is a fake signal.
        max_drawdown = None
        beta = None
        sharpe_ratio = None
        risk_metrics_available = False
        risk_reason = "insufficient historical data for risk calculations"

        # weighted_investment_score = weighted average of allocated securities'
        # scores (by investable weight), distinct from any single security's score.
        weighted_investment_score = float(np.dot(weights, scores))

        # Diversification (Phase A v1)
        diversification = self._diversification_score(
            weights, sectors, correlation_available=correlation_available
        )

        # Determine unallocated reason
        unallocated_reason = "unknown"
        if unallocated_capital > 0:
            if len(allocation) == 0:
                unallocated_reason = "no qualifying investment opportunities"
            elif len(allocation) < len(opportunities):
                unallocated_reason = "position/sector limits prevent full deployment"
            else:
                unallocated_reason = "position limits prevent full deployment"

        # Generate explanation
        explanation = self._generate_explanation(
            allocation,
            request,
            portfolio_risk,
            diversification,
            weighted_investment_score,
            allocated_capital,
            unallocated_capital,
        )

        return PortfolioOptimizeResponse(
            capital=request.capital,
            cash_reserve=request.cash_reserve,
            investable_capital=investable,
            allocated_capital=allocated_capital,
            unallocated_capital=unallocated_capital,
            unallocated_reason=unallocated_reason,
            allocation=allocation,
            portfolio=PortfolioMetrics(
                weighted_investment_score=weighted_investment_score,
                diversification_score=diversification,
                risk=PortfolioRiskMetrics(
                    expected_risk=portfolio_risk,
                    volatility=volatility,
                    max_drawdown=max_drawdown,
                    beta=beta,
                    sharpe_ratio=sharpe_ratio,
                ),
                data_quality=PortfolioDataQuality(
                    risk_metrics_available=risk_metrics_available,
                    reason=risk_reason,
                ),
            ),
            explanation=explanation,
        )

    @staticmethod
    def _apply_sector_limits(
        weights: np.ndarray, sectors: list[str], max_sector_weight: float
    ) -> np.ndarray:
        """Apply sector concentration limits."""
        unique_sectors = set(sectors)
        for sector in unique_sectors:
            sector_mask = np.array([s == sector for s in sectors])
            sector_weight = np.sum(weights[sector_mask])
            if sector_weight > max_sector_weight:
                scale = max_sector_weight / sector_weight
                weights[sector_mask] *= scale
        return weights

    @staticmethod
    def _generate_explanation(
        allocation: list[PortfolioAllocation],
        request: PortfolioOptimizeRequest,
        risk: float,
        diversification: float,
        fit_score: float,
        allocated_capital: float,
        unallocated_capital: float,
    ) -> str:
        """Generate a human-readable explanation of the allocation."""
        lines = [
            f"Portfolio optimized for {request.risk_profile} risk profile.",
            f"Investment horizon: {request.investment_horizon}.",
            f"Capital: ${request.capital:,.0f} (Cash reserve: ${request.cash_reserve:,.0f}).",
            f"Investable capital: ${request.capital - request.cash_reserve:,.0f}.",
            f"Allocated capital: ${allocated_capital:,.0f}.",
            f"Unallocated capital: ${unallocated_capital:,.0f}.",
            f"Portfolio expected risk: {risk:.1%}",
            f"Diversification score: {diversification:.0f}/100",
            f"Portfolio fit score: {fit_score:.1f}/100",
            "",
            "Top allocations:",
        ]
        for a in allocation[:5]:
            lines.append(
                f"  {a.ticker}: {a.investable_weight:.1%} of investable "
                f"({a.portfolio_weight:.1%} of total, ${a.amount:,.0f})"
            )

        lines.extend([
            "",
            "Constraints applied:",
            f"  Max position weight: {request.max_position_weight:.0%}",
            f"  Max sector weight: {request.max_sector_weight:.0%}",
        ])

        return "\n".join(lines)