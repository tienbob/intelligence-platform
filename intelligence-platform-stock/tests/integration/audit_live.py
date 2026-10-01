import asyncio, uuid
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import text
from app.core.database import async_session_factory, engine
from app.core.jobs import reserve_job
from app.core.security import IdempotencyReplay
from app.core.rate_limit import RedisRateLimiter
from app.core.config import get_settings
from app.domains.stock.models.alert import Alert
from app.domains.stock.api.alerts import list_alerts, mark_alert_read

def req(uid, key='audit'):
    return Request({'type':'http','headers':[(b'x-user-id',str(uid).encode()),(b'x-user-role',b'USER'),(b'idempotency-key',key.encode())]})

async def main():
    async with engine.connect() as c:
        assert (await c.execute(text('SELECT current_database()'))).scalar().startswith('audit_verify_')
    key=str(uuid.uuid4())
    async def reserve():
        async with async_session_factory() as db:
            try:
                job=await reserve_job(db,req(1,key),'audit',{'x':1})
                job.response={'id':job.id}
                await db.commit()
                return job.id
            except IdempotencyReplay as replay:
                return replay.body['id']
    ids=await asyncio.gather(*(reserve() for _ in range(8)))
    assert len(set(ids))==1
    async with async_session_factory() as db:
        try: await reserve_job(db,req(1,key),'audit',{'x':2})
        except HTTPException as e: assert e.status_code==409
        else: raise AssertionError('Changed body accepted')
    async with async_session_factory() as db:
        private=Alert(user_id=1,alert_type='price_alert',severity='medium',message='private')
        shared=Alert(alert_type='price_alert',severity='medium',message='shared')
        db.add_all([private,shared]);await db.commit()
        private_id,shared_id=private.id,shared.id
    async with async_session_factory() as db:
        other=await list_alerts(req(2),False,100,0,db)
        assert private_id not in [a.id for a in other.alerts]
        try: await mark_alert_read(private_id,req(2),db)
        except HTTPException as e: assert e.status_code==404
        else: raise AssertionError('Cross-user dismiss allowed')
    async with async_session_factory() as db: await mark_alert_read(shared_id,req(1),db)
    async with async_session_factory() as db:
        first=await list_alerts(req(1),True,100,0,db)
        second=await list_alerts(req(2),True,100,0,db)
        assert shared_id not in [a.id for a in first.alerts]
        assert shared_id in [a.id for a in second.alerts]
    clients=[RedisRateLimiter(get_settings().REDIS_URL) for _ in range(2)]
    rate_key='audit:'+str(uuid.uuid4())
    async def hit(i):
        try: await clients[i%2].check(rate_key,3);return True
        except HTTPException as e: assert e.status_code==429;return False
    assert sum(await asyncio.gather(*(hit(i) for i in range(12))))==3
    await clients[0].reset(rate_key)
    for client in clients: await client.connection().aclose()
    await engine.dispose()
    print('PASS: atomic reservation/replay, changed-body conflict, two-user alert isolation, independent shared receipts, shared Redis Lua quota')
asyncio.run(main())
