"""File-only complete-release contract. Never grants roots or invokes commands.

The generic updater may use ReleaseStore.transaction under its instance lock.
This module does not alter the legacy single-script updater/rollout policy.
"""
import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

FILES = ('stella_agent.py', 'node_files.py')
LIMIT = 2 * 1024 * 1024


class ReleaseError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def release_id(manifest):
    return hashlib.sha256(canonical(manifest)).hexdigest()


@lru_cache(maxsize=4)
def _source_declarations(body):
    # Retain only immutable facts from a complete, compilable exact source.
    # Never cache ASTs, manifests, filesystem metadata or failed parses.
    tree = ast.parse(body)
    compile(tree, '<release>', 'exec')
    return tuple((n.targets[0].id, n.value.value) for n in tree.body
                 if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant))


def declaration(body, name):
    # Other inputs accepted by ast.parse (including mutable ASTs/bytearrays)
    # keep their original validation path, without hashing or retaining them.
    parse = _source_declarations if type(body) is bytes and len(body) <= LIMIT else _source_declarations.__wrapped__
    values = [value for symbol, value in parse(body) if symbol == name]
    if len(values) != 1:
        raise ReleaseError('invalid_version_declaration')
    return values[0]


def build_release(source):
    source = Path(source)
    bodies = {name: (source / name).read_bytes() for name in FILES}
    version = declaration(bodies['stella_agent.py'], 'AGENT_VERSION')
    module_version = declaration(bodies['node_files.py'], 'FILE_MODULE_VERSION')
    protocol = declaration(bodies['node_files.py'], 'FILE_PROTOCOL')
    files = {name: {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
             for name, body in bodies.items()}
    files['stella_agent.py']['version'] = version
    files['node_files.py'].update(version=module_version, protocol=protocol, platforms=['linux'])
    manifest = {'format': 1, 'version': version, 'files': files}
    validate_manifest(manifest)
    return manifest, bodies


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) != {'format', 'version', 'files'} or type(value['format']) is not int or value['format'] != 1:
        raise ReleaseError('invalid_release_manifest')
    if not isinstance(value['version'], str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value['version']):
        raise ReleaseError('invalid_release_version')
    if not isinstance(value['files'], dict) or set(value['files']) != set(FILES):
        raise ReleaseError('incomplete_release')
    for name in FILES:
        info = value['files'][name]
        keys = {'size', 'sha256', 'version'} | ({'protocol', 'platforms'} if name == 'node_files.py' else set())
        if not isinstance(info, dict) or set(info) != keys:
            raise ReleaseError('invalid_file_manifest')
        if type(info['size']) is not int or not 0 < info['size'] <= LIMIT or not isinstance(info['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', info['sha256']):
            raise ReleaseError('invalid_file_digest')
        if not isinstance(info['version'], str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', info['version']):
            raise ReleaseError('invalid_module_version')
    if value['files']['stella_agent.py']['version'] != value['version']:
        raise ReleaseError('inconsistent_release_version')
    module = value['files']['node_files.py']
    if type(module['protocol']) is not int or module['protocol'] != 1 or module['platforms'] != ['linux']:
        raise ReleaseError('unsupported_file_protocol')
    return value


def verify_body(name, info, body):
    if not isinstance(body, bytes) or len(body) != info['size'] or hashlib.sha256(body).hexdigest() != info['sha256']:
        raise ReleaseError('release_size_hash_mismatch')
    symbol = 'AGENT_VERSION' if name == 'stella_agent.py' else 'FILE_MODULE_VERSION'
    if declaration(body, symbol) != info['version']:
        raise ReleaseError('release_version_mismatch')
    if name == 'node_files.py' and declaration(body, 'FILE_PROTOCOL') != info['protocol']:
        raise ReleaseError('release_protocol_mismatch')


def fsync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class ReleaseStore:
    """Private immutable generations, selected with one atomic JSON pointer.

    No same-UID hostile-process sandbox is claimed. Caller owns this directory
    and must serialize resident process handoff under its existing instance lock.
    A crash leaves the directory lock in place: never auto-break an unknown lock.
    On Windows, the caller must provision an instance-private NTFS DACL first.
    """
    def __init__(self, root):
        self.root = Path(root).absolute()
        if self.root == self.root.parent:
            raise ReleaseError('invalid_release_store')
        for item in [*self.root.parents, self.root]:
            if item.is_symlink():
                raise ReleaseError('symlink_release_store')
        self.root.mkdir(mode=0o700, exist_ok=True)
        self._private(self.root, directory=True)

    @staticmethod
    def _private(path, directory=False):
        info = path.lstat()
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
            raise ReleaseError('unsafe_release_file')
        if os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ReleaseError('untrusted_release_owner_mode')

    def _read(self, path, limit=LIMIT):
        self._private(path)
        with path.open('rb') as source:
            body = source.read(limit + 1)
        if len(body) > limit:
            raise ReleaseError('release_size_limit')
        return body

    def _atomic(self, path, body):
        fd, name = tempfile.mkstemp(prefix='.pointer-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(body)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, path)
            fsync_directory(self.root)
        finally:
            Path(name).unlink(missing_ok=True)

    def current(self):
        pointer = self.root / 'current.json'
        if not pointer.exists() and not pointer.is_symlink():
            return None
        value = json.loads(self._read(pointer, 256))
        if not isinstance(value, dict) or set(value) != {'release'} or not isinstance(value['release'], str) or not re.fullmatch('[a-f0-9]{64}', value['release']):
            raise ReleaseError('invalid_release_pointer')
        path = self.root / value['release']
        self.verify(path, value['release'])
        return path

    def verify(self, path, expected):
        self._private(path, directory=True)
        manifest = validate_manifest(json.loads(self._read(path / 'manifest.json', 8192)))
        if release_id(manifest) != expected or set(p.name for p in path.iterdir()) != set(FILES) | {'manifest.json'}:
            raise ReleaseError('release_generation_mismatch')
        for name in FILES:
            verify_body(name, manifest['files'][name], self._read(path / name))
        return manifest

    @staticmethod
    def probe(path, manifest):
        # Import actual staged bytes with the resident interpreter, no run/main,
        # no inherited center credentials, proxy configuration or database DSN.
        code = ('import sys; sys.path.insert(0,sys.argv[1]); '
                'import stella_agent,node_files,httpx; '
                'assert stella_agent.AGENT_VERSION == sys.argv[2]; '
                'assert node_files.FILE_MODULE_VERSION == sys.argv[3]; '
                'assert node_files.FILE_PROTOCOL == 1; '
                'assert callable(node_files.FileWorker); '
                'assert node_files.Sandbox.from_env().roots() == []')
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TMPDIR', 'TEMP') if k in os.environ}
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(path), manifest['version'], manifest['files']['node_files.py']['version']], env=env, cwd=path, capture_output=True, timeout=15)
        if result.returncode:
            raise ReleaseError('release_load_validation_failed')

    @contextlib.contextmanager
    def transaction(self, manifest, fetch):
        # Copy untrusted input so a callback cannot mutate admitted metadata.
        manifest = validate_manifest(json.loads(canonical(manifest)))
        lock = self.root / '.install-lock'
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError:
            raise ReleaseError('release_install_busy') from None
        stage = None
        switched = False
        previous = None
        try:
            current = self.current()
            pointer = self.root / 'current.json'
            previous = self._read(pointer, 256) if current else None
            identity = release_id(manifest)
            target = self.root / identity
            if not target.exists():
                stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.root))
                for name in FILES:
                    info = manifest['files'][name]
                    body = fetch(name, dict(info))
                    verify_body(name, info, body)
                    with (stage / name).open('xb') as out:
                        os.chmod(stage / name, 0o600)
                        out.write(body)
                        out.flush()
                        os.fsync(out.fileno())
                with (stage / 'manifest.json').open('xb') as out:
                    os.chmod(stage / 'manifest.json', 0o600)
                    out.write(canonical(manifest))
                    out.flush()
                    os.fsync(out.fileno())
                self.verify(stage, identity)
                self.probe(stage, manifest)
                fsync_directory(stage)
                os.rename(stage, target)
                stage = None
                fsync_directory(self.root)
            self.verify(target, identity)
            self.probe(target, manifest)
            # Set the rollback flag before replacing: a subsequent fsync failure
            # must still restore the old pointer rather than expose a false fail.
            switched = True
            self._atomic(pointer, canonical({'release': identity}))
            if self.current() != target:
                raise ReleaseError('release_readback_failed')
            yield target
            self.verify(target, identity)
        except BaseException:
            if switched:
                if previous is None:
                    (self.root / 'current.json').unlink(missing_ok=True)
                    fsync_directory(self.root)
                else:
                    self._atomic(self.root / 'current.json', previous)
            raise
        finally:
            if stage is not None:
                shutil.rmtree(stage)
            lock.rmdir()

    def install(self, manifest, fetch):
        with self.transaction(manifest, fetch) as path:
            return path


def checked_origin(origin, allow_loopback=False):
    from urllib.parse import urlsplit
    p = urlsplit(origin)
    if (p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password
            or p.query or p.fragment or p.path not in ('', '/')
            or (p.scheme != 'https' and not (allow_loopback and p.hostname in ('127.0.0.1', '::1')))):
        raise ReleaseError('file_release_requires_https_origin')
    return origin.rstrip('/')


def download_release(origin, token, store, expected, *, allow_loopback=False):
    """Fetch a pre-approved *complete* manifest, never a version announcement.

    The expected canonical manifest digest is mandatory. Same version with new
    bytes therefore cannot silently replace an approved package. Generic rollout
    version/monotonic policy remains the caller's responsibility.
    """
    import httpx
    import time
    origin = checked_origin(origin, allow_loopback)
    if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
        raise ReleaseError('invalid_release_pin')
    if not isinstance(token, str) or not token or any(x in token for x in '\r\n\x00'):
        raise ReleaseError('invalid_file_agent_token')
    with httpx.Client(base_url=origin, headers={'Authorization': 'Bearer ' + token, 'Accept-Encoding': 'identity'}, trust_env=False, follow_redirects=False, timeout=10) as client:
        def fetch_path(path, limit):
            body = bytearray()
            deadline = time.monotonic() + 30
            with client.stream('GET', path) as response:
                if response.status_code != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ReleaseError('file_release_http_refused')
                for chunk in response.iter_raw(chunk_size=65536):
                    if len(body) + len(chunk) > limit or time.monotonic() > deadline:
                        raise ReleaseError('file_release_download_budget')
                    body.extend(chunk)
            return bytes(body)
        manifest = validate_manifest(json.loads(fetch_path('/agent/files/release', 8192)))
        if release_id(manifest) != expected:
            raise ReleaseError('file_release_pin_mismatch')
        return store.install(manifest, lambda name, info: fetch_path('/agent/files/release/' + expected + '/' + name, info['size']))


def installed_module(store):
    import types
    path = store.current()
    if path is None:
        raise ReleaseError('file_release_not_installed')
    manifest = store.verify(path, path.name)
    if sys.platform not in manifest['files']['node_files.py']['platforms']:
        raise ReleaseError('file_worker_platform_unsupported')
    body = store._read(path / 'node_files.py')
    verify_body('node_files.py', manifest['files']['node_files.py'], body)
    # A normal import writes __pycache__ and invalidates an immutable generation.
    # Compile the verified bytes directly; never import an unverified fallback.
    module = types.ModuleType('_stella_files_' + path.name)
    module.__file__ = str(path / 'node_files.py')
    exec(compile(body, module.__file__, 'exec'), module.__dict__)
    return module, manifest


def run_worker(store, origin, token, interval=.5, *, allow_loopback=False, on_ready=None, before_tick=None):
    """Optional isolated file-only service; no app imports, shell or DB access."""
    import signal
    import threading
    origin = checked_origin(origin, allow_loopback)
    if not .05 <= interval <= 60:
        raise ReleaseError('invalid_worker_interval')
    if any(k.startswith('POSTGRES_') for k in os.environ):
        raise ReleaseError('file_worker_database_environment_refused')
    if not token or any(c in token for c in '\r\n\x00'):
        raise ReleaseError('invalid_file_agent_token')
    module, manifest = installed_module(store)
    sandbox = module.Sandbox.from_env()
    stop = threading.Event()
    def shutdown(*_):
        stop.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    worker = module.FileWorker(origin, token, sandbox)
    print(json.dumps({'event': 'start', 'release': release_id(manifest), 'module_sha256': manifest['files']['node_files.py']['sha256'], 'module_version': manifest['files']['node_files.py']['version'], 'pid': os.getpid(), 'roots': sandbox.roots(), 'app_imported': any(k == 'app' or k.startswith('app.') for k in sys.modules), 'postgres_environment_present': any(k.startswith('POSTGRES_') for k in os.environ)}), flush=True)
    ticks = 0
    ready = False
    try:
        while not stop.is_set():
            if before_tick is not None:
                before_tick()  # Binding removal is fatal, not a retryable HTTP error.
            try:
                worker.tick()
                ticks += 1
                if not ready and on_ready is not None:
                    on_ready()
                    ready = True
            except Exception as exc:
                # Never log request URLs/leases/tokens or exception text.
                print(json.dumps({'event': 'worker_error', 'kind': type(exc).__name__}), flush=True)
            stop.wait(interval)
    finally:
        worker.client.close()
        print(json.dumps({'event': 'stop', 'pid': os.getpid(), 'ticks': ticks}), flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Private file-only complete-release installer/worker; no root grants')
    parser.add_argument('action', choices=('fetch', 'check', 'run'))
    parser.add_argument('--store', required=True)
    parser.add_argument('--origin')
    parser.add_argument('--release', help='Approved SHA256 of canonical complete manifest (required for fetch)')
    parser.add_argument('--interval', type=float, default=.5)
    parser.add_argument('--allow-loopback', action='store_true', help='Explicit isolated local HTTP test transport only')
    args = parser.parse_args()
    try:
        store = ReleaseStore(args.store)
        if args.action == 'check':
            _, manifest = installed_module(store)
            print(json.dumps({'release': release_id(manifest), 'manifest': manifest}), flush=True)
        elif args.action == 'fetch':
            download_release(args.origin, os.environ.get('STELLA_TOKEN'), store, args.release, allow_loopback=args.allow_loopback)
            print(json.dumps({'release': store.current().name}), flush=True)
        else:
            run_worker(store, args.origin, os.environ.get('STELLA_TOKEN'), args.interval, allow_loopback=args.allow_loopback)
    except Exception as exc:
        print(json.dumps({'event': 'refused', 'kind': type(exc).__name__}), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
