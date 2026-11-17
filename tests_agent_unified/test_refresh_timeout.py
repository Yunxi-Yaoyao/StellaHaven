"""Only network socket timeouts may retain an already verified bound worker."""
import hashlib
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError

import pytest
from agent import stella_agent as a
from agent import node_files_delivery as d
from test_unified_agent import center, wait_until


@pytest.mark.parametrize('error,temporary', [
    (TimeoutError(), True), (socket.timeout(), True),
    (URLError(TimeoutError()), True),
    (URLError('timed out'), False), (URLError(ConnectionRefusedError()), False),
    (URLError(ssl.SSLCertVerificationError(1, 'untrusted fixture')), False),
    (ssl.SSLCertVerificationError(1, 'untrusted fixture'), False),
    (HTTPError('https://owned.invalid', 401, TimeoutError(), {}, None), False),
    (HTTPError('https://owned.invalid', 403, TimeoutError(), {}, None), False),
    (HTTPError('https://owned.invalid', 503, 'unavailable', {}, None), False),
    (ValueError('hash mismatch'), False),
    (subprocess.TimeoutExpired('load-probe', 10), False),
])
def test_exact_transport_timeout_classification(monkeypatch, error, temporary):
    import urllib.request
    class Opener:
        def open(self, *args, **kwargs): raise error
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    fetch = a._file_fetcher({'origin': 'https://owned.invalid', 'token': 'synthetic'})
    if temporary:
        with pytest.raises(a._FileNetworkTimeout): fetch('/agent/identity', 8192)
    else:
        with pytest.raises(type(error)) as refused: fetch('/agent/identity', 8192)
        assert refused.value is error
        assert not isinstance(refused.value, a._FileNetworkTimeout)


def spec_for(center, tmp_path):
    return {'origin': center['url'], 'token': 'owned-refresh-only',
            'binding': dict(center['identity']), 'legacy': None, 'store': str(tmp_path / 'packages')}


@pytest.mark.parametrize('cached', [False, True])
def test_actual_startup_timeout_never_creates_worker_or_authority(center, tmp_path, cached):
    if cached:
        manifest, bodies = d.build_release(Path(a.__file__).parent)
        a._FilePackage(tmp_path / 'packages').install(manifest, lambda path, limit: bodies[path.rsplit('/', 1)[-1]])
    center['delay'] = 4
    manager = a._FileSupervisor(lambda: spec_for(center, tmp_path), allow_loopback=True)
    try:
        manager.tick(); prepare = manager.preparing
        wait_until(lambda: prepare.poll() is not None)
        assert prepare.returncode == 75
        manager.tick()
        assert manager.worker is None and manager.worker_key is None
        assert manager.bound_identity is None and center['claims'] == 0
        assert (tmp_path / 'packages/current.json').exists() is cached
        assert manager.next_prepare > time.monotonic()
    finally: manager.close()


@pytest.mark.parametrize('change', ['center', 'node', 'disabled', 'roots', 'bad_manifest', 'same_version_drift', 'bad_package'])
def test_verified_worker_still_stops_on_identity_revocation_and_integrity(center, tmp_path, change):
    spec = spec_for(center, tmp_path)
    manager = a._FileSupervisor(lambda: dict(spec), allow_loopback=True, refresh=.15)
    try:
        wait_until(lambda: (manager.tick() or True) and center['claims'] > 0)
        worker = manager.worker
        if change == 'center': center['identity']['center_id'] = 'd' * 64
        elif change == 'node': center['identity']['node_id'] = 2
        elif change == 'disabled': center['config']['enabled'] = False
        elif change == 'roots': center['config']['roots'] = {}
        elif change == 'bad_manifest': center['manifest']['files']['node_files.py']['sha256'] = '0' * 64
        elif change == 'same_version_drift': center['manifest']['files']['stella_agent.py']['sha256'] = '0' * 64
        elif change == 'bad_package':
            # A new module release must actually fetch bytes (not cached reuse).
            body = center['bodies']['node_files.py'].replace(b"FILE_MODULE_VERSION = '1.0.0'", b"FILE_MODULE_VERSION = '1.0.1'", 1)
            assert body != center['bodies']['node_files.py']
            center['manifest']['files']['node_files.py'].update(version='1.0.1', size=len(body), sha256=hashlib.sha256(body).hexdigest())
            center['bad'] = True
        wait_until(lambda: (manager.tick() or True) and worker.poll() is not None)
        assert manager.worker is None and not Path('/proc/' + str(worker.pid)).exists()
    finally: manager.close()


@pytest.mark.parametrize('change', ['origin', 'token', 'binding'])
def test_local_binding_changes_stop_worker_before_any_retry(center, tmp_path, change):
    spec = spec_for(center, tmp_path)
    manager = a._FileSupervisor(lambda: dict(spec), allow_loopback=True)
    try:
        wait_until(lambda: (manager.tick() or True) and center['claims'] > 0)
        worker = manager.worker
        if change == 'origin': spec['origin'] = center['url'] + '/'
        elif change == 'token': spec['token'] = 'synthetic-replacement'
        else: spec['binding'] = {'center_id': 'f' * 64, 'node_id': 9}
        manager.tick()
        assert worker.poll() is not None and manager.worker is None
        assert manager.worker_key is None
    finally: manager.close()


@pytest.mark.parametrize('status', [401, 403, 503, 'drip'])
def test_real_http_refusal_stops_verified_worker(center, tmp_path, status):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    manifest, bodies = d.build_release(Path(a.__file__).parent)
    state = {'status': 200}
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/agent/identity': value = center['identity']
            elif self.path == '/agent/files/config': value = center['config']
            elif self.path == '/agent/files/release': value = manifest
            else: value = bodies[self.path.rsplit('/', 1)[-1]]
            code = state['status'] if self.path == '/agent/files/config' else 200
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            if code == 'drip':
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
                # Reads keep succeeding without completing the config body.
                try:
                    for byte in body:
                        if release.wait(.5): break
                        self.wfile.write(bytes([byte])); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError): pass
                return
            self.send_response(code); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200); self.end_headers(); self.wfile.write(b'null')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    spec = spec_for(center, tmp_path); spec['origin'] = 'http://127.0.0.1:' + str(server.server_port)
    manager = a._FileSupervisor(lambda: dict(spec), allow_loopback=True, refresh=.15)
    try:
        wait_until(lambda: (manager.tick() or True) and manager.worker is not None)
        worker = manager.worker; state['status'] = status
        notices = []; manager._notice = notices.append
        started = time.monotonic()
        wait_until(lambda: (manager.tick() or True) and worker.poll() is not None, timeout=26 if status == 'drip' else 8)
        assert manager.worker is None
        if status == 'drip':
            assert time.monotonic() - started >= 20
            assert 'configuration/package deadline exceeded' in notices
            assert not any('retained' in notice for notice in notices)
    finally:
        release.set(); manager.close(); server.shutdown(); server.server_close(); thread.join(3)


def test_real_untrusted_tls_is_not_a_temporary_timeout(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    result = subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    spec = {'origin': 'https://127.0.0.1:' + str(server.server_port), 'token': 'owned-tls-only', 'binding': None, 'legacy': None, 'store': str(tmp_path / 'packages')}
    manager = a._FileSupervisor(lambda: spec)
    try:
        manager.tick(); prepare = manager.preparing
        wait_until(lambda: prepare.poll() is not None)
        assert prepare.returncode == 1
        manager.tick(); assert manager.worker is None and manager.bound_identity is None
        assert not (tmp_path / 'packages').exists()
    finally:
        manager.close(); server.shutdown(); server.server_close(); thread.join(3)


def test_real_ten_second_load_deadline_remains_fail_closed(center, tmp_path):
    spec = spec_for(center, tmp_path)
    manager = a._FileSupervisor(lambda: dict(spec), allow_loopback=True, refresh=.15)
    try:
        wait_until(lambda: (manager.tick() or True) and center['claims'] > 0)
        worker = manager.worker
        body = center['bodies']['stella_agent.py'].replace(b'AGENT_VERSION = "0.6.21"', b'AGENT_VERSION = "0.6.22"', 1)
        assert body != center['bodies']['stella_agent.py']
        marker = tmp_path / 'load-entered'
        body += ('\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("ready")\nimport time\ntime.sleep(60)\n').encode()
        center['bodies']['stella_agent.py'] = body
        center['manifest']['version'] = '0.6.22'
        center['manifest']['files']['stella_agent.py'].update(version='0.6.22', size=len(body), sha256=hashlib.sha256(body).hexdigest())
        # The load probe's existing ten-second deadline also remains fatal; it
        # must never be confused with a network timeout by exception name.
        wait_until(lambda: (manager.tick() or True) and marker.exists())
        wait_until(lambda: (manager.tick() or True) and worker.poll() is not None, timeout=23)
        assert manager.worker is None
    finally: manager.close()
