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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_actor, owns_row, visible_to_actor
from app.domains.stock.schemas.backtest import (
    BacktestBenchmarkResponse,
    BacktestResultResponse,
    BacktestRunDetailResponse,
    BacktestRunListResponse,
    BacktestRunRequest,
    BacktestRunResponse,
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
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List backtest snapshots (GLOBAL market data — shared by all users)."""
    engine = BacktestEngine(db)
    snapshots = await engine.list_snapshots(limit=limit, offset=offset)
    return BacktestSnapshotListResponse(
        snapshots=[BacktestSnapshotResponse.model_validate(s) for s in snapshots],
    )


@router.get("/snapshots/{snapshot_id}", response_model=BacktestSnapshotResponse)
async def get_snapshot(snapshot_id: int, db: AsyncSession = Depends(get_db)):
    """Get a backtest snapshot by ID (GLOBAL — any user's run may pin it)."""
    engine = BacktestEngine(db)
    snapshot = await engine.get_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return BacktestSnapshotResponse.model_validate(snapshot)


# ── Runs ─────────────────────────────────────────────────────────


@router.post("/runs", response_model=BacktestRunResponse, status_code=202)
async def create_backtest_run(
    request: BacktestRunRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create and execute a backtest run (Section 162). User-bound to caller."""
    actor = get_actor(fastapi_request)
    from app.core.jobs import reserve_job
    from app.domains.stock.models.backtest import BacktestRun
    job = await reserve_job(db, fastapi_request, "backtest", request.model_dump(mode="json"))
    run = BacktestRun(**request.model_dump(exclude={"tickers"}), user_id=actor.get("user_id"), status="queued")
    db.add(run)
    await db.flush()
    response = BacktestRunResponse.model_validate(run)
    job.response = response.model_dump(mode="json")
    await db.commit()
    return response


@router.get("/runs", response_model=BacktestRunListResponse)
async def list_backtest_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List backtest runs (lean rows: what the FE table renders).

    User-bound: own + system (NULL) rows. Global snapshots stay unscoped.
    """
    engine = BacktestEngine(db)
    actor = get_actor(request)
    runs = await engine.list_runs(limit=limit, offset=offset, actor=actor)
    return BacktestRunListResponse(
        runs=[BacktestRunResponse.model_validate(r) for r in runs],
    )


@router.get("/runs/{run_id}", response_model=BacktestRunDetailResponse)
async def get_backtest_run(
    run_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Get backtest run detail (lean: result + benchmark + trades).

    Child rows (result/benchmark/trades) inherit the run's ownership —
    verified on the parent run row (404 if another user's).
    """
    engine = BacktestEngine(db)
    run = await engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    if not owns_row(run.user_id, get_actor(request)):
        raise HTTPException(status_code=404, detail="Backtest run not found")

    result = await engine.get_result(run_id)
    benchmark = await engine.get_benchmark(run_id)
    trades = await engine.get_trades(run_id, limit=101)

    return BacktestRunDetailResponse(
        run=BacktestRunResponse.model_validate(run),
        result=BacktestResultResponse.model_validate(result) if result else None,
        benchmark=BacktestBenchmarkResponse.model_validate(benchmark) if benchmark else None,
        has_more=len(trades) > 100,
        trades=[BacktestTradeResponse.model_validate(t) for t in trades[:100]],
    )


@router.get("/runs/{run_id}/trades", response_model=BacktestTradeListResponse)
async def get_backtest_trades(
    run_id: int,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get trades for a backtest run (ownership via parent run row)."""
    engine = BacktestEngine(db)
    run = await engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    if not owns_row(run.user_id, get_actor(request)):
        raise HTTPException(status_code=404, detail="Backtest run not found")

    trades = await engine.get_trades(run_id, limit=limit + 1, offset=offset)
    return BacktestTradeListResponse(
        has_more=len(trades) > limit,
        trades=[BacktestTradeResponse.model_validate(t) for t in trades[:limit]],
    )