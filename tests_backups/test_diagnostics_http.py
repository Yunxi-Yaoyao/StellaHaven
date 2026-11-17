"""Real authenticated product backup + independent synthetic PG/ZIP readback."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import uuid
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def schema_engine(engine, owned, monkeypatch):
    import app.database as database
    from app.services.ha_state import metadata
    schema = 'backup_diag_' + uuid.uuid4().hex
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(), current_user')).one() == (owned['database'], owned['user'])
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = create_engine(engine.url, connect_args={'options': f'-csearch_path={schema},public -cstatement_timeout=12000'}, pool_size=8, max_overflow=0)
    with scoped.begin() as conn:
        assert conn.execute(text('SELECT current_database(), current_user, current_schema()')).one() == (owned['database'], owned['user'], schema)
        # checkfirst=False: empty public tables from the outer fixture must not
        # mask the private schema's independent model tables.
        database.Base.metadata.create_all(conn, checkfirst=False)
        metadata.create_all(conn, checkfirst=False)
    monkeypatch.setattr(database, 'engine', scoped)
    monkeypatch.setattr(database, 'sessionLocal', sessionmaker(bind=scoped, autoflush=False))
    yield scoped, schema
    scoped.dispose()
    with engine.begin() as conn:
        assert conn.execute(text('SELECT current_database(), current_user')).one() == (owned['database'], owned['user'])
        conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        assert conn.execute(text('SELECT count(*) FROM pg_namespace WHERE nspname=:name'), {'name':schema}).scalar_one() == 0


@pytest.fixture
def http_fixture(schema_engine, tmp_path):
    from app.routers.backups import router
    from app.routers.auth import router as auth
    from app.services.backup_center import BackupCenter
    from app.services.request_security import MainSiteSecurityMiddleware
    scoped, schema = schema_engine
    app = FastAPI()
    app.include_router(auth)
    app.include_router(router)
    from app.routers.homebg import router as homebg_router
    app.include_router(homebg_router)
    app.add_middleware(MainSiteSecurityMiddleware)
    center = BackupCenter(scoped, tmp_path / 'data', key=b'synthetic')
    app.state.backup_center = center
    with TestClient(app, base_url='http://testserver') as client:
        assert app.dependency_overrides == {}
        assert client.get('/operations/backups').status_code == 401
        response = client.post('/auth/register', json={'username':'diagnostic-owner','password':'synthetic-daily-password','display_name':'Synthetic'})
        assert response.status_code == 201
        with TestClient(app, base_url='http://testserver') as anonymous:
            assert anonymous.post('/operations/backups', json={'scope':'settings'}).status_code == 401
        assert client.post('/auth/admin/setup', json={'user_password':'synthetic-daily-password','new_password':'synthetic-manage-password'}).status_code == 410
        assert client.post('/auth/admin/unlock', json={'password':'synthetic-manage-password'}).status_code == 410
        yield client, center, scoped, schema
    center.wait()


def test_product_settings_all_success_independent_readback(http_fixture, owned, tmp_path):
    client, center, scoped, schema = http_fixture
    from app.services import blob_store
    from app.models.config import AppConfig
    from app.services.backup_archive import validate_archive
    from app.services.backup_postgres import pg_binary, pg_environment, tool_environment
    resource = b'\x89PNG\r\nSYNTHETIC-CONFIGURATION-ASSET'
    with Session(scoped) as db:
        db.add(AppConfig(key='public_host', value='https://synthetic.invalid'))
        blob_store.put(db, 'homebg/fixture.png', io.BytesIO(resource), 'image/png', 1024)
        db.add(AppConfig(key='homebg_index', value=json.dumps([{'id':'sample','name':'fixture','file':'fixture.png','isSystem':True}])))
        db.commit()
    # Local file side of all-mode is independently exercised too.
    files = center.data_root / 'assets'
    files.mkdir(parents=True)
    (files / 'fixture.txt').write_bytes(b'SYNTHETIC-FILE-RESOURCE')
    checks = {}
    all_dump = tmp_path / 'synthetic.dump'
    for scope in ('settings', 'all'):
        accepted = client.post('/operations/backups', json={'scope':scope})
        assert accepted.status_code == 202
        center.wait()
        status = client.get('/operations/backups')
        assert status.status_code == 200
        job = status.json()['job']
        assert job['id'] == accepted.json()['id'] and job['state'] == 'succeeded'
        assert job['reason_code'] is None and job['failed_stage'] is None
        with scoped.connect() as independent:
            stored = json.loads(independent.execute(text("SELECT value FROM app_config WHERE key='backup_center_v1'")).scalar_one())['job']
            assert stored == job
        record = next(r for r in status.json()['records'] if r['id'] == job['record_id'])
        downloaded = client.get('/operations/backups/' + record['id'] + '/download')
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == record['sha256']
        manifest = validate_archive(io.BytesIO(downloaded.content))
        assert manifest['id'] == record['id'] and manifest['scope'] == scope
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
            if scope == 'settings':
                assert archive.read('resources/homebg/fixture.png') == resource
                data = json.loads(archive.read('settings.json'))
                assert next(r for r in data['config'] if r['key']=='public_host')['value'] == 'https://synthetic.invalid'
                assert json.loads(next(r for r in data['config'] if r['key']=='homebg_index')['value'])[0]['isSystem'] is True
            else:
                all_dump.write_bytes(archive.read('database.dump'))
                assert archive.read('files/assets/fixture.txt') == b'SYNTHETIC-FILE-RESOURCE'
        checks[scope] = {'job':job, 'record':record, 'download_sha256':hashlib.sha256(downloaded.content).hexdigest()}
    assert len(client.get('/operations/backups').json()['records']) == 2
    assert client.get('/operations/backups').json()['config']['enabled'] is False
    # Synthetic only, genuinely empty target; this is not historical recovery.
    target_name = 'backup_diag_restore_' + uuid.uuid4().hex[:12]
    admin = create_engine(scoped.url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        assert conn.execute(text('SELECT current_database(), current_user')).one() == ('postgres', owned['user'])
        conn.execute(text(f'CREATE DATABASE {target_name}'))
    target = create_engine(scoped.url.set(database=target_name))
    try:
        with target.connect() as conn:
            assert conn.execute(text('SELECT current_database(), current_user')).one() == (target_name, owned['user'])
            assert conn.execute(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'")).scalar_one() == 0
        executable = pg_binary('pg_restore')
        result = subprocess.run([executable, '--single-transaction', '--exit-on-error', '--no-owner', '--no-acl', '--dbname='+target_name, str(all_dump)], env=pg_environment(target.url), capture_output=True, timeout=60)
        assert result.returncode == 0, f'pg_restore exit {result.returncode}'
        with target.connect() as conn:
            assert conn.execute(text(f"SELECT value FROM {schema}.app_config WHERE key='public_host'")).scalar_one() == 'https://synthetic.invalid'
            restored = b''.join(bytes(r[0]) for r in conn.execute(text(f"SELECT data FROM {schema}.blob_chunks WHERE key='homebg/fixture.png' ORDER BY number")))
            assert restored == resource
            assert conn.execute(text(f'SELECT count(*) FROM {schema}.users')).scalar_one() == 1
        versions = {name:subprocess.run([pg_binary(name), '--version'], capture_output=True, timeout=10, env=tool_environment()).stdout.decode().strip() for name in ('pg_dump','pg_restore')}
        receipt = {'checks':checks, 'private_schema':schema, 'consumer_versions':versions, 'restored_resource_sha256':hashlib.sha256(restored).hexdigest(), 'expected_resource_sha256':hashlib.sha256(resource).hexdigest(), 'source':'synthetic only; no production data', 'restore':'new empty database, single transaction, 60s deadline'}
        (Path(os.environ['TMPDIR'])/'http-success-receipt.json').write_text(json.dumps(receipt, indent=2))
    finally:
        target.dispose()
        with admin.connect() as conn:
            assert conn.execute(text('SELECT current_database(), current_user')).one() == ('postgres', owned['user'])
            conn.execute(text(f'DROP DATABASE {target_name} WITH (FORCE)'))
            assert conn.execute(text('SELECT count(*) FROM pg_database WHERE datname=:name'), {'name':target_name}).scalar_one() == 0
        admin.dispose()


def test_valid_uploaded_padded_mp4_can_be_backed_up_without_weakening_archive_guard(http_fixture, tmp_path):
    """ISO BMFF permits free-space atoms; compressible is not corrupt media."""
    import struct
    from app.services.backup_archive import MAX_RATIO, validate_archive, InvalidArchive
    client, center, scoped, schema = http_fixture
    before = []
    for _ in range(2):
        assert client.post('/operations/backups', json={'scope':'settings'}).status_code == 202
        center.wait()
        assert center.status()['job']['state'] == 'succeeded'
    old = client.get('/operations/backups').json()['records']
    before = {r['id']:hashlib.sha256((center.store().path/r['filename']).read_bytes()).hexdigest() for r in old}
    source = tmp_path/'synthetic.mp4'
    generated = subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=16x16:r=1','-frames:v','1','-c:v','libx264','-pix_fmt','yuv420p','-y',str(source)], capture_output=True, timeout=20)
    assert generated.returncode == 0
    # 48 MiB legal free-space atom; the product's 80 MiB upload cap is unchanged.
    with source.open('ab') as stream:
        stream.write(struct.pack('>I4s',48*1024**2+8,b'free'))
        for _ in range(48):
            stream.write(bytes(1024**2))
    probe = subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_name,width,height','-of','json',str(source)], capture_output=True, timeout=10)
    assert probe.returncode == 0
    assert json.loads(probe.stdout)['streams'][0] == {'codec_name':'h264','width':16,'height':16}
    original = source.read_bytes()
    # Independent reproduction of the old writer's offending bytes. Keep the
    # untrusted validator unchanged: a compressed bomb MUST still be rejected.
    bad = tmp_path/'untrusted-deflated.zip'
    with zipfile.ZipFile(bad,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('resources/homebg/example.mp4',original)
        archive.writestr('settings.json',b'{}')
        archive.writestr('manifest.json',b'{}')
    with zipfile.ZipFile(bad) as archive:
        info = archive.getinfo('resources/homebg/example.mp4')
        ratio = info.file_size/info.compress_size
        assert ratio > MAX_RATIO
    with pytest.raises(InvalidArchive) as rejected:
        validate_archive(bad)
    assert rejected.value.reason_code == 'archive_size_compression_limit'
    response = client.post('/homebg/upload', headers={'Origin':'http://testserver'}, files={'file':('fixture.mp4',original,'video/mp4')})
    assert response.status_code == 200
    uploaded = response.json()
    assert uploaded['media']['status'] == 'ready'
    admitted = client.post('/operations/backups',json={'scope':'settings'})
    assert admitted.status_code == 202
    center.wait()
    final = client.get('/operations/backups').json()
    job = final['job']
    # During RED, preserve observed location and exact old-byte equality before
    # the intended success assertion fails. This is not a historical diagnosis.
    preserved = {r['id']:hashlib.sha256((center.store().path/r['filename']).read_bytes()).hexdigest() for r in old if (center.store().path/r['filename']).exists()}
    if job['state'] != 'succeeded':
        assert final['records'] == old and preserved == before
        assert job['reason_code'] == 'archive_size_compression_limit'
        assert job['failed_stage'] == 'validating_publishing'
    receipt = {'job':job,'synthetic_only':True,'ffprobe':json.loads(probe.stdout),'old_writer_ratio':ratio,'validator_limit':MAX_RATIO,'old_archive_hashes_before':before,'old_archive_hashes_after':preserved,'uploaded_original_sha256':hashlib.sha256(original).hexdigest()}
    (Path(os.environ['TMPDIR'])/('padded-mp4-'+job['state']+'.json')).write_text(json.dumps(receipt,indent=2))
    assert job['state'] == 'succeeded', job
    record = next(r for r in final['records'] if r['id']==job['record_id'])
    download = client.get('/operations/backups/'+record['id']+'/download')
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == record['sha256']
    validate_archive(io.BytesIO(download.content))
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        name = 'resources/'+uploaded['url'].removeprefix('/assets/')
        assert archive.read(name) == original
        assert archive.getinfo(name).compress_type == zipfile.ZIP_STORED
    assert len(final['records']) == 2
    receipt.update(download_sha256=hashlib.sha256(download.content).hexdigest(),
                   record=record, original_readback_equal=True,
                   strict_validator_still_rejects_deflated_input=True,
                   oldest_fixture_retired_only_after_success=True)
    (Path(os.environ['TMPDIR'])/'padded-mp4-succeeded.json').write_text(json.dumps(receipt,indent=2))
