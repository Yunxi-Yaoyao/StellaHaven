"""Owner settings use real HTTP + isolated SQLite, no live PG connections."""
import asyncio
import threading
import time
import json
from uuid import UUID
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from tests_website_settings.test_website_settings import api_env, upstream
from app.models.config import AppConfig
from app.routers.integrations_host import IntegrationsHostMiddleware
from app.services import access_entries
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
P='https://stella.test'
L='https://stella.p.test'
OWNER='00000000-0000-4000-8000-000000000001'

@compiles(JSONB,'sqlite')
def sqlite_jsonb(element,compiler,**kw):
    return 'JSON'

@pytest.fixture
def access(api_env,monkeypatch):
    from app.routers.config import router
    from app.models.config import AppConfig
    from app.models.node import Node
    from app.models.monitor import Monitor,MonitorGroup,MonitorGroupMember
    from app.services.admin_security import STATE_KEY
    c,f,app,admin=api_env
    app.include_router(router)
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':P,'private':L},{'service_id':'web-project-runtime','public':'https://pages.test','private':'https://pages.p.test'}]))
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS',P+','+L)
    with f() as db:
        # V11 apply reconciles real system groups in the same transaction.
        for table in (Node.__table__,Monitor.__table__,MonitorGroup.__table__,MonitorGroupMember.__table__):
            table.create(db.get_bind())
        db.add(AppConfig(key=STATE_KEY,value=json.dumps({'owner_id':OWNER})));db.commit()
    return c,f,app,admin

def test_read_check_apply_and_disable_preserves_addresses(access):
    c,f,app,admin=access
    r=c.get('/config/access-entries')
    assert r.status_code==200,r.text
    initial=r.json()
    assert initial['settings']=={'revision':0,'enabled':False,'public_origin':P,'private_origin':L}
    from app.models.config import AppConfig
    with f() as db: assert db.get(AppConfig,'access_entries.v1') is None
    bootstrap_check=c.post('/config/access-entries/check',json=initial['settings'])
    assert bootstrap_check.status_code==200,bootstrap_check.text
    assert bootstrap_check.json()['can_apply'] is True
    with f() as db: assert db.get(AppConfig,'access_entries.v1') is None
    # Applying an explicit owner override remains supported.
    configured=apply_value(c,enabled=True,private_origin=L)
    assert configured.status_code==200,configured.text
    initial=configured.json()
    assert initial['settings']=={'revision':1,'enabled':True,'public_origin':P,'private_origin':L}
    draft=initial['settings']|{'enabled':False}
    checked=c.post('/config/access-entries/check',json=draft)
    assert checked.status_code==200,checked.text
    assert checked.json()['can_apply'] is True
    assert checked.json()['network']['tls']=='unknown'
    with f() as db: assert json.loads(db.get(AppConfig,'access_entries.v1').value)['settings']==initial['settings']
    saved=c.put('/config/access-entries',json=draft|{'checked_digest':checked.json()['digest']})
    assert saved.status_code==200,saved.text
    assert saved.json()['settings']==draft|{'revision':2}
    assert c.get('/config/access-entries').json()['settings']==saved.json()['settings']
    assert c.put('/config/access-entries',json=draft|{'checked_digest':checked.json()['digest']}).status_code==409
    with f() as db:
        value=json.loads(db.get(AppConfig,'access_entries.v1').value)
        assert value['owner_id']==OWNER
        assert value['settings']==draft|{'revision':2}


def apply_value(c,**change):
    draft=c.get('/config/access-entries').json()['settings']|change
    result=c.post('/config/access-entries/check',json=draft).json()
    return c.put('/config/access-entries',json=draft|{'checked_digest':result['digest']})


def test_applied_revision_drives_new_direct_proxy_and_pages_selection(access,monkeypatch):
    from app.services import access_entries as access_service,entry_registry as registry,web_project_runtime as pages
    c,f,*_=access
    rows=json.loads(__import__('os').environ['STELLA_ENTRY_REGISTRY'])
    rows.append({'service_id':'site','public':'https://app.test','private':'https://app.p.test'})
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps(rows))
    direct=dict(id='site',mode='iframe',browser_url='https://app.test/path',private_address='https://app.p.test/private',entry_policy='follow')
    proxy=dict(id='site',mode='isolated_proxy',origin='https://app.test')
    from fastapi import HTTPException
    with access_service.request_snapshot(f):
        assert registry.browser_url(direct,L)==direct['private_address']
        assert registry.module_context(proxy,L)=='https://app.p.test'
        assert pages.destination(L)=='https://pages.p.test'
    from app.models.config import AppConfig
    with f() as db: assert db.get(AppConfig,access_service.KEY) is None
    # Explicit null is an owner override, unlike an absent configuration row.
    assert apply_value(c,private_origin=None).status_code==200
    with access_service.request_snapshot(f):
        for select_private in (lambda:registry.browser_url(direct,L),lambda:registry.module_context(proxy,L),lambda:pages.destination(L)):
            with pytest.raises(HTTPException) as rejected:
                select_private()
            assert rejected.value.status_code==409
    assert apply_value(c,enabled=True,private_origin=L).status_code==200
    with access_service.request_snapshot(f):
        assert registry.browser_url(direct,L)==direct['private_address']
        assert registry.module_context(proxy,L)=='https://app.p.test'
        assert pages.destination(L)=='https://pages.p.test'
    assert apply_value(c,enabled=False).status_code==200
    with access_service.request_snapshot(f):
        assert registry.browser_url(direct,L)==direct['private_address']
        assert registry.module_context(proxy,L)=='https://app.p.test'
        assert registry.browser_url(dict(direct,entry_policy='public'),L)==direct['browser_url']
        assert registry.module_context(dict(proxy,entry_policy='public'),L)=='https://app.test'
        assert pages.destination(L)=='https://pages.p.test'
        assert registry.parent_context(L)=='private'  # old origin remains trusted
        assert access_service.current()['revision']==3
    assert access_service.current() is None


def test_direct_private_address_is_not_a_trusted_host_or_backend_target(access):
    from app.services import entry_registry as registry
    c,f,*_=access
    module=dict(id='external',mode='iframe',browser_url='https://service.test/public',private_address='https://service.lan.test/private',entry_policy='follow')
    registry.validate_website_entry(module)
    assert registry.browser_url(module,L)==module['private_address']
    from app.services.request_security import trusted_origins
    assert 'https://service.lan.test' not in trusted_origins()
    assert 'external' not in registry.records()


@pytest.mark.parametrize('stored',['{bad-json',json.dumps({'owner_id':OWNER,'settings':{'revision':0,'enabled':False,'public_origin':P,'private_origin':'https://bad.test/'}}),json.dumps({'owner_id':'00000000-0000-4000-8000-000000000002','settings':{'revision':0,'enabled':False,'public_origin':P,'private_origin':L}})])
def test_persisted_corruption_never_bootstraps_or_mutates_on_read(access,stored):
    from app.models.config import AppConfig
    from app.services import access_entries as service
    from fastapi import HTTPException
    c,f,*_=access
    with f() as db:db.add(AppConfig(key=service.KEY,value=stored));db.commit()
    assert c.get('/config/access-entries').status_code==503
    with pytest.raises(HTTPException) as rejected:
        with service.request_snapshot(f):pass
    assert rejected.value.status_code==503
    with f() as db:assert db.get(AppConfig,service.KEY).value==stored


def test_adapter_selection_persists_without_replacing_connection_or_code(access,upstream):
    c,f,*_=access
    root,_,_=upstream
    payload=dict(address=root+'/',open_behavior='external',idempotency_key='adapter-preserved',connection={'transport':'direct','injection_delivery':'loader'},access_adapter='openlist')
    created=c.post(P+'/website-settings',json=payload)
    assert created.status_code==201,created.text
    mid=created.json()['id']
    assert created.json()['access_adapter']=='openlist'
    from app.services import integrations as store
    active=dict(enabled=True,css='body {color:red}',js='window.customOwnerCode=1',version='owner-v1',timing='dom_ready',csp_policy='reject')
    with f() as db,store.edit(db) as config:
        config['modules'][mid]['injection']['active']=active
    updated=c.patch(P+'/website-settings/'+mid,json={'address':root+'/','access_adapter':'generic'})
    assert updated.status_code==200,updated.text
    assert c.get('/external-modules/'+mid).json()['access_adapter']=='generic'
    with f() as db:
        module=store.state(db)['modules'][mid]
        assert module['injection']['active']==active
        assert module['connection']['transport']=='direct'


@pytest.mark.parametrize('address',['https://evil.test','https://stella.test.evil','https://user:secret@stella.test','https://stella.test/','http://stella.test','https://stella.test:443','https://stella.test#bad'])
def test_unknown_or_malformed_main_entries_never_expand_trust(access,address):
    c,f,*_=access
    draft=c.get('/config/access-entries').json()['settings']|{'public_origin':address}
    result=c.post('/config/access-entries/check',json=draft)
    if result.status_code==200: assert result.json()['can_apply'] is False
    else: assert result.status_code==422
    from app.services.request_security import trusted_origins
    assert trusted_origins()=={P,L}


def test_owner_gate_and_digest_bind_revision_deployment_and_payload(access,monkeypatch):
    c,f,app,admin=access
    from app.routers.auth import admin_user
    from fastapi import HTTPException
    def locked():raise HTTPException(403,'locked')
    original=app.dependency_overrides[admin_user]
    app.dependency_overrides[admin_user]=locked
    assert c.get('/config/access-entries').status_code==403
    app.dependency_overrides[admin_user]=original
    draft=c.get('/config/access-entries').json()['settings']|{'private_origin':L}
    result=c.post('/config/access-entries/check',json=draft).json()
    assert c.put('/config/access-entries',json=draft|{'enabled':not draft['enabled'],'checked_digest':result['digest']}).status_code==409
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS',P)
    assert c.put('/config/access-entries',json=draft|{'checked_digest':result['digest']}).status_code==422
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS',P+','+L)
    from types import SimpleNamespace
    app.dependency_overrides[admin_user]=lambda:SimpleNamespace(id=UUID('00000000-0000-4000-8000-000000000002'))
    assert c.get('/config/access-entries').status_code==403


# Async Host snapshot regression: real SQL IO and request-task context.
@pytest.mark.parametrize('database', ['sqlite', 'postgresql'])
def test_slow_snapshot_sql_does_not_stop_independent_loop(tmp_path, monkeypatch, database):
    import os
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', '[{"service_id":"stella","public":"https://main.test"}]')
    if database == 'postgresql':
        dsn = os.environ.get('STELLA_HOST_LOOP_TEST_DSN')
        if not dsn: pytest.skip('explicit owned PG fixture required')
        engine = create_engine(dsn)
        assert engine.url.database.startswith('host_loop_regression_'), 'owned empty PG database required'
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'snapshot.db'))
    AppConfig.__table__.create(engine)
    started = threading.Event()
    released = threading.Event()
    threads = []
    class OwnedSession(Session):
        def __init__(self, *a, **kw):
            threads.append(('create', threading.get_ident()))
            super().__init__(*a, **kw)
        def close(self):
            threads.append(('close', threading.get_ident()))
            return super().close()
    factory = sessionmaker(engine, class_=OwnedSession)
    @event.listens_for(engine, 'before_cursor_execute')
    def slow(conn, cursor, statement, parameters, context, many):
        threads.append(('sql', threading.get_ident()))
        started.set()
        if database == 'postgresql':
            cursor.execute('SELECT pg_sleep(0.25)')
        assert released.wait(2), 'bounded SQL release failed'
    def release():
        assert started.wait(2)
        time.sleep(.25)
        released.set()
    releaser = threading.Thread(target=release)
    releaser.start()
    async def exercise():
        ticks = []
        async def heartbeat():
            while not released.is_set():
                if started.is_set(): ticks.append(time.monotonic())
                await asyncio.sleep(.005)
        async def app(scope, receive, send):
            assert access_entries.current()['public_origin'] == 'https://main.test'
        async def receive(): return {'type': 'http.disconnect'}
        async def send(message): pass
        middleware = IntegrationsHostMiddleware(app, db_factory=factory, main_origin='https://main.test')
        loop_thread = threading.get_ident()
        beat = asyncio.create_task(heartbeat())
        try:
            await middleware({'type':'http','method':'GET','path':'/assets/main.css','headers':[(b'host',b'main.test')]}, receive, send)
            await beat
            assert len(ticks) >= 5, f'snapshot SQL blocked independent heartbeat: {len(ticks)} ticks'
            assert all(t != loop_thread for _, t in threads), threads
            assert len({t for _, t in threads}) == 1, 'Session must stay in one worker'
            assert [kind for kind, _ in threads] == ['create', 'sql', 'close']
            assert access_entries.current() is None
        finally:
            released.set()
            await beat
    try: asyncio.run(exercise())
    finally:
        released.set(); releaser.join(3); engine.dispose()


def test_async_snapshot_fresh_nested_immutable_and_task_local(tmp_path, monkeypatch):
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', '[{"service_id":"stella","public":"https://main.test"}]')
    engine = create_engine('sqlite:///' + str(tmp_path / 'contexts.db'))
    AppConfig.__table__.create(engine)
    factory = sessionmaker(engine)
    async def run():
        async with access_entries.async_request_snapshot(factory) as outer:
            assert access_entries.current() is outer
            with pytest.raises(TypeError): outer['revision'] = 99
            async with access_entries.async_request_snapshot(factory) as inner:
                assert inner == outer and inner is not outer
                assert access_entries.current() is inner
            assert access_entries.current() is outer
            async def sibling():
                async with access_entries.async_request_snapshot(factory) as own:
                    await asyncio.sleep(0)
                    assert own is access_entries.current() and own is not outer
                assert access_entries.current() is outer
            await asyncio.gather(sibling(), sibling())
            assert access_entries.current() is outer
            with factory() as db:
                db.add(AppConfig(key=access_entries.KEY, value='{invalid'))
                db.commit()
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as error:
                async with access_entries.async_request_snapshot(factory): pass
            assert error.value.status_code == 503
            assert access_entries.current() is outer
        assert access_entries.current() is None
    try: asyncio.run(run())
    finally: engine.dispose()


def test_cancelled_dispatch_restores_parent_context_and_closes_db(tmp_path, monkeypatch):
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', '[{"service_id":"stella","public":"https://main.test"}]')
    engine = create_engine('sqlite:///' + str(tmp_path / 'cancel.db'))
    AppConfig.__table__.create(engine)
    factory = sessionmaker(engine)
    async def run():
        entered = asyncio.Event()
        async def app(scope, receive, send):
            assert access_entries.current() is not None
            assert engine.pool.checkedout() == 0
            entered.set()
            await asyncio.Event().wait()
        async def noop(*args): pass
        middleware = IntegrationsHostMiddleware(app, factory)
        async with access_entries.async_request_snapshot(factory) as parent:
            task = asyncio.create_task(middleware({'type':'http','method':'GET','path':'/','headers':[(b'host',b'main.test')]}, noop, noop))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert access_entries.current() is parent
        assert access_entries.current() is None
        assert engine.pool.checkedout() == 0
    try: asyncio.run(run())
    finally: engine.dispose()


def test_cancel_during_snapshot_read_never_leaks_session_or_context(tmp_path, monkeypatch):
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', '[{"service_id":"stella","public":"https://main.test"}]')
    engine = create_engine('sqlite:///' + str(tmp_path / 'cancel-read.db'))
    AppConfig.__table__.create(engine)
    factory = sessionmaker(engine)
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    @event.listens_for(engine, 'before_cursor_execute')
    def hold(*args):
        entered.set()
        assert release.wait(2)
    @event.listens_for(engine, 'checkin')
    def checkin(*args): closed.set()
    async def run():
        async def acquire():
            async with access_entries.async_request_snapshot(factory):
                pytest.fail('cancelled request must not dispatch')
        task = asyncio.create_task(acquire())
        try:
            while not entered.is_set(): await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert access_entries.current() is None
        finally:
            release.set()
            for _ in range(1000):
                if closed.is_set(): break
                await asyncio.sleep(.001)
        assert closed.is_set() and engine.pool.checkedout() == 0
    try: asyncio.run(run())
    finally: release.set(); engine.dispose()
