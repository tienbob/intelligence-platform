"""Run with python -m app.workers.jobs. No API process owns execution."""
import asyncio
import hashlib
from sqlalchemy import select, text
from app.core.database import engine, async_session_factory
from app.core.jobs import WorkJob
from app.core.logging import get_logger
logger = get_logger(__name__)

async def fail_target(job, reason):
    from app.domains.stock.models.analysis import Analysis
    from app.domains.stock.models.backtest import BacktestRun
    async with async_session_factory() as db:
        if job.kind == 'analysis':
            row = (await db.execute(select(Analysis).where(Analysis.analysis_id == job.response.get('analysis_id')).with_for_update())).scalar_one_or_none()
            if row and row.status not in {'completed', 'failed', 'cancelled'}:
                row.status = 'failed'
                row.llm_analysis = {**(row.llm_analysis or {}), '_failure_reason': reason}
        elif job.kind == 'backtest':
            row = await db.get(BacktestRun, job.response.get('id'))
            if row and row.status not in {'completed', 'failed'}:
                row.status = 'failed'; row.error_message = reason
        await db.commit()

async def execute(job):
    if job.kind == 'analysis':
        from app.domains.stock.api.analysis import run_company_analysis
        p = job.payload
        await run_company_analysis(job.response['analysis_id'], p['ticker'], p['include_news'], p['include_fundamentals'], p['include_technical'], p['include_macro'])
    elif job.kind == 'backtest':
        from app.domains.stock.models.backtest import BacktestRun
        from app.domains.stock.scoring.backtest import BacktestEngine
        from app.domains.stock.schemas.backtest import BacktestRunRequest
        p = BacktestRunRequest.model_validate(job.payload)
        async with async_session_factory() as db:
            row = await db.get(BacktestRun, job.response['id'])
            try:
                await BacktestEngine(db).run_backtest(**p.model_dump(), existing_run=row)
            except Exception:
                await db.rollback()
                raise
    else:
        raise ValueError('Unsupported work kind')

async def process(job_id):
    # Connection ownership persists across domain-session commits. Hash is
    # stable across processes; collisions only serialize unrelated work.
    lock_id = int.from_bytes(hashlib.sha256(job_id.encode()).digest()[:8], 'big', signed=True)
    async with engine.connect() as conn:
        locked = (await conn.execute(text('SELECT pg_try_advisory_lock(:id)'), {'id': lock_id})).scalar()
        if not locked: return
        try:
            async with async_session_factory() as db:
                job = await db.get(WorkJob, job_id)
                if not job or job.status not in {'queued', 'running'}: return
                abandoned = job.status == 'running'
                job.status = 'running'
                await db.commit()
            if abandoned:
                await fail_target(job, 'Worker interrupted. Retry as a new action; the previous provider call may have completed.')
                status = 'failed'
            else:
                try:
                    await execute(job)
                    status = 'completed'
                except Exception:
                    logger.exception('Work job failed: %s', job.id)
                    await fail_target(job, 'Processing failed. Retry as a new action or contact support with the job ID.')
                    status = 'failed'
            async with async_session_factory() as db:
                current = await db.get(WorkJob, job.id)
                current.status = status
                await db.commit()
        finally:
            await conn.execute(text('SELECT pg_advisory_unlock(:id)'), {'id': lock_id})
            await conn.commit()

async def run():
    while True:
        try:
            async with async_session_factory() as db:
                ids = (await db.execute(select(WorkJob.id).where(WorkJob.status.in_(['queued','running'])).order_by(WorkJob.created_at).limit(100))).scalars().all()
            for job_id in ids: await process(job_id)
        except Exception:
            logger.exception('Worker polling failed; retrying')
        await asyncio.sleep(2)

if __name__ == '__main__':
    asyncio.run(run())
