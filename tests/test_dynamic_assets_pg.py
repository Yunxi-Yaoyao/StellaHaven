"""Real isolated PostgreSQL regression; no production engine calls."""
import io
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.blob import BlobObject
from app.models.config import AppConfig
from app.routers import homebg, auth
from app.services import blob_store


@pytest.fixture
def media_client(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv('STELLA_BLOB_STORAGE', 'postgres')
    monkeypatch.setenv('STELLA_BLOB_CACHE', str(tmp_path / 'cache'))
    monkeypatch.setattr(homebg, 'HOMEBG_DIR', tmp_path / 'absent-legacy')
    monkeypatch.setattr(homebg, 'INDEX', tmp_path / 'absent-legacy' / 'index.json')
    user = User(username='media_' + uuid4().hex, display_name='media', password_hash='unused', is_admin=False)
    db_session.add(user)
    db_session.commit()
    app = FastAPI()
    app.include_router(homebg.router)
    app.include_router(auth.router)
    # Imported at fixture time so initial RED is a missing behavior assertion.
    try:
        from app.routers.dynamic_assets import router
        app.include_router(router)
    except ImportError:
        pass
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[auth.current_user] = lambda: user
    with TestClient(app) as client:
        yield client, user, app


def test_pg_limits_and_rollback(media_client, db_session, monkeypatch):
    from fastapi import UploadFile, HTTPException
    from sqlalchemy import func
    client, user, app = media_client
    before = db_session.execute(select(func.count()).select_from(BlobObject)).scalar_one()
    class BoundedSource:
        def __init__(self, total):
            self.remaining = total
            self.maximum = 0
        def read(self, n=-1):
            assert 0 < n <= blob_store.CHUNK_SIZE
            self.maximum = max(self.maximum, n)
            length = min(n, self.remaining)
            self.remaining -= length
            return b'x' * length
    source = BoundedSource(homebg.MAX_SIZE + 1)
    with pytest.raises(HTTPException) as exc:
        homebg._pg_upload(db_session, UploadFile(filename='large.mp4', file=source), user, 'mp4')
    assert exc.value.status_code == 400
    assert source.maximum <= blob_store.CHUNK_SIZE
    assert db_session.execute(select(func.count()).select_from(BlobObject)).scalar_one() == before
    source = BoundedSource(10 * 1024 * 1024 + 1)
    with pytest.raises(HTTPException):
        auth._upload_avatar_pg(db_session, user, UploadFile(filename='large.png', file=source), 'png')
    assert db_session.execute(select(func.count()).select_from(BlobObject)).scalar_one() == before
    previous = homebg._pg_load(db_session)
    with pytest.raises(RuntimeError):
        with homebg._pg_index(db_session) as entries:
            blob_store.put(db_session, 'homebg/rollback.png', io.BytesIO(b'rollback'), 'image/png', 80)
            entries.append({'id': 'rollback'})
            raise RuntimeError('injected failure before publish')
    db_session.rollback()
    assert homebg._pg_load(db_session) == previous
    assert blob_store.metadata(db_session, 'homebg/rollback.png') is None


def test_background_visibility_and_system_protection(media_client, db_session):
    client, user, app = media_client
    owner_id = user.id  # Auth reloads a user per request; asset GET now closes its DB session.
    r = client.post('/homebg/upload', files={'file': ('test.png', b'invalid-but-retained', 'image/png')})
    assert r.status_code == 200
    entry = r.json()
    stranger = User(id=uuid4(), username='stranger', display_name='stranger', password_hash='unused', is_admin=False)
    app.dependency_overrides[auth.current_user] = lambda: stranger
    assert entry['id'] not in [e['id'] for e in client.get('/homebg/').json()]
    assert client.patch('/homebg/' + entry['id'], json={'name': 'stolen'}).status_code == 404
    db_session.rollback()
    assert client.delete('/homebg/' + entry['id']).status_code == 404
    db_session.rollback()
    assert client.post('/homebg/' + entry['id'] + '/optimize').status_code == 404
    db_session.rollback()
    assert client.get(entry['url']).status_code == 200  # existing public semantics
    with homebg._pg_index(db_session) as entries:
        next(e for e in entries if e['id'] == entry['id'])['isDefault'] = True
    db_session.commit()
    app.dependency_overrides[auth.current_user] = lambda: db_session.get(User, owner_id)
    assert client.delete('/homebg/' + entry['id']).status_code == 400
    db_session.rollback()
    assert client.get('/assets/homebg/not-present.png').status_code == 404
    assert client.get('/homebg/media', params={'url': '/etc/passwd'}).status_code == 400


def test_legacy_router_does_not_shadow_other_assets(media_client):
    from app.routers.dynamic_assets import router
    assert all('/{kind}/' not in route.path for route in router.routes)


def test_avatar_pg_history_prunes_and_keeps_unique_urls(media_client, db_session):
    client, user, app = media_client
    urls = []
    for i in range(6):
        r = client.post('/auth/avatar', files={'file': ('avatar.png', bytes([i]) * 32, 'image/png')})
        assert r.status_code == 200, r.text
        urls.append(r.json()['avatar_url'])
        assert blob_store.metadata(db_session, urls[-1].removeprefix('/assets/')) is not None
    assert len(set(urls)) == 6
    assert client.get('/auth/avatars').json() == list(reversed(urls[1:]))
    assert client.get(urls[0]).status_code == 404
    assert client.get(urls[-1]).content == bytes([5]) * 32
    assert client.post('/auth/avatar-pick', json={'url': urls[1]}).json()['avatar_url'] == urls[1]


def test_background_pg_upload_and_public_range(media_client, db_session):
    client, user, app = media_client
    import subprocess
    payload = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                              'color=red:s=32x32', '-frames:v', '1', '-threads', '1',
                              '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'],
                             check=True, capture_output=True).stdout
    r = client.post('/homebg/upload', files={'file': ('tiny.png', payload, 'image/png')})
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry['owner'] == str(user.id)
    assert entry['media']['status'] == 'ready', entry['media']
    assert client.get(entry['media']['poster']).status_code == 200
    assert client.post('/homebg/' + entry['id'] + '/optimize').json()['status'] == 'ready'
    assert blob_store.metadata(db_session, entry['url'].removeprefix('/assets/'))['size'] == len(payload)
    assert client.get(entry['url']).content == payload
    assert client.head(entry['url']).status_code == 200
    rr = client.get(entry['url'], headers={'Range': 'bytes=1-4'})
    assert rr.status_code == 206 and rr.content == payload[1:5]
    assert client.get('/homebg/media', params={'url': entry['url']}).status_code == 200
    assert client.patch('/homebg/' + entry['id'], json={'name': 'renamed'}).json()['name'] == 'renamed'
    assert client.delete('/homebg/' + entry['id']).status_code == 200
    assert client.get(entry['url']).status_code == 404


def test_main_mount_and_legacy_asset_fallthrough(db_session, monkeypatch, tmp_path):
    from main import app
    from app.routers import dynamic_assets
    from fastapi.staticfiles import StaticFiles
    monkeypatch.setenv('STELLA_BLOB_STORAGE', 'file')
    monkeypatch.setenv('STELLA_BLOB_CACHE', str(tmp_path / 'main-cache'))
    root = tmp_path / 'assets'
    for name in ('homebg', 'avatars', 'widget'):
        (root / name).mkdir(parents=True)
        (root / name / 'sample.png').write_bytes(name.encode())
    monkeypatch.setattr(dynamic_assets, 'ROOT', root)
    mount = next(r for r in app.routes if getattr(r, 'path', None) == '/assets')
    monkeypatch.setattr(mount, 'app', StaticFiles(directory=root))
    overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            for name in ('homebg', 'avatars', 'widget'):
                response = client.get('/assets/' + name + '/sample.png')
                assert response.status_code == 200
                assert response.content == name.encode()
            assert client.head('/assets/homebg/sample.png').status_code == 200
            assert client.get('/assets/widget/missing.png').status_code == 404
            # Even when a stale upload exists, PostgreSQL misses must be 404.
            monkeypatch.setenv('STELLA_BLOB_STORAGE', 'postgres')
            assert client.get('/assets/homebg/sample.png').status_code == 404
            assert client.get('/assets/avatars/sample.png').status_code == 404
            assert client.get('/assets/widget/sample.png').content == b'widget'
            for kind in ('homebg', 'avatars'):
                key = kind + '/pg-mounted.png'
                blob_store.put(db_session, key, io.BytesIO(b'pg-mounted'), 'image/png', 100)
                db_session.commit()
                r = client.get('/assets/' + key)
                assert r.status_code == 200 and r.content == b'pg-mounted'
                rr = client.get('/assets/' + key, headers={'Range': 'bytes=0-1'})
                assert rr.status_code == 206 and rr.content == b'pg'
                blob_store.delete(db_session, key)
                db_session.commit()
                assert client.get('/assets/' + key).status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)


def test_legacy_avatar_upload_history_and_fetch(media_client, monkeypatch, tmp_path):
    from app.routers import dynamic_assets
    client, user, app = media_client
    monkeypatch.setenv('STELLA_BLOB_STORAGE', 'file')
    monkeypatch.setattr(auth, '__file__', str(tmp_path / 'app' / 'routers' / 'auth.py'))
    monkeypatch.setattr(dynamic_assets, 'ROOT', tmp_path / 'data' / 'assets')
    r = client.post('/auth/avatar', files={'file': ('avatar.png', b'legacy-avatar', 'image/png')})
    assert r.status_code == 200, r.text
    url = r.json()['avatar_url']
    assert client.get(url).content == b'legacy-avatar'
    assert client.get('/auth/avatars').json() == [url]
    assert client.post('/auth/avatar-pick', json={'url': url}).json()['avatar_url'] == url


def test_pg_video_derivatives_fresh_session_and_cache(media_client, db_session, monkeypatch, tmp_path):
    import subprocess
    from sqlalchemy.orm import Session
    client, user, app = media_client
    source = tmp_path / 'video.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=24', '-t', '0.5', '-c:v',
                    'libx264', '-crf', '0', '-threads', '1', str(source)],
                   check=True, capture_output=True, timeout=30)
    payload = source.read_bytes()
    response = client.post('/homebg/upload', files={'file': ('video.mp4', payload, 'video/mp4')})
    assert response.status_code == 200, response.text
    entry = response.json()
    assert entry['media']['status'] == 'ready', entry['media']
    urls = set(entry['media']['variants'].values()) | {entry['media']['poster'], entry['media']['thumbnail']}
    assert len(urls) == 5  # original, two videos, two previews
    assert not homebg.HOMEBG_DIR.exists()
    # A separate DB session and empty cache emulate another app process.
    monkeypatch.setenv('STELLA_BLOB_CACHE', str(tmp_path / 'second-node-cache'))
    with Session(db_session.get_bind()) as fresh:
        app.dependency_overrides[get_db] = lambda: fresh
        assert entry['id'] in [e['id'] for e in client.get('/homebg/').json()]
        for url in urls:
            r = client.get(url)
            assert r.status_code == 200 and r.content
            assert client.head(url).status_code == 200
            assert client.get(url, headers={'If-None-Match': r.headers['etag']}).status_code == 304
        assert client.get(entry['url']).content == payload
        assert client.get(entry['url'], headers={'Range': 'bytes=10-39'}).content == payload[10:40]
        assert client.delete('/homebg/' + entry['id']).status_code == 200
        for url in urls:
            assert client.get(url).status_code == 404
    app.dependency_overrides[get_db] = lambda: db_session
