import asyncio
import pytest


def test_media_gate_rejects_third_but_health_remains_available():
    from app.services.media_limits import MediaLimitsMiddleware
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();count=0
        async def app(scope,receive,send):
            nonlocal count
            if scope['path']=='/homebg/upload':
                count+=1
                if count==2:entered.set()
                await release.wait()
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
        gate=MediaLimitsMiddleware(app,enabled=True)
        async def request(path):
            messages=[]
            async def receive():return {'type':'http.request','body':b'', 'more_body':False}
            async def send(message):messages.append(message)
            await gate({'type':'http','path':path,'method':'POST','headers':[]},receive,send)
            return messages[0]['status']
        a=asyncio.create_task(request('/homebg/upload'));b=asyncio.create_task(request('/homebg/upload'))
        await asyncio.wait_for(entered.wait(),2)
        assert await request('/homebg/upload')==503
        assert await request('/live')==200
        release.set();assert await a==await b==200
        assert gate.active==0
    asyncio.run(scenario())


def test_actual_body_limit_and_cleanup():
    from app.services.media_limits import MediaLimitsMiddleware
    async def scenario():
        async def app(scope,receive,send):
            await receive();await receive()
            raise AssertionError('oversized request must not reach business work')
        gate=MediaLimitsMiddleware(app,enabled=True,limits={'/homebg/upload':4})
        parts=iter([b'123',b'45'])
        async def receive():return {'type':'http.request','body':next(parts),'more_body':True}
        output=[]
        async def send(message):output.append(message)
        await gate({'type':'http','path':'/homebg/upload','method':'POST','headers':[]},receive,send)
        assert output[0]['status']==413 and gate.active==0
    asyncio.run(scenario())
