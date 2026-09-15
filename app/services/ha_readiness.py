"""Primary-only business admission, not a leader-election or fencing mechanism.

Patroni's /primary endpoint reports a running primary holding the leader lock.
PostgreSQL demotion/watchdog must independently reject stale primary writes.
"""
import os
import httpx
from starlette.responses import JSONResponse

async def patroni_primary():
    base=os.getenv('STELLA_PATRONI_URL','http://127.0.0.1:8008').rstrip('/')
    async with httpx.AsyncClient(trust_env=False,timeout=1.0) as client:
        response=await client.get(base+'/primary')
    if response.status_code!=200:
        return False
    status=response.json()
    return status.get('state')=='running' and status.get('role') in ('primary','master')

class PrimaryOnlyMiddleware:
    def __init__(self,app,enabled=False,checker=None):
        self.app=app
        self.enabled=enabled
        self.checker=checker or patroni_primary

    async def __call__(self,scope,receive,send):
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
