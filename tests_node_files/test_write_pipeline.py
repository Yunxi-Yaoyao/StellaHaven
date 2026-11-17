import hashlib
import time
from uuid import uuid4
import httpx
from test_pipeline import submit, complete
from app.database import sessionLocal
from app.models.node_file import FileJob
from app.models.user import AuthSession
from app.security import make_access_token


def upload(s, op, path, data, **extra):
    job = submit(s, op, path, size=len(data), sha256=hashlib.sha256(data).hexdigest(), **extra)
    assert job['state'] == 'uploading'
    for offset in range(0, len(data), 65536):
        response = s['client'].put('/node-files/requests/' + job['id'] + '/upload', params={'offset': offset}, content=data[offset:offset+65536])
        assert response.status_code == 200, response.text
    sealed = s['client'].post('/node-files/requests/' + job['id'] + '/seal')
    assert sealed.status_code == 200, sealed.text
    return complete(s, job)


def test_raw_upload_cas_create_rename_copy_move(system):
    s = system
    data = bytes(range(256)) * 600
    job = upload(s, 'upload', 'raw-upload.bin', data)
    assert job['state'] == 'done', job
    assert (s['root'] / 'raw-upload.bin').read_bytes() == data
    assert complete(s, submit(s, 'mkdir', 'write-folder'))['state'] == 'done'
    assert complete(s, submit(s, 'create', 'new.txt'))['state'] == 'done'
    assert complete(s, submit(s, 'rename', 'new.txt', destination='renamed.txt'))['state'] == 'done'
    assert complete(s, submit(s, 'copy', 'raw-upload.bin', destination='write-folder/copy.bin'))['state'] == 'done'
    assert complete(s, submit(s, 'move', 'renamed.txt', destination='write-folder/moved.txt'))['state'] == 'done'
    assert (s['root'] / 'write-folder/copy.bin').read_bytes() == data
    assert (s['root'] / 'write-folder/moved.txt').is_file()
    assert upload(s, 'upload', 'raw-upload.bin', b'no overwrite')['error'] == 'destination_exists'
    assert (s['root'] / 'raw-upload.bin').read_bytes() == data
    preview = complete(s, submit(s, 'preview', 'hello.txt'))['result']
    (s['root'] / 'hello.txt').write_text('outside edit')
    failed = upload(s, 'edit', 'hello.txt', b'edited', etag=preview['etag'])
    assert failed['state'] == 'failed' and failed['error'] == 'cas_conflict'
    assert (s['root'] / 'hello.txt').read_text() == 'outside edit'
    fresh = complete(s, submit(s, 'preview', 'hello.txt'))['result']
    assert upload(s, 'edit', 'hello.txt', '已保存\n'.encode(), etag=fresh['etag'])['state'] == 'done'
    assert (s['root'] / 'hello.txt').read_text() == '已保存\n'


def test_staging_cancel_and_result_never_contains_file_body(system):
    s = system
    # This test is collected before the unknown-fence test by the runner order.
    data = b'private synthetic file body'
    job = submit(s, 'upload', 'cancelled-upload', size=len(data), sha256=hashlib.sha256(data).hexdigest())
    assert s['client'].put('/node-files/requests/' + job['id'] + '/upload', params={'offset': 0}, content=data).status_code == 200
    s['client'].post('/node-files/requests/' + job['id'] + '/cancel').raise_for_status()
    assert s['client'].post('/node-files/requests/' + job['id'] + '/seal').status_code == 409
    s['worker'].tick()
    assert not (s['root'] / 'cancelled-upload').exists()
    with sessionLocal() as db:
        row = db.get(FileJob, job['id'])
        assert 'private synthetic' not in str(row.request)
        assert row.state == 'cancelled'
        from app.services.node_files import spool
        assert not spool(row).exists(), 'cancelled staging bytes must be cleaned immediately'


def test_idempotency_and_raw_chunk_concurrency(system):
    from concurrent.futures import ThreadPoolExecutor
    s = system
    key = str(uuid4())
    payload = {'request_key': key, 'node_id': 930001, 'root': 'fixture', 'op': 'create', 'path': 'concurrent-created.txt'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(s['client'].post, '/node-files/requests', json=payload) for _ in range(2)]
        responses = [f.result(timeout=10) for f in futures]
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()['id'] == responses[1].json()['id']
    assert complete(s, responses[0].json())['state'] == 'done'
    assert s['client'].post('/node-files/requests', json=payload).json()['state'] == 'done'
    receipt = s['client'].get('/node-files/by-key/' + key)
    assert receipt.status_code == 200 and receipt.json()['id'] == responses[0].json()['id']
    changed = {**payload, 'path': 'changed-target'}
    assert s['client'].post('/node-files/requests', json=changed).status_code == 409
    data = b'concurrent body'
    job = submit(s, 'upload', 'concurrent-upload.txt', size=len(data), sha256=hashlib.sha256(data).hexdigest())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(s['client'].put, '/node-files/requests/' + job['id'] + '/upload', params={'offset': 0}, content=data) for _ in range(2)]
        responses = [f.result(timeout=10) for f in futures]
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert s['client'].post('/node-files/requests/' + job['id'] + '/seal').status_code == 200
    assert complete(s, job)['state'] == 'done'
    assert (s['root'] / 'concurrent-upload.txt').read_bytes() == data


def test_post_commit_io_failure_is_unknown_not_false_failure(system, monkeypatch):
    import json
    import os
    import stat
    from agent import node_files as nf
    s = system
    directory = s['root'] / 'uncertain-root'
    directory.mkdir()
    policy = json.loads(s['policy'].read_text())
    policy['930001']['uncertain'] = {'owners': [str(s['uid'])], 'write': True}
    s['policy'].write_text(json.dumps(policy))
    s['worker'].sandbox.allowed['uncertain'] = {'path': str(directory), 'write': True}
    s['worker'].tick()
    job = submit(s, 'create', 'commit.txt', root='uncertain')
    real_fsync = os.fsync
    def fail_directory_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError('synthetic post-commit directory sync failure')
        return real_fsync(fd)
    with monkeypatch.context() as scope:
        scope.setattr(nf.os, 'fsync', fail_directory_sync)
        result = complete(s, job)
    assert (directory / 'commit.txt').is_file(), 'fault must occur AFTER real mutation'
    assert result['state'] == 'unknown', result
    assert complete(s, submit(s, 'list', root='uncertain'))['state'] == 'done'
    blocked = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'uncertain', 'op': 'create', 'path': 'retry.txt'})
    assert blocked.status_code == 409


def test_revoked_root_cannot_replay_cached_request_result(system):
    s = system
    job = complete(s, submit(s, 'preview', 'hello.txt'))
    original = s['policy'].read_text()
    try:
        s['policy'].write_text('{}')
        replay = s['client'].post('/node-files/requests', json={'request_key': job['request_key'], 'node_id': 930001, 'root': 'fixture', 'op': 'preview', 'path': 'hello.txt'})
        assert replay.status_code == 404, 'idempotency must not bypass a revoked root grant'
        assert s['client'].get('/node-files/requests/' + job['id']).status_code == 404
    finally:
        s['policy'].write_text(original)


def test_database_row_lock_wait_never_blocks_event_loop(system):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import event, select
    from app.database import engine
    s = system
    data = b'x'
    job = submit(s, 'upload', 'row-lock-wait', size=1, sha256=hashlib.sha256(data).hexdigest())
    reached = threading.Event()
    def observe(conn, cursor, statement, parameters, context, executemany):
        if 'node_file_jobs' in statement and 'FOR UPDATE' in statement:
            reached.set()
    held = sessionLocal()
    held.scalar(select(FileJob).where(FileJob.id == job['id']).with_for_update())
    event.listen(engine, 'before_cursor_execute', observe)
    responsive = False
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(s['client'].put, '/node-files/requests/' + job['id'] + '/upload', params={'offset': 0}, content=data)
            try:
                assert reached.wait(2), 'upload did not reach the real PG lock'
                try:
                    response = httpx.get(s['url'] + '/node-files/nodes', cookies=dict(s['client'].cookies), timeout=1.5)
                    responsive = response.status_code == 200
                except httpx.TimeoutException:
                    responsive = False
            finally:
                held.rollback()
            assert pending.result(timeout=5).status_code == 200
    finally:
        held.close()
        event.remove(engine, 'before_cursor_execute', observe)
        s['client'].post('/node-files/requests/' + job['id'] + '/cancel').raise_for_status()
    assert responsive, 'synchronous row-lock wait blocked the ASGI event loop'


def test_unknown_write_blocks_replay_but_allows_readonly_reconciliation(system):
    s = system
    job = submit(s, 'create', 'must-not-execute.txt')
    claim = s['worker'].client.post('/agent/files/claim', json={'roots': {'fixture': True}}).json()
    assert claim['id'] == job['id']
    cancelled = s['client'].post('/node-files/requests/' + job['id'] + '/cancel').json()
    assert cancelled['state'] == 'unknown'
    late = s['worker'].client.post('/agent/files/requests/' + job['id'] + '/result', json={'lease': claim['lease'], 'result': {'path': 'must-not-execute.txt'}})
    assert late.status_code == 409
    assert not (s['root'] / 'must-not-execute.txt').exists()
    # Read-only check remains executable, not a repeated write.
    assert complete(s, submit(s, 'list'))['state'] == 'done'
    sid = uuid4()
    with sessionLocal() as db:
        db.add(AuthSession(id=sid, user_id=s['uid'], refresh_hash=uuid4().hex))
        db.commit()
    with httpx.Client(base_url=s['url'], cookies={'stella_at': make_access_token(str(s['uid']), str(sid))}) as client:
        blocked = client.post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'create', 'path': 'bypass.txt'})
        assert blocked.status_code == 409
    # Keep unknown result in the journal. The fixture uses a DIFFERENT explicit
    # root ID for following tests rather than offering a product "clear unknown".
    with sessionLocal() as db:
        assert db.get(FileJob, job['id']).state == 'unknown'


