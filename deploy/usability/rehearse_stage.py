#!/usr/bin/env python3
"""Rehearse a verified image stage with real nginx/TLS on scratch loopback only.
Persistent evidence, all public files hashed via HTTP. Not production acceptance.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import deploysafe as d


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def rehearse(stage, snapshot, out):
    stage, snapshot, out = Path(stage), Path(snapshot), d.trusted(out, exists=False)
    m = d.verify_stage(stage)
    d.require(not out.exists(), 'evidence directory exists')
    out.mkdir(parents=True, mode=0o700)
    manifest, assets, versions = d.install_release(stage, out / 'served')
    source = d.read(stage / 'source-index.html')
    class PrimaryFixture(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
        def do_GET(self):
            if self.path in ('/', '/source'):
                code, body = 200, source
            elif self.path == '/live':
                code, body = 200, b'{"fixture":true}'
            else:
                code, body = 403, b'PRIVATE PRIMARY FIXTURE'
            self.send_response(code)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Cache-Control', 'private, no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), PrimaryFixture)
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    process = None
    try:
        tls_port, http_port = port(), port()
        cert, key = out / 'cert.pem', out / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=stella.xiya.live', '-addext', 'subjectAltName=DNS:stella.xiya.live',
                        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
        baseline = d.read(snapshot)
        # Keep a production-path preview separately; never load that file locally.
        preview = d.render(baseline.decode(), assets)
        d.atomic(out / 'production-layout-preview.conf', preview.encode())
        candidate = d.render(baseline.decode(), assets, str(out / 'safe.log'))
        candidate = candidate.replace('listen 80;', f'listen 127.0.0.1:{http_port};')
        candidate = candidate.replace('listen 443 ssl;', f'listen 127.0.0.1:{tls_port} ssl;')
        candidate = candidate.replace('/etc/ssl/xiya.live/fullchain.pem', str(cert)).replace('/etc/ssl/xiya.live/privkey.pem', str(key))
        candidate = candidate.replace('http://127.0.0.1:12031', f'http://127.0.0.1:{upstream.server_port}')
        d.require('/var/log/nginx/' not in candidate and '127.0.0.1:12031' not in candidate and '/etc/ssl/' not in candidate,
                  'scratch config leaked production target')
        vhost = out / 'stella-scratch.conf'
        d.atomic(vhost, candidate.encode())
        config = out / 'nginx.conf'
        d.atomic(config, f'''user root;
worker_processes 1;
pid {out}/nginx.pid;
error_log {out}/nginx-error.log crit;
events {{ worker_connections 128; }}
http {{ include /etc/nginx/mime.types; default_type application/octet-stream;
access_log off;
include {vhost};
}}
'''.encode())
        nginx = ['nginx', '-p', str(out), '-c', str(config)]
        subprocess.run(nginx + ['-t'], check=True, capture_output=True)
        process = subprocess.Popen(nginx + ['-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def get(path, compressed=False):
            hfile = out / 'last-response-headers.txt'
            args = ['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '5',
                    '--resolve', f'stella.xiya.live:{tls_port}:127.0.0.1', '--cacert', str(cert), '-D', str(hfile)]
            if compressed:
                args += ['--compressed']
            body = d.command(args + [f'https://stella.xiya.live:{tls_port}{path}'])
            headers = hfile.read_text().lower()
            return int(headers.splitlines()[0].split()[1]), headers, body
        end = time.monotonic() + 5
        while True:
            try:
                d.require(get('/live')[0] == 200, 'scratch readiness')
                break
            except ValueError:
                d.require(time.monotonic() < end, 'scratch readiness timeout')
                time.sleep(0.03)
        checks = []
        for name in m['public']:
            code, headers, body = get('/' + name)
            d.require(code == 200 and d.sha(body) == m['files'][name]['sha256'], 'real nginx body mismatch')
            d.require('cache-control: public, max-age=604800, immutable' in headers and
                      'x-stella-static-sha256: ' + m['files'][name]['sha256'] in headers, 'real nginx static header mismatch')
            checks.append({'path': '/' + name, 'status': code, 'sha256': d.sha(body), 'bytes': len(body)})
        for path in ('/', '/source'):
            code, headers, body = get(path)
            d.require(code == 200 and d.sha(body) == m['files']['index.html']['sha256'] and 'immutable' not in headers, 'primary HTML fixture mismatch')
        private = {}
        for path in ('/auth/login', '/api/test', '/attachments/private', '/assets/private', '/app/data/secret', '/integration-assets/gallery.js'):
            code, _, _ = get(path)
            d.require(code == 403, 'private path escaped primary fixture')
            private[path] = code
        missing = get('/static/missing-abcdefgh.js')[0]
        d.require(missing == 404, 'missing static fallback leak')
        compression = {}
        for suffix in ('.js', '.css'):
            name = next(x for x in m['public'] if x.endswith(suffix) and m['files'][x]['size'] >= 1024)
            code, headers, body = get('/' + name, compressed=True)
            d.require(code == 200 and 'content-encoding: gzip' in headers and d.sha(body) == m['files'][name]['sha256'], 'gzip body/header mismatch')
            compression[suffix] = {'path': name, 'decoded_sha256': d.sha(body), 'gzip': True}
        d.command(nginx + ['-s', 'quit'])
        process.communicate(timeout=5)
        process = None
        rows = [json.loads(x) for x in (out / 'safe.log').read_text().splitlines()]
        d.require(rows and all(set(x) == {'time', 'origin', 'method', 'path', 'status', 'bytes', 'request_time',
                                          'upstream_connect_time', 'upstream_header_time', 'upstream_response_time'} for x in rows), 'JSON log schema')
        result = dict(scope='scratch-real-nginx-image-stage-only', image=m['image'], revision=m['revision'],
                      version=m['version'], verified_public_files=len(checks), total_dist_files=len(m['files']),
                      nginx_version=subprocess.run(['nginx', '-v'], capture_output=True, check=True).stderr.decode().strip(),
                      snapshot_sha256=d.sha(baseline), html_sha256=d.sha(source), checks=checks,
                      primary_fixture_private_status=private, missing_static_status=missing, gzip=compression,
                      production_write=False, original_TLS_preserved_in_preview=True)
        d.atomic(out / 'result.json', d.encoded(result))
        return result
    finally:
        if process:
            process.terminate()
            process.communicate(timeout=5)
        upstream.shutdown()
        upstream.server_close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', type=Path, required=True)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    result = rehearse(a.stage, a.snapshot, a.out)
    print(json.dumps({k: v for k, v in result.items() if k != 'checks'}, indent=2))
