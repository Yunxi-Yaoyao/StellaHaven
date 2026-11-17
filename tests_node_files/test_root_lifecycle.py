"""Explicit / advertisement only; never issue a host-/ filesystem request.

Filesystem / operations live in test_root_scope's owned mount+chroot fixture.
"""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from tests_node_files.test_lifecycle_protocol import real_identity_transport
from tests_node_files.test_lifecycle_stop_recovery import unprivileged


def test_root_policy_survives_real_uid_lifecycle_environment_whitelist(system, tmp_path, monkeypatch):
    assert os.environ.get('NODE_FILES_NAMESPACE_FIXTURE') == '1'
    lc, lifecycle, adapter = unprivileged(system, tmp_path, monkeypatch)
    config = lifecycle.config / 'files.env'
    config.write_text('STELLA_FILE_ROOTS=' + json.dumps(json.dumps({'system': {'path': '/'}})) + '\nPOSTGRES_PASSWORD=synthetic-not-a-secret\nHTTP_PROXY=http://127.0.0.1:1\nUNRELATED_SYNTHETIC=must-drop\n')
    config.chmod(0o600)
    policy = json.loads(system['policy'].read_text())
    policy['930001']['system'] = {'owners': [str(system['uid'])], 'label': '/', 'write': False}
    system['policy'].write_text(json.dumps(policy))
    package = tmp_path / 'root-package.tar'
    pin = lc.build_package(Path(lc.__file__).parent, package)
    protected = {p: p.read_bytes() for p in (lifecycle.config / 'agent.env', lifecycle.config / 'instance.json', lifecycle.code / 'stella_agent.py')}
    try:
        status = lifecycle.install(package, pin['sha256'], pin['release'], sys.executable)
        assert status['authenticated_ready'] and status['integrity']
        from app.database import sessionLocal
        from app.models.node_file import FileAgent
        with sessionLocal() as db:
            assert db.get(FileAgent, 930001).roots == {'system': False}
        response = system['client'].post('/node-files/requests', json={'request_key': str(uuid4()), 'node_id': 930001, 'root': 'system', 'op': 'create', 'path': 'never-created'})
        assert response.status_code == 403, response.text
        log = adapter.logs[-1].read_text()
        start = next(json.loads(x) for x in log.splitlines() if x.startswith('{') and json.loads(x).get('event') == 'start')
        assert start['roots'] == [{'id': 'system', 'write': False}]
        assert not start['app_imported'] and not start['postgres_environment_present']
        proc = Path(f'/proc/{adapter.process.pid}/status').read_text()
        assert set(next(x for x in proc.splitlines() if x.startswith('Uid:')).split()[1:]) == {'65534'}
        assert all(p.read_bytes() == body for p, body in protected.items())
        assert config.read_text().startswith('STELLA_FILE_ROOTS=')
        stopped = lifecycle.stop()
        assert stopped['systemd']['MainPID'] == '0' and adapter.process.poll() is not None
        (Path(os.environ['NODE_FILES_EVIDENCE']) / 'root-lifecycle.json').write_text(json.dumps({'pin': pin, 'start': start, 'uid': 65534, 'readonly_write_http_status': response.status_code, 'host_root_filesystem_requests': 0, 'protected_unchanged': True, 'child_stopped': True, 'boundary': 'real independent dropped-UID worker/HTTP/PG; fixture systemd, no PID1 deployment'}, indent=2))
    finally:
        adapter.halt()
        system['policy'].write_text(json.dumps({k: {r: v for r, v in roots.items() if r != 'system'} for k, roots in policy.items()}))
