"""Real owner cookie/CSRF + PostgreSQL preference portability, no dependency overrides."""
import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture
def site(engine, tmp_path):
    from app.routers.auth import router as auth
    from app.routers.backups import router
    from app.services.backup_center import BackupCenter
    from app.services.request_security import MainSiteSecurityMiddleware
    from app.validation_errors import validation_exception_handler
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(auth)
    app.include_router(router)
    app.add_middleware(MainSiteSecurityMiddleware)
    center = BackupCenter(engine, tmp_path / 'data', key=b'fixture-client-preferences')
    app.state.backup_center = center
    with TestClient(app, base_url='http://testserver') as client:
        registered = client.post('/auth/register', json={
            'username': 'preference-owner', 'password': 'fixture-daily-password', 'display_name': 'Preferences'})
        assert registered.status_code == 201, registered.text
        yield client, center
    center.wait()


def payload(revision=0):
    return {'expected_revision': revision, 'appearance': 'B',
            'home': {'theme': 'classic', 'siteTitle': '最新主页', 'signature': '仅签名', 'live2d': False},
            'ui': {'backgroundQuality': 'original', 'sidebarFold': True, 'serversFold': True,
                   'toolsOpen': True, 'worldMapCollapsed': True, 'monitorMode': 'simple',
                   'noteEditMode': 'markdown', 'listFold': True, 'driveBackground': 'image'}}


def test_un_elevated_owner_can_save_all_19_pure_preferences_but_not_backup_or_restore(site):
    client, center = site
    assert client.get('/operations/backups/client-preferences').json()['revision'] == 0
    saved = client.put('/operations/backups/client-preferences', json=payload())
    assert saved.status_code == 200, saved.text
    read = client.get('/operations/backups/client-preferences').json()
    assert read == saved.json()
    assert read['revision'] == 1 and read['ui'] == payload()['ui']
    assert read['home']['siteTitle'] == '最新主页' and read['appearance'] == 'B'
    # Preference saves need only the ordinary owner session. An anonymous
    # client still cannot start either dangerous operation.
    with TestClient(client.app, base_url='http://testserver') as anonymous:
        assert anonymous.post('/operations/backups', json={'scope': 'settings'}).status_code == 401
        assert anonymous.post('/operations/backups/missing/restore', json={'confirm': 'missing.zip'}).status_code == 401
    assert center.status()['config']['enabled'] is False and center.status()['records'] == []
    assert not center.data_root.joinpath('backups').exists()


@pytest.mark.parametrize('field,value', [
    ('signature', 'x' * 513), ('siteTitle', 'x' * 121), ('signature', 'unsafe\u0000text'),
    ('bgImage', 'https://remote.example/background'), ('bgImage', '/assets/homebg/../private'),
    ('avatar', '/assets/avatars/..'),
])
def test_home_contract_matches_the_audited_local_allowlist(site, field, value):
    client, _ = site
    data = payload()
    data['home'][field] = value
    invalid = client.put('/operations/backups/client-preferences', json=data)
    assert invalid.status_code == 422, invalid.text
    assert value not in invalid.text
    assert client.get('/operations/backups/client-preferences').json()['revision'] == 0


def test_preferences_csrf_owner_revision_and_strict_nested_boundaries(site, engine):
    from uuid import uuid4
    from app.schemas.backups import ClientPreferences
    client, _ = site
    other = str(uuid4())
    foreign = ClientPreferences(revision=91, appearance='A').model_dump_json()
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO app_config(key,value) VALUES (:key,:value)'), {'key':'client-preferences:'+other, 'value':foreign})
    assert client.put('/operations/backups/client-preferences', json=payload(), headers={'Origin':'http://evil.test'}).status_code == 403
    assert client.put('/operations/backups/client-preferences', json=payload(), headers={'Host':'evil.test'}).status_code == 421
    saved = client.put('/operations/backups/client-preferences', json=payload(), headers={'Origin':'http://testserver'})
    assert saved.status_code == 200
    assert client.put('/operations/backups/client-preferences', json=payload()).status_code == 409
    assert client.get('/operations/backups/client-preferences', params={'owner':other}).json() == saved.json()
    for invalid in (payload(1) | {'owner':other}, payload(1) | {'token':'NEVER-ECHO-TOKEN'},
                    payload(1) | {'home':{'notes':'NEVER-ECHO-TOKEN'}},
                    payload(1) | {'ui':{'noteDraft':'NEVER-ECHO-TOKEN'}},
                    payload(1) | {'ui':{'sidebarFold':'1'}},
                    payload(1) | {'home':{'bgCrop':{'cx':.5,'cy':.5,'w':1,'h':1,'runtime':'NEVER-ECHO-TOKEN'}}}):
        result = client.put('/operations/backups/client-preferences', json=invalid)
        assert result.status_code == 422 and 'NEVER-ECHO-TOKEN' not in result.text
    with engine.begin() as conn:
        assert conn.execute(text('SELECT value FROM app_config WHERE key=:key'), {'key':'client-preferences:'+other}).scalar_one() == foreign
        conn.execute(text('UPDATE auth_sessions SET revoked=true'))
    assert client.get('/operations/backups/client-preferences').status_code == 401
    assert client.put('/operations/backups/client-preferences', json=payload(1)).status_code == 401


@pytest.mark.parametrize('with_custom', [False, True])
def test_post_zip_contains_latest_preferences_and_restore_readback_preserves_private_content(site, engine, with_custom):
    from uuid import uuid4, UUID
    from sqlalchemy.orm import Session
    from app.models.config import AppConfig
    from app.models.workspace import Workspace
    from app.models.document import Document
    from app.services import blob_store
    client, center = site
    owner = client.get('/auth/me').json()['id']
    workspace, document = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Workspace(id=workspace, user_id=UUID(owner), name='private-workspace'))
        db.flush()
        db.add(Document(id=document, workspace_id=workspace, title='private-note', file_path='/private.md', content='PREFS-PRIVATE-NOTE-BODY', content_hash='fixture'))
        db.add(AppConfig(key='web-project:'+str(document), value='PREFS-PRIVATE-WEB-SOURCE'))
        db.add(AppConfig(key='localStorage-token-private', value='PREFS-PRIVATE-BROWSER-TOKEN'))
        blob_store.put(db, 'attachments/private', io.BytesIO(b'PREFS-PRIVATE-ATTACHMENT'), 'application/octet-stream', 1000)
        db.commit()
    first = client.put('/operations/backups/client-preferences', json=payload()).json()
    latest = payload(first['revision']); latest['home']['siteTitle']='点击备份前的最新主页';latest['appearance']='A'
    if with_custom:
        latest['appearance'] = 'custom'
        latest['customAppearance'] = {'version':1,'base':'B','overrides':{'accent':'#AABBCC','metric-cpu':'#ABCDEF'}}
    saved = client.put('/operations/backups/client-preferences', json=latest)
    assert saved.status_code == 200
    assert client.post('/auth/admin/setup', json={'user_password':'fixture-daily-password','new_password':'fixture-management-password'}).status_code == 410
    assert client.post('/auth/admin/unlock', json={'password':'fixture-management-password'}).status_code == 410
    assert client.post('/operations/backups', json={'scope':'settings'}).status_code == 202
    center.wait()
    status = client.get('/operations/backups').json()
    assert status['job']['state'] == 'succeeded', status
    record = status['records'][0]
    download = client.get('/operations/backups/'+record['id']+'/download')
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        raw = b''.join(archive.read(name) for name in archive.namelist())
        data = json.loads(archive.read('settings.json'))
        prefs = json.loads(next(row['value'] for row in data['config'] if row['key']=='client-preferences:'+owner))
        assert prefs == saved.json()
        for secret in (b'PREFS-PRIVATE-NOTE-BODY',b'PREFS-PRIVATE-WEB-SOURCE',b'PREFS-PRIVATE-BROWSER-TOKEN',b'PREFS-PRIVATE-ATTACHMENT',client.cookies.get('stella_at').encode()):
            assert secret not in raw
    changed = payload(prefs['revision']);changed['home']['siteTitle']='稍后被恢复';changed['appearance']='B'
    changed_response = client.put('/operations/backups/client-preferences', json=changed)
    assert changed_response.status_code == 200
    if with_custom:
        assert changed_response.json()['customAppearance'] == latest['customAppearance']
    assert client.post('/operations/backups/'+record['id']+'/restore', json={'confirm':record['filename']}).status_code == 202
    center.wait()
    assert client.get('/operations/backups').json()['job']['state'] == 'succeeded'
    read = client.get('/operations/backups/client-preferences').json()
    assert read['revision'] > prefs['revision']+1
    assert read | {'revision':prefs['revision']} == prefs
    with Session(engine) as db:
        assert db.get(Document,document).content == 'PREFS-PRIVATE-NOTE-BODY'
        assert b''.join(blob_store.read_range(db,'attachments/private',0,24)) == b'PREFS-PRIVATE-ATTACHMENT'


def test_scheduled_backup_uses_last_confirmed_account_preferences_without_browser_polling(site):
    from datetime import datetime, timezone
    client, center = site
    saved = client.put('/operations/backups/client-preferences', json=payload()).json()
    invalid = payload(saved['revision']); invalid['home']['signature']='x'*513
    assert client.put('/operations/backups/client-preferences', json=invalid).status_code == 422
    assert client.post('/auth/admin/setup', json={'user_password':'fixture-daily-password','new_password':'fixture-management-password'}).status_code == 410
    assert client.post('/auth/admin/unlock', json={'password':'fixture-management-password'}).status_code == 410
    config = client.patch('/operations/backups/config', json={'expected_revision':0,'enabled':True,'scope':'settings','timezone':'UTC','time':'03:00'})
    assert config.status_code == 200
    assert center.status()['records'] == []
    assert center.tick(datetime(2026,10,18,3,0,tzinfo=timezone.utc)) is not None
    center.wait()
    state = client.get('/operations/backups').json()
    assert state['job']['state'] == 'succeeded'
    record = state['records'][0]
    downloaded = client.get('/operations/backups/'+record['id']+'/download')
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        rows = json.loads(archive.read('settings.json'))['config']
        bundled = json.loads(next(row['value'] for row in rows if row['key'].startswith('client-preferences:')))
        assert bundled == saved
