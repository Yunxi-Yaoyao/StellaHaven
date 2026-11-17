"""Owned readiness transports; no application/config import or live endpoints."""
import asyncio
import importlib.util
from pathlib import Path
import pytest

SOURCE = Path(__file__).parents[1] / 'app/services/ha_readiness.py'
def module():
    spec=importlib.util.spec_from_file_location('owned_readiness',SOURCE)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class Reply:
    status_code=200
    def json(self):return {'state':'running','role':'primary'}


def test_owned_probe_reuses_transport_but_checks_both_sources_every_time(monkeypatch):
    m=module();clients=[];sql=[]
    class Client:
        def __init__(self,**kw):self.closed=False;self.requests=0;clients.append(self)
        async def get(self,url):self.requests+=1;return Reply()
        async def aclose(self):self.closed=True
    engine=type('Engine',(),{'dispose':lambda self:sql.append('dispose')})()
    monkeypatch.setattr(m.httpx,'AsyncClient',Client)
    monkeypatch.setattr(m,'_create_probe_engine',lambda:engine,raising=False)
    states=iter([True,False,True])
    monkeypatch.setattr(m,'_sql_is_primary',lambda pool:sql.append(pool) or next(states))
    async def run():
        async with m.PrimaryReadiness() as probe:
            assert await probe.check() is True
            assert await probe.check() is False
            assert await probe.check() is True
        assert len(clients)==1 and clients[0].requests==3 and clients[0].closed
        assert sql==[engine,engine,engine,'dispose']
    asyncio.run(run())


def test_sql_pool_reuses_connection_with_fresh_transaction_and_failure_cleanup():
    from sqlalchemy import create_engine, event
    m=module();engine=create_engine('sqlite://',pool_size=1)
    rows=iter([(True,True),(False,True),RuntimeError('statement timeout'),(True,True)])
    physical=[];rollbacks=[]
    event.listen(engine,'connect',lambda *args:physical.append(1))
    event.listen(engine,'rollback',lambda *args:rollbacks.append(1))
    def statement(cursor,sql,parameters,context):
        value=next(rows)
        if isinstance(value,Exception):raise value
        cursor.execute('SELECT %s, %s' % value)
        return True
    event.listen(engine,'do_execute',statement)
    assert m._sql_is_primary(engine) is True
    assert m._sql_is_primary(engine) is False
    with pytest.raises(RuntimeError,match='statement timeout'):m._sql_is_primary(engine)
    assert m._sql_is_primary(engine) is True
    assert len(physical)==1
    assert len(rollbacks)==4
    engine.dispose()


def test_middleware_owns_probe_lifespan_and_closes_on_shutdown(monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    m=module();events=[];states=iter([True,False,TimeoutError(),True])
    class Probe:
        async def __aenter__(self):events.append('open');return self
        async def __aexit__(self,*exc):events.append('close')
        async def check(self):
            events.append('check');value=next(states)
            if isinstance(value,Exception):raise value
            return value
    monkeypatch.setattr(m,'PrimaryReadiness',Probe)
    async def unowned():raise AssertionError('unowned transport fallback')
    monkeypatch.setattr(m,'patroni_primary',unowned)
    app=m.PrimaryOnlyMiddleware(Starlette(),enabled=True)
    with TestClient(app) as c:
        assert c.get('/ready-primary').status_code==200
        assert c.post('/save').status_code==503
        assert c.post('/save').status_code==503
        assert c.get('/ready-primary').status_code==200
    assert events==['open','check','check','check','check','close']


@pytest.mark.parametrize('failure',['http-timeout','malformed-json','sql-timeout'])
def test_owned_probe_failure_is_closed_then_recovers_and_releases(monkeypatch,failure):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    m=module();events=[];calls=0;sql_calls=0
    class Client:
        def __init__(self,**kw):pass
        async def get(self,url):
            nonlocal calls
            calls+=1
            if calls==2 and failure=='http-timeout':raise TimeoutError('fixture HTTP timeout')
            if calls==2 and failure=='malformed-json':
                class Broken(Reply):
                    def json(self):raise ValueError('fixture malformed JSON')
                return Broken()
            return Reply()
        async def aclose(self):events.append('http-close')
    engine=type('Engine',(),{'dispose':lambda self:events.append('sql-dispose')})()
    def sql(pool):
        nonlocal sql_calls
        sql_calls+=1
        if sql_calls==2 and failure=='sql-timeout':raise TimeoutError('fixture SQL timeout')
        return True
    monkeypatch.setattr(m.httpx,'AsyncClient',Client)
    monkeypatch.setattr(m,'_create_probe_engine',lambda:engine)
    monkeypatch.setattr(m,'_sql_is_primary',sql)
    with TestClient(m.PrimaryOnlyMiddleware(Starlette(),enabled=True)) as client:
        assert client.get('/ready-primary').status_code==200
        assert client.post('/save').status_code==503
        assert client.get('/ready-primary').status_code==200
    assert calls==3
    assert events==['http-close','sql-dispose']
