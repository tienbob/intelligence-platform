import asyncio, uuid, sys
from datetime import datetime, timezone
from sqlalchemy import text
from app.core.database import engine, async_session_factory
from app.core.jobs import WorkJob
from app.domains.stock.models.backtest import BacktestRun
from app.workers.jobs import process

async def main():
    async with engine.connect() as c:
        assert (await c.execute(text('SELECT current_database()'))).scalar().startswith('audit_verify_')
    jobid=str(uuid.uuid4())
    async with async_session_factory() as db:
        run=BacktestRun(name='crash audit', strategy='equal_weight',status='queued',start_date=datetime(2020,1,1,tzinfo=timezone.utc),end_date=datetime(2021,1,1,tzinfo=timezone.utc),initial_capital=1000)
        db.add(run); await db.flush(); rid=run.id
        db.add(WorkJob(id=jobid,kind='backtest',scope='audit',key=jobid,fingerprint='x',payload={},response={'id':rid},status='queued'))
        await db.commit()
    code="import asyncio; import app.workers.jobs as w; w.execute=lambda job: asyncio.sleep(600); asyncio.run(w.process("+repr(jobid)+"))"
    child=await asyncio.create_subprocess_exec(sys.executable,'-c',code)
    try:
        for _ in range(100):
            async with async_session_factory() as db:
                job=await db.get(WorkJob,jobid)
                if job.status=='running': break
            await asyncio.sleep(.1)
        else: raise AssertionError('worker did not claim job')
    finally:
        child.kill();await child.wait()
    await process(jobid)
    async with async_session_factory() as db:
        assert (await db.get(WorkJob,jobid)).status=='failed'
        assert (await db.get(BacktestRun,rid)).status=='failed'
    async with engine.connect() as a, engine.connect() as b:
        assert (await a.execute(text('SELECT pg_try_advisory_lock(734201930)'))).scalar()
        assert not (await b.execute(text('SELECT pg_try_advisory_lock(734201930)'))).scalar()
        await a.execute(text('SELECT pg_advisory_unlock(734201930)'))
        assert (await b.execute(text('SELECT pg_try_advisory_lock(734201930)'))).scalar()
        await b.execute(text('SELECT pg_advisory_unlock(734201930)'))
    await engine.dispose()
    print('PASS: killed-worker recovery fails job and run explicitly; scheduler lock exclusion and transfer')
asyncio.run(main())
