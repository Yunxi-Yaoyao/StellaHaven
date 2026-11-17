import io
import json
import time
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text


def test_real_management_auth_http_jobs_download_verify_restore_delete(engine, tmp_path):
    from app.routers.backups import router
    from app.routers.auth import router as auth
    from app.services.backup_center import BackupCenter
    from app.services.request_security import MainSiteSecurityMiddleware
    from app.validation_errors import validation_exception_handler
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(auth)
    app.include_router(router)
    app.add_middleware(MainSiteSecurityMiddleware)
    center = BackupCenter(engine, tmp_path / 'data', key=b'fixture')
    app.state.backup_center = center
    with TestClient(app, base_url='http://testserver') as client:
        assert not app.dependency_overrides
        assert client.get('/operations/backups').status_code == 401
        # Real initialization and cookies; independent password endpoints are retired.
        daily = 'fixture-daily-password'
        manage = 'fixture-independent-manage-password'
        registered = client.post('/auth/register', json={'username': 'backup-owner', 'password': daily, 'display_name': 'Backup Owner'})
        assert registered.status_code == 201, registered.text
        with TestClient(app,base_url='http://testserver') as anonymous:
            assert anonymous.post('/operations/backups',json={'scope':'settings'}).status_code==401
        assert client.post('/auth/admin/setup', json={'user_password': daily, 'new_password': manage}).status_code == 410
        assert client.post('/auth/admin/unlock', json={'password': manage}).status_code == 410
        default = client.get('/operations/backups').json()
        assert default['config']['enabled'] is False and default['records'] == []
        invalid = client.patch('/operations/backups/config', json={'expected_revision': 0, 'scope': 'notes', 'password': 'DO-NOT-ECHO'})
        assert invalid.status_code == 422 and 'DO-NOT-ECHO' not in invalid.text
        prefs = {'expected_revision': 0, 'appearance': 'B', 'home': {'theme': 'classic', 'particles': 'off', 'bgImage': '',
                 'bgCrop': {'cx': .4, 'cy': .5, 'w': .8, 'h': .9}, 'siteTitle': 'fixture', 'signature': 'signature',
                 'meetDate': '2026-05-31', 'live2d': False, 'avatar': '/avatar.png'}}
        saved = client.put('/operations/backups/client-preferences', json=prefs)
        assert saved.status_code == 200, saved.text
        assert client.get('/operations/backups/client-preferences').json()['appearance'] == 'B'
        assert client.put('/operations/backups/client-preferences', json=prefs | {'token': 'NEVER-ECHO-TOKEN'}).status_code == 422
        created = client.post('/operations/backups', json={'scope': 'settings'})
        assert created.status_code == 202, created.text
        center.wait()
        status = client.get('/operations/backups').json()
        assert status['job']['state'] == 'succeeded', status
        record = status['records'][0]
        download = client.get('/operations/backups/' + record['id'] + '/download')
        assert download.status_code == 200 and download.content.startswith(b'PK')
        assert download.headers['cache-control'] == 'no-store'
        assert client.post('/operations/backups/' + record['id'] + '/verify').status_code == 202
        center.wait()
        assert client.get('/operations/backups').json()['job']['state'] == 'succeeded'
        changed = client.get('/operations/backups/client-preferences').json()
        assert client.put('/operations/backups/client-preferences', json={'expected_revision':changed['revision'],'appearance':'A','home':changed['home']}).status_code==200
        assert client.post('/operations/backups/' + record['id'] + '/restore', json={'confirm': 'wrong'}).status_code == 422
        assert client.post('/operations/backups/' + record['id'] + '/restore', json={'confirm': record['filename']}).status_code == 202
        center.wait()
        assert client.get('/operations/backups').json()['job']['state'] == 'succeeded'
        assert client.get('/operations/backups/client-preferences').json()['appearance']=='B'
        assert client.get('/operations/backups/client-preferences').json()['revision']>changed['revision']+1
        assert client.post('/operations/backups',json={'scope':'all'}).status_code==202
        center.wait()
        full_status=client.get('/operations/backups').json()
        assert full_status['job']['state']=='succeeded',full_status
        full=next(r for r in full_status['records'] if r['scope']=='all')
        maintenance=client.post('/operations/backups/'+full['id']+'/restore',json={'confirm':full['filename']})
        assert maintenance.status_code==409 and maintenance.json()['detail']['code']=='maintenance_required'
        assert '--maintenance' in maintenance.json()['detail']['command']
        path=center.store().path/record['filename']
        path.write_bytes(b'corrupt ZIP')
        assert client.post('/operations/backups/'+record['id']+'/verify').status_code==202
        center.wait()
        corrupt=client.get('/operations/backups').json()
        assert corrupt['job']['state']=='failed'
        assert next(r for r in corrupt['records'] if r['id']==record['id'])['verified'] is False
        assert client.get('/operations/backups/'+record['id']+'/download').status_code==422
        path.write_bytes(download.content)
        assert client.post('/auth/admin/lock').status_code == 410
        assert client.get('/operations/backups/' + record['id'] + '/download').status_code == 200
        assert client.post('/auth/admin/unlock', json={'password': manage}).status_code == 410
        assert client.request('DELETE', '/operations/backups/' + record['id'], json={'confirm': record['filename']}).status_code == 204
        assert all(r['id']!=record['id'] for r in client.get('/operations/backups').json()['records'])
        forbidden = client.post('/operations/backups', headers={'Origin': 'http://evil.test'}, json={'scope': 'settings'})
        assert forbidden.status_code == 403
