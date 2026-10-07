#!/usr/bin/env python3
"""Real loopback nginx; synthetic upstream only. No Stella imports or reloads."""
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
BODY = b'0123456789abcdef' * 208014
STATE = {}
EVENTS = []

def asset(name):
    return "/assets/homebg/media-" + hashlib.sha256(name.encode()).hexdigest()[:24] + "-compressed1.mp4"


class Origin(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        item = STATE.get(self.path, {})
        body = item.get('body', BODY)
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        status = item.get('status', 200)
        if status == 200 and self.headers.get('If-None-Match') == etag:
            status = 304
        payload = body if status == 200 else b''
        EVENTS.append({'path': self.path, 'method': self.command, 'status': status,
                       'bytes': len(payload) if self.command != 'HEAD' else 0,
                       'headers': dict(self.headers)})
        self.send_response(status)
        self.send_header('ETag', etag)
        self.send_header('Content-Type', item.get('type', 'video/mp4'))
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Accept-Ranges', 'bytes')
        for k, v in item.get('headers', {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    do_HEAD = do_GET
    do_POST = do_GET


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='stella-bg-', dir=os.environ.get('TMPDIR', '/root/.hermes/cache/scratch'))
        cls.worker_name = next((name for name in ('http','www-data') if any(u.pw_name==name for u in pwd.getpwall())), '')
        if os.getuid()==0 and not cls.worker_name: raise RuntimeError('a nonprivileged nginx worker account is required')
        cls.root = Path(cls.tmp.name)
        cls.root.chmod(0o755)
        cls.origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        threading.Thread(target=cls.origin.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        origin = f'http://127.0.0.1:{cls.origin.server_port}'
        for directory in ('cache', 'client', 'proxy'):
            p = cls.root / directory
            p.mkdir(mode=0o700)
            if os.getuid() == 0:
                worker = pwd.getpwnam(cls.worker_name)
                os.chown(p, worker.pw_uid, worker.pw_gid)
        plain = f'location / {{ proxy_pass {origin}; }}'
        http_config = ''
        location = plain
        if not ARGS.baseline:
            http_config = (HERE / 'http.conf').read_text().replace('/var/cache/nginx/stella-homebg', '/proc/self/cwd/cache')
            location = (HERE / 'location.conf').read_text().replace('http://127.0.0.1:12031', origin) + plain
        user = f'user {cls.worker_name};' if os.getuid() == 0 else ''
        config = f'''{user}
worker_processes 1;
pid /proc/self/cwd/nginx.pid;
error_log /proc/self/cwd/error.log info;
events {{ worker_connections 128; }}
http {{
 client_body_temp_path /proc/self/cwd/client;
 proxy_temp_path /proc/self/cwd/proxy;
 log_format probe '$host $uri $status $upstream_cache_status';
 access_log /proc/self/cwd/access.log probe;
 {http_config}
 server {{ listen 127.0.0.1:{cls.port} default_server; server_name _; {plain} }}
 server {{ listen 127.0.0.1:{cls.port}; server_name stella.xiya.live;
 add_header X-Inherited-Security fixture always;
 {location}
 }}
}}
'''
        (cls.root / 'nginx.conf').write_text(config)
        cmd = ['nginx', '-p', '/proc/self/cwd/', '-c', 'nginx.conf']
        subprocess.run(cmd + ['-t'], cwd=cls.root, check=True, capture_output=True)
        cls.process = subprocess.Popen(cmd + ['-g', 'daemon off;'], cwd=cls.root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.1):
                    break
            except OSError:
                if cls.process.poll() is not None:
                    assert cls.process.stderr is not None
                    raise RuntimeError(cls.process.stderr.read().decode())
                time.sleep(.02)
        else:
            raise RuntimeError('scratch nginx did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.send_signal(signal.SIGQUIT)
        cls.process.wait(timeout=10)
        cls.origin.shutdown()
        cls.origin.server_close()
        report = Path(ARGS.evidence)
        report.mkdir(parents=True, exist_ok=True)
        for filename in ('nginx.conf', 'access.log', 'error.log'):
            (report / filename).write_bytes((cls.root / filename).read_bytes())
        (report / 'origin-events.json').write_text(json.dumps(EVENTS, indent=2))
        cls.tmp.cleanup()

    def request(self, path, method='GET', host='stella.xiya.live', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=8)
        conn.request(method, path, headers={'Host': host, **(headers or {})})
        response = conn.getresponse()
        result = response.status, dict((k.lower(), v) for k, v in response.getheaders()), response.read()
        conn.close()
        return result

    def events(self, path):
        return [event for event in EVENTS if event['path'] == path]

    def assert_uncached(self, path, **kwargs):
        before = len(self.events(path))
        for _ in range(2):
            self.assertEqual(self.request(path, **kwargs)[0], 200)
        self.assertEqual(len(self.events(path)) - before, 2)

    def test_warm_full_download(self):
        path = asset('warm')
        for _ in range(2):
            self.assertEqual(self.request(path)[2], BODY)
        self.assertEqual(len(self.events(path)), 1)

    def test_changed_bytes_after_expiry(self):
        path = asset('changed')
        first = self.request(path)
        STATE[path] = {'body': b'NEW-ORIGIN-BYTES'}
        time.sleep(2.1)
        status, headers, body = self.request(path)
        self.assertEqual((status, body), (200, b'NEW-ORIGIN-BYTES'))
        self.assertNotEqual(headers['etag'], first[1]['etag'])
        self.assertEqual(self.events(path)[-1]['headers']['If-None-Match'], first[1]['etag'])

    def test_deleted_after_expiry(self):
        path = asset('deleted')
        self.request(path)
        STATE[path] = {'status': 404}
        time.sleep(2.1)
        for _ in range(2):
            self.assertEqual(self.request(path)[::2], (404, b''))
        self.assertEqual(len(self.events(path)), 3)

    def test_error_after_expiry_never_stale(self):
        path = asset('error')
        self.request(path)
        STATE[path] = {'status': 500}
        time.sleep(2.1)
        for _ in range(2):
            self.assertEqual(self.request(path)[::2], (500, b''))
        self.assertEqual(len(self.events(path)), 3)

    def test_range_cold_then_complete_download(self):
        path = asset('range')
        status, headers, body = self.request(path, headers={'Range': 'bytes=10-19'})
        self.assertEqual((status, body), (206, BODY[10:20]))
        self.assertEqual(headers['content-range'], f'bytes 10-19/{len(BODY)}')
        self.assertEqual(self.request(path)[2], BODY)
        events = self.events(path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['bytes'], len(BODY))
        self.assertNotIn('Range', events[0]['headers'])

    def test_if_range_matches_and_mismatches(self):
        path = asset('if-range')
        etag = self.request(path)[1]['etag']
        for condition, status, expected in ((etag, 206, BODY[:8]), ('"old"', 200, BODY)):
            with self.subTest(condition=condition):
                result = self.request(path, headers={'Range': 'bytes=0-7', 'If-Range': condition})
                self.assertEqual(result[::2], (status, expected))
        self.assertEqual(len(self.events(path)), 1)
        self.assertNotIn('If-Range', self.events(path)[0]['headers'])

    def test_head_cold_then_get(self):
        path = asset('head')
        status, headers, body = self.request(path, method='HEAD')
        self.assertEqual((status, body), (200, b''))
        self.assertEqual(int(headers['content-length']), len(BODY))
        self.assertEqual(self.request(path)[2], BODY)
        self.assertEqual(len(self.events(path)), 1)
        self.assertEqual(self.events(path)[0]['method'], 'GET')

    def test_client_conditional(self):
        path = asset('conditional')
        etag = self.request(path)[1]['etag']
        self.assertEqual(self.request(path, headers={'If-None-Match': etag})[::2], (304, b''))
        self.assertEqual(len(self.events(path)), 1)

    def test_native_private_no_store_set_cookie(self):
        for name, headers in (
            ('private', {'Cache-Control': 'private'}),
            ('no-store', {'Cache-Control': 'no-store'}),
            ('cookie', {'Set-Cookie': 'fixture=synthetic; HttpOnly'}),
        ):
            with self.subTest(name=name):
                path = asset(name)
                STATE[path] = {'headers': headers}
                self.assert_uncached(path)
                self.assertFalse(any(path.encode() in p.read_bytes() for p in (self.root / 'cache').rglob('*') if p.is_file()))

    def test_origin_explicit_ttl_takes_precedence(self):
        paths = []
        for name, headers in (
            ('max-age', {'Cache-Control': 'public, max-age=604800, immutable'}),
            ('expires', {'Expires': 'Thu, 31 Dec 2037 23:55:55 GMT'}),
            ('accel', {'X-Accel-Expires': '86400'}),
        ):
            path = asset(name)
            STATE[path] = {'headers': headers}
            self.assertEqual(self.request(path)[2], BODY)
            paths.append(path)
            STATE[path] = {'status': 404}
        time.sleep(2.1)
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[::2], (200, BODY))
                self.assertEqual(len(self.events(path)), 1)

    def test_other_private_routes_never_cached(self):
        for path in ('/api/private', '/auth/me', '/drive/file.mp4', '/gallery/file.mp4',
                     '/assets/avatars/a.png', '/index.html', '/assets/homebg/private/a.mp4'):
            with self.subTest(path=path):
                self.assert_uncached(path)

    def test_other_host_never_cached(self):
        self.assert_uncached(asset('other-host'), host='other.xiya.live')

    def test_query_encoded_and_traversal_bypass(self):
        for path in (asset('query')+'?private=synthetic',
                     '/assets/homebg/%65ncoded.mp4', '/assets/homebg/a..mp4'):
            with self.subTest(path=path):
                self.assert_uncached(path)

    def test_authorization_and_post_bypass(self):
        self.assert_uncached(asset('auth'), headers={'Authorization': 'Bearer synthetic'})
        self.assert_uncached(asset('post'), method='POST')

    def test_html_mime_bypasses(self):
        path = asset('html')
        STATE[path] = {'type': 'text/html', 'body': b'<html>private fixture</html>'}
        self.assert_uncached(path)

    def test_security_headers_and_forwarding(self):
        path = asset('forward')
        status, headers, _ = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(headers['x-inherited-security'], 'fixture')
        sent = self.events(path)[0]['headers']
        self.assertEqual(sent['Host'], 'stella.xiya.live')
        self.assertEqual(sent['X-Forwarded-Proto'], 'http')
        self.assertEqual(sent['X-Real-IP'], '127.0.0.1')
        self.assertEqual(sent['X-Forwarded-For'], '127.0.0.1')

    def test_original_wallpaper_keeps_origin_range_and_bypasses_cache(self):
        path='/assets/homebg/0123456789ab.mp4'
        self.assert_uncached(path, headers={'Range':'bytes=10-19','If-Range':'"synthetic"'})
        for event in self.events(path):
            self.assertEqual(event['headers'].get('Range'),'bytes=10-19')
            self.assertEqual(event['headers'].get('If-Range'),'"synthetic"')

    def test_worker_only_cache_directory(self):
        stat = (self.root / 'cache').stat()
        self.assertEqual(stat.st_mode & 0o777, 0o700)
        self.assertEqual(stat.st_uid, pwd.getpwnam(self.worker_name).pw_uid if os.getuid() == 0 else os.getuid())
        self.assertNotIn('Permission denied', (self.root / 'error.log').read_text())

    def test_revalidation_respects_explicit_ttl(self):
        path = asset('revalidate-lifetime')
        self.request(path)
        STATE[path] = {'headers': {'Cache-Control': 'public, max-age=86400'}}
        time.sleep(2.1)
        self.request(path)
        STATE[path] = {'status': 404}
        time.sleep(2.1)
        self.assertEqual(self.request(path)[::2], (200, BODY))
        self.assertEqual([e['status'] for e in self.events(path)], [200, 304])

    def test_private_revalidation_not_retained(self):
        path = asset('revalidate-private')
        self.request(path)
        STATE[path] = {'headers': {'Cache-Control': 'private, no-store'}}
        time.sleep(2.1)
        self.request(path)
        STATE[path] = {'status': 404}
        time.sleep(2.1)
        self.assertEqual(self.request(path)[0], 404)

    def test_non_200_with_explicit_public_ttl_not_cached(self):
        for status in (206, 302, 404, 500):
            with self.subTest(status=status):
                path = asset('status-'+str(status))
                STATE[path] = {'status': status, 'headers': {'Cache-Control': 'public, max-age=604800'}}
                for _ in range(2):
                    self.assertEqual(self.request(path)[0], status)
                self.assertEqual(len(self.events(path)), 2)

    def test_concurrent_cold_requests_coalesce(self):
        from concurrent.futures import ThreadPoolExecutor
        path = asset('concurrent')
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.request(path), range(4)))
        for status, _, body in responses:
            self.assertEqual(status, 200)
            self.assertEqual(body, BODY)
        self.assertEqual(len(self.events(path)), 1)

    def test_revalidate_avoids_second_large_body(self):
        path = asset('revalidate')
        first = self.request(path)
        self.assertEqual(first[0], 200)
        self.assertEqual(first[2], BODY)
        time.sleep(2.1)  # nginx cache expiry uses whole seconds
        second = self.request(path)
        self.assertEqual(second[2], BODY)
        events = self.events(path)
        self.assertEqual([e['status'] for e in events], [200, 304])
        self.assertEqual(sum(e['bytes'] for e in events), len(BODY))
        self.assertEqual(events[-1]['headers'].get('If-None-Match'), first[1]['etag'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--test', action='append')
    ARGS = parser.parse_args()
    selected = ARGS.test or (['test_revalidate_avoids_second_large_body'] if ARGS.baseline else [])
    suite = (unittest.TestSuite(CacheTests(name) for name in selected) if selected
             else unittest.defaultTestLoader.loadTestsFromTestCase(CacheTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {'baseline': ARGS.baseline, 'tests': result.testsRun,
               'failures': len(result.failures), 'errors': len(result.errors),
               'nginx': subprocess.run(['nginx', '-v'], capture_output=True, text=True).stderr.strip(),
               'failed_tests': [str(t) for t, _ in result.failures + result.errors]}
    Path(ARGS.evidence).mkdir(parents=True, exist_ok=True)
    (Path(ARGS.evidence) / 'result.json').write_text(json.dumps(summary, indent=2))
    raise SystemExit(not result.wasSuccessful())
