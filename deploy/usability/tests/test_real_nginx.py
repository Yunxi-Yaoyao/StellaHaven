"""REAL nginx + TLS, isolated loopback fixture upstream; no production requests.
Tests use synthetic fixtures explicitly, never pretend these are new image assets.
"""
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_deploysafe as fixtures

d, BASE = fixtures.d, fixtures.BASE


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which('nginx') and shutil.which('openssl') and shutil.which('curl'), 'nginx/openssl/curl required')
class RealNginx(unittest.TestCase):
    def test_tls_static_primary_private_gzip_logs_retention_and_rollback(self):
        tmp = tempfile.TemporaryDirectory(prefix='stella-edge-nginx-', dir=os.environ['TMPDIR'])
        root = Path(tmp.name)
        upstream, process = None, None
        try:
            fixture = fixtures.Tests()
            fixture.root = root
            a, m1 = fixture.stage()
            b, m2 = fixture.stage('ijklmnop')
            port, redirect_port = free_port(), free_port()
            class Handler(BaseHTTPRequestHandler):
                primary = True
                source = d.read(a / 'source-index.html')
                def log_message(self, format, *args):
                    pass
                def do_GET(self):
                    if self.headers.get('Upgrade') == 'websocket':
                        self.send_response(101)
                        self.send_header('Upgrade', 'websocket')
                        self.send_header('Connection', 'Upgrade')
                        self.end_headers()
                        return
                    status = 200 if self.primary else 503
                    if self.path.startswith(('/attachments/', '/assets/private', '/app/data')):
                        status = 403
                    body = self.source if self.path in ('/', '/source') else ('PRIMARY ' + self.path).encode()
                    self.send_response(status)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'private, no-store')
                    self.end_headers()
                    self.wfile.write(body)
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=upstream.serve_forever, daemon=True)
            thread.start()
            cert, key = root / 'cert.pem', root / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=stella.xiya.live', '-addext', 'subjectAltName=DNS:stella.xiya.live,DNS:other.xiya.live,DNS:app-test.xiya.live',
                            '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
            vhost = root / 'stella.conf'
            original = BASE.replace('listen 80;', f'listen 127.0.0.1:{redirect_port};').replace('listen 443 ssl;', f'listen 127.0.0.1:{port} ssl;')
            original = original.replace('/etc/ssl/xiya.live/fullchain.pem', str(cert)).replace('/etc/ssl/xiya.live/privkey.pem', str(key))
            original = original.replace('http://127.0.0.1:12031', f'http://127.0.0.1:{upstream.server_port}').replace('/var/log/nginx/stella-safe-access.log', str(root / 'safe.log'))
            vhost.write_text(original)
            # Strict production renderer only understands reviewed production layout;
            # translate the scratch fixture at the renderer boundary, never loosen it.
            real_render = d.render
            def scratch_render(old, assets):
                self.assertEqual(old, original if '# BEGIN STELLA EDGE' not in old else old)
                normalized = old.replace(f'listen 127.0.0.1:{redirect_port};', 'listen 80;').replace(f'listen 127.0.0.1:{port} ssl;', 'listen 443 ssl;')
                normalized = normalized.replace(f'http://127.0.0.1:{upstream.server_port}', 'http://127.0.0.1:12031')
                value = real_render(normalized, assets, str(root / 'safe.log'))
                return value.replace('listen 80;', f'listen 127.0.0.1:{redirect_port};').replace('listen 443 ssl;', f'listen 127.0.0.1:{port} ssl;').replace('http://127.0.0.1:12031', f'http://127.0.0.1:{upstream.server_port}')
            conf = root / 'nginx.conf'
            other = f'''server {{ listen 127.0.0.1:{port} ssl; server_name other.xiya.live;
ssl_certificate {cert}; ssl_certificate_key {key}; location / {{ return 200 'OTHER DOMAIN'; }} }}
server {{ listen 127.0.0.1:{port} ssl; server_name app-test.xiya.live;
ssl_certificate {cert}; ssl_certificate_key {key}; location / {{ return 200 'INTEGRATION PRIMARY'; }} }}
'''
            conf.write_text(f'''user root;
worker_processes 1;
pid {root}/nginx.pid;
error_log {root}/nginx-error.log crit;
events {{ worker_connections 128; }}
http {{ include /etc/nginx/mime.types; default_type application/octet-stream;
access_log off;
log_format stella_upgrade_safe '$uri $status';
include {vhost};
{other}
}}
''')
            def run(argv):
                if argv[0] == 'nginx':
                    argv = ['nginx', '-p', str(root), '-c', str(conf)] + argv[1:]
                return d.command(argv, timeout=15)
            run(['nginx', '-t'])
            process = subprocess.Popen(['nginx', '-p', str(root), '-c', str(conf), '-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            def get(path, host='stella.xiya.live', compressed=False, extra=()):
                headers = root / ('headers-' + str(time.monotonic_ns()))
                argv = ['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '3',
                        '--resolve', f'{host}:{port}:127.0.0.1', '--cacert', str(cert), '-D', str(headers)]
                if compressed:
                    argv += ['--compressed']
                argv += list(extra) + [f'https://{host}:{port}{path}']
                body = d.command(argv, timeout=5)
                h = headers.read_text().lower()
                status = int(h.splitlines()[0].split()[1])
                return status, h, body
            deadline = time.monotonic() + 5
            while True:
                try:
                    self.assertEqual(get('/live')[0], 200)
                    break
                except (ValueError, AssertionError):
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.03)
            # Use real nginx validation/reload/readback, real HTTP hashes as health.
            fail_health = False
            def health(m, assets, primary_manifest=None):
                if fail_health:
                    raise ValueError('injected post-reload health failure')
                self.assertEqual(d.sha(get('/')[2]), (primary_manifest or m)['files']['index.html']['sha256'])
                deadline = time.monotonic() + 5
                stable_since = None
                while True:
                    if all(get('/' + n)[0] == 200 and d.sha(get('/' + n)[2]) == assets[n]['sha256'] for n in m['public']):
                        if stable_since is None:
                            stable_since = time.monotonic()
                        if time.monotonic() - stable_since > 0.3:
                            break
                    else:
                        stable_since = None
                    if time.monotonic() > deadline:
                        raise ValueError('scratch reload timeout')
                    time.sleep(0.03)
                for name in m['public']:
                    code, headers, body = get('/' + name)
                    self.assertEqual(code, 200)
                    self.assertEqual(d.sha(body), assets[name]['sha256'])
                    self.assertIn('public, max-age=604800, immutable', headers)
                    self.assertNotIn('set-cookie:', headers)
            deployer = d.Deployer(vhost, root / 'served', root / 'state', run, health,
                                  recovery_health=lambda: d.require(get('/live')[0] == 200, 'scratch rollback health'))
            with patch.object(d, 'render', side_effect=scratch_render):
                tx1 = deployer.apply(a, d.sha(original.encode()))
                code, headers, body = get('/static/index-abcdefgh.js', compressed=True)
                self.assertEqual(code, 200)
                self.assertIn('content-encoding: gzip', headers)
                self.assertIn('vary: accept-encoding', headers)
                self.assertEqual(d.sha(body), m1['files']['static/index-abcdefgh.js']['sha256'])
                self.assertTrue('application/javascript' in headers or 'text/javascript' in headers)
                self.assertIn('text/css', get('/static/index-abcdefgh.css')[1])
                for path in ('/', '/source', '/auth/login', '/api/test', '/integration-assets/gallery.js'):
                    code, headers, body = get(path + '?token=must-not-log')
                    self.assertEqual(code, 200)
                    self.assertEqual(body, ('PRIMARY ' + path + '?token=must-not-log').encode())
                    self.assertIn('private, no-store', headers)
                    self.assertNotIn('immutable', headers)
                for path in ('/static/missing-abcdefgh.js', '/static/debug.js.map', '/static/private.txt'):
                    self.assertEqual(get(path)[0], 404)
                self.assertIn(get('/static/..%2f..%2fetc/passwd')[0], (400, 404))
                for path in ('/attachments/private', '/assets/private', '/app/data/private'):
                    self.assertEqual(get(path)[0], 403)
                self.assertEqual(get('/static/index-abcdefgh.js', 'other.xiya.live')[2], b'OTHER DOMAIN')
                self.assertEqual(get('/static/index-abcdefgh.js', 'app-test.xiya.live')[2], b'INTEGRATION PRIMARY')
                context = ssl.create_default_context(cafile=str(cert))
                with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                    with context.wrap_socket(raw, server_hostname='stella.xiya.live') as ws:
                        ws.sendall(b'GET /ws/test HTTP/1.1\r\nHost: stella.xiya.live\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n')
                        handshake = ws.recv(4096)
                        self.assertIn(b' 101 ', handshake.split(b'\r\n')[0])
                Handler.primary = False
                self.assertEqual(get('/auth/login')[0], 503)
                self.assertEqual(get('/static/index-abcdefgh.js')[0], 200)
                Handler.primary = True
                tx2 = deployer.apply(b, d.sha(vhost.read_bytes()), primary_stage=a)
                self.assertEqual(get('/static/index-abcdefgh.js')[0], 200)
                self.assertEqual(get('/static/index-ijklmnop.js')[0], 200)
                self.assertEqual(d.sha(get('/source')[2]), m1['files']['index.html']['sha256'])
                Handler.source = d.read(b / 'source-index.html')
                self.assertEqual(d.sha(get('/')[2]), m2['files']['index.html']['sha256'])
                self.assertEqual(get('/static/index-abcdefgh.js')[0], 200)
                # A third apply fails health after real reload; restores byte-exact config.
                previous = vhost.read_bytes()
                fail_health = True
                with self.assertRaisesRegex(ValueError, 'injected'):
                    deployer.apply(b, d.sha(previous))
                self.assertEqual(vhost.read_bytes(), previous)
                fail_health = False
                # curl production command within rollback would hit :443, so map ONLY
                # that health read to the scratch TLS listener; still verified curl.
                original_run = deployer.run
                def rollback_run(argv):
                    if argv[0] == 'curl':
                        self.assertEqual(get('/live')[0], 200)
                        return b'healthy'
                    return original_run(argv)
                deployer.run = rollback_run
                Handler.source = d.read(a / 'source-index.html')
                deployer.rollback(tx2)
                self.assertIn('index-abcdefgh.js', vhost.read_text())
                self.assertNotIn('location = /static/index-ijklmnop.js', vhost.read_text())
                deployer.rollback(tx1)
                self.assertEqual(vhost.read_bytes(), original.encode())
                # Persistent public assets retained after config rollback, no GC.
                self.assertEqual(len(list((deployer.root / 'releases').iterdir())), 2)
            # Flush request log by stopping our own master gracefully.
            run(['nginx', '-s', 'quit'])
            process.communicate(timeout=5)
            process = None
            rows = [json.loads(x) for x in (root / 'safe.log').read_text().splitlines() if x.startswith('{')]
            self.assertTrue(rows)
            self.assertNotIn('must-not-log', json.dumps(rows))
            self.assertTrue(any(x['path'] == '/auth/login' and x['status'] == 503 for x in rows))
            self.assertTrue(any(x['upstream_connect_time'] != '-' for x in rows if x['path'] == '/source'))
            self.assertTrue(any(x['upstream_connect_time'] in ('', '-') for x in rows if x['path'].startswith('/static/')), rows)
            self.assertTrue(all(x['origin'].startswith('https://stella.xiya.live') for x in rows))
            for row in rows:
                self.assertEqual(set(row), {'time', 'origin', 'method', 'path', 'status', 'bytes', 'request_time',
                                           'upstream_connect_time', 'upstream_header_time', 'upstream_response_time'})
        finally:
            if process:
                process.terminate()
                process.communicate(timeout=5)
            if upstream:
                upstream.shutdown()
                upstream.server_close()
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
