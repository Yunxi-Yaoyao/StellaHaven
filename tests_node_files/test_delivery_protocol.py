"""Actual authenticated HTTP distribution -> private generation install."""
from uuid import uuid4


def test_authenticated_complete_release_http_install(system, tmp_path):
    import httpx
    from agent.node_files_delivery import ReleaseStore, canonical, release_id
    s = system
    with httpx.Client(base_url=s['url'], headers={'Authorization': 'Bearer ' + s['token']}, trust_env=False) as agent:
        response = agent.get('/agent/files/release')
        assert response.status_code == 200, 'missing authenticated complete-release distribution'
        assert response.headers['cache-control'] == 'no-store'
        manifest = response.json()
        identity = release_id(manifest)
        def fetch(name, info):
            result = agent.get('/agent/files/release/' + identity + '/' + name)
            assert result.status_code == 200
            assert result.headers['cache-control'] == 'no-store'
            return result.content
        store = ReleaseStore(tmp_path / 'http-installed')
        path = store.install(manifest, fetch)
        assert (path / 'manifest.json').read_bytes() == canonical(manifest)
        assert store.current() == path
        assert agent.get('/agent/files/release/' + '0' * 64 + '/node_files.py').status_code == 409
        assert agent.get('/agent/files/release/' + identity + '/install.sh').status_code == 404
        assert agent.post('/agent/files/release', json={'command': 'ignored'}).status_code == 405
        from agent.node_files_delivery import download_release, ReleaseError
        import pytest
        refused_store = ReleaseStore(tmp_path / 'refused-pin')
        with pytest.raises(ReleaseError, match='pin_mismatch'):
            download_release(s['url'], s['token'], refused_store, '0' * 64, allow_loopback=True)
        assert refused_store.current() is None
    with httpx.Client(base_url=s['url'], trust_env=False) as anonymous:
        assert anonymous.get('/agent/files/release').status_code == 401
        assert anonymous.get('/agent/files/release/' + identity + '/node_files.py').status_code == 401
    with httpx.Client(base_url=s['url'], headers={'Authorization': 'Bearer synthetic-invalid-' + uuid4().hex}, trust_env=False) as stranger:
        assert stranger.get('/agent/files/release').status_code == 401


def test_downloaded_worker_process_uses_real_protocol_with_read_only_grant(system, tmp_path):
    from agent import node_files_delivery as delivery
    assert hasattr(delivery, 'download_release'), 'missing pinned downloader and installed worker entrypoint'
    import hashlib
    import json
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path
    s = system
    import httpx
    with httpx.Client(base_url=s['url'], headers={'Authorization': 'Bearer ' + s['token']}, trust_env=False) as client:
        manifest = client.get('/agent/files/release').json()
    identity = delivery.release_id(manifest)
    store = delivery.ReleaseStore(tmp_path / 'service-install')
    active = delivery.download_release(s['url'], s['token'], store, identity, allow_loopback=True)
    env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'HOME')}
    env.update(STELLA_TOKEN=s['token'], STELLA_FILE_ROOTS=json.dumps({'fixture': {'path': str(s['root']), 'write': False}}), PYTHONDONTWRITEBYTECODE='1')
    script = Path(delivery.__file__).resolve()
    argv = [sys.executable, '-I', '-B', str(script), 'run', '--store', str(store.root), '--origin', s['url'], '--allow-loopback', '--interval', '.05']
    log = tmp_path / 'worker.log'
    with log.open('w') as out:
        process = subprocess.Popen(argv, env=env, cwd=tmp_path, stdout=out, stderr=out)
        try:
            for _ in range(120):
                if '"event": "start"' in log.read_text():
                    break
                assert process.poll() is None, log.read_text()
                time.sleep(.05)
            else:
                raise AssertionError(log.read_text())
            start = json.loads(log.read_text().splitlines()[0])
            assert start['module_sha256'] == manifest['files']['node_files.py']['sha256']
            assert start['release'] == identity and start['app_imported'] is False and start['postgres_environment_present'] is False
            def request(op, path=''):
                response = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': op, 'path': path})
                assert response.status_code == 201, response.text
                job = response.json()
                for _ in range(120):
                    result = s['client'].get('/node-files/requests/' + job['id'])
                    assert result.status_code == 200, result.text
                    if result.json()['state'] in ('done', 'failed', 'unknown'):
                        assert result.json()['state'] == 'done', result.text
                        return result.json()
                    time.sleep(.05)
                raise AssertionError(result.text)
            listing = request('list')
            assert 'hello.txt' in {x['name'] for x in listing['result']['entries']}
            preview = request('preview', 'hello.txt')
            assert preview['result']['text'] == (s['root'] / 'hello.txt').read_text()
            download = request('download', 'download.bin')
            body = s['client'].get('/node-files/requests/' + download['id'] + '/download').content
            assert body == s['binary']
            assert hashlib.sha256(body).hexdigest() == download['result']['sha256']
            denied = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'create', 'path': 'must-not-exist'})
            assert denied.status_code == 403 and not (s['root'] / 'must-not-exist').exists()
        finally:
            process.terminate()
            process.wait(timeout=15)
    assert process.returncode == 0, log.read_text()
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert events[-1]['event'] == 'stop' and events[-1]['ticks'] > 0
    phase_events = {'readonly': events}
    from app.database import sessionLocal
    from app.models.node_file import FileAgent
    for phase, roots in [('empty', None), ('writable', {'fixture': {'path': str(s['root']), 'write': True}})]:
        phase_env = dict(env)
        phase_env.pop('STELLA_FILE_ROOTS')
        if roots is not None:
            phase_env['STELLA_FILE_ROOTS'] = json.dumps(roots)
        phase_log = tmp_path / (phase + '.log')
        with phase_log.open('w') as out:
            process = subprocess.Popen(argv, env=phase_env, cwd=tmp_path, stdout=out, stderr=out)
            try:
                expected_roots = {} if phase == 'empty' else {'fixture': True}
                for _ in range(120):
                    assert process.poll() is None, phase_log.read_text()
                    with sessionLocal() as db:
                        registered = db.get(FileAgent, 930001)
                        if '"event": "start"' in phase_log.read_text() and registered.roots == expected_roots:
                            break
                    time.sleep(.05)
                else:
                    raise AssertionError(phase_log.read_text())
                if phase == 'empty':
                    denied = s['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'fixture', 'op': 'list'})
                    assert denied.status_code == 409 and denied.json()['detail'] == 'agent_root_not_allowed'
                else:
                    request('create', 'deployed-create')
                    assert (s['root'] / 'deployed-create').read_bytes() == b''
            finally:
                process.terminate()
                process.wait(timeout=15)
        assert process.returncode == 0, phase_log.read_text()
        phase_events[phase] = [json.loads(line) for line in phase_log.read_text().splitlines()]
        assert phase_events[phase][-1]['event'] == 'stop'
    (s['root'] / 'deployed-create').unlink()
    # Missing module at installed boot must fail before any claim or fallback.
    (active / 'node_files.py').unlink()
    failed = subprocess.run(argv, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert failed.returncode != 0 and '"event": "start"' not in failed.stdout
    evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
    (evidence / 'installed-worker.json').write_text(json.dumps({'release': identity, 'module_sha256': start['module_sha256'], 'bytes': len(body), 'download_sha256': hashlib.sha256(body).hexdigest(), 'events': phase_events, 'missing_module_exit': failed.returncode, 'worker_env_keys': sorted(env)}, indent=2))


def test_real_worker_failed_start_rolls_back_complete_release(system, tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    import pytest
    from agent import node_files_delivery as d
    from app.database import sessionLocal
    from app.models.node_file import FileAgent
    manifest, bodies = d.build_release(Path(d.__file__).parent)
    store = d.ReleaseStore(tmp_path / 'actual-start-rollback')
    original = store.install(manifest, lambda name, info: bodies[name])
    pointer = (store.root / 'current.json').read_bytes()
    candidate = tmp_path / 'new-module'
    candidate.mkdir()
    for name, body in bodies.items():
        (candidate / name).write_bytes(body.replace(b"FILE_MODULE_VERSION = '1.0.0'", b"FILE_MODULE_VERSION = '1.0.1'"))
    target_manifest, target_bodies = d.build_release(candidate)
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR')}
    env.update(STELLA_TOKEN=system['token'], STELLA_FILE_ROOTS='{"fixture":{"path":"/not-authorized","write":"true"}}')
    with sessionLocal() as db:
        before = db.get(FileAgent, 930001).seen
    with pytest.raises(subprocess.CalledProcessError) as failed:
        with store.transaction(target_manifest, lambda name, info: target_bodies[name]) as active:
            assert active != original and store.current() == active
            subprocess.run([sys.executable, '-I', '-B', d.__file__, 'run', '--store', str(store.root), '--origin', system['url'], '--allow-loopback'], env=env, cwd=tmp_path, capture_output=True, text=True, check=True, timeout=20)
    assert failed.value.returncode == 1 and '"event": "start"' not in failed.value.stdout
    assert store.current() == original
    assert (store.root / 'current.json').read_bytes() == pointer
    assert d.installed_module(store)[0].FILE_MODULE_VERSION == '1.0.0'
    with sessionLocal() as db:
        assert db.get(FileAgent, 930001).seen == before
    (Path(os.environ['NODE_FILES_EVIDENCE']) / 'actual-start-rollback.json').write_text(json.dumps({'old_release': original.name, 'refused_release': d.release_id(target_manifest), 'child_exit': failed.value.returncode, 'pointer_restored_exactly': True, 'agent_presence_unchanged': True}, indent=2))
