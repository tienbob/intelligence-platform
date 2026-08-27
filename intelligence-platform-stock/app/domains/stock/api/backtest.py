"""
Backtesting API endpoints (Section 162, Phase 9).

    POST   /backtest/snapshots          → create point-in-time snapshot
    GET    /backtest/snapshots          → list snapshots
    GET    /backtest/snapshots/{id}     → get snapshot
    POST   /backtest/runs               → create and run a backtest
    GET    /backtest/runs               → list backtest runs
    GET    /backtest/runs/{id}          → get run detail with results
    GET    /backtest/runs/{id}/trades   → get trades for a run
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.stock.models.backtest import (
    BacktestRun,
    BacktestSnapshot,
)
from app.domains.stock.schemas.backtest import (
    BacktestAIEvaluationResponse,
    BacktestBenchmarkResponse,
    BacktestResultResponse,
    BacktestRunDetailResponse,
    BacktestRunListResponse,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestScoreEvaluationResponse,
    BacktestSnapshotListResponse,
    BacktestSnapshotRequest,
    BacktestSnapshotResponse,
    BacktestTradeListResponse,
    BacktestTradeResponse,
)
from app.domains.stock.scoring.backtest import BacktestEngine

router = APIRouter(prefix="/backtest", tags=["backtest"])


# ── Snapshots ────────────────────────────────────────────────────


@router.post("/snapshots", response_model=BacktestSnapshotResponse, status_code=201)
async def create_snapshot(
    request: BacktestSnapshotRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a point-in-time dataset snapshot (Section 162)."""
    engine = BacktestEngine(db)
    snapshot = await engine.create_snapshot(
        name=request.name,
        as_of=request.as_of,
        description=request.description,
        tickers=request.tickers,
    )
    return BacktestSnapshotResponse.model_validate(snapshot)


@router.get("/snapshots", response_model=BacktestSnapshotListResponse)
async def list_snapshots(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List backtest snapshots."""
    engine = BacktestEngine(db)
    snapshots = await engine.list_snapshots(limit=limit, offset=offset)
    total = (await db.execute(select(func.count(BacktestSnapshot.id)))).scalar() or 0
    return BacktestSnapshotListResponse(
        snapshots=[BacktestSnapshotResponse.model_validate(s) for s in snapshots],
        total=total,
    )


@router.get("/snapshots/{snapshot_id}", response_model=BacktestSnapshotResponse)
async def get_snapshot(snapshot_id: int, db: AsyncSession = Depends(get_db)):
    """Get a backtest snapshot by ID."""
    engine = BacktestEngine(db)
    snapshot = await engine.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return BacktestSnapshotResponse.model_validate(snapshot)


# ── Runs ─────────────────────────────────────────────────────────


@router.post("/runs", response_model=BacktestRunResponse, status_code=201)
async def create_backtest_run(
    request: BacktestRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create and execute a backtest run (Section 162)."""
    engine = BacktestEngine(db)
    try:
        run = await engine.run_backtest(
            name=request.name,
            strategy=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            benchmark_ticker=request.benchmark_ticker,
            parameters=request.parameters,
            tickers=request.tickers,
            snapshot_id=request.snapshot_id,
        )
    except ValueError as exc:
        # Bad strategy/parameters — client error, not a server fault.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Execution failures are persisted on the run row (status=failed +
        # error_message); surface the reason instead of a bare 500.
        raise HTTPException(
            status_code=500, detail=f"Backtest execution failed: {exc}"
        ) from exc
    return BacktestRunResponse.model_validate(run)


@router.get("/runs", response_model=BacktestRunListResponse)
async def list_backtest_runs(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    """List backtest runs."""
    engine = BacktestEngine(db)
    runs = await engine.list_runs(limit=limit, offset=offset)
    total = (await db.execute(select(func.count(BacktestRun.id)))).scalar() or 0
    return BacktestRunListResponse(
        runs=[BacktestRunResponse.model_validate(r) for r in runs],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=BacktestRunDetailResponse)
async def get_backtest_run(run_id: int, db: AsyncSession = Depends(get_db)):
    """Get backtest run detail with results (Section 162)."""
    engine = BacktestEngine(db)
    run = await engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    result = await engine.get_result(run_id)
    benchmark = await engine.get_benchmark(run_id)
    trades = await engine.get_trades(run_id)
    score_evals = await engine.get_score_evaluations(run_id)
    ai_evals = await engine.get_ai_evaluations(run_id)

    return BacktestRunDetailResponse(
        run=BacktestRunResponse.model_validate(run),
        result=BacktestResultResponse.model_validate(result) if result else None,
        benchmark=BacktestBenchmarkResponse.model_validate(benchmark) if benchmark else None,
        trades=[BacktestTradeResponse.model_validate(t) for t in trades],
        score_evaluations=[
            BacktestScoreEvaluationResponse.model_validate(s) for s in score_evals
        ],
        ai_evaluations=[
            BacktestAIEvaluationResponse.model_validate(a) for a in ai_evals
        ],
    )


@router.get("/runs/{run_id}/trades", response_model=BacktestTradeListResponse)
async def get_backtest_trades(
    run_id: int,
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get trades for a backtest run."""
    engine = BacktestEngine(db)
    run = await engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    trades = await engine.get_trades(run_id, limit=limit)
    return BacktestTradeListResponse(
        trades=[BacktestTradeResponse.model_validate(t) for t in trades],
        total=len(trades),
    )