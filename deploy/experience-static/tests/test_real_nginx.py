"""Real isolated TLS nginx; fixture auth upstream, NEVER production auth/DB.
Set STELLA_STATIC_BUNDLE and STELLA_STATIC_VERSION to also exercise real public
vendor bytes. The upstream remains explicitly synthetic in either mode.
"""
import gzip
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import threading
import time
import unittest

import test_public_assets as f
import test_stage as staging


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class RealNginx(f.FixtureCase):
    stage = staging.StageTest.stage

    def test_tls_gzip_cache_and_exact_anonymous_boundary(self):
        self.assertIsNotNone(shutil.which('nginx'), 'real nginx required, do not skip this gate')
        self.assertIsNotNone(shutil.which('openssl'), 'openssl required')
        bundle_arg = os.environ.get('STELLA_STATIC_BUNDLE')
        if bundle_arg:
            bundle = Path(bundle_arg)
            m = json.loads((bundle / 'manifest.json').read_bytes())
            origin = m['source']['origin']
            module = m['source']['module_id']
            m = self.tool.verify(bundle, os.environ['STELLA_STATIC_VERSION'], module, origin)
            shutil.copytree(bundle, self.root / 'bundle')
        else:
            m = self.build()
            module, origin = f.MODULE, f.ORIGIN
        target = self.root / 'edge' / module
        retained_check = None
        if bundle_arg:
            receipt = self.stage([('bundle', m)], module_id=module, origin=origin, target_root=str(target))
        else:
            prior = self.stage([('bundle', m)], name='previous-stage', target_root=str(target))
            next_name = 'next-12345678.js'
            next_body = f.BODY + b'// next release'
            (self.source / next_name).write_bytes(next_body)
            self.spec['files'] = {next_name: dict(sha256=f.sha(next_body), size=len(next_body))}
            next_manifest = self.build(name='next-bundle')
            receipt = self.stage([('next-bundle', next_manifest)], target_root=str(target),
                                 previous=dict(path=str(self.root / 'previous-stage'), version=prior['version']))
            retained_check = (f.PREFIX + next_name, f.sha(next_body))
        shutil.copytree(self.root / 'stage' / 'releases', target / 'releases')
        host = origin.split('://', 1)[1]
        prefix = m['source']['asset_prefix']
        upstream_hits = []
        class Handler(BaseHTTPRequestHandler):
            primary = True
            def log_message(self, format, *args):
                pass
            def do_GET(self):
                upstream_hits.append(self.path)
                status = 503 if not self.primary else (200 if self.headers.get('Cookie') == 'fixture=owner' else 401)
                body = b'FIXTURE AUTHENTICATED DYNAMIC' if status == 200 else b'FIXTURE BLOCKED'
                self.send_response(status)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Cache-Control', 'private, no-store')
                self.send_header('Content-Security-Policy', "default-src 'self'")
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        process = None
        evidence: dict = dict(scope='real isolated nginx TLS; synthetic auth/primary upstream; no DB',
                        asset_source='actual supplied public bundle' if bundle_arg else 'synthetic public assets',
                        version=m['version'], assets=[], boundary=[])
        try:
            cert, key = self.root / 'cert.pem', self.root / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=' + host, '-addext', 'subjectAltName=DNS:' + host,
                            '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
            port, http_port = free_port(), free_port()
            common = f'''include {self.root}/stage/locations.conf;
location / {{ proxy_pass http://127.0.0.1:{upstream.server_port}; }}'''
            conf = self.root / 'nginx.conf'
            conf.write_text(f'''user {os.environ.get('USER', 'root')};
worker_processes 1;
pid {self.root}/nginx.pid;
error_log {self.root}/error.log crit;
events {{ worker_connections 64; }}
http {{
 access_log off;
 client_body_temp_path {self.root}/client-temp;
 proxy_temp_path {self.root}/proxy-temp;
 fastcgi_temp_path {self.root}/fastcgi-temp;
 uwsgi_temp_path {self.root}/uwsgi-temp;
 scgi_temp_path {self.root}/scgi-temp;
 server {{ listen 127.0.0.1:{port} ssl; server_name _;
 ssl_certificate {cert}; ssl_certificate_key {key};
 {common}
 }}
 server {{ listen 127.0.0.1:{http_port}; server_name _; {common} }}
}}
''')
            command = ['nginx', '-p', str(self.root), '-c', str(conf)]
            validated = subprocess.run(command + ['-t'], capture_output=True, text=True, check=True)
            evidence['nginx_test'] = validated.stderr
            evidence['nginx_version'] = subprocess.run(['nginx', '-v'], capture_output=True, text=True, check=True).stderr.strip()
            process = subprocess.Popen(command + ['-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            context = ssl.create_default_context(cafile=str(cert))
            def request(path, headers=None, method='GET', tls=True):
                conn = HTTPConnection('127.0.0.1', port if tls else http_port, timeout=3)
                raw = socket.create_connection(('127.0.0.1', port if tls else http_port), timeout=3)
                conn.sock = context.wrap_socket(raw, server_hostname=host) if tls else raw
                try:
                    conn.request(method, path, headers={'Host': host, **(headers or {})})
                    response = conn.getresponse()
                    return response.status, dict((k.lower(), v) for k, v in response.getheaders()), response.read()
                finally:
                    conn.close()
            deadline = time.monotonic() + 5
            while True:
                try:
                    self.assertEqual(request('/')[0], 401)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.025)
            upstream_hits.clear()
            for name, entry in sorted(m['source']['files'].items()):
                uri = prefix + name
                start = time.monotonic()
                code, headers, wire = request(uri, {'Accept-Encoding': 'gzip'})
                ms = (time.monotonic() - start) * 1000
                self.assertEqual(code, 200)
                self.assertEqual(headers.get('content-encoding'), 'gzip')
                self.assertEqual(headers.get('vary'), 'Accept-Encoding')
                self.assertEqual(headers.get('cache-control'), 'public, max-age=31536000, immutable')
                self.assertEqual(headers.get('x-content-type-options'), 'nosniff')
                self.assertNotIn('set-cookie', headers)
                self.assertEqual(f.sha(gzip.decompress(wire)), entry['sha256'])
                self.assertEqual(headers.get('x-stella-static-sha256'), entry['sha256'])
                self.assertEqual(len(wire), m['gzip'][name]['size'])
                evidence['assets'].append(dict(path=uri, bytes=entry['size'], gzip_bytes=len(wire),
                                               milliseconds=round(ms, 3), headers=headers, sha256=entry['sha256']))
                status, h, body = request(uri, {'Accept-Encoding': 'gzip', 'If-None-Match': headers['etag']})
                self.assertEqual(status, 304)
                self.assertEqual(body, b'')
                self.assertIn('immutable', h['cache-control'])
            if retained_check:
                code, headers, body = request(retained_check[0], {'Accept-Encoding': 'gzip'})
                self.assertEqual(code, 200)
                self.assertEqual(f.sha(gzip.decompress(body)), retained_check[1])
                evidence['retained_versions'] = receipt['versions']
                self.assertEqual(len(receipt['versions']), 2)
            self.assertEqual(upstream_hits, [], 'approved assets/304 must not contact upstream')
            name = sorted(m['source']['files'])[0]
            uri = prefix + name
            self.assertEqual(f.sha(request(uri)[2]), m['source']['files'][name]['sha256'])
            self.assertEqual(request(uri, method='HEAD')[2], b'')
            self.assertEqual(request(uri, {'Range': 'bytes=0-9'})[0], 206)
            for bad, headers, method, tls in [
                (uri, {'Host': 'app-' + '0' * 32 + '.example.test'}, 'GET', True),
                (uri, {'Host': host + ':123'}, 'GET', True),
                (uri + '?download=private', {}, 'GET', True),
                (uri.replace('/assets/', '/assets/../assets/'), {}, 'GET', True),
                (uri.replace('/assets/', '/assets/%2e/'), {}, 'GET', True),
                (uri.replace('/assets/', '//assets/'), {}, 'GET', True),
                (uri, {}, 'POST', True), (uri, {}, 'GET', False),
            ]:
                status, headers, body = request(bad, headers, method, tls)
                self.assertIn(status, (403, 404, 405), bad)
                self.assertNotIn('immutable', headers.get('cache-control', ''))
                evidence['boundary'].append(dict(path=bad, status=status, kind='noncanonical/host/method/scheme'))
            for path in ['/', '/api/me', '/private/file', '/download/file', '/drive/openlist/d/file',
                         '/drive/openlist/api/fs/list', prefix + 'unknown-12345678.js',
                         prefix + name + '.gz', '/manifest.json', '/auth/login']:
                status, headers, body = request(path)
                self.assertEqual(status, 401, path)
                self.assertEqual(headers.get('cache-control'), 'private, no-store')
                status, headers, body = request(path, {'Cookie': 'fixture=owner'})
                self.assertEqual(status, 200)
                self.assertEqual(headers.get('content-security-policy'), "default-src 'self'")
                self.assertEqual(body, b'FIXTURE AUTHENTICATED DYNAMIC')
                self.assertNotIn('immutable', headers.get('cache-control', ''))
                evidence['boundary'].append(dict(path=path, anonymous=401, owner=200, kind='unchanged fixture auth'))
            Handler.primary = False
            self.assertEqual(request('/api/me', {'Cookie': 'fixture=owner'})[0], 503)
            self.assertEqual(request(uri)[0], 200)
            Handler.primary = True
            # Missing known bytes and late filesystem symlink cannot enter upstream
            # or inherit cache-on-error, including gzip_static's alternate file path.
            public = target / 'releases' / m['version'] / 'public'
            (public / name).unlink()
            status, headers, _ = request(uri)
            self.assertEqual(status, 404)
            self.assertNotIn('immutable', headers.get('cache-control', ''))
            (public / name).symlink_to(self.source / f.NAME)
            self.assertIn(request(uri)[0], (403, 404))
            (public / (name + '.gz')).unlink()
            (public / (name + '.gz')).symlink_to(cert)
            self.assertIn(request(uri, {'Accept-Encoding': 'gzip'})[0], (403, 404))
            evidence['verified'] = ['gzip all assets', 'ETag 304 zero body all assets', 'HEAD', 'Range',
                                    'module/host/scheme/raw-path isolation', 'dynamic owner auth fixture',
                                    'dynamic primary guard fixture', 'missing and symlink refusal']
        finally:
            if process is not None:
                process.terminate()
                process.communicate(timeout=5)
            upstream.shutdown()
            upstream.server_close()
        if os.environ.get('STELLA_STATIC_EVIDENCE'):
            Path(os.environ['STELLA_STATIC_EVIDENCE']).write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
