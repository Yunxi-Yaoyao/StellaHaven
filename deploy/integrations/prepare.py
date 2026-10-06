#!/usr/bin/env python3
"""Generate and optionally nginx-test a staged bundle. NEVER install/reload/change DNS/FRP."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess


def render_nginx(cert: str, key: str) -> str:
    for path in (cert, key):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', path):
            raise ValueError('absolute certificate path required')
    return r'''# Install only inside nginx http{} after separate deployment approval.
# Uses existing HK FRPS12031 -> stella-web HA group -> local25131 gated runtime.
map $http_upgrade $stella_integrations_connection {
    default upgrade;
    '' close;
}
log_format stella_integrations_safe '$time_iso8601 $host $request_method $uri $status $body_bytes_sent';
server {
    listen 80;
    server_name "~^app-[^.]+\.xiya\.live$";
    if ($host !~ "^app-[0-9a-f]{32}\.xiya\.live$") { return 404; }
    access_log /dev/null;
    return 308 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name "~^app-[^.]+\.xiya\.live$";
    if ($host !~ "^app-[0-9a-f]{32}\.xiya\.live$") { return 404; }
    ssl_certificate CERT;
    ssl_certificate_key KEY;
    ssl_protocols TLSv1.2 TLSv1.3;
    # Disable raw error logging: nginx error request strings can contain query tokens.
    # Use aggregate operational receipts for diagnostics; safe access format omits query/headers.
    error_log /dev/null crit;
    access_log /dev/null stella_integrations_safe;
    client_max_body_size 256m;
    location / {
        proxy_pass http://127.0.0.1:12031;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $stella_integrations_connection;
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_redirect off;
        proxy_connect_timeout 10s;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
'''.replace('CERT', cert).replace('KEY', key)


def validation_commands(output: Path) -> str:
    return 'nginx -t -p ' + shlex.quote(str(output.resolve()) + '/') + ' -c ' + shlex.quote(str(output.resolve() / 'nginx-test.conf'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cert', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = render_nginx(args.cert, args.key)
    candidate = output / 'stella-integrations.conf'
    harness = output / 'nginx-test.conf'
    for target in (candidate, harness):
        if target.exists():
            parser.error('output already exists; choose a new staging directory')
    candidate.write_text(config)
    harness.write_text('worker_processes 1;\nerror_log /dev/null;\npid ' + str(output / 'nginx.pid') + ';\nevents {}\nhttp {\ninclude ' + str(candidate) + ';\n}\n')
    print(validation_commands(output))
    if args.validate:
        result = subprocess.run(['nginx', '-t', '-p', str(output) + '/', '-c', str(harness)], check=False)
        return result.returncode
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
