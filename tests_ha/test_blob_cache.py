"""Cache tests are self-contained; never import destructive tests/conftest."""
import asyncio
import errno
import hashlib
import io
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models.blob import BlobObject, BlobChunk
from app.services import blob_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('STELLA_BLOB_CACHE', str(tmp_path / 'cache'))
    monkeypatch.setenv('STELLA_BLOB_CACHE_MAX_BYTES', '8192')
    engine = create_engine('sqlite:///' + str(tmp_path / 'test.db'))
    BlobObject.__table__.create(engine)
    BlobChunk.__table__.create(engine)
    with Session(engine) as db:
        for key in ('a', 'b', 'c'):
            blob_store.put(db, key, io.BytesIO(key.encode()*4096), 'application/octet-stream', 4096)
        db.commit()
    yield engine, tmp_path / 'cache'
    engine.dispose()


def get(engine, key, method='GET'):
    with Session(engine) as db:
        return blob_store.response(db, key, Request({'type':'http', 'method':method, 'headers':[]}))


def test_active_download_budget_and_eviction(store):
    engine, cache = store
    first, second = get(engine, 'a'), get(engine, 'b')
    try:
        with pytest.raises(HTTPException) as exc:
            get(engine, 'c')
        assert exc.value.status_code == 503
        assert sum(p.stat().st_blocks*512 for p in cache.glob('*.bin')) <= 8192
    finally:
        for response in (first, second):
            if hasattr(response, 'lease'):
                response.lease.close()
    third = get(engine, 'c')
    try:
        assert len(list(cache.glob('*.bin'))) == 2
        assert not (cache/(hashlib.sha256(b'a'*4096).hexdigest()+'.bin')).exists()
    finally:
        third.lease.close()


@pytest.mark.parametrize('operation', ['posix_fallocate', 'fsync'])
def test_enospc_controlled_and_no_partial_cache(store, monkeypatch, operation):
    engine, cache = store
    def full(*args):
        raise OSError(errno.ENOSPC, 'test disk full')
    with monkeypatch.context() as scoped:
        scoped.setattr(os, operation, full)
        with pytest.raises(HTTPException) as exc:
            get(engine, 'a')
        assert exc.value.status_code == 503
        assert exc.value.headers['Cache-Control'] == 'no-store'
    assert not list(cache.glob('*.bin')) and not list(cache.glob('.fill-*'))
    response = get(engine, 'a')
    response.lease.close()


def test_ttl_orphans_and_foreign_paths(store, monkeypatch):
    engine, cache = store
    response = get(engine, 'a'); response.lease.close()
    old = next(cache.glob('*.bin'))
    os.utime(old, (1,1))
    (cache/'.fill-abcdefgh').write_bytes(b'orphan')
    (cache/'foreign-file').write_bytes(b'keep')
    (cache/'subdir').mkdir()
    (cache/'subdir'/'keep').write_bytes(b'keep')
    (cache/'foreign-link').symlink_to(cache/'foreign-file')
    monkeypatch.setenv('STELLA_BLOB_CACHE_TTL_SECONDS', '1')
    response = get(engine, 'b'); response.lease.close()
    assert not old.exists() and not (cache/'.fill-abcdefgh').exists()
    assert (cache/'foreign-file').read_bytes() == b'keep'
    assert (cache/'subdir'/'keep').read_bytes() == b'keep'
    assert (cache/'foreign-link').is_symlink()


@pytest.mark.parametrize('blocked_message', ['http.response.start', 'http.response.body'])
def test_disconnect_and_cancellation_release_lease(store, blocked_message):
    engine, cache = store
    async def run(disconnect):
        response = get(engine, 'a')
        started = asyncio.Event()
        async def send(message):
            if message['type'] == blocked_message:
                started.set()
                await asyncio.Event().wait()
        async def receive():
            await started.wait()
            if disconnect:
                return {'type':'http.disconnect'}
            await asyncio.Event().wait()
        scope = {'type':'http', 'method':'GET', 'headers':[]}
        task = asyncio.create_task(response(scope, receive, send))
        await asyncio.wait_for(started.wait(), 2)
        if not disconnect:
            task.cancel()
        try:
            await asyncio.wait_for(task, 2)
        except asyncio.CancelledError:
            pass
        assert response.lease.fd is None
    asyncio.run(run(True))
    asyncio.run(run(False))


def test_process_shared_pin_and_hash_dedup(store):
    import subprocess
    import sys
    engine, cache = store
    first = get(engine, 'a')
    script = '''
import hashlib, os
from app.services.blob_cache import acquire
from fastapi import HTTPException
payload = b'a'*4096
lease = acquire(hashlib.sha256(payload).hexdigest(),len(payload),lambda:iter([payload]))
print(os.fstat(lease.fd).st_ino, flush=True)
lease.close()
payload = b'b'*4096
lease = acquire(hashlib.sha256(payload).hexdigest(),len(payload),lambda:iter([payload]))
try:
    payload = b'c'*4096
    acquire(hashlib.sha256(payload).hexdigest(),len(payload),lambda:iter([payload]))
except HTTPException as exc:
    print(exc.status_code, flush=True)
finally:
    lease.close()
'''
    try:
        proc = subprocess.run([sys.executable,'-c',script], capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.splitlines() == [str(os.fstat(first.lease.fd).st_ino),'503']
        assert len(list(cache.glob('*.bin'))) == 2
    finally:
        first.lease.close()


def test_reserved_fill_budget_and_crash_recovery(store):
    import select
    import subprocess
    import sys
    engine, cache = store
    first = get(engine, 'a')
    script = '''
import hashlib, time
from app.services.blob_cache import acquire
payload = b'b'*4096
def chunks():
    print('reserved', flush=True)
    time.sleep(30)
    yield payload
acquire(hashlib.sha256(payload).hexdigest(),len(payload),chunks)
'''
    process = subprocess.Popen([sys.executable,'-c',script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        assert process.stdout.readline().strip() == 'reserved'
        files = list(cache.glob('*.bin')) + list(cache.glob('.fill-*'))
        assert len(files) == 2
        assert sum(p.stat().st_blocks*512 for p in files) <= 8192
    finally:
        process.kill(); process.wait(timeout=5)
        process.stdout.close(); process.stderr.close()
    try:
        third = get(engine, 'c')
        third.lease.close()
        assert not list(cache.glob('.fill-*'))
        assert first.lease.path.read_bytes() == b'a'*4096
    finally:
        first.lease.close()
