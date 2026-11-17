"""Shared wallpaper lifecycle: real PG, ordinary owner sessions, no auth overrides."""
import io
import json
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(os.getenv('NAV_NATIVE_PG_TEST') != '1', reason='owned nonce PG required')


@pytest.fixture
def lane():
    from qa.native_nav_pg_guard import target, verify_connection
    port, database, username, _ = target()
    from app.database import Base, get_db
    from app.models.user import User
    from app.models.config import AppConfig
    from app.models.native_nav import NavState, NavAsset
    from app.models.blob import BlobObject, BlobChunk
    from app.routers import auth, homebg, native_nav, dynamic_assets, config, backups
    from app.services import blob_store
    from app.services.admin_security import STATE_KEY
    engine = create_engine(f'postgresql://{username}@127.0.0.1:{port}/{database}')
    schema = 'media_' + uuid4().hex
    with engine.begin() as c:
        verify_connection(c, database, username)
        c.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = create_engine(engine.url, connect_args={'options': f'-csearch_path={schema}'})
    factory = sessionmaker(scoped, autoflush=False)
    Base.metadata.create_all(scoped, tables=[User.__table__, auth.AuthSession.__table__, AppConfig.__table__, NavState.__table__, NavAsset.__table__, BlobObject.__table__, BlobChunk.__table__])
    app = FastAPI()
    for router in (auth.router, homebg.router, native_nav.router, dynamic_assets.router, config.public_router, backups.router):
        app.include_router(router)
    from types import SimpleNamespace
    app.state.backup_center = SimpleNamespace(engine=scoped)  # actual preference service engine, no job executor needed
    def dependency(request: Request):
        with factory() as db:
            conn = db.connection()
            info = conn.info
            info['media_actor'] = request.headers.get('x-media-qa')
            try:
                yield db
            finally:
                info.pop('media_actor',None)
    app.dependency_overrides[get_db] = dependency
    uid = uuid4()
    with factory() as db:
        db.add(User(id=uid, username='media-owner', display_name='Media owner', password_hash=auth.hash_password('synthetic-media-password')))
        db.add(AppConfig(key=STATE_KEY, value=json.dumps({'owner_id':str(uid)})))
        entry = {'id':'fixture','file':'fixture.mp4','ext':'mp4','name':'Fixture','owner':str(uid),'media':{'status':'ready','url':'/assets/homebg/fixture.mp4','poster':'/assets/homebg/fixture-poster.webp','thumbnail':'/assets/homebg/fixture-thumb.webp','variants':{'original':'/assets/homebg/fixture.mp4','compressed1':'/assets/homebg/fixture-c1.mp4','compressed2':'/assets/homebg/fixture-c2.mp4'}}}
        db.add(AppConfig(key='homebg_index', value=json.dumps([entry])))
        for key in ('fixture.mp4','fixture-poster.webp','fixture-thumb.webp','fixture-c1.mp4','fixture-c2.mp4'):
            blob_store.put(db, 'homebg/'+key, io.BytesIO(b'synthetic-'+key.encode()), 'video/mp4', 1000)
        db.commit()
    clients = [TestClient(app, base_url='https://media-qa.test') for _ in range(2)]
    for client in clients:
        response = client.post('/auth/login', json={'username':'media-owner','password':'synthetic-media-password'})
        assert response.status_code == 200, response.text
        assert client.get('/nav-data').status_code == 200  # warm lazy routes
    try:
        yield clients, factory, uid, scoped
    finally:
        for client in clients: client.close()
        scoped.dispose()
        with engine.begin() as c:
            verify_connection(c, database, username)
            c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert c.scalar(text('SELECT count(*) FROM information_schema.schemata WHERE schema_name=:s'), {'s':schema}) == 0
        engine.dispose()


def test_home_reference_delete_is_409_and_keeps_all_bytes(lane):
    clients, factory, uid, _ = lane
    client = clients[0]
    assert client.patch('/auth/me', json={'home_bg':'/assets/homebg/fixture-c1.mp4'}).status_code == 200
    before = client.get('/homebg/').json()
    response = clients[1].delete('/homebg/fixture')
    assert response.status_code == 409, response.text
    assert '引用' in response.text
    assert client.get('/homebg/').json() == before
    for url in ['/assets/homebg/'+name for name in ('fixture.mp4','fixture-poster.webp','fixture-thumb.webp','fixture-c1.mp4','fixture-c2.mp4')]:
        assert client.get(url).status_code == 200
    from app.models.user import User
    with factory() as db:
        assert db.get(User,uid).home_bg == '/assets/homebg/fixture-c1.mp4'


@pytest.mark.parametrize('writer', ['home','nav','preferences'])
@pytest.mark.parametrize('first', ['write','delete'])
def test_two_sessions_share_lifecycle_lock_in_both_orders(lane, writer, first, monkeypatch):
    clients, factory, uid, engine = lane
    held, release, attempted = Event(), Event(), Event()
    pids = {}
    body = clients[0].get('/nav-data').json()
    body['mutation_id'] = str(uuid4())
    body['data']['preferences'].update(background='custom', backgroundUrl='/assets/homebg/fixture-c1.mp4')
    if writer=='preferences':
        from app.services import backup_preferences
        from app.schemas.backups import ClientPreferences
        preference_body=ClientPreferences().model_dump(exclude={'revision'},exclude_none=True)
        preference_body['home']['bgImage']='/assets/homebg/fixture-c1.mp4'
        preference_body['expected_revision']=0
        real_session=backup_preferences.Session
        def observed_session(*args,**kwargs):
            session=real_session(*args,**kwargs)
            connection_info=[]
            def began(db, transaction, conn):
                conn.info['media_actor']='first' if first=='write' else 'second'
                connection_info.append(conn.info)
            def ended(db, transaction):
                if transaction.parent is None:
                    for info in connection_info: info.pop('media_actor',None)
            event.listen(session,'after_begin',began)
            event.listen(session,'after_transaction_end',ended)
            return session
        monkeypatch.setattr(backup_preferences,'Session',observed_session)
    def before(conn, cursor, statement, parameters, context, many):
        actor = conn.info.get('media_actor')
        if actor:
            pids[actor] = conn.connection.driver_connection.get_backend_pid()
            if actor == 'second': attempted.set()
    def after(conn, cursor, statement, parameters, context, many):
        if conn.info.get('media_actor') != 'first' or held.is_set(): return
        if first=='write' and writer=='preferences':
            if not statement.startswith('INSERT INTO app_config') or parameters.get('key')!='client-preferences:'+str(uid): return
        else:
            match = ('UPDATE users SET' if writer == 'home' else 'UPDATE nav_states SET') if first == 'write' else 'DELETE FROM blob_chunks'
            if match not in statement: return
        held.set()
        assert release.wait(8), 'controlled holder release timeout'
    event.listen(engine, 'before_cursor_execute', before)
    event.listen(engine, 'after_cursor_execute', after)
    def action(actor, op):
        client = clients[0 if actor == 'first' else 1]
        headers = {'x-media-qa':actor}
        if op == 'delete': return client.delete('/homebg/fixture', headers=headers)
        if writer == 'home': return client.patch('/auth/me', json={'home_bg':'/assets/homebg/fixture-c1.mp4'}, headers=headers)
        if writer == 'preferences': return client.put('/operations/backups/client-preferences',json=preference_body,headers=headers)
        return client.put('/nav-data', json=body, headers=headers)
    observed = None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(action, 'first', first)
            try:
                assert held.wait(5), 'holder never reached real mutation'
                waiter = pool.submit(action, 'second', 'delete' if first == 'write' else 'write')
                assert attempted.wait(5)
                deadline = time.monotonic()+1
                while time.monotonic()<deadline and not waiter.done():
                    if 'second' in pids:
                        with factory() as db:
                            row = db.execute(text('SELECT wait_event_type, pg_blocking_pids(pid), query FROM pg_stat_activity WHERE pid=:pid'), {'pid':pids['second']}).one()
                            if row[0] == 'Lock' and pids['first'] in row[1]:
                                observed = {'wait_event_type':row[0], 'blockers':row[1], 'query':row[2]}
                                break
                    time.sleep(.01)
            finally:
                release.set()
            a, b = holder.result(timeout=8), waiter.result(timeout=8)
        expected = (200,409)
        assert (a.status_code,b.status_code) == expected, (a.text,b.text,observed)
        assert observed and 'homebg_index' in observed['query'], observed
        from app.models.user import User
        from app.models.native_nav import NavState
        from app.services import blob_store
        with factory() as db:
            if writer=='preferences':
                from app.models.config import AppConfig
                row=db.get(AppConfig,'client-preferences:'+str(uid))
                url=json.loads(row.value)['home']['bgImage'] if row else ''
            else:
                url = db.get(User,uid).home_bg if writer == 'home' else (db.get(NavState,uid).data['preferences']['backgroundUrl'] if db.get(NavState,uid) else '')
            exists = blob_store.metadata(db,'homebg/fixture-c1.mp4') is not None
            assert (url,exists) == (('/assets/homebg/fixture-c1.mp4',True) if first == 'write' else ('',False))
        evidence = Path(os.environ['NAV_EVIDENCE'])/f'race-{writer}-{first}.json'
        evidence.write_text(json.dumps({'writer':writer,'first':first,'statuses':[a.status_code,b.status_code],'observed':observed,'fresh_readback':True},indent=2))
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', before)
        event.remove(engine, 'after_cursor_execute', after)


@pytest.mark.parametrize('alias', [
    '/assets/homebg/fixture.mp4', '/assets/homebg/fixture-c1.mp4',
    '/assets/homebg/fixture-c2.mp4?cache=1#t=1',
    'https://media-qa.test/assets/homebg/fixture-c1.mp4?cache=1#t=1',
    '//media-qa.test/assets/homebg/fixture-poster.webp',
    pytest.param('//MEDIA-QA.TEST:443/assets/homebg/fixture-c1.mp4', id='protocol_default_port'),
    '/assets/homebg/%66ixture-thumb.webp',
    '/assets/homebg/unused/../fixture.mp4',
])
def test_home_and_site_alias_references_block_delete(lane, alias):
    clients, factory, uid, _ = lane
    assert clients[0].patch('/auth/me', json={'home_bg':alias}).status_code == 200
    assert clients[0].get('/config/site-background').json()['value'] == alias
    before = clients[0].get('/homebg/').json()
    r = clients[1].delete('/homebg/fixture')
    assert r.status_code == 409, r.text
    assert r.json()['detail']['references'] == ['首页/站点背景引用']
    assert clients[0].get('/homebg/').json() == before


@pytest.mark.parametrize('location', ['background','title','card_icon','card_url','engine_icon'])
def test_all_saved_navigation_media_slots_block_delete(lane, location):
    clients, factory, uid, _ = lane
    body = clients[0].get('/nav-data').json()
    url = 'https://media-qa.test/assets/homebg/fixture-c2.mp4?version=1#t=0'
    prefs = body['data']['preferences']
    if location == 'background': prefs.update(background='custom',backgroundUrl=url)
    if location == 'title': prefs['titleImage'] = url
    if location.startswith('card'):
        body['data']['groups'] = [{'id':str(uuid4()),'title':'Synthetic','items':[{'id':str(uuid4()),'title':'Card','url':url if location=='card_url' else 'https://example.test','icon':{'src':url if location=='card_icon' else ''}}]}]
    if location == 'engine_icon': prefs['engines'] = [{'id':str(uuid4()),'title':'Search','url':'https://example.test?q={query}','icon':url}]
    r = clients[0].put('/nav-data', json={**body,'mutation_id':str(uuid4())})
    assert r.status_code == 200, r.text
    before = clients[0].get('/nav-data').json()
    r = clients[1].delete('/homebg/fixture')
    assert r.status_code == 409, r.text
    assert r.json()['detail']['references'] == ['已保存导航引用']
    assert clients[0].get('/nav-data').json() == before
    assert clients[0].get('/assets/homebg/fixture-c2.mp4').status_code == 200


def test_delete_first_rejects_new_missing_aliases_but_not_remote_and_retains_legacy(lane, monkeypatch, tmp_path):
    clients, factory, uid, _ = lane
    from app.routers import homebg
    from app.models.user import User
    from app.models.native_nav import NavState
    from app.schemas.native_nav import NavData
    monkeypatch.setattr(homebg,'HOMEBG_DIR',tmp_path)
    (tmp_path/'fixture.mp4').write_bytes(b'stale local copy must not resurrect PG object')
    # Merely reading/cancelling picker state has no writes.
    before = clients[0].get('/homebg/').json()
    for _ in range(2): assert clients[0].get('/homebg/').json() == before
    assert clients[1].delete('/homebg/fixture').status_code == 200
    assert clients[0].get('/homebg/').json() == []
    for name in ('fixture.mp4','fixture-c1.mp4','fixture-c2.mp4','fixture-poster.webp','fixture-thumb.webp'):
        assert clients[0].get('/assets/homebg/'+name).status_code == 404
    body = clients[0].get('/nav-data').json()
    for url in ('/assets/homebg/fixture.mp4','https://media-qa.test/assets/homebg/fixture-c1.mp4?x=1'):
        r = clients[0].patch('/auth/me', json={'home_bg':url,'display_name':'Must roll back'})
        assert r.status_code == 409, r.text
        r = clients[1].put('/nav-data', json={**body,'mutation_id':str(uuid4()),'data':{**body['data'],'preferences':{**body['data']['preferences'],'backgroundUrl':url}}})
        assert r.status_code == 409, r.text
    assert clients[0].get('/auth/me').json()['display_name'] == 'Media owner'
    assert clients[0].get('/nav-data').json() == body
    # An external server with the same path is not this library.
    remote = 'https://external.example/assets/homebg/fixture.mp4'
    assert clients[0].patch('/auth/me', json={'home_bg':remote}).status_code == 200
    data = NavData().model_dump(mode='json');data['preferences']['backgroundUrl']=remote
    assert clients[1].put('/nav-data',json={**body,'mutation_id':str(uuid4()),'data':data}).status_code == 200
    # Historical unavailable URLs remain editable, without allowing NEW missing refs.
    with factory() as db:
        db.get(User,uid).home_bg = '/assets/homebg/historical.png'
        row = db.get(NavState,uid);data['preferences']['backgroundUrl']='/assets/homebg/historical.png';row.data=data
        db.commit()
    assert clients[0].patch('/auth/me',json={'home_bg':'/assets/homebg/historical.png','display_name':'Renamed'}).status_code == 200
    body=clients[1].get('/nav-data').json();body['data']['preferences']['title']='Legacy editable'
    assert clients[1].put('/nav-data',json={**body,'mutation_id':str(uuid4())}).status_code == 200


@pytest.mark.parametrize('protection', ['default','system','foreign','revoked','inactive','owner_switch','anonymous'])
def test_existing_media_authority_guards_are_preserved(lane, protection):
    clients, factory, uid, _ = lane
    from app.models.config import AppConfig
    from app.models.user import User, AuthSession
    from app.services.admin_security import STATE_KEY
    expected = 400
    with factory() as db:
        row=db.get(AppConfig,'homebg_index');entries=json.loads(row.value)
        if protection in ('default','system'):
            entries[0]['isDefault' if protection=='default' else 'isSystem']=True
        elif protection=='foreign': entries[0]['owner']=str(uuid4());expected=404
        elif protection=='revoked':
            for session in db.scalars(select(AuthSession)): session.revoked=True
            expected=401
        elif protection=='inactive': db.get(User,uid).is_active=False;expected=401
        elif protection=='owner_switch':
            other=uuid4();db.add(User(id=other,username='other',display_name='Other'))
            db.get(AppConfig,STATE_KEY).value=json.dumps({'owner_id':str(other)});expected=403
        else: clients[1].cookies.clear();expected=401
        row.value=json.dumps(entries);db.commit()
    r=clients[1].delete('/homebg/fixture')
    assert r.status_code==expected,r.text
    from app.services import blob_store
    with factory() as db:
        assert len(json.loads(db.get(AppConfig,'homebg_index').value))==1
        assert all(blob_store.metadata(db,'homebg/'+name) is not None for name in ('fixture.mp4','fixture-c1.mp4','fixture-c2.mp4','fixture-poster.webp','fixture-thumb.webp'))


@pytest.mark.parametrize('operation', ['delete','home','nav'])
def test_real_deferred_commit_failure_rolls_back_media_and_reference(lane, operation):
    clients, factory, uid, engine = lane
    from sqlalchemy.exc import DBAPIError
    from app.models.config import AppConfig
    from app.models.user import User
    from app.models.native_nav import NavState
    from app.services import blob_store
    table, change = ('blob_objects','DELETE') if operation=='delete' else ('users' if operation=='home' else 'nav_states','UPDATE')
    with engine.begin() as c:
        c.execute(text("CREATE FUNCTION media_reject_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic deferred media commit rejection'; END $$"))
        c.execute(text(f'CREATE CONSTRAINT TRIGGER media_reject_commit AFTER {change} ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION media_reject_commit()'))
    before = clients[0].get('/homebg/').json()
    navbefore = clients[0].get('/nav-data').json()
    body = json.loads(json.dumps(navbefore));body['data']['preferences']['backgroundUrl']='/assets/homebg/fixture-c1.mp4';body['mutation_id']=str(uuid4())
    def act():
        if operation=='delete': return clients[0].delete('/homebg/fixture')
        if operation=='home': return clients[0].patch('/auth/me',json={'home_bg':'/assets/homebg/fixture-c1.mp4'})
        return clients[0].put('/nav-data',json=body)
    with pytest.raises(DBAPIError, match='synthetic deferred media commit rejection'):
        act()
    # Before retry: a genuinely new session sees the untouched durable state.
    with factory() as db:
        assert len(json.loads(db.get(AppConfig,'homebg_index').value))==1
        assert db.get(User,uid).home_bg==''
        assert db.get(NavState,uid) is None
        assert all(blob_store.metadata(db,'homebg/'+name) is not None for name in ('fixture.mp4','fixture-c1.mp4','fixture-c2.mp4','fixture-poster.webp','fixture-thumb.webp'))
    assert clients[1].get('/homebg/').json()==before
    assert clients[1].get('/nav-data').json()==navbefore
    with engine.begin() as c:
        c.execute(text(f'DROP TRIGGER media_reject_commit ON {table}'))
    assert act().status_code==200


def test_package_import_cannot_publish_a_deleted_shared_background(lane):
    clients, *_ = lane
    from app.services.native_nav_package import package, sha
    from app.schemas.native_nav import NavData
    data=NavData().model_dump(mode='json');data['preferences'].update(background='custom',backgroundUrl='/assets/homebg/fixture-c1.mp4')
    source=json.dumps(package(data,[]))
    before=clients[0].get('/nav-data').json()
    assert clients[0].post('/nav-package-preview',json={'source':source}).status_code==200
    assert clients[1].delete('/homebg/fixture').status_code==200
    r=clients[0].post('/nav-package-import',json={'source':source,'digest':sha(source.encode()),'confirmed':True,'revision':0,'mutation_id':str(uuid4())})
    assert r.status_code==409,r.text
    assert clients[0].get('/nav-data').json()==before


def test_legacy_file_reference_flock_lives_until_root_transaction_end(lane, monkeypatch, tmp_path):
    import fcntl
    clients, factory, uid, _ = lane
    from app.routers import homebg
    from app.services.homebg_references import lock_library
    from app.models.user import User
    monkeypatch.setenv('STELLA_BLOB_STORAGE','file')
    monkeypatch.setattr(homebg,'HOMEBG_DIR',tmp_path)
    monkeypatch.setattr(homebg,'INDEX',tmp_path/'index.json')
    entry={'id':'legacy','name':'Legacy','file':'legacy.mp4','ext':'mp4','owner':str(uid)}
    homebg._save([entry]);(tmp_path/'legacy.mp4').write_bytes(b'legacy original')
    (tmp_path/'.legacy.mp4.media.json').write_text(json.dumps({'variants':{'compressed1':'/assets/homebg/legacy-c1.mp4'}}))
    (tmp_path/'legacy-c1.mp4').write_bytes(b'legacy compressed')
    for end in ('commit','rollback','close'):
        db=factory()
        lock_library(db)
        with (tmp_path/'.index.lock').open('a+b') as contender:
            with pytest.raises(BlockingIOError): fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
        getattr(db,end)()
        with (tmp_path/'.index.lock').open('a+b') as contender:
            fcntl.flock(contender,fcntl.LOCK_EX|fcntl.LOCK_NB)
        db.close()
    assert clients[0].patch('/auth/me',json={'home_bg':'/assets/homebg/legacy-c1.mp4'}).status_code==200
    assert clients[1].delete('/homebg/legacy').status_code==409
    assert (tmp_path/'legacy.mp4').read_bytes()==b'legacy original'
    assert clients[0].patch('/auth/me',json={'home_bg':''}).status_code==200
    assert clients[1].delete('/homebg/legacy').status_code==200
    assert not (tmp_path/'legacy.mp4').exists()
    assert homebg._load()==[]
    assert clients[0].patch('/auth/me',json={'home_bg':'/assets/homebg/legacy.mp4'}).status_code==409


def test_packaged_default_matches_public_asset_boundary(lane, tmp_path, monkeypatch):
    clients, *_ = lane
    root=tmp_path/'packaged';(root/'homebg').mkdir(parents=True)
    target=root/'homebg/default-bg-kimono.jpeg';target.write_bytes(b'packaged default')
    monkeypatch.setenv('STELLA_PACKAGED_ASSETS_ROOT',str(root))
    url='/assets/homebg/default-bg-kimono.jpeg'
    assert clients[0].patch('/auth/me',json={'home_bg':url}).status_code==200
    assert clients[0].get(url).content==b'packaged default'
    assert clients[0].patch('/auth/me',json={'home_bg':''}).status_code==200
    target.unlink();outside=tmp_path/'not-packaged.jpeg';outside.write_bytes(b'not served')
    target.symlink_to(outside)
    assert clients[0].get(url).status_code==404
    assert clients[0].patch('/auth/me',json={'home_bg':url}).status_code==409


def test_account_presentation_background_participates_in_shared_references(lane):
    clients, *_ = lane
    from app.schemas.backups import ClientPreferences
    path='/operations/backups/client-preferences'
    value=ClientPreferences().model_dump(exclude={'revision'},exclude_none=True)
    value['home']['bgImage']='/assets/homebg/fixture-c1.mp4'
    r=clients[0].put(path,json={**value,'expected_revision':0})
    assert r.status_code==200,r.text
    r=clients[1].delete('/homebg/fixture')
    assert r.status_code==409,r.text
    assert '账号首页偏好引用' in r.text
    value['home']['bgImage']=''
    assert clients[0].put(path,json={**value,'expected_revision':1}).status_code==200
    assert clients[1].delete('/homebg/fixture').status_code==200
    value['home']['bgImage']='/assets/homebg/fixture-c1.mp4'
    assert clients[0].put(path,json={**value,'expected_revision':2}).status_code==409
    actual=clients[1].get(path).json()
    assert actual['revision']==2 and actual['home']['bgImage']==''
