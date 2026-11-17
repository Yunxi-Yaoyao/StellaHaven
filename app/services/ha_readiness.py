"""Primary-only business admission, not a leader-election or fencing mechanism.

Patroni's /primary endpoint reports a running primary holding the leader lock.
PostgreSQL demotion/watchdog must independently reject stale primary writes.
"""
import os
import httpx
from starlette.responses import JSONResponse

async def patroni_primary(client=None, engine=None):
    base=os.getenv('STELLA_PATRONI_URL','http://127.0.0.1:8008').rstrip('/')
    if client is None:
        async with httpx.AsyncClient(trust_env=False,timeout=1.0) as owned:
            return await patroni_primary(owned, engine)
    response=await client.get(base+'/primary')
    if response.status_code!=200:
        return False
    status=response.json()
    if status.get('state')!='running' or status.get('role') not in ('primary','master'):
        return False
    from starlette.concurrency import run_in_threadpool
    if engine is None:
        return await run_in_threadpool(_sql_is_primary)
    return await run_in_threadpool(_sql_is_primary, engine)


class PrimaryReadiness:
    """One ASGI lifespan owns transports; never owns a cached primary verdict."""
    async def __aenter__(self):
        self.engine=_create_probe_engine()
        try:
            self.client=httpx.AsyncClient(trust_env=False,timeout=1.0)
        except BaseException:
            self.engine.dispose()
            raise
        return self

    async def __aexit__(self,*exc):
        from starlette.concurrency import run_in_threadpool
        try:
            await self.client.aclose()
        finally:
            await run_in_threadpool(self.engine.dispose)

    async def check(self):
        return await patroni_primary(self.client,self.engine)


def _create_probe_engine():
    from sqlalchemy import create_engine
    from app.config import settings
    # Dedicated bounded pool: probe timeouts never leak into business sessions.
    return create_engine(settings.database_url, pool_size=2, max_overflow=0,
                         pool_timeout=1, pool_pre_ping=True,
                         connect_args={'connect_timeout':2,
                                       'options':'-c statement_timeout=1000'})


def _sql_is_primary(engine=None):
    from sqlalchemy import text
    owned=engine is None
    engine=engine or _create_probe_engine()
    try:
        # Closing returns the connection with rollback on success AND failure;
        # every checkout executes a new query, never a retained transaction.
        with engine.connect() as con:
            row=con.execute(text("SELECT NOT pg_is_in_recovery(), current_setting('transaction_read_only')='off'")).fetchone()
            return bool(row and row[0] and row[1])
    finally:
        if owned:engine.dispose()

class PrimaryOnlyMiddleware:
    def __init__(self,app,enabled=False,checker=None):
        self.app=app
        self.enabled=enabled
        self.checker=checker or patroni_primary
        self.owned_probe=enabled and checker is None

    async def __call__(self,scope,receive,send):
        if scope['type']=='lifespan' and self.owned_probe:
            async with PrimaryReadiness() as probe:
                previous=self.checker
                self.checker=probe.check
                try:
                    return await self.app(scope,receive,send)
                finally:
                    self.checker=previous
        if scope['type'] not in ('http','websocket'):
            return await self.app(scope,receive,send)
        path=scope.get('path','')
        if path=='/live' and scope['type']=='http':
            return await JSONResponse({'alive':True})(scope,receive,send)
        if not self.enabled:
            return await self.app(scope,receive,send)
        try:
            ready=await self.checker()
        except Exception:
            ready=False
        if not ready:
            if scope['type']=='websocket':
                return await send({'type':'websocket.close','code':1013})
            return await JSONResponse({'detail':'This node is not the active primary'},status_code=503,headers={'Retry-After':'2'})(scope,receive,send)
        if path=='/ready-primary' and scope['type']=='http':
            return await JSONResponse({'ready':True,'role':'primary'})(scope,receive,send)
        return await self.app(scope,receive,send)
