"""CI-only PostgreSQL admission and startup-filtered loopback relay (stdlib).

The existing manual Docker guards remain separate. This is not a DSN override:
only the bootstrap's exact CI service, private marker and control identity enter.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import socket
import socketserver
import struct
import threading


def ci_service():
    if not (os.environ.get('CI') == 'true' and os.environ.get('GITLAB_CI') == 'true'
            and re.fullmatch(r'[1-9][0-9]*', os.environ.get('CI_JOB_ID', ''))):
        raise ValueError('explicit GitLab CI job required')
    expected = {'POSTGRES_HOST': 'postgres', 'POSTGRES_PORT': '5432',
                'POSTGRES_DB': 'stella', 'POSTGRES_USER': 'stalla'}
    if any(os.environ.get(k) != v for k, v in expected.items()):
        raise ValueError('only exact CI postgres/stalla/stella service admitted')
    if not os.environ.get('POSTGRES_PASSWORD') or os.environ.get('DATABASE_URL'):
        raise ValueError('CI bootstrap credential required; arbitrary DSN forbidden')
    ips = sorted({x[4][0] for x in socket.getaddrinfo('postgres', 5432, type=socket.SOCK_STREAM)})
    if len(ips) != 1 or not ipaddress.ip_address(ips[0]).is_private or ipaddress.ip_address(ips[0]).is_loopback:
        raise ValueError('single private sidecar address required')
    return ips[0]


def marker_path():
    root = Path(os.environ['TMPDIR'])
    info = root.stat()
    if not root.is_absolute() or root.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('private owned TMPDIR required')
    return root / 'owned-ci-pg.json'


def bootstrap(connection):
    """Called only after the unchanged stella_test bootstrap succeeded."""
    address = ci_service()
    path = marker_path()
    if path.exists():
        raise ValueError('refuse replacing CI sidecar identity')
    nonce = secrets.token_hex(16)
    with connection.cursor() as c:
        c.execute('SELECT system_identifier::text FROM pg_control_system()')
        system = c.fetchone()[0]
        c.execute('CREATE TABLE public.stella_ci_fixture_identity (nonce text PRIMARY KEY, job text NOT NULL)')
        c.execute('INSERT INTO public.stella_ci_fixture_identity VALUES (%s,%s)', (nonce, os.environ['CI_JOB_ID']))
    data = dict(format=1, job=os.environ['CI_JOB_ID'], nonce=nonce, system=system, address=address)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(data, f)


def admitted_marker():
    address = ci_service()
    path = marker_path()
    info = path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('unsafe CI identity file')
    data = json.loads(path.read_text())
    if (set(data) != {'format', 'job', 'nonce', 'system', 'address'} or data['format'] != 1
            or data['job'] != os.environ['CI_JOB_ID'] or data['address'] != address
            or not re.fullmatch('[a-f0-9]{32}', data['nonce']) or not re.fullmatch('[0-9]+', data['system'])):
        raise ValueError('CI sidecar identity mismatch')
    return data


def verify_admin(connection, marker):
    with connection.cursor() as c:
        c.execute('SELECT current_database(), current_user, host(inet_server_addr()), system_identifier::text FROM pg_control_system()')
        if c.fetchone() != ('stella_test', 'stalla', marker['address'], marker['system']):
            raise ValueError('foreign CI sidecar')
        c.execute('SELECT nonce, job FROM public.stella_ci_fixture_identity')
        if c.fetchall() != [(marker['nonce'], marker['job'])]:
            raise ValueError('foreign CI bootstrap marker')


def read_exact(sock, length):
    data = b''
    while len(data) < length:
        value = sock.recv(length - len(data))
        if not value:
            raise ValueError('truncated PostgreSQL startup')
        data += value
    return data


def startup(sock, database):
    for _ in range(3):
        length = struct.unpack('!I', read_exact(sock, 4))[0]
        if not 8 <= length <= 16384:
            raise ValueError('invalid startup length')
        body = read_exact(sock, length - 4)
        protocol = struct.unpack('!I', body[:4])[0]
        if protocol in (80877103, 80877104) and length == 8:
            sock.sendall(b'N')  # No TLS/GSS tunnelling around startup admission.
            continue
        if protocol != 196608 or not body.endswith(b'\0\0'):
            raise ValueError('only protocol 3 startup admitted')
        fields = body[4:-2].split(b'\0')
        if len(fields) % 2:
            raise ValueError('invalid startup fields')
        pairs = list(zip(fields[::2], fields[1::2]))
        values = dict(pairs)
        if len(values) != len(pairs) or values.get(b'user') != database.encode() or values.get(b'database') != database.encode():
            raise ValueError('relay only admits its exact owned role/database')
        return struct.pack('!I', length) + body
    raise ValueError('startup negotiation budget exceeded')


class Relay(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, database):
        self.upstream = (address, 5432)
        self.database = database
        self.sockets = set()
        self.lock = threading.Lock()
        super().__init__(('127.0.0.1', 0), RelayHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        with self.lock:
            for sock in list(self.sockets):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError('relay failed to stop')


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        try:
            self.request.settimeout(5)
            first = startup(self.request, self.server.database)
            upstream = socket.create_connection(self.server.upstream, timeout=5)
            upstream.sendall(first)
            self.request.settimeout(None)
            upstream.settimeout(None)
            with self.server.lock:
                self.server.sockets.update((self.request, upstream))
            while True:
                ready, _, _ = select.select([self.request, upstream], [], [], 2)
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.request else self.request).sendall(data)
        except (OSError, ValueError):
            return
        finally:
            with self.server.lock:
                self.server.sockets.discard(self.request)
                self.server.sockets.discard(upstream)
            if upstream:
                upstream.close()


def owned_target():
    """Fixture-side CI entrance. Does not replace the manual Docker guard."""
    if os.environ.get('STELLA_CI_UNIFIED') == '1':
        from deploy.ci.unified_ci import fixture_target
        return fixture_target()
    path = Path(os.environ['STELLA_CI_OWNED_RECEIPT'])
    root = Path(os.environ['TMPDIR'])
    if path.parent != root or not path.name.startswith('owner-') or root.is_symlink():
        raise ValueError('foreign owner receipt')
    data = json.loads(path.read_text())
    nonce = os.environ.get('STELLA_CI_OWNED_NONCE', '')
    name = os.environ.get('POSTGRES_DB', '')
    if (not re.fullmatch('[a-f0-9]{32}', nonce) or name not in ('nodefiles_' + nonce, 'navqa_' + nonce)
            or data != {'format': 1, 'nonce': nonce, 'database': name, 'port': os.environ.get('POSTGRES_PORT'), 'pid': os.getppid()}
            or os.environ.get('POSTGRES_HOST') != '127.0.0.1' or os.environ.get('POSTGRES_USER') != name
            or path.stat().st_mode & 0o077 or path.stat().st_uid != os.geteuid()):
        raise ValueError('owned target identity mismatch')
    port = int(data['port'])
    if not (os.environ.get('CI') == 'true' and os.environ.get('GITLAB_CI') == 'true'
            and re.fullmatch('[1-9][0-9]*', os.environ.get('CI_JOB_ID', ''))
            and 1024 < port < 65536 and port not in (5432, 24532, 25432, 25436)):
        raise ValueError('owned CI listener admission failed')
    inodes = {line.split()[9] for line in Path('/proc/net/tcp').read_text().splitlines()[1:]
              if line.split()[1] == f'0100007F:{port:04X}' and line.split()[3] == '0A'}
    parent_sockets = {os.readlink(p) for p in Path(f'/proc/{os.getppid()}/fd').iterdir()}
    if not any('socket:[' + inode + ']' in parent_sockets for inode in inodes):
        raise ValueError('relay is not this exact parent process listener')
    return port, name, name, 'ci-owned-' + nonce
