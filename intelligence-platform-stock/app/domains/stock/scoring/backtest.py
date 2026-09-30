"""
Backtesting engine (Section 162, Phase 9).

Implements:
- Point-in-time dataset generation and historical snapshot support
- Strategy, score, and portfolio backtesting validation
- Benchmark comparisons and AI evaluation

No production investment strategy should be trusted before this phase.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.domains.stock.config import get_stock_config
from app.core.database import commit_session
from app.core.logging import get_logger
from app.domains.stock.models.analysis import Analysis, InvestmentScore
from app.domains.stock.models.backtest import (
    BacktestAIEvaluation,
    BacktestBenchmark,
    BacktestResult,
    BacktestRun,
    BacktestScoreEvaluation,
    BacktestSnapshot,
    BacktestTrade,
)
from app.domains.stock.models.company import Company
from app.domains.stock.models.stock_price import StockPrice

logger = get_logger(__name__)
settings = get_stock_config()

# Supported strategies
SUPPORTED_STRATEGIES = {
    "score_threshold",
    "momentum",
    "equal_weight",
    "portfolio_optimizer",
}

# Forward-return windows for score/AI evaluation, in *calendar* days (these
# are consumed via ``timedelta(days=...)`` against timestamp columns in
# ``_evaluate_scores`` / ``_evaluate_ai``). 30/91/182 approximate 1/3/6
# calendar months. Do NOT confuse these with the *trading-day* lookback
# windows used by the momentum strategy below (60/126/252), which index
# directly into a price DataFrame rather than being added to a timestamp.
FORWARD_RETURN_WINDOWS = {
    "1m": 30,
    "3m": 91,
    "6m": 182,
}

# Maximum allowed gap (in calendar days) between the target forward-return
# date and the last available price.  If the gap exceeds this tolerance the
# forward horizon has not actually been reached yet (common when the run date
# is recent and the future price data hasn't been ingested), so the forward
# return is treated as unknown (None) rather than silently using a stale "last
# available" price.
FORWARD_RETURN_TOLERANCE = timedelta(days=5)


def _forward_return_at_horizon(
    ts_list: list[datetime],
    px_list: Any,
    base_idx: int,
    target_date: datetime,
) -> float | None:
    """Forward return of the close nearest ``target_date`` vs the base close.

    Reports a value ONLY when the horizon has actually been reached: the last
    available price at-or-before ``target_date`` must exist (not be older than
    the base entry) and sit within ``FORWARD_RETURN_TOLERANCE`` of the target.
    Otherwise the horizon hasn't elapsed (or prices are stale), so ``None`` is
    returned instead of silently reporting a stale "last available" price as
    realized performance. This is what keeps 1m/3m/6m forward returns from
    collapsing to identical stale values for recent score dates.

    Args:
        ts_list: Ascending price timestamps for one company.
        px_list: Price rows parallel to ``ts_list`` (needs ``.close``).
        base_idx: Index of the base price (first close at/after score date).
        target_date: Score timestamp + horizon window in calendar days.
    """
    last_idx = bisect_right(ts_list, target_date) - 1
    if last_idx < base_idx:
        return None
    if (target_date - ts_list[last_idx]) > FORWARD_RETURN_TOLERANCE:
        return None
    base_price = px_list[base_idx].close
    if base_price <= 0:
        return None
    return (px_list[last_idx].close - base_price) / base_price

# Default lookback (in trading days) used to estimate realized volatility
# for the portfolio-optimizer strategy when sizing positions.
_DEFAULT_VOLATILITY_LOOKBACK = 60


def _mark_to_market(
    cash: float,
    holdings: dict[str, float],
    price_data: dict[str, pd.DataFrame],
    date: Any,
    last_prices: dict[str, float],
) -> float:
    """
    Compute portfolio value on ``date``.

    If a held ticker has no price row on ``date`` (data gap, halt, etc.),
    fall back to the last observed price for that ticker instead of
    silently dropping the position's value for the day — dropping it
    would show up as a fake dip/jump in the equity curve and skew every
    downstream metric (volatility, Sharpe, drawdown) computed from it.
    """
    portfolio_value = cash
    for ticker, shares in holdings.items():
        df = price_data.get(ticker)
        price: float | None = None
        if df is not None and date in df.index:
            price = float(df.loc[date, "close"])
            last_prices[ticker] = price
        else:
            price = last_prices.get(ticker)
        if price is not None:
            portfolio_value += shares * price
    return portfolio_value


# Strategies whose trade decisions read investment-score history.
SCORE_DRIVEN_STRATEGIES = frozenset({"score_threshold", "portfolio_optimizer"})


def compute_snapshot_coverage(
    snapshot: BacktestSnapshot | None,
    strategy: str,
    benchmark_source: str = "live",
) -> dict[str, Any]:
    """Describe which DECISION inputs of a run are pinned vs read live (F12).

    Backtest snapshots capture prices (and benchmark prices) as of their
    ``as_of`` date plus the *latest* score per ticker — but NOT full score
    history or fundamentals/news/events. Score-driven strategies therefore
    resolve scores from live (date-bounded) tables even on a pinned run, and
    a benchmark ticker missing from the snapshot falls back to live tables.

    The report is stored on the run so the API/UI can say "partially pinned"
    instead of implying full reproducibility (audit F12). Evaluation phases
    (score/AI evaluation) deliberately read live data — they measure
    outcomes, they do not drive decisions.
    """
    if snapshot is None:
        live = ["prices", "benchmark"]
        if strategy in SCORE_DRIVEN_STRATEGIES:
            live.append("score_history")
        return {
            "mode": "unpinned",
            "snapshot_id": None,
            "snapshot_as_of": None,
            "pinned": [],
            "live": live,
        }

    pinned = ["prices"]
    live: list[str] = []
    if strategy in SCORE_DRIVEN_STRATEGIES:
        live.append("score_history")
    if benchmark_source == "snapshot":
        pinned.append("benchmark")
    elif benchmark_source == "live":
        live.append("benchmark")
    # benchmark_source == "none": no benchmark computed at all — neither list.

    return {
        "mode": "partially_pinned" if live else "pinned",
        "snapshot_id": snapshot.id,
        "snapshot_as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
        "pinned": pinned,
        "live": live,
    }


class BacktestEngine:
    """
    Implements Phase 9 backtesting features.

    Provides:
    - ``create_snapshot`` — build a point-in-time dataset snapshot
    - ``run_backtest`` — execute a strategy backtest
    - ``evaluate_scores`` — evaluate investment scores vs actual outcomes
    - ``evaluate_ai`` — evaluate AI analysis quality
    - ``compare_benchmark`` — compare strategy vs benchmark
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Point-in-time dataset generation ──────────────────────────

    async def create_snapshot(
        self,
        name: str,
        as_of: datetime,
        description: str | None = None,
        tickers: list[str] | None = None,
        created_by: str | None = None,
    ) -> BacktestSnapshot:
        """
        Build a point-in-time dataset snapshot (Section 162).

        Captures prices, scores, fundamentals, events, and news as of a
        specific date. This prevents look-ahead bias in backtesting.
        """
        # Resolve companies
        company_query = select(Company)
        if tickers:
            company_query = company_query.where(
                Company.ticker.in_([t.upper() for t in tickers])
            )
        companies_result = await self.session.execute(company_query)
        companies = companies_result.scalars().all()

        # Capture prices as of the snapshot date
        prices: dict[str, Any] = {}
        for company in companies:
            price_result = await self.session.execute(
                select(StockPrice)
                .where(StockPrice.company_id == company.id)
                .where(StockPrice.interval == "1d")
                .where(StockPrice.timestamp <= as_of)
                .order_by(StockPrice.timestamp)
            )
            price_rows = price_result.scalars().all()
            if price_rows:
                prices[company.ticker] = [
                    {
                        "timestamp": p.timestamp.isoformat(),
                        "close": p.close,
                        "volume": p.volume,
                    }
                    for p in price_rows
                ]

        # Capture scores as of the snapshot date
        scores: dict[str, Any] = {}
        for company in companies:
            score_result = await self.session.execute(
                select(InvestmentScore)
                .where(InvestmentScore.company_id == company.id)
                .where(InvestmentScore.timestamp <= as_of)
                .order_by(desc(InvestmentScore.timestamp))
                .limit(1)
            )
            score = score_result.scalar_one_or_none()
            if score:
                scores[company.ticker] = {
                    "timestamp": score.timestamp.isoformat(),
                    "overall_score": score.overall_score,
                    "recommendation": score.recommendation,
                    "scoring_model": score.scoring_model,
                    "scoring_version": score.scoring_version,
                }

        snapshot = BacktestSnapshot(
            name=name,
            as_of=as_of,
            description=description,
            prices=prices,
            scores=scores,
            source_data_version=f"snapshot_{as_of.strftime('%Y%m%d')}",
            created_by=created_by,
        )
        self.session.add(snapshot)
        await commit_session(self.session)
        logger.info("Created backtest snapshot '%s' as of %s", name, as_of)
        return snapshot

    async def _price_data_from_snapshot(
        self,
        snapshot: BacktestSnapshot,
        start_date: datetime,
        end_date: datetime,
        tickers: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Build the same ``{ticker: DataFrame}`` structure ``_load_price_data``
        returns, but sourced from a point-in-time snapshot instead of live
        tables, so a run pinned to ``snapshot_id`` only ever sees prices
        that were captured as of the snapshot's ``as_of`` date — no
        look-ahead bias on the price side.

        Note: ``BacktestSnapshot.scores`` only captures the *latest* score
        per ticker as of ``as_of`` (see ``create_snapshot``), not a full
        score history, so score-driven strategies (``score_threshold``,
        ``portfolio_optimizer``) still resolve scores via live queries
        even when a snapshot is supplied. Price data — which is what
        actually drives trade execution and mark-to-market — is fully
        snapshot-backed. Extending snapshots to capture score history is
        a separate follow-up, not something this fix silently papers over.
        """
        wanted = {t.upper() for t in tickers} if tickers else None
        price_data: dict[str, pd.DataFrame] = {}

        for ticker, rows in (snapshot.prices or {}).items():
            if wanted and ticker not in wanted:
                continue

            records = []
            for row in rows:
                ts = datetime.fromisoformat(row["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                lo, hi = start_date, end_date
                if lo.tzinfo is None:
                    lo = lo.replace(tzinfo=timezone.utc)
                if hi.tzinfo is None:
                    hi = hi.replace(tzinfo=timezone.utc)
                if ts < lo or ts > hi:
                    continue
                records.append(
                    {"date": ts, "close": row["close"], "volume": row.get("volume")}
                )

            if not records:
                continue

            df = pd.DataFrame(records)
            df.set_index("date", inplace=True)
            df.sort_index(inplace=True)
            price_data[ticker] = df

        return price_data

    # ── Strategy backtesting ──────────────────────────────────────

    async def run_backtest(
        self,
        name: str,
        strategy: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 100000.0,
        benchmark_ticker: str = "SPY",
        parameters: dict[str, Any] | None = None,
        tickers: list[str] | None = None,
        snapshot_id: int | None = None,
        existing_run: BacktestRun | None = None,
        user_id: int | None = None,
    ) -> BacktestRun:
        """
        Execute a strategy backtest (Section 162).

        Strategies:
        - ``score_threshold``: buy when investment score >= threshold
        - ``momentum``: buy top-N by momentum, rebalance periodically
        - ``equal_weight``: equal-weight all tracked companies
        - ``portfolio_optimizer``: use the portfolio optimizer for allocation

        If ``snapshot_id`` is provided, price data is sourced from that
        point-in-time snapshot instead of live tables (see
        ``_price_data_from_snapshot`` for what is and isn't snapshot-backed
        today).

        If ``existing_run`` is provided (e.g. by the scheduler worker picking
        up a ``queued`` row), it is executed in place — status transitions
        happen on that row — instead of creating a duplicate run record.
        """
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"Unsupported strategy: {strategy}")

        parameters = parameters or {}

        # Create the run record — or adopt the caller-supplied row (scheduler
        # queue processing) so queued runs are executed in place instead of
        # spawning a duplicate on every scheduler tick.
        if existing_run is not None:
            run = existing_run
            run.status = "running"
            run.error_message = None
            await self.session.flush()
        else:
            run = BacktestRun(
                name=name,
                strategy=strategy,
                status="running",
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                benchmark_ticker=benchmark_ticker,
                parameters=parameters,
                snapshot_id=snapshot_id,
                user_id=user_id,
                scoring_model=settings.SCORING_MODEL,
                scoring_version=settings.SCORING_VERSION,
            )
            self.session.add(run)
            await self.session.flush()

        run_id = run.id

        # Resolve the snapshot up front (if any) so a bad snapshot_id fails
        # the run the same way a missing price range does, rather than
        # silently falling back to live data.
        snapshot: BacktestSnapshot | None = None
        if snapshot_id is not None:
            snapshot = await self.get_snapshot(snapshot_id)
            if snapshot is None:
                run.status = "failed"
                run.error_message = f"Snapshot {snapshot_id} not found"
                await commit_session(self.session)
                logger.warning(
                    "Backtest run %d failed: snapshot %s not found",
                    run.id,
                    snapshot_id,
                )
                return run

        try:
            # Load price data for the backtest period — from the snapshot
            # when one was supplied, otherwise from live tables.
            if snapshot is not None:
                price_data = await self._price_data_from_snapshot(
                    snapshot, start_date, end_date, tickers
                )
            else:
                price_data = await self._load_price_data(
                    start_date, end_date, tickers
                )

            # Guard: fail fast if there's no price data to backtest against,
            # instead of silently completing with zero trades and a flat
            # equity curve (e.g. a date range outside the ingested history,
            # or outside what a snapshot captured).
            if not price_data or not any(len(df) > 0 for df in price_data.values()):
                run.status = "failed"
                run.error_message = (
                    f"No price data available for {start_date.date()}–{end_date.date()}"
                    + (f" (tickers: {', '.join(tickers)})" if tickers else "")
                    + (f" (snapshot: {snapshot_id})" if snapshot_id else "")
                )
                await commit_session(self.session)
                logger.warning("Backtest run %d failed: no price data in range", run.id)
                return run

            # Execute the strategy
            if strategy == "score_threshold":
                trades, equity_curve = await self._run_score_threshold(
                    run.id, price_data, start_date, end_date, initial_capital, parameters
                )
            elif strategy == "momentum":
                trades, equity_curve = await self._run_momentum(
                    run.id, price_data, start_date, end_date, initial_capital, parameters
                )
            elif strategy == "equal_weight":
                trades, equity_curve = await self._run_equal_weight(
                    run.id, price_data, start_date, end_date, initial_capital, parameters
                )
            elif strategy == "portfolio_optimizer":
                trades, equity_curve = await self._run_portfolio_optimizer(
                    run.id, price_data, start_date, end_date, initial_capital, parameters
                )
            else:
                raise ValueError(f"Unsupported strategy: {strategy}")

            # Persist the trades the strategy generated — the strategy
            # methods build BacktestTrade objects but don't add them to
            # the session themselves, so without this they're computed
            # into the performance stats but never actually stored.
            self.session.add_all(trades)

            # Compute performance metrics
            result = self._compute_performance(
                run.id, equity_curve, initial_capital, trades
            )
            self.session.add(result)

            # Benchmark comparison — sourced from the snapshot when the run
            # is snapshot-pinned, so the benchmark side doesn't retain
            # look-ahead access to live tables the strategy side was denied.
            benchmark, benchmark_source = await self._compare_benchmark(
                run.id, equity_curve, benchmark_ticker, start_date, end_date,
                snapshot=snapshot,
            )
            if benchmark:
                self.session.add(benchmark)

            # Record exactly which decision inputs were pinned vs read live
            # (audit F12). Snapshots capture prices/benchmark but NOT score
            # history, so score-driven strategies are honestly marked
            # "partially_pinned" instead of implying full reproducibility.
            run.snapshot_coverage = compute_snapshot_coverage(
                snapshot=snapshot,
                strategy=strategy,
                benchmark_source=benchmark_source,
            )

            # Score evaluation
            await self._evaluate_scores(run.id, start_date, end_date, tickers)

            # AI evaluation
            await self._evaluate_ai(run.id, start_date, end_date, tickers)

            run.status = "completed"
            await commit_session(self.session)
            logger.info("Backtest run %d completed: strategy=%s", run.id, strategy)
            return run

        except Exception as exc:
            # Discard partial trades/results and reset an aborted transaction
            # before recording failure. Queued runs already exist durably.
            await self.session.rollback()
            failed_run = await self.session.get(BacktestRun, run_id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                await commit_session(self.session)
            logger.exception("Backtest run %d failed", run_id)
            raise

    async def _load_price_data(
        self,
        start_date: datetime,
        end_date: datetime,
        tickers: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Load price data for all tracked companies in the period."""
        company_query = select(Company)
        if tickers:
            company_query = company_query.where(
                Company.ticker.in_([t.upper() for t in tickers])
            )
        companies_result = await self.session.execute(company_query)
        companies = companies_result.scalars().all()

        price_data: dict[str, pd.DataFrame] = {}
        for company in companies:
            price_result = await self.session.execute(
                select(StockPrice)
                .where(StockPrice.company_id == company.id)
                .where(StockPrice.interval == "1d")
                .where(StockPrice.timestamp >= start_date)
                .where(StockPrice.timestamp <= end_date)
                .order_by(StockPrice.timestamp)
            )
            price_rows = price_result.scalars().all()
            if not price_rows:
                logger.warning(
                    "Backtest: requested ticker %s has no daily price data "
                    "in %s–%s; skipping",
                    company.ticker, start_date, end_date,
                )
                continue

            df = pd.DataFrame(
                [
                    {
                        "date": p.timestamp,
                        "close": p.close,
                        "volume": p.volume,
                    }
                    for p in price_rows
                ]
            )
            df.set_index("date", inplace=True)
            price_data[company.ticker] = df

        return price_data

    async def _run_score_threshold(
        self,
        run_id: int,
        price_data: dict[str, pd.DataFrame],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        parameters: dict[str, Any],
    ) -> tuple[list[BacktestTrade], list[dict[str, Any]]]:
        """
        Score-threshold strategy: buy when investment score >= threshold.

        Rebalances monthly. Sells when score drops below threshold.
        """
        threshold = parameters.get("threshold", 70)
        rebalance_days = parameters.get("rebalance_days", 21)  # ~monthly

        # Load scores for the period
        score_result = await self.session.execute(
            select(InvestmentScore, Company)
            .join(Company, Company.id == InvestmentScore.company_id)
            .where(InvestmentScore.timestamp >= start_date)
            .where(InvestmentScore.timestamp <= end_date)
            .order_by(InvestmentScore.timestamp)
        )
        score_rows = score_result.all()

        # Group scores by ticker
        scores_by_ticker: dict[str, list[tuple[datetime, float]]] = {}
        for score, company in score_rows:
            if score.overall_score is not None:
                scores_by_ticker.setdefault(company.ticker, []).append(
                    (score.timestamp, score.overall_score)
                )

        trades: list[BacktestTrade] = []
        equity_curve: list[dict[str, Any]] = []
        cash = initial_capital
        holdings: dict[str, float] = {}  # ticker -> shares
        last_prices: dict[str, float] = {}

        # Iterate through trading days
        all_dates = sorted(
            set(
                date
                for df in price_data.values()
                for date in df.index
            )
        )

        for i, date in enumerate(all_dates):
            # Rebalance check
            if i % rebalance_days == 0:
                # Determine which tickers meet the threshold
                qualifying: list[str] = []
                for ticker, df in price_data.items():
                    if date not in df.index:
                        continue
                    # Find the latest score at or before this date
                    latest_score = None
                    for score_date, score_val in scores_by_ticker.get(ticker, []):
                        if score_date <= date:
                            latest_score = score_val
                        else:
                            break
                    if latest_score is not None and latest_score >= threshold:
                        qualifying.append(ticker)

                # Sell positions that no longer qualify
                for ticker in list(holdings.keys()):
                    if ticker not in qualifying and date in price_data.get(ticker, pd.DataFrame()).index:
                        price = price_data[ticker].loc[date, "close"]
                        shares = holdings.pop(ticker)
                        amount = shares * price
                        cash += amount
                        trades.append(BacktestTrade(
                            run_id=run_id,
                            ticker=ticker,
                            action="SELL",
                            trade_date=date,
                            price=float(price),
                            shares=float(shares),
                            amount=float(amount),
                            reason="Score below threshold",
                        ))

                # Buy qualifying positions with available cash
                if qualifying and cash > 0:
                    per_position = cash / len(qualifying)
                    for ticker in qualifying:
                        if date not in price_data[ticker].index:
                            continue
                        price = price_data[ticker].loc[date, "close"]
                        if price <= 0:
                            continue
                        shares = per_position / price
                        amount = shares * price
                        cash -= amount
                        holdings[ticker] = holdings.get(ticker, 0) + shares
                        trades.append(BacktestTrade(
                            run_id=run_id,
                            ticker=ticker,
                            action="BUY",
                            trade_date=date,
                            price=float(price),
                            shares=float(shares),
                            amount=float(amount),
                            reason=f"Score >= {threshold}",
                        ))

            # Mark to market
            portfolio_value = _mark_to_market(cash, holdings, price_data, date, last_prices)

            equity_curve.append({
                "date": date.isoformat(),
                "value": round(float(portfolio_value), 2),
            })

        # Liquidate remaining positions at end — dated with the actual last
        # bar for that ticker, not the nominal end_date (they can differ when
        # a ticker's history stops short of the period end).
        for ticker, shares in holdings.items():
            df = price_data.get(ticker)
            if df is not None and len(df) > 0:
                last_price = df["close"].iloc[-1]
                last_date = df.index[-1]
                amount = shares * last_price
                cash += amount
                trades.append(BacktestTrade(
                    run_id=run_id,
                    ticker=ticker,
                    action="SELL",
                    trade_date=last_date,
                    price=float(last_price),
                    shares=float(shares),
                    amount=float(amount),
                    reason="End of backtest",
                ))

        return trades, equity_curve

    async def _run_momentum(
        self,
        run_id: int,
        price_data: dict[str, pd.DataFrame],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        parameters: dict[str, Any],
    ) -> tuple[list[BacktestTrade], list[dict[str, Any]]]:
        """
        Momentum strategy: buy top-N by momentum, rebalance periodically.
        """
        top_n = parameters.get("top_n", 5)
        lookback_trading_days = parameters.get("lookback_trading_days", 60)
        rebalance_days = parameters.get("rebalance_days", 21)

        trades: list[BacktestTrade] = []
        equity_curve: list[dict[str, Any]] = []
        cash = initial_capital
        holdings: dict[str, float] = {}
        last_prices: dict[str, float] = {}

        all_dates = sorted(
            set(
                date
                for df in price_data.values()
                for date in df.index
            )
        )

        for i, date in enumerate(all_dates):
            if i % rebalance_days == 0:
                # Compute momentum for each ticker
                momentum_scores: dict[str, float] = {}
                for ticker, df in price_data.items():
                    if date not in df.index:
                        continue
                    # Momentum = (current_price - price_N_sessions_ago) / price_N_sessions_ago.
                    # Uses trading-day lookback (positional index), which is the
                    # standard convention for financial momentum (e.g. 60 trading
                    # days ≈ 3 months, 126 ≈ 6 months, 252 ≈ 1 year).
                    idx = df.index.get_loc(date)
                    if idx < lookback_trading_days:
                        continue
                    past_price = df["close"].iloc[idx - lookback_trading_days]
                    current_price = df["close"].iloc[idx]
                    if past_price > 0:
                        momentum_scores[ticker] = (current_price - past_price) / past_price

                # Select top-N
                top_tickers = sorted(
                    momentum_scores, key=momentum_scores.get, reverse=True
                )[:top_n]

                # Sell positions not in top-N
                for ticker in list(holdings.keys()):
                    if ticker not in top_tickers and date in price_data.get(ticker, pd.DataFrame()).index:
                        price = price_data[ticker].loc[date, "close"]
                        shares = holdings.pop(ticker)
                        amount = shares * price
                        cash += amount
                        trades.append(BacktestTrade(
                            run_id=run_id,
                            ticker=ticker,
                            action="SELL",
                            trade_date=date,
                            price=float(price),
                            shares=float(shares),
                            amount=float(amount),
                            reason="Momentum drop",
                        ))

                # Buy top-N
                if top_tickers and cash > 0:
                    per_position = cash / len(top_tickers)
                    for ticker in top_tickers:
                        if date not in price_data[ticker].index:
                            continue
                        price = price_data[ticker].loc[date, "close"]
                        if price <= 0:
                            continue
                        shares = per_position / price
                        amount = shares * price
                        cash -= amount
                        holdings[ticker] = holdings.get(ticker, 0) + shares
                        trades.append(BacktestTrade(
                            run_id=run_id,
                            ticker=ticker,
                            action="BUY",
                            trade_date=date,
                            price=float(price),
                            shares=float(shares),
                            amount=float(amount),
                            reason="Momentum top-N",
                        ))

            # Mark to market
            portfolio_value = _mark_to_market(cash, holdings, price_data, date, last_prices)

            equity_curve.append({
                "date": date.isoformat(),
                "value": round(float(portfolio_value), 2),
            })

        # Liquidate remaining positions — dated with the actual last bar.
        for ticker, shares in holdings.items():
            df = price_data.get(ticker)
            if df is not None and len(df) > 0:
                last_price = df["close"].iloc[-1]
                last_date = df.index[-1]
                amount = shares * last_price
                cash += amount
                trades.append(BacktestTrade(
                    run_id=run_id,
                    ticker=ticker,
                    action="SELL",
                    trade_date=last_date,
                    price=float(last_price),
                    shares=float(shares),
                    amount=float(amount),
                    reason="End of backtest",
                ))

        return trades, equity_curve

    async def _run_equal_weight(
        self,
        run_id: int,
        price_data: dict[str, pd.DataFrame],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        parameters: dict[str, Any],
    ) -> tuple[list[BacktestTrade], list[dict[str, Any]]]:
        """
        Equal-weight strategy: buy all tracked companies equally, hold.
        """
        trades: list[BacktestTrade] = []
        equity_curve: list[dict[str, Any]] = []
        cash = initial_capital
        holdings: dict[str, float] = {}
        last_prices: dict[str, float] = {}

        all_dates = sorted(
            set(
                date
                for df in price_data.values()
                for date in df.index
            )
        )

        if not all_dates:
            return trades, equity_curve

        # Initial buy on first date
        first_date = all_dates[0]
        available_tickers = [
            t for t, df in price_data.items() if first_date in df.index
        ]
        if available_tickers and cash > 0:
            per_position = cash / len(available_tickers)
            for ticker in available_tickers:
                price = price_data[ticker].loc[first_date, "close"]
                if price <= 0:
                    continue
                shares = per_position / price
                amount = shares * price
                cash -= amount
                holdings[ticker] = shares
                trades.append(BacktestTrade(
                    run_id=run_id,
                    ticker=ticker,
                    action="BUY",
                    trade_date=first_date,
                    price=float(price),
                    shares=float(shares),
                    amount=float(amount),
                    reason="Equal weight",
                ))

        # Mark to market daily
        for date in all_dates:
            portfolio_value = _mark_to_market(cash, holdings, price_data, date, last_prices)

            equity_curve.append({
                "date": date.isoformat(),
                "value": round(float(portfolio_value), 2),
            })

        # Liquidate at end — dated with the actual last bar.
        for ticker, shares in holdings.items():
            df = price_data.get(ticker)
            if df is not None and len(df) > 0:
                last_price = df["close"].iloc[-1]
                last_date = df.index[-1]
                amount = shares * last_price
                cash += amount
                trades.append(BacktestTrade(
                    run_id=run_id,
                    ticker=ticker,
                    action="SELL",
                    trade_date=last_date,
                    price=float(last_price),
                    shares=float(shares),
                    amount=float(amount),
                    reason="End of backtest",
                ))

        return trades, equity_curve

    async def _run_portfolio_optimizer(
        self,
        run_id: int,
        price_data: dict[str, pd.DataFrame],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        parameters: dict[str, Any],
    ) -> tuple[list[BacktestTrade], list[dict[str, Any]]]:
        """
        Portfolio-optimizer strategy: use the portfolio optimizer for allocation.
        """
        from app.domains.stock.schemas.portfolio import PortfolioOptimizeRequest
        from app.domains.stock.scoring.portfolio_optimizer import PortfolioOptimizer

        rebalance_days = parameters.get("rebalance_days", 21)
        risk_profile = parameters.get("risk_profile", "moderate")
        max_position_weight = parameters.get("max_position_weight", 0.15)
        max_sector_weight = parameters.get("max_sector_weight", 0.30)
        volatility_lookback = parameters.get(
            "volatility_lookback", _DEFAULT_VOLATILITY_LOOKBACK
        )

        trades: list[BacktestTrade] = []
        equity_curve: list[dict[str, Any]] = []
        cash = initial_capital
        holdings: dict[str, float] = {}
        last_prices: dict[str, float] = {}

        all_dates = sorted(
            set(
                date
                for df in price_data.values()
                for date in df.index
            )
        )

        # Resolve Company rows for every ticker in this run once, up front,
        # so per-rebalance opportunity-building can read real sector data
        # instead of hardcoding "Unknown" for every asset (which previously
        # collapsed max_sector_weight into a single portfolio-wide cap).
        companies_result = await self.session.execute(
            select(Company).where(Company.ticker.in_(list(price_data.keys())))
        )
        company_by_ticker: dict[str, Company] = {
            c.ticker: c for c in companies_result.scalars().all()
        }

        # Preload every score for the run's tickers once (up to end_date),
        # replacing the previous one-query-per-ticker-per-rebalance-day
        # pattern. Lookup semantics are unchanged: latest score at or before
        # the rebalance date.
        score_history_result = await self.session.execute(
            select(InvestmentScore, Company)
            .join(Company, Company.id == InvestmentScore.company_id)
            .where(Company.ticker.in_(list(price_data.keys())))
            .where(InvestmentScore.timestamp <= end_date)
            .order_by(InvestmentScore.timestamp)
        )
        scores_by_ticker: dict[str, list[tuple[datetime, InvestmentScore]]] = {}
        for score_row, score_company in score_history_result.all():
            scores_by_ticker.setdefault(score_company.ticker, []).append(
                (score_row.timestamp, score_row)
            )

        for i, date in enumerate(all_dates):
            if i % rebalance_days == 0:
                # Build opportunities from latest scores
                opportunities: list[dict[str, Any]] = []
                for ticker, df in price_data.items():
                    if date not in df.index:
                        continue
                    # Latest preloaded score at or before this date
                    score = None
                    for score_ts, score_row in scores_by_ticker.get(ticker, []):
                        if score_ts <= date:
                            score = score_row
                        else:
                            break

                    # Realized volatility from actual price history up to
                    # this date (annualized), instead of a hardcoded 0.25
                    # for every asset regardless of how it actually behaves.
                    idx = df.index.get_loc(date)
                    window_start = max(0, idx - volatility_lookback)
                    hist = df["close"].iloc[window_start : idx + 1]
                    hist_returns = hist.pct_change().dropna()
                    if len(hist_returns) >= 2:
                        volatility = float(hist_returns.std() * np.sqrt(252))
                    else:
                        volatility = 0.25  # insufficient history — fall back

                    company = company_by_ticker.get(ticker)
                    sector = getattr(company, "sector", None) if company else None

                    opportunities.append({
                        "ticker": ticker,
                        "score": score.overall_score if score and score.overall_score else 50,
                        "risk_score": score.risk_score if score and score.risk_score else 50,
                        "volatility": volatility,
                        "sector": sector or "Unknown",
                    })

                if not opportunities:
                    continue

                # Run optimizer
                request = PortfolioOptimizeRequest(
                    capital=cash + sum(
                        holdings.get(t, 0) * price_data[t].loc[date, "close"]
                        for t in holdings if date in price_data.get(t, pd.DataFrame()).index
                    ),
                    cash_reserve=0,
                    risk_profile=risk_profile,
                    max_position_weight=max_position_weight,
                    max_sector_weight=max_sector_weight,
                )
                optimizer = PortfolioOptimizer()
                result = optimizer.optimize(opportunities, request)

                # Sell positions not in allocation
                target_tickers = {a.ticker for a in result.allocation}
                for ticker in list(holdings.keys()):
                    if ticker not in target_tickers and date in price_data.get(ticker, pd.DataFrame()).index:
                        price = price_data[ticker].loc[date, "close"]
                        shares = holdings.pop(ticker)
                        amount = shares * price
                        cash += amount
                        trades.append(BacktestTrade(
                            run_id=run_id,
                            ticker=ticker,
                            action="SELL",
                            trade_date=date,
                            price=float(price),
                            shares=float(shares),
                            amount=float(amount),
                            reason="Optimizer rebalance",
                        ))

                # Buy target allocations
                for allocation in result.allocation:
                    ticker = allocation.ticker
                    if date not in price_data.get(ticker, pd.DataFrame()).index:
                        continue
                    price = price_data[ticker].loc[date, "close"]
                    if price <= 0:
                        continue
                    target_amount = allocation.amount
                    current_value = holdings.get(ticker, 0) * price
                    delta = target_amount - current_value
                    if abs(delta) < 100:  # Skip tiny trades
                        continue
                    if delta > 0 and delta <= cash:
                        shares = delta / price
                        cash -= delta
                        holdings[ticker] = holdings.get(ticker, 0) + shares
                        trades.append(BacktestTrade(
                            run_id=run_id,
                            ticker=ticker,
                            action="BUY",
                            trade_date=date,
                            price=float(price),
                            shares=float(shares),
                            amount=float(delta),
                            reason="Optimizer allocation",
                        ))
                    elif delta < 0:
                        sell_shares = min(holdings.get(ticker, 0), -delta / price)
                        if sell_shares > 0:
                            amount = sell_shares * price
                            cash += amount
                            holdings[ticker] -= sell_shares
                            if holdings[ticker] <= 0.001:
                                del holdings[ticker]
                            trades.append(BacktestTrade(
                                run_id=run_id,
                                ticker=ticker,
                                action="SELL",
                                trade_date=date,
                                price=float(price),
                                shares=float(sell_shares),
                                amount=float(amount),
                                reason="Optimizer rebalance",
                            ))

            # Mark to market
            portfolio_value = _mark_to_market(cash, holdings, price_data, date, last_prices)

            equity_curve.append({
                "date": date.isoformat(),
                "value": round(float(portfolio_value), 2),
            })

        # Liquidate at end — dated with the actual last bar.
        for ticker, shares in holdings.items():
            df = price_data.get(ticker)
            if df is not None and len(df) > 0:
                last_price = df["close"].iloc[-1]
                last_date = df.index[-1]
                amount = shares * last_price
                cash += amount
                trades.append(BacktestTrade(
                    run_id=run_id,
                    ticker=ticker,
                    action="SELL",
                    trade_date=last_date,
                    price=float(last_price),
                    shares=float(shares),
                    amount=float(amount),
                    reason="End of backtest",
                ))

        return trades, equity_curve

    # ── Performance metrics ───────────────────────────────────────

    def _compute_performance(
        self,
        run_id: int,
        equity_curve: list[dict[str, Any]],
        initial_capital: float,
        trades: list[BacktestTrade],
    ) -> BacktestResult:
        """Compute performance metrics from the equity curve."""
        if not equity_curve:
            return BacktestResult(
                run_id=run_id,
                total_return=0.0,
                final_capital=initial_capital,
                total_trades=len(trades),
                trade_count=len(trades),
            )

        values = pd.Series([p["value"] for p in equity_curve])
        final_capital = float(values.iloc[-1])
        total_return = (final_capital - initial_capital) / initial_capital

        # Annualized return
        n_days = len(values)
        if n_days > 1 and initial_capital > 0:
            annualized = (final_capital / initial_capital) ** (252 / n_days) - 1
        else:
            annualized = 0.0

        # Volatility (daily returns annualized)
        returns = values.pct_change().dropna()
        if len(returns) >= 2:
            volatility = float(returns.std() * np.sqrt(252))
        else:
            volatility = 0.0

        # Sharpe ratio (assume 0% risk-free)
        if volatility > 0:
            sharpe = float((returns.mean() * 252) / volatility)
        else:
            sharpe = 0.0

        # Max drawdown
        running_max = values.cummax()
        drawdown = (values - running_max) / running_max
        max_drawdown = float(abs(drawdown.min())) if len(drawdown) > 0 else 0.0

        # Realized outcomes use average-cost accounting, weighted by shares.
        # Each sell execution is one closed outcome; breakeven is not a win.
        positions: dict[str, tuple[float, float]] = {}
        wins = closed = 0
        for trade in trades:
            quantity, cost = positions.get(trade.ticker, (0.0, 0.0))
            shares = float(trade.shares)
            if trade.action == "BUY":
                positions[trade.ticker] = (quantity + shares, cost + shares * trade.price)
            elif trade.action == "SELL" and quantity > 0:
                sold = min(shares, quantity)
                average_cost = cost / quantity
                closed += 1
                wins += int(trade.price > average_cost)
                remaining = quantity - sold
                positions[trade.ticker] = (remaining, remaining * average_cost)
        win_rate = wins / closed if closed else None

        return BacktestResult(
            run_id=run_id,
            total_return=round(total_return, 6),
            annualized_return=round(annualized, 6),
            volatility=round(volatility, 6),
            sharpe_ratio=round(sharpe, 6),
            max_drawdown=round(max_drawdown, 6),
            win_rate=round(win_rate, 6) if win_rate is not None else None,
            total_trades=len(trades),
            final_capital=round(final_capital, 2),
            equity_curve={"points": equity_curve},
            trade_count=len(trades),
        )

    # ── Benchmark comparison ──────────────────────────────────────

    async def _compare_benchmark(
        self,
        run_id: int,
        equity_curve: list[dict[str, Any]],
        benchmark_ticker: str,
        start_date: datetime,
        end_date: datetime,
        snapshot: BacktestSnapshot | None = None,
    ) -> tuple["BacktestBenchmark | None", str]:
        """Compare strategy performance against a benchmark (Section 162).

        When ``snapshot`` is supplied, benchmark prices are sourced from the
        snapshot first so a snapshot-pinned run doesn't silently read live
        tables (which would give the benchmark side look-ahead access the
        strategy side was denied). Live tables are only used as a fallback
        when the benchmark ticker wasn't captured in the snapshot.

        Returns ``(benchmark, source)`` where source is ``"snapshot"``,
        ``"live"`` or ``"none"`` (no benchmark computed) — recorded on the
        run as part of its snapshot-coverage disclosure (audit F12).
        """
        ticker = benchmark_ticker.upper()

        # ── Source 1: point-in-time snapshot ─────────────────────
        benchmark_points: list[tuple[datetime, float]] | None = None
        if snapshot is not None:
            rows = (snapshot.prices or {}).get(ticker)
            if rows:
                lo, hi = start_date, end_date
                if lo.tzinfo is None:
                    lo = lo.replace(tzinfo=timezone.utc)
                if hi.tzinfo is None:
                    hi = hi.replace(tzinfo=timezone.utc)
                points: list[tuple[datetime, float]] = []
                for row in rows:
                    ts = datetime.fromisoformat(row["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < lo or ts > hi:
                        continue
                    points.append((ts, float(row["close"])))
                if len(points) >= 2:
                    benchmark_points = points
                else:
                    logger.warning(
                        "Benchmark %s has <2 points in snapshot %s for the "
                        "run period; falling back to live tables",
                        ticker,
                        snapshot.id,
                    )

        # Where the benchmark series will come from — disclosed on the run
        # via compute_snapshot_coverage (audit F12).
        benchmark_source = "snapshot" if benchmark_points is not None else "live"

        # ── Source 2: live tables (fallback / no snapshot) ───────
        if benchmark_points is None:
            benchmark_result = await self.session.execute(
                select(Company).where(Company.ticker == ticker)
            )
            benchmark_company = benchmark_result.scalar_one_or_none()
            if not benchmark_company:
                logger.warning("Benchmark %s not found", ticker)
                return None, "none"

            price_result = await self.session.execute(
                select(StockPrice)
                .where(StockPrice.company_id == benchmark_company.id)
                .where(StockPrice.interval == "1d")
                .where(StockPrice.timestamp >= start_date)
                .where(StockPrice.timestamp <= end_date)
                .order_by(StockPrice.timestamp)
            )
            price_rows = price_result.scalars().all()
            if len(price_rows) < 2:
                return None, "none"
            benchmark_points = [(p.timestamp, p.close) for p in price_rows]

        benchmark_start = benchmark_points[0][1]
        benchmark_end = benchmark_points[-1][1]
        benchmark_return = (benchmark_end - benchmark_start) / benchmark_start if benchmark_start else 0.0

        # Strategy return
        if not equity_curve:
            return None, "none"
        strategy_start = equity_curve[0]["value"]
        strategy_end = equity_curve[-1]["value"]
        strategy_return = (strategy_end - strategy_start) / strategy_start if strategy_start else 0.0

        # Alpha = strategy_return - benchmark_return
        alpha = strategy_return - benchmark_return

        # Beta: covariance(strategy_returns, benchmark_returns) / var(benchmark_returns).
        # Build date-indexed return series and inner-join on date so beta is
        # computed only on days where both strategy and benchmark have data.
        strategy_dates = [p["date"] for p in equity_curve]
        strategy_values = pd.Series(
            [p["value"] for p in equity_curve],
            index=pd.to_datetime(strategy_dates),
        )
        strategy_returns = strategy_values.pct_change().dropna()

        benchmark_values = pd.Series(
            [close for _, close in benchmark_points],
            index=pd.to_datetime([ts for ts, _ in benchmark_points]),
        )
        benchmark_returns = benchmark_values.pct_change().dropna()

        # Inner join on date — only use days where both series have returns
        aligned = pd.concat(
            [strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()

        beta = None
        tracking_error = None
        information_ratio = None

        if len(aligned) >= 2:
            s_ret = aligned["strategy"].values
            b_ret = aligned["benchmark"].values

            # Match np.cov's default ddof=1 — mixing population variance
            # with sample covariance inflates beta by n/(n-1).
            b_var = np.var(b_ret, ddof=1)
            if b_var > 0:
                beta = float(np.cov(s_ret, b_ret)[0, 1] / b_var)

            # Tracking error
            diff = s_ret - b_ret
            tracking_error = float(np.std(diff) * np.sqrt(252))

            # Information ratio
            if tracking_error and tracking_error > 0:
                information_ratio = float((np.mean(diff) * 252) / tracking_error)

        return BacktestBenchmark(
            run_id=run_id,
            benchmark_ticker=benchmark_ticker.upper(),
            benchmark_return=round(benchmark_return, 6),
            strategy_return=round(strategy_return, 6),
            alpha=round(alpha, 6),
            beta=round(beta, 6) if beta is not None else None,
            tracking_error=round(tracking_error, 6) if tracking_error is not None else None,
            information_ratio=round(information_ratio, 6) if information_ratio is not None else None,
            outperformed=strategy_return > benchmark_return,
        ), benchmark_source

    # ── Score evaluation ──────────────────────────────────────────

    async def _evaluate_scores(
        self,
        run_id: int,
        start_date: datetime,
        end_date: datetime,
        tickers: list[str] | None = None,
    ) -> None:
        """
        Evaluate investment scores vs actual forward returns (Section 162).

        For each score record, compute forward returns at 1m, 3m, 6m horizons.
        """
        score_query = (
            select(InvestmentScore, Company)
            .join(Company, Company.id == InvestmentScore.company_id)
            .where(InvestmentScore.timestamp >= start_date)
            .where(InvestmentScore.timestamp <= end_date)
        )
        if tickers:
            score_query = score_query.where(
                Company.ticker.in_([t.upper() for t in tickers])
            )

        score_result = await self.session.execute(score_query)
        score_rows = score_result.all()
        if not score_rows:
            return

        # Bulk-load daily prices for every involved company once, spanning
        # the widest forward window any score needs, instead of issuing one
        # unbounded per-row query per score (N+1).
        company_ids = {company.id for _, company in score_rows}
        window_start = min(score.timestamp for score, _ in score_rows)
        window_end = max(score.timestamp for score, _ in score_rows) + timedelta(
            days=max(FORWARD_RETURN_WINDOWS.values())
        )
        price_result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id.in_(company_ids))
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp >= window_start)
            .where(StockPrice.timestamp <= window_end)
            .order_by(StockPrice.timestamp)
        )
        # Parallel timestamp/row lists per company (ascending), so lookups
        # below are O(log n) bisects instead of linear scans.
        price_ts: dict[int, list[datetime]] = {}
        price_rows: dict[int, list[StockPrice]] = {}
        for p in price_result.scalars().all():
            price_ts.setdefault(p.company_id, []).append(p.timestamp)
            price_rows.setdefault(p.company_id, []).append(p)

        for score, company in score_rows:
            if score.overall_score is None:
                continue

            ts_list = price_ts.get(company.id)
            px_list = price_rows.get(company.id)
            if not ts_list or not px_list:
                continue

            # First close at or after the score timestamp (base price)
            base_idx = bisect_left(ts_list, score.timestamp)
            if base_idx >= len(px_list):
                continue
            base_price = px_list[base_idx].close
            if base_price <= 0:
                continue

            # Compute forward returns. Each horizon independently reports
            # None until its window has actually elapsed (see
            # _forward_return_at_horizon) — recent scores no longer get
            # identical 1m/3m/6m values copied from the latest stale price.
            forward_returns: dict[str, float | None] = {}
            for label, days in FORWARD_RETURN_WINDOWS.items():
                forward_returns[label] = _forward_return_at_horizon(
                    ts_list,
                    px_list,
                    base_idx,
                    score.timestamp + timedelta(days=days),
                )

            # Determine actual outcome based on 3m forward return
            actual_outcome = None
            fr_3m = forward_returns.get("3m")
            if fr_3m is not None:
                if fr_3m > 0.05:
                    actual_outcome = "POSITIVE"
                elif fr_3m < -0.05:
                    actual_outcome = "NEGATIVE"
                else:
                    actual_outcome = "NEUTRAL"

            evaluation = BacktestScoreEvaluation(
                run_id=run_id,
                ticker=company.ticker,
                score_date=score.timestamp,
                score=score.overall_score,
                recommendation=score.recommendation,
                forward_return_1m=forward_returns.get("1m"),
                forward_return_3m=forward_returns.get("3m"),
                forward_return_6m=forward_returns.get("6m"),
                actual_outcome=actual_outcome,
            )
            self.session.add(evaluation)

    # ── AI evaluation ─────────────────────────────────────────────

    async def _evaluate_ai(
        self,
        run_id: int,
        start_date: datetime,
        end_date: datetime,
        tickers: list[str] | None = None,
    ) -> None:
        """
        Evaluate AI analysis quality (Section 162).

        Compares LLM direction/confidence against actual price movement.
        """
        analysis_query = (
            select(Analysis, Company)
            .join(Company, Company.id == Analysis.company_id)
            .where(Analysis.status == "completed")
            .where(Analysis.created_at >= start_date)
            .where(Analysis.created_at <= end_date)
        )
        if tickers:
            analysis_query = analysis_query.where(
                Company.ticker.in_([t.upper() for t in tickers])
            )

        analysis_result = await self.session.execute(analysis_query)
        analysis_rows = analysis_result.all()
        if not analysis_rows:
            return

        # Bulk-load daily prices once for all analyzed companies across the
        # widest 3m forward window needed, replacing the previous per-row
        # unbounded query (N+1).
        ai_company_ids = {company.id for _, company in analysis_rows}
        ai_window_start = min(analysis.created_at for analysis, _ in analysis_rows)
        ai_window_end = max(analysis.created_at for analysis, _ in analysis_rows) + timedelta(
            days=FORWARD_RETURN_WINDOWS["3m"]
        )
        ai_price_result = await self.session.execute(
            select(StockPrice)
            .where(StockPrice.company_id.in_(ai_company_ids))
            .where(StockPrice.interval == "1d")
            .where(StockPrice.timestamp >= ai_window_start)
            .where(StockPrice.timestamp <= ai_window_end)
            .order_by(StockPrice.timestamp)
        )
        ai_price_ts: dict[int, list[datetime]] = {}
        ai_price_rows: dict[int, list[StockPrice]] = {}
        for p in ai_price_result.scalars().all():
            ai_price_ts.setdefault(p.company_id, []).append(p.timestamp)
            ai_price_rows.setdefault(p.company_id, []).append(p)

        for analysis, company in analysis_rows:
            if not analysis.llm_analysis or not isinstance(analysis.llm_analysis, dict):
                continue

            llm_output = analysis.llm_analysis
            llm_confidence = llm_output.get("confidence")
            market_interpretation = llm_output.get("market_interpretation", {})

            # Determine LLM direction
            llm_direction = None
            if isinstance(market_interpretation, dict):
                direction = market_interpretation.get("direction")
                if direction in ("bullish", "bearish", "neutral"):
                    llm_direction = direction
            elif isinstance(market_interpretation, str):
                lower = market_interpretation.lower()
                if "bull" in lower:
                    llm_direction = "bullish"
                elif "bear" in lower:
                    llm_direction = "bearish"
                else:
                    llm_direction = "neutral"

            # Forward price data from the preloaded bulk cache
            ai_ts_list = ai_price_ts.get(company.id)
            ai_px_list = ai_price_rows.get(company.id)
            if not ai_ts_list or not ai_px_list:
                continue

            base_idx = bisect_left(ai_ts_list, analysis.created_at)
            if base_idx >= len(ai_px_list):
                continue
            base_price = ai_px_list[base_idx].close
            if base_price <= 0:
                continue

            # 3-month forward return — only compute when the forward horizon
            # has actually been reached (last price within tolerance of target).
            target_date = analysis.created_at + timedelta(days=FORWARD_RETURN_WINDOWS["3m"])
            last_idx = bisect_right(ai_ts_list, target_date) - 1
            horizon_reached = (
                last_idx >= base_idx
                and (target_date - ai_ts_list[last_idx]) <= FORWARD_RETURN_TOLERANCE
            )

            actual_direction = None
            direction_accuracy = None
            forward_return = None
            if horizon_reached:
                forward_return = (ai_px_list[last_idx].close - base_price) / base_price

            # Determine actual direction (only when horizon is reached)
            if forward_return is not None:
                if forward_return > 0.02:
                    actual_direction = "up"
                elif forward_return < -0.02:
                    actual_direction = "down"
                else:
                    actual_direction = "flat"

            # Direction accuracy — only meaningful when actual direction
            # can be determined from real (not stale) price data.
            if forward_return is not None and llm_direction:
                if llm_direction == "bullish":
                    direction_accuracy = actual_direction == "up"
                elif llm_direction == "bearish":
                    direction_accuracy = actual_direction == "down"
                else:
                    direction_accuracy = actual_direction == "flat"

            # Evidence count
            evidence = llm_output.get("evidence", {})
            evidence_count = evidence.get("source_count", 0) if isinstance(evidence, dict) else 0
            source_backed = evidence_count > 0 if evidence_count is not None else None

            evaluation = BacktestAIEvaluation(
                run_id=run_id,
                analysis_id=analysis.id,
                ticker=company.ticker,
                analysis_date=analysis.created_at,
                llm_confidence=llm_confidence,
                llm_direction=llm_direction,
                actual_direction=actual_direction,
                direction_accuracy=direction_accuracy,
                forward_return=round(forward_return, 6) if forward_return is not None else None,
                evidence_count=evidence_count,
                source_backed=source_backed,
            )
            self.session.add(evaluation)

    # ── Query helpers ─────────────────────────────────────────────

    async def get_run(self, run_id: int) -> BacktestRun | None:
        """Get a backtest run by ID."""
        return await self.session.get(BacktestRun, run_id)

    async def list_runs(
        self, limit: int = 20, offset: int = 0, actor: dict[str, Any] | None = None
    ) -> list[BacktestRun]:
        """List backtest runs (own + system rows; admin sees all)."""
        from app.core.security import visible_to_actor

        result = await self.session.execute(
            select(BacktestRun)
            .options(load_only(
                BacktestRun.id, BacktestRun.name, BacktestRun.strategy,
                BacktestRun.status, BacktestRun.start_date, BacktestRun.end_date,
                BacktestRun.initial_capital, BacktestRun.error_message,
                BacktestRun.snapshot_coverage, raiseload=True,
            ))
            .where(visible_to_actor(BacktestRun.user_id, actor))
            .order_by(desc(BacktestRun.created_at), desc(BacktestRun.id))
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_result(self, run_id: int) -> BacktestResult | None:
        """Get backtest result for a run."""
        result = await self.session.execute(
            select(BacktestResult).where(BacktestResult.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_benchmark(self, run_id: int) -> BacktestBenchmark | None:
        """Get benchmark comparison for a run."""
        result = await self.session.execute(
            select(BacktestBenchmark).where(BacktestBenchmark.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_trades(self, run_id: int, limit: int = 100) -> list[BacktestTrade]:
        """Get trades for a run."""
        result = await self.session.execute(
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.trade_date)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_score_evaluations(
        self, run_id: int, limit: int = 100
    ) -> list[BacktestScoreEvaluation]:
        """Get score evaluations for a run."""
        result = await self.session.execute(
            select(BacktestScoreEvaluation)
            .where(BacktestScoreEvaluation.run_id == run_id)
            .order_by(BacktestScoreEvaluation.score_date)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_ai_evaluations(
        self, run_id: int, limit: int = 100
    ) -> list[BacktestAIEvaluation]:
        """Get AI evaluations for a run."""
        result = await self.session.execute(
            select(BacktestAIEvaluation)
            .where(BacktestAIEvaluation.run_id == run_id)
            .order_by(BacktestAIEvaluation.analysis_date)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_snapshots(
        self, limit: int = 20, offset: int = 0
    ) -> list[BacktestSnapshot]:
        """List backtest snapshots."""
        result = await self.session.execute(
            select(BacktestSnapshot)
            .options(load_only(
                BacktestSnapshot.id, BacktestSnapshot.name, BacktestSnapshot.as_of,
                BacktestSnapshot.description, raiseload=True,
            ))
            .order_by(desc(BacktestSnapshot.as_of), desc(BacktestSnapshot.id))
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_snapshot(self, snapshot_id: int) -> BacktestSnapshot | None:
        """Get a backtest snapshot by ID."""
        return await self.session.get(BacktestSnapshot, snapshot_id)