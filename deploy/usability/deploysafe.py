#!/usr/bin/env python3
"""Versioned PUBLIC dist/static only; offline staging by default, explicit local apply.
No app/DB/FRP/DNS/container lifecycle or network tuning. Stdlib, Python >=3.11.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

REGISTRY = 'gitlab-registry.xiya.live/yaoyao/stellahaven'
VHOST = Path('/etc/nginx/conf.d/stella.xiya.live.conf')
ROOT = Path('/var/www/stella-public-static')
STATE = Path('/var/lib/stella-edge-deploy')
HEX = r'[0-9a-f]{64}'
ASSET = re.compile(r'static/[A-Za-z0-9_][A-Za-z0-9_.-]*-[A-Za-z0-9_-]{8,}\.(?:js|css|woff2?|ttf|otf|png|jpe?g|webp|gif|avif|svg|ico|wasm)$')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def trusted(path, exists=True):
    """Reject symlinks at every component and writable/unowned parent chains."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute contained path required')
    for p in reversed((path, *path.parents)):
        if not p.exists() and not p.is_symlink():
            require(not exists or p != path, 'path missing')
            continue
        s = p.lstat()
        require(not stat.S_ISLNK(s.st_mode), 'symlink rejected')
        require(s.st_uid == os.getuid() and not s.st_mode & 0o022, 'untrusted owner/mode')
    return path


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        require(stat.S_ISREG(os.fstat(f.fileno()).st_mode), 'regular file required')
        return f.read()


def atomic(path, data, mode=0o600):
    path = trusted(path, exists=False)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    trusted(path.parent)
    fd, name = tempfile.mkstemp(prefix='.atomic-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def command(argv, timeout=90):
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    require(p.returncode == 0, 'command failed: ' + argv[0])
    return p.stdout


def lock_file(state):
    path = trusted(Path(state) / 'lock', exists=False)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    require(stat.S_ISREG(os.fstat(fd).st_mode), 'regular lock required')
    return os.fdopen(fd, 'r+')


def validate_manifest(m):
    require(set(m) == {'schema', 'image', 'image_id', 'revision', 'files', 'public', 'version'}, 'manifest fields')
    require(m['schema'] == 'stella-public-static-v1', 'manifest schema')
    require(re.fullmatch(re.escape(REGISTRY) + '@sha256:' + HEX, m['image']), 'immutable image digest required')
    require(re.fullmatch('sha256:' + HEX, m['image_id']), 'full image ID required')
    require(re.fullmatch('[0-9a-f]{40}', m['revision']), 'full revision required')
    require(isinstance(m['files'], dict) and m['files'] and 'index.html' in m['files'], 'dist manifest empty')
    for name, entry in m['files'].items():
        require(re.fullmatch(r'[A-Za-z0-9_./-]+', name) and not name.startswith('/') and
                all(x not in ('', '.', '..') for x in name.split('/')), 'manifest traversal rejected')
        require(set(entry) == {'sha256', 'size'} and re.fullmatch(HEX, entry['sha256']) and
                type(entry['size']) is int and entry['size'] >= 0, 'file fingerprint invalid')
    require(isinstance(m['public'], list) and m['public'] == sorted(set(m['public'])) and m['public'], 'public set invalid')
    require(m['public'] == sorted(x for x in m['files'] if ASSET.fullmatch(x)), 'public set must be exact hashed dist/static subset')
    require(any(x.endswith('.js') for x in m['public']), 'no JS entry')
    core = dict(m)
    core.pop('version')
    require(m['version'] == sha(encoded(core)), 'manifest identity mismatch')
    return m


def make_stage(dist, image, image_id, revision, out):
    """Called after extraction; never walk /app/data, mounts or live runtime assets."""
    dist, out = Path(dist), trusted(out, exists=False)
    require(not out.exists(), 'stage already exists')
    files = {}
    require(dist.is_dir() and not dist.is_symlink(), 'dist missing/symlink')
    for p in sorted(dist.rglob('*')):
        require(not p.is_symlink(), 'dist symlink rejected')
        if p.is_dir():
            continue
        require(p.is_file(), 'special dist file rejected')
        data = read(p)
        files[p.relative_to(dist).as_posix()] = {'sha256': sha(data), 'size': len(data)}
    m = dict(schema='stella-public-static-v1', image=image, image_id=image_id,
             revision=revision, files=files, public=sorted(x for x in files if ASSET.fullmatch(x)))
    m['version'] = sha(encoded(m))
    validate_manifest(m)
    # Source index remains a PRIVATE verification artifact, never a served file.
    html = read(dist / 'index.html').decode()
    refs = re.findall(r'(?:src|href)=[\"\'](/static/[^\"\']+)', html)
    require(refs and all(x[1:] in m['public'] for x in refs), 'HTML static references outside public manifest')
    out.mkdir(parents=True, mode=0o700)
    (out / 'public' / 'static').mkdir(parents=True, mode=0o755)
    for name in m['public']:
        atomic(out / 'public' / name, read(dist / name), 0o644)
    atomic(out / 'source-index.html', read(dist / 'index.html'))
    atomic(out / 'manifest.json', encoded(m))
    verify_stage(out)
    return m


def verify_stage(stage):
    stage = trusted(stage)
    m = validate_manifest(json.loads(read(stage / 'manifest.json')))
    expected = {'manifest.json', 'source-index.html'} | {'public/' + x for x in m['public']}
    actual = set()
    for p in stage.rglob('*'):
        trusted(p)
        if not p.is_dir():
            actual.add(p.relative_to(stage).as_posix())
    require(actual == expected, 'stage extra/missing files')
    require(sha(read(stage / 'source-index.html')) == m['files']['index.html']['sha256'], 'HTML hash mismatch')
    for name in m['public']:
        data = read(stage / 'public' / name)
        require({'sha256': sha(data), 'size': len(data)} == m['files'][name], 'asset hash mismatch')
    return m


def extract(image, revision, out, read_only_container=None):
    """Local image-only reader: create a NEVER-started isolated temporary carrier.
    Only /app/frontend/dist is copied. Optional read-only exact-image container
    uses inspect/cp only. Otherwise explicit LOCAL create/rm, never start/pull.
    """
    require(re.fullmatch(re.escape(REGISTRY) + '@sha256:' + HEX, image), 'immutable image required')
    require(re.fullmatch('[0-9a-f]{40}', revision), 'full revision required')
    info = json.loads(command(['docker', 'image', 'inspect', image]))[0]
    require(image in info.get('RepoDigests', []), 'digest not locally present')
    # No Env/credentials logged. OCI revision label is optional, but cannot disagree.
    labels = info.get('Config', {}).get('Labels') or {}
    require(labels.get('org.opencontainers.image.revision', revision) == revision, 'image revision mismatch')
    if read_only_container is not None:
        require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', read_only_container), 'container name invalid')
        container = json.loads(command(['docker', 'inspect', read_only_container]))[0]
        require(container['Image'] == info['Id'] and container['HostConfig']['ReadonlyRootfs'] is True,
                'read-only container exact image mismatch')
        dist = Path('/app/frontend/dist')
        for mount in container['Mounts']:
            dest = Path(mount['Destination'])
            require(dest != dist and dest not in dist.parents and dist not in dest.parents,
                    'dist intercepted by mount')
        for line in command(['docker', 'diff', read_only_container]).decode().splitlines():
            changed = Path(line[2:])
            require(changed != dist and dist not in changed.parents and changed != dist.parent,
                    'readonly carrier overlay dist change rejected')
        with tempfile.TemporaryDirectory(prefix='stella-edge-readonly-', dir=os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch'))) as tmp:
            command(['docker', 'cp', read_only_container + ':/app/frontend/dist', tmp + '/dist'])
            return make_stage(Path(tmp) / 'dist', image, info['Id'], revision, out)
    name = 'stella-edge-extract-' + uuid.uuid4().hex
    carrier = None
    with tempfile.TemporaryDirectory(prefix='stella-edge-extract-', dir=os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch'))) as tmp:
        try:
            carrier = command(['docker', 'create', '--name', name, '--network', 'none', '--restart', 'no',
                               '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                               '--entrypoint', '/bin/false', image]).decode().strip()
            command(['docker', 'cp', carrier + ':/app/frontend/dist', tmp + '/dist'])
            return make_stage(Path(tmp) / 'dist', image, info['Id'], revision, out)
        finally:
            if carrier:
                command(['docker', 'rm', carrier])


LOG_FORMAT = r'''log_format stella_edge_timing escape=json '{"time":"$time_iso8601","origin":"$scheme://$host","method":"$request_method","path":"$uri","status":$status,"bytes":$body_bytes_sent,"request_time":"$request_time","upstream_connect_time":"$upstream_connect_time","upstream_header_time":"$upstream_header_time","upstream_response_time":"$upstream_response_time"}';
'''


def render(old, assets, access_log='/var/log/nginx/stella-safe-access.log'):
    """Strict snapshot transformer: preserve all proxy/TLS directives byte-for-byte."""
    if old.startswith(LOG_FORMAT):
        old = old[len(LOG_FORMAT):]
    old = re.sub(r'    # BEGIN STELLA EDGE\n.*?    # END STELLA EDGE\n', '', old, flags=re.S)
    require(old.count('server_name stella.xiya.live;') == 2 and
            old.count('proxy_pass http://127.0.0.1:12031;') == 1 and
            old.count('location / {') == 1 and old.count('listen 443 ssl;') == 1, 'unexpected vhost layout; refuse')
    require(not re.search(r'location\s+(?:=\s+|\^~\s+)?/static', old), 'existing static location; refuse')
    require(old.count('access_log ') == 2 and old.count('error_log /dev/null crit;') == 2, 'safe logging baseline required')
    # Changing only this dedicated vhost; shared formats/integration hosts untouched.
    require(re.fullmatch(r'/[A-Za-z0-9_./-]+', access_log) and '..' not in Path(access_log).parts, 'unsafe access log path')
    old = re.sub(r'access_log [^;]+;', 'access_log ' + access_log + ' stella_edge_timing;', old)
    block = ['    # BEGIN STELLA EDGE', '    gzip on;', '    gzip_vary on;', '    gzip_min_length 1024;',
             '    gzip_types application/javascript text/javascript text/css application/wasm;',
             '    location ^~ /static/ { return 404; }']
    for name, item in sorted(assets.items()):
        require(ASSET.fullmatch(name) and re.fullmatch(r'/[A-Za-z0-9_./-]+', item['path']) and
                '..' not in Path(item['path']).parts and re.fullmatch(HEX, item['sha256']), 'unsafe asset location')
        block += ['    location = /' + name + ' {', '        alias ' + item['path'] + ';',
                  '        disable_symlinks on;', '        limit_except GET HEAD { deny all; }',
                  '        add_header Cache-Control "public, max-age=604800, immutable";',
                  '        add_header X-Stella-Static-SHA256 "' + item['sha256'] + '";',
                  '        add_header X-Content-Type-Options nosniff;', '    }']
    block += ['    # END STELLA EDGE', '']
    return LOG_FORMAT + old.replace('    location / {', '\n'.join(block) + '    location / {', 1)


def collect(root, new_manifest):
    """Union of retained immutable versions. Same URL cannot change its bytes."""
    root = trusted(root)
    assets, versions = {}, []
    for release in sorted((root / 'releases').iterdir()):
        trusted(release)
        require(re.fullmatch(HEX, release.name) and release.is_dir(), 'release directory invalid')
        m = validate_manifest(json.loads(read(release / 'manifest.json')))
        require(m['version'] == release.name, 'release name mismatch')
        versions.append(release.name)
        expected = {'manifest.json'} | {'public/' + name for name in m['public']}
        actual = set()
        for p in release.rglob('*'):
            trusted(p)
            if not p.is_dir():
                actual.add(p.relative_to(release).as_posix())
        require(actual == expected, 'release extra/missing files')
        for name in m['public']:
            path = release / 'public' / name
            data = read(path)
            require({'sha256': sha(data), 'size': len(data)} == m['files'][name], 'retained asset corrupt')
            entry = {'sha256': sha(data), 'size': len(data), 'path': str(path)}
            require(name not in assets or assets[name]['sha256'] == entry['sha256'], 'same URL different bytes rejected')
            assets.setdefault(name, entry)
    require(new_manifest['version'] in versions, 'new version missing')
    return assets, versions


def install_release(stage, root):
    m = verify_stage(stage)
    root = trusted(root, exists=False)
    root.mkdir(parents=True, mode=0o755, exist_ok=True)
    releases = root / 'releases'
    releases.mkdir(mode=0o755, exist_ok=True)
    trusted(releases)
    target = releases / m['version']
    created = False
    if not target.exists():
        tmp = releases / ('.stage-' + uuid.uuid4().hex)
        tmp.mkdir(mode=0o755)
        try:
            shutil.copytree(Path(stage) / 'public', tmp / 'public')
            os.chmod(tmp / 'public', 0o755)
            atomic(tmp / 'manifest.json', encoded(m), 0o644)
            for p in tmp.rglob('*'):
                os.chmod(p, 0o755 if p.is_dir() else 0o644)
                if p.is_file():
                    with p.open('rb') as f:
                        os.fsync(f.fileno())
            directories = [tmp, *(p for p in tmp.rglob('*') if p.is_dir())]
            for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.rename(tmp, target)
            created = True
            for directory in (releases, root, root.parent):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)
    try:
        assets, versions = collect(root, m)
    except BaseException:
        if created:
            shutil.rmtree(target)
        raise
    return m, assets, versions


class Deployer:
    """Host-local one-vhost transaction. Unit tests inject commands and health.
    Persistent backup plus config before reload; rollback is operator-repeatable.
    Not a distributed app+edge transaction or kill/power-loss automatic watchdog.
    """
    def __init__(self, vhost=VHOST, root=ROOT, state=STATE, run=command, health=None, recovery_health=None):
        self.vhost, self.root, self.state = Path(vhost), Path(root), Path(state)
        self.run = run
        self.health = health or self.production_health
        self.recovery_health = recovery_health or self.production_recovery_health

    def production_recovery_health(self):
        self.run(['curl', '--silent', '--show-error', '--fail', '--noproxy', '*', '--max-time', '15',
                  '--resolve', 'stella.xiya.live:443:127.0.0.1', 'https://stella.xiya.live/live'])

    def nginx_test_reload(self):
        self.run(['nginx', '-t'])
        self.run(['nginx', '-s', 'reload'])

    def production_health(self, manifest, assets, primary_manifest=None):
        # Resolve localhost but keep original HTTPS Host/SNI and certificate checks.
        base = ['curl', '--silent', '--show-error', '--fail', '--noproxy', '*',
                '--max-time', '15', '--resolve', 'stella.xiya.live:443:127.0.0.1']
        html = self.run(base + ['https://stella.xiya.live/'])
        primary = primary_manifest or manifest
        require(sha(html) == primary['files']['index.html']['sha256'], 'primary HTML != explicitly approved image')
        require(self.run(base + ['https://stella.xiya.live/live']), 'primary live health failed')
        for name in sorted(assets):
            # Reload is asynchronous: identical primary bytes alone cannot prove
            # the edge config is active. Require our marker AND public cache header.
            deadline, stable = time.monotonic() + 8, None
            while True:
                try:
                    raw = self.run(base + ['--include', 'https://stella.xiya.live/' + name])
                    header, body = raw.split(b'\r\n\r\n', 1)
                    good = (b' 200 ' in header.split(b'\r\n')[0] and sha(body) == assets[name]['sha256'] and
                            ('x-stella-static-sha256: ' + assets[name]['sha256']).encode() in header.lower() and
                            b'cache-control: public, max-age=604800, immutable' in header.lower())
                except ValueError:
                    good = False
                if good:
                    stable = stable or time.monotonic()
                    # Stabilize first asset across overlapping old/new workers;
                    # subsequent assets still retry mismatched headers/body hashes.
                    if name != manifest['public'][0] or time.monotonic() - stable >= 0.3:
                        break
                else:
                    stable = None
                require(time.monotonic() < deadline, 'HTTPS asset headers/identity mismatch after reload')
                time.sleep(0.05)

    def readback(self, content):
        require(read(self.vhost) == content, 'exact config readback failed')
        require(content in self.run(['nginx', '-T']), 'active config readback failed')

    def apply(self, stage, expected_vhost_sha, primary_stage=None):
        require(re.fullmatch(HEX, expected_vhost_sha), 'full reviewed vhost SHA required')
        trusted(self.vhost)
        trusted(self.state, exists=False).mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.state, 0o700)
        trusted(self.state)
        with lock_file(self.state) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            old = read(self.vhost)
            require(sha(old) == expected_vhost_sha, 'vhost changed since approval')
            self.run(['nginx', '-t'])
            full = self.run(['nginx', '-T'])
            prior = install_release(primary_stage, self.root)[0] if primary_stage is not None else None
            m, assets, versions = install_release(stage, self.root)
            candidate = render(old.decode(), assets).encode()
            tx = self.state / uuid.uuid4().hex
            tx.mkdir(mode=0o700)
            atomic(tx / 'previous.conf', old)
            atomic(tx / 'complete-nginx-before.txt', full)
            atomic(tx / 'candidate.conf', candidate)
            atomic(tx / 'manifest.json', encoded(m))
            old_mode = stat.S_IMODE(self.vhost.stat().st_mode)
            receipt = dict(schema='stella-edge-transaction-v1', vhost=str(self.vhost),
                           old_sha256=sha(old), new_sha256=sha(candidate), old_mode=old_mode,
                           version=m['version'], retained_versions=versions, status='prepared')
            receipt['expected_primary_version'] = (prior or m)['version']
            atomic(tx / 'receipt.json', encoded(receipt))
            for directory in (self.state, self.state.parent):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            try:
                atomic(self.vhost, candidate, old_mode)
                self.nginx_test_reload()
                self.readback(candidate)
                if prior is None:
                    self.health(m, assets)
                else:
                    self.health(m, assets, prior)
                receipt['status'] = 'verified'
                atomic(tx / 'receipt.json', encoded(receipt))
                return str(tx)
            except BaseException:
                # Includes Ctrl-C. SIGKILL/power-loss needs explicit rollback command.
                atomic(self.vhost, old, old_mode)
                try:
                    self.nginx_test_reload()
                    self.readback(old)
                    self.recovery_health()
                    receipt['status'] = 'rolled-back'
                except BaseException:
                    receipt['status'] = 'rollback-needs-operator'
                atomic(tx / 'receipt.json', encoded(receipt))
                raise

    def rollback(self, tx):
        trusted(self.state)
        tx = trusted(tx)
        require(tx.parent == self.state and re.fullmatch('[0-9a-f]{32}', tx.name), 'transaction outside trusted state')
        with lock_file(self.state) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            receipt = json.loads(read(tx / 'receipt.json'))
            require(receipt['schema'] == 'stella-edge-transaction-v1' and receipt['vhost'] == str(self.vhost), 'receipt target mismatch')
            old = read(tx / 'previous.conf')
            require(sha(old) == receipt['old_sha256'] and read(self.vhost) in (old, read(tx / 'candidate.conf')), 'backup mismatch or later deployment; refuse')
            require(sha(read(tx / 'candidate.conf')) == receipt['new_sha256'], 'candidate tampered')
            atomic(self.vhost, old, receipt['old_mode'])
            self.nginx_test_reload()
            self.readback(old)
            # Query-free GET through original TLS; rollback can precede app rollback.
            self.recovery_health()
            receipt['status'] = 'rolled-back'
            atomic(tx / 'receipt.json', encoded(receipt))
            return str(tx)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    ex = sub.add_parser('extract', help='explicit LOCAL temporary Docker carrier, never started; no pull')
    ex.add_argument('--image', required=True)
    ex.add_argument('--revision', required=True)
    ex.add_argument('--read-only-container', help='read-only exact-image carrier, inspect/cp only, NO lifecycle writes')
    ex.add_argument('--out', type=Path, required=True)
    ve = sub.add_parser('verify-stage', help='offline hashes only')
    ve.add_argument('stage', type=Path)
    ap = sub.add_parser('apply', help='MUTATING, host-local only, after operator approval')
    ap.add_argument('stage', type=Path)
    ap.add_argument('--expected-vhost-sha256', required=True)
    ap.add_argument('--primary-stage', type=Path, help='pre-publication: explicitly approved current HTML stage; retain both versions')
    ap.add_argument('--approve-production-write', action='store_true', required=True)
    ro = sub.add_parser('rollback', help='MUTATING exact dedicated vhost restore')
    ro.add_argument('transaction', type=Path)
    ro.add_argument('--approve-production-write', action='store_true', required=True)
    a = p.parse_args()
    if a.action == 'extract':
        result = extract(a.image, a.revision, a.out, a.read_only_container)
    elif a.action == 'verify-stage':
        result = verify_stage(a.stage)
    else:
        require(os.geteuid() == 0, 'root local operator required')
        result = Deployer().apply(a.stage, a.expected_vhost_sha256, a.primary_stage) if a.action == 'apply' else Deployer().rollback(a.transaction)
    print(json.dumps({'action': a.action, 'result': result}, sort_keys=True))


if __name__ == '__main__':
    main()
