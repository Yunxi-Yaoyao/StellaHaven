"""Owned PostgreSQL + real HTTP routes, synthetic permission boundary only."""
import copy
import json
import subprocess
import time
from uuid import uuid4
from types import SimpleNamespace
import pytest
from tests_website_settings import review_isolation  # fail-closed application bootstrap
from tests_website_settings.test_website_settings import upstream

@pytest.fixture(scope='module')
def factory():
    from sqlalchemy import text
    from app.database import sessionLocal
    # Import completeness must never turn the review bootstrap into a usable DB.
    with sessionLocal() as forbidden:
        with pytest.raises(AssertionError,match='Only fixture-owned engines may connect'):
            forbidden.execute(text('SELECT 1'))
    from tests_website_settings.save_owned_pg import isolated_factory
    yield from isolated_factory()

@pytest.fixture
def client(factory):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.auth import current_user, admin_user
    from app.routers.integrations import router
    from app.routers.website_settings import router as websites
    from app.models.config import AppConfig
    from app.services import integrations as store
    app=FastAPI(); app.include_router(router); app.include_router(websites)
    permission={'allowed':True}
    def identity():
        if not permission['allowed']: raise HTTPException(403,'fixture revoked')
        return SimpleNamespace(id='owner-fixture')
    def db():
        with factory() as session: yield session
    app.dependency_overrides.update({get_db:db,current_user:identity,admin_user:identity})
    with factory() as session:
        session.query(AppConfig).delete();session.commit()
    # Audit persistence is independently covered; this fixture owns only AppConfig.
    original=store.record_change;store.record_change=lambda *a,**k:None
    try:
        with TestClient(app,base_url='http://stella.test') as c: yield c,permission
    finally:store.record_change=original

def test_navigation_committed_cas_receipt_and_light_read(client,factory):
    c,permission=client
    initial=c.get('/navigation').json()
    assert initial['revision']==0
    assert initial['modules']==[]
    body={'entries':[{'id':'notes','title':'Notes saved','visible':True}], 'expected_revision':0,'mutation_id':'navigation-save-0001'}
    saved=c.put('/navigation',json=body)
    assert saved.status_code==200,saved.text
    ack=saved.json();assert ack['revision']==1 and ack['mutation_id']==body['mutation_id']
    assert ack['entries'][0]['title']=='Notes saved'
    assert c.get('/navigation').json()['entries']==ack['entries']
    assert c.put('/navigation',json=body).json()==ack
    second=body|{'expected_revision':1,'mutation_id':'navigation-save-0002','entries':[{'id':'home','title':'Home next'}]}
    assert c.put('/navigation',json=second).json()['revision']==2
    stale=c.put('/navigation',json=body)
    assert stale.status_code==409  # an old receipt never rolls current revision back
    assert c.put('/navigation',json=body|{'mutation_id':'stale-new-key'}).status_code==409
    permission['allowed']=False
    assert c.put('/navigation',json=second).status_code==403
    permission['allowed']=True
    assert c.get('/navigation').json()['revision']==2

def test_metadata_save_offline_returns_canonical_navigation(client,factory,upstream,monkeypatch):
    c,_=client; root,_,seen=upstream
    payload={'address':root+'/site','name':'Original','icon':'globe','idempotency_key':'create-offline-test'}
    created=c.post('/website-settings',json=payload)
    assert created.status_code==201,created.text
    mid=created.json()['id']
    from app.services import website_settings as service, integrations as store
    async def offline(*args,**kwargs): raise AssertionError('Metadata save must not probe remote')
    monkeypatch.setattr(service,'check_draft',offline)
    edited=payload|{'name':'Offline metadata','icon':'star','idempotency_key':'offline-edit-key'}
    saved=c.patch('/website-settings/'+mid,json=edited)
    assert saved.status_code==200,saved.text
    ack=saved.json();assert ack['name']=='Offline metadata'
    assert next(e for e in ack['navigation']['entries'] if e['id']==mid)['title']=='Offline metadata'
    assert ack['idempotency_key']=='offline-edit-key'
    summary=c.get('/navigation').json()['modules'][0]
    assert summary['id']==mid and summary['name']=='Offline metadata'
    assert 'injection' not in summary and 'request_policy' not in summary
    assert c.get('/external-modules/'+mid).json()['name']==ack['name']
    assert c.patch('/website-settings/'+mid,json=edited).json()==ack
    receipt=c.get('/website-settings/'+mid+'/receipt',params={'idempotency_key':'offline-edit-key'})
    assert receipt.status_code==200 and receipt.json()==ack
    with factory() as db: before=copy.deepcopy(store.state(db))
    # Changed unsafe addresses still take authoritative validation, not the local fast path.
    monkeypatch.undo()
    denied=c.patch('/website-settings/'+mid,json=edited|{'address':'http://169.254.169.254/latest','idempotency_key':'unsafe-edit-key'})
    assert denied.status_code==422,denied.text
    with factory() as db: assert store.state(db)==before

@pytest.mark.parametrize('phase', ['read', 'lock', 'commit'])
@pytest.mark.parametrize('reject', [False, True])
def test_metadata_sql_wait_keeps_unrelated_http_alive(client, factory, upstream, monkeypatch, phase, reject):
    """Hold actual PG SQL; a watchdog releases even an unfixed blocked loop."""
    import asyncio
    import threading
    import httpx
    from sqlalchemy import event, text
    from app.services import integrations as store
    c, _ = client
    root, _, _ = upstream
    created = c.post('/website-settings', json=dict(address=root+'/site', name='Before', idempotency_key='heartbeat-create'))
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    before = c.get('/external-modules/'+mid).json()
    with factory() as db: config_before = copy.deepcopy(store.state(db))
    engine = factory.kw['bind']
    import sqlalchemy.orm
    sessions = []
    Session = sqlalchemy.orm.Session
    class WorkerSession(Session):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.thread = threading.get_ident()
            self.closed = False
            sessions.append(self)
        def get(self, *a, **kw):
            assert threading.get_ident() == self.thread
            return super().get(*a, **kw)
        def execute(self, *a, **kw):
            assert threading.get_ident() == self.thread
            return super().execute(*a, **kw)
        def commit(self):
            assert threading.get_ident() == self.thread
            return super().commit()
        def rollback(self):
            assert threading.get_ident() == self.thread
            return super().rollback()
        def close(self):
            assert threading.get_ident() == self.thread
            try: return super().close()
            finally: self.closed = True
    monkeypatch.setattr(sqlalchemy.orm, 'Session', WorkerSession)
    entered, released = threading.Event(), threading.Event()
    lock_key = 72361026
    control = engine.connect()
    control.execute(text('SELECT pg_advisory_lock(:key)'), {'key': lock_key})
    if phase == 'lock':
        control.execute(text('SELECT key FROM app_config WHERE key=:key FOR UPDATE'), {'key':store.KEY})
    if phase == 'commit':
        with factory() as db:
            failure = "RAISE EXCEPTION 'heartbeat transaction rollback';" if reject else ''
            db.execute(text("CREATE FUNCTION metadata_hold_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(72361026); " + failure + " RETURN NEW; END $$"))
            db.execute(text('CREATE CONSTRAINT TRIGGER metadata_hold_commit AFTER UPDATE ON app_config DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION metadata_hold_commit()'))
            db.commit()
    armed = [True]
    def hold(conn, cursor, statement, *args):
        sql = statement.lower()
        matches = ((phase == 'read' and sql.startswith('select') and 'app_config' in sql)
            or (phase == 'lock' and sql.startswith('insert') and 'app_config' in sql)
            or (phase == 'commit' and sql.startswith('update') and 'app_config' in sql))
        if armed[0] and matches:
            armed[0] = False
            entered.set()
            if phase == 'read': cursor.execute('SELECT pg_advisory_xact_lock(72361026)')
    event.listen(engine, 'before_cursor_execute', hold)
    def watchdog():
        assert entered.wait(5), 'save never reached held SQL'
        time.sleep(.5)
        control.rollback()
        control.execute(text('SELECT pg_advisory_unlock(:key)'), {'key':lock_key})
        control.commit()
        released.set()
    watcher = threading.Thread(target=watchdog)
    watcher.start()
    if reject and phase != 'commit':
        def fault(*a, **kw): raise RuntimeError('heartbeat transaction rollback')
        monkeypatch.setattr(store, 'record_change', fault)
    @c.app.get('/metadata-heartbeat')
    async def heartbeat(): return {'alive':True}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=c.app), base_url='http://stella.test') as wire:
            task = asyncio.create_task(wire.patch('/website-settings/'+mid, json=dict(address=root+'/site', name='After', idempotency_key='heartbeat-edit')))
            try:
                while not entered.is_set(): await asyncio.sleep(.001)
                await asyncio.sleep(.03)
                alive = await wire.get('/metadata-heartbeat')
                responsive = not released.is_set()
                assert alive.status_code == 200 and alive.json() == {'alive':True}
                if reject:
                    with pytest.raises(Exception, match='heartbeat transaction rollback'): await task
                else:
                    response = await task
                    assert response.status_code == 200, response.text
                    assert response.json()['name'] == 'After'
                assert responsive, 'synchronous metadata SQL blocked unrelated HTTP until watchdog released PostgreSQL'
            finally:
                if not task.done(): await task
    try:
        asyncio.run(exercise())
    finally:
        watcher.join(6)
        event.remove(engine, 'before_cursor_execute', hold)
        control.close()
        if phase == 'commit':
            with factory() as db:
                db.execute(text('DROP TRIGGER metadata_hold_commit ON app_config'))
                db.execute(text('DROP FUNCTION metadata_hold_commit()')); db.commit()
    assert not watcher.is_alive()
    assert len(sessions) == 2 and all(session.closed for session in sessions)
    assert engine.pool.checkedout() == 0
    after = c.get('/external-modules/'+mid).json()
    if reject:
        assert after == before
        with factory() as db: assert store.state(db) == config_before
    else: assert after['name'] == 'After'


@pytest.mark.parametrize('changed_revision', [False, True])
def test_metadata_worker_keeps_original_request_snapshot(client, factory, upstream, monkeypatch, changed_revision):
    import asyncio
    from contextlib import contextmanager
    from app.models.config import AppConfig
    from app.services import integrations as store, access_entries
    from app.services import website_settings as service
    from app.services.admin_security import STATE_KEY
    c, _ = client
    root, _, _ = upstream
    created = c.post('/website-settings', json=dict(address=root+'/site', idempotency_key='context-create'))
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    owner = '00000000-0000-4000-8000-000000000001'
    with factory() as db:
        db.add(AppConfig(key=STATE_KEY, value=json.dumps(dict(owner_id=owner, enabled=True, version=1, grants={}))))
        db.commit()
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([dict(service_id='stella', public='https://snapshot.fixture.test')]))
    seen = []
    original_edit = store.edit
    @contextmanager
    def changed_access(db):
        seen.append(access_entries.current())
        if changed_revision:
            with factory() as other:
                other.add(AppConfig(key=access_entries.KEY, value=json.dumps(dict(owner_id=owner,
                    settings=access_entries.bootstrap() | {'revision':1}))))
                other.commit()
        with original_edit(db) as config: yield config
    monkeypatch.setattr(store, 'edit', changed_access)
    async def exercise():
        async with access_entries.async_request_snapshot(factory) as original:
            with factory() as request_db:
                if changed_revision:
                    from fastapi import HTTPException
                    with pytest.raises(HTTPException) as rejected:
                        await service.save_website(factory.kw['bind'], service.WebsiteInput(address=root+'/site', name='Snapshot save'), 'owner-fixture', parent_origin='http://stella.test', mid=mid)
                    assert rejected.value.status_code == 409
                    assert rejected.value.detail == '保存期间内外网设置已改变，请重新检查'
                else:
                    result = await service.save_website(factory.kw['bind'], service.WebsiteInput(address=root+'/site', name='Snapshot save'), 'owner-fixture', parent_origin='http://stella.test', mid=mid)
                    assert result['name'] == 'Snapshot save'
                assert access_entries.current() is original
                assert seen == [original] and seen[0] is original
        assert access_entries.current() is None
    asyncio.run(exercise())
    assert c.get('/external-modules/'+mid).json()['name'] == (created.json()['name'] if changed_revision else 'Snapshot save')


def test_cancelled_metadata_read_closes_worker_session_without_write(client, factory, upstream, monkeypatch):
    import asyncio
    import threading
    import httpx
    import sqlalchemy.orm
    from sqlalchemy import event, text
    from app.services import integrations as store
    c, _ = client
    root, _, _ = upstream
    created = c.post('/website-settings', json=dict(address=root+'/site', idempotency_key='cancel-create'))
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    before = c.get('/external-modules/'+mid).json()
    engine = factory.kw['bind']
    entered, closed = threading.Event(), threading.Event()
    owner_threads = []
    OriginalSession = sqlalchemy.orm.Session
    class OwnedSession(OriginalSession):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.owner_thread = threading.get_ident()
            owner_threads.append(self.owner_thread)
        def get(self, *a, **kw):
            assert threading.get_ident() == self.owner_thread
            return super().get(*a, **kw)
        def close(self):
            assert threading.get_ident() == self.owner_thread
            try: return super().close()
            finally: closed.set()
    monkeypatch.setattr(sqlalchemy.orm, 'Session', OwnedSession)
    control = engine.connect()
    control.execute(text('SELECT pg_advisory_lock(72361027)'))
    def hold(conn, cursor, statement, *args):
        if not entered.is_set() and statement.lower().startswith('select') and 'app_config' in statement:
            entered.set(); cursor.execute('SELECT pg_advisory_xact_lock(72361027)')
    event.listen(engine, 'before_cursor_execute', hold)
    def release():
        assert entered.wait(5)
        time.sleep(.3)
        control.execute(text('SELECT pg_advisory_unlock(72361027)')); control.commit()
    watcher = threading.Thread(target=release); watcher.start()
    async def exercise():
        loop_thread = threading.get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=c.app), base_url='http://stella.test') as wire:
            task = asyncio.create_task(wire.patch('/website-settings/'+mid, json=dict(address=root+'/site', name='Never written')))
            while not entered.is_set(): await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            while not closed.is_set(): await asyncio.sleep(.001)
        assert owner_threads and all(t != loop_thread for t in owner_threads)
    try: asyncio.run(exercise())
    finally:
        watcher.join(6); event.remove(engine, 'before_cursor_execute', hold); control.close()
    assert closed.is_set() and not watcher.is_alive()
    assert c.get('/external-modules/'+mid).json() == before
    assert engine.pool.checkedout() == 0


def test_commit_failure_never_returns_ack_and_same_key_can_retry(client,factory):
    from sqlalchemy import text
    c,_=client
    before=c.get('/navigation').json()
    with factory() as db:
        db.execute(text("CREATE FUNCTION save_light_reject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture deferred commit rejection'; END $$"))
        db.execute(text('CREATE CONSTRAINT TRIGGER save_light_reject AFTER INSERT OR UPDATE ON app_config DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION save_light_reject()'))
        db.commit()
    body={'entries':[{'id':'home','title':'Not committed'}],'expected_revision':0,'mutation_id':'commit-failure-retry'}
    try:
        with pytest.raises(Exception,match='fixture deferred commit rejection'):
            c.put('/navigation',json=body)
        assert c.get('/navigation').json()==before
    finally:
        with factory() as db:
            db.execute(text('DROP TRIGGER save_light_reject ON app_config'))
            db.execute(text('DROP FUNCTION save_light_reject()'));db.commit()
    committed=c.put('/navigation',json=body)
    assert committed.status_code==200,committed.text
    assert c.get('/navigation').json()==committed.json()
