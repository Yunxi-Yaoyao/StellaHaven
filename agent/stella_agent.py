#!/usr/bin/env python3
"""Stella Agent — 被纳管服务器的采集上报 + 任务执行客户端。

单文件，仅依赖标准库 + psutil + httpx（跨 Linux / Windows / 飞牛OS）。

职责：
1. 采集本机数据：网卡流量（默认出口网卡）、系统指标（CPU/内存/磁盘）
2. 5s 上报流量 + 60s 上报系统指标（上报即心跳）
3. 内存队列补传：上报失败时数据压队列，恢复后按时间顺序批量补传
4. 5s 轮询待办任务（打流/MTR/命令），执行后回传结果
5. 检测默认出口网卡（默认路由），上报网卡清单供中心配置监控范围

用法：
    stella-agent --url http://<stella>:12031 --token <token>
    或环境变量 STELLA_URL / STELLA_TOKEN
"""
import argparse
import base64
import hashlib
import ipaddress
import math
import json
import os
import platform
import re
import select
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
import zlib
from collections import deque
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    psutil = None

try:
    import httpx
except ImportError:
    httpx = None


AGENT_VERSION = "0.6.21"


class _FilePackage:
    """Stdlib bootstrap for old single-script installs; immutable whole packages.

    TLS authenticates the manifest; SHA256 is integrity, not a signature. Never
    import adjacent modules until every byte and the actual interpreter probe pass.
    The owning supervisor serializes installs. Keep the previous generation.
    """
    names = ('stella_agent.py', 'node_files.py')
    limit = 2 * 1024 * 1024

    def __init__(self, root):
        from pathlib import Path
        self.root = Path(os.path.abspath(root))
        for part in reversed([self.root, *self.root.parents]):
            if part.is_symlink():
                raise ValueError('unsafe file package path')
            if part.exists():
                self._safe(part, True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._safe(self.root, True)

    @staticmethod
    def _safe(path, directory=False):
        import stat
        st = path.lstat()
        if (path.is_symlink() or st.st_uid != os.geteuid() or st.st_mode & 0o022
                or not (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode) and st.st_nlink == 1)):
            raise ValueError('unsafe file package')

    @staticmethod
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')

    @classmethod
    def manifest(cls, value):
        value = json.loads(cls.canonical(value))
        if (not isinstance(value, dict) or set(value) != {'format', 'version', 'files'}
                or type(value['format']) is not int or value['format'] != 1
                or not isinstance(value['version'], str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value['version'])
                or not isinstance(value['files'], dict) or set(value['files']) != set(cls.names)):
            raise ValueError('invalid file manifest')
        for name in cls.names:
            info = value['files'][name]
            keys = {'size', 'sha256', 'version'} | ({'protocol', 'platforms'} if name == 'node_files.py' else set())
            if (not isinstance(info, dict) or set(info) != keys or type(info['size']) is not int
                    or not 0 < info['size'] <= cls.limit or not isinstance(info['sha256'], str)
                    or not re.fullmatch('[a-f0-9]{64}', info['sha256']) or not isinstance(info['version'], str)
                    or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', info['version'])):
                raise ValueError('invalid file metadata')
        if value['files']['stella_agent.py']['version'] != value['version']:
            raise ValueError('inconsistent file version')
        info = value['files']['node_files.py']
        if type(info['protocol']) is not int or info['protocol'] != 1 or info['platforms'] != ['linux']:
            raise ValueError('unsupported file protocol')
        return value

    @staticmethod
    def _body(name, info, body):
        import ast
        import hashlib
        if len(body) != info['size'] or hashlib.sha256(body).hexdigest() != info['sha256']:
            raise ValueError('file package size/hash mismatch')
        tree = ast.parse(body)
        compile(tree, name, 'exec')
        symbol = 'AGENT_VERSION' if name == 'stella_agent.py' else 'FILE_MODULE_VERSION'
        def declarations(key):
            return [n.value.value for n in tree.body if isinstance(n, ast.Assign)
                    and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                    and n.targets[0].id == key and isinstance(n.value, ast.Constant)]
        if declarations(symbol) != [info['version']] or (name == 'node_files.py' and declarations('FILE_PROTOCOL') != [1]):
            raise ValueError('file package declaration mismatch')

    def verify(self, path, manifest):
        self._safe(path, True)
        if {p.name for p in path.iterdir()} != set(self.names) | {'manifest.json'}:
            raise ValueError('incomplete file package')
        for name in (*self.names, 'manifest.json'):
            self._safe(path / name)
        if (path / 'manifest.json').read_bytes() != self.canonical(manifest):
            raise ValueError('file manifest changed')
        for name in self.names:
            with (path / name).open('rb') as source:
                self._body(name, manifest['files'][name], source.read(self.limit + 1))

    @staticmethod
    def _sync(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def install(self, manifest, fetch, cancelled=lambda: False):
        import hashlib
        import shutil
        import tempfile
        from pathlib import Path
        manifest = self.manifest(manifest)
        identity = hashlib.sha256(self.canonical(manifest)).hexdigest()
        target = self.root / identity
        stage = None
        try:
            if not target.exists():
                stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.root))
                for name in self.names:
                    if cancelled():
                        raise ValueError('file install cancelled')
                    info = manifest['files'][name]
                    body = fetch('/agent/files/release/' + identity + '/' + name, info['size'])
                    self._body(name, info, body)
                    with (stage / name).open('xb') as out:
                        os.chmod(out.name, 0o600)
                        out.write(body); out.flush(); os.fsync(out.fileno())
                with (stage / 'manifest.json').open('xb') as out:
                    out.write(self.canonical(manifest)); out.flush(); os.fsync(out.fileno())
                self.verify(stage, manifest)
                # Explicit status, no asserts (works under PYTHONOPTIMIZE too).
                probe = ('import os,signal,sys,ctypes; '
                         'guard=ctypes.CDLL(None,use_errno=True).prctl(1,signal.SIGKILL,0,0,0); '
                         'sys.exit(1) if guard!=0 or os.getppid()!=int(sys.argv[4]) else None; '
                         'sys.path.insert(0,sys.argv[1]); import stella_agent,node_files; '
                         'sys.exit(73 if stella_agent.AGENT_VERSION==sys.argv[2] and '
                         'node_files.FILE_MODULE_VERSION==sys.argv[3] and node_files.FILE_PROTOCOL==1 and '
                         'callable(node_files.FileWorker) and callable(stella_agent.main) else 1)')
                result = subprocess.run([sys.executable, '-I', '-B', '-c', probe, str(stage), manifest['version'], manifest['files']['node_files.py']['version'], str(os.getpid())],
                                        env={'PATH': '/usr/bin:/bin'}, cwd=stage, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if result.returncode != 73:
                    raise ValueError('file package load failed')
                self._sync(stage)
                os.rename(stage, target); stage = None
                self._sync(self.root)
            self.verify(target, manifest)
            if cancelled():
                raise ValueError('file install cancelled')
            pointer = self.root / 'current.json'
            if pointer.exists():
                self._safe(pointer)
            body = self.canonical({'release': identity})
            if not pointer.exists() or pointer.read_bytes() != body:
                fd, temporary = tempfile.mkstemp(prefix='.pointer-', dir=self.root)
                try:
                    with os.fdopen(fd, 'wb') as out:
                        out.write(body); out.flush(); os.fsync(out.fileno())
                    os.replace(temporary, pointer); self._sync(self.root)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            return target
        finally:
            if stage is not None:
                shutil.rmtree(stage)



def _file_roots(config, legacy=None):
    """Only the center's closed explicit grant, or explicit legacy local roots."""
    if legacy is not None:
        value = json.loads(legacy)
        if not isinstance(value, dict):
            raise ValueError('invalid legacy roots')
        for key, root in value.items():
            if (not isinstance(key, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', key)
                    or not isinstance(root, dict) or set(root) != {'path', 'write'}
                    or not isinstance(root['path'], str) or not root['path'].startswith('/')
                    or type(root['write']) is not bool):
                raise ValueError('invalid legacy root')
        return value
    if (isinstance(config, dict) and set(config) == {'enabled', 'roots', 'revision'}
            and config['enabled'] is True and isinstance(config['revision'], str)
            and re.fullmatch('[a-f0-9]{64}', config['revision'])
            and config['roots'] == {'system': {'path': '/', 'write': True}}
            and type(config['roots']['system']['write']) is bool):
        return {'system': {'path': '/', 'write': True}}
    return {}


class _FileSupervisor:
    """Nonblocking main-loop control. Network/bootstrap runs in a killable child.

    No service is created. Children retain the Agent's systemd cgroup; separate
    process groups allow bounded owned cleanup without signalling foreign PIDs.
    Tokens/config travel over stdin, never argv or the child's environment.
    """
    def __init__(self, snapshot, *, allow_loopback=False, refresh=5, backoff=1):
        self.snapshot = snapshot
        self.allow_loopback = allow_loopback
        self.refresh, self.backoff = refresh, backoff
        self.worker = self.preparing = None
        self.spec = self.key = self.worker_key = None
        self.bound_identity = None
        self.next_prepare = self.next_worker = 0
        self.failures = 0
        self.closed = False

    @staticmethod
    def _notice(event):
        print('[files] ' + event, file=sys.stderr, flush=True)

    def _spawn(self, script, action, spec, output=False):
        r, w = os.pipe()
        try:
            child = subprocess.Popen([sys.executable, '-I', '-B', str(script), action, str(r), str(os.getpid())],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE if output else subprocess.DEVNULL,
                stderr=None, env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
                cwd='/', pass_fds=(r,), start_new_session=True)
            child._file_guard = w
            child._file_started = time.monotonic()
            child.stdin.write(_FilePackage.canonical(spec)); child.stdin.close()
            return child
        except BaseException:
            os.close(w)
            if 'child' in locals():
                self._stop(child)
            raise
        finally:
            os.close(r)

    @staticmethod
    def _stop(child):
        import signal
        if child is None:
            return
        # Reap even a previously crashed child before releasing its parent pipe.
        try:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=.3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=1)
        except ProcessLookupError:
            child.wait(timeout=1)
        finally:
            if child.stdout is not None:
                child.stdout.close()
            guard = getattr(child, '_file_guard', None)
            if guard is not None:
                os.close(guard); child._file_guard = None

    def close(self):
        self.closed = True
        for field in ('worker', 'preparing'):
            self._stop(getattr(self, field)); setattr(self, field, None)

    def tick(self):
        from pathlib import Path
        if self.closed:
            return
        now = time.monotonic()
        try:
            spec = self.snapshot()
            key = _FilePackage.canonical(spec)
        except Exception:
            self._stop(self.worker); self.worker = None
            self._stop(self.preparing); self.preparing = None
            self._notice('local binding refused')
            return
        if key != self.key:
            self._stop(self.worker); self.worker = None
            self._stop(self.preparing); self.preparing = None
            self.spec, self.key = spec, key
            self.worker_key = self.bound_identity = None
            self.next_prepare = self.next_worker = 0
            self.failures = 0
        if self.worker is not None and self.worker.poll() is not None:
            self._notice('worker exited; bounded restart backoff')
            self._stop(self.worker); self.worker = None
            self.failures = min(self.failures + 1, 6)
            self.next_worker = now + min(30, self.backoff * 2 ** (self.failures - 1))
        if self.worker is not None and now - self.worker._file_started > 60:
            self.failures = 0
        if self.preparing is not None:
            if now - self.preparing._file_started > 20:
                self._notice('configuration/package deadline exceeded')
                self._stop(self.preparing); self.preparing = None
                self._stop(self.worker); self.worker = None
                self.next_prepare = now + self.refresh
            elif self.preparing.poll() is not None:
                try:
                    if (self.preparing.returncode == 75 and self.worker is not None
                            and self.worker_key is not None):
                        # The local spec key was checked above. This is only a
                        # socket timeout from bootstrap, not a new grant: the
                        # existing worker still uses live claim/status/admit
                        # owner/session/token/policy fences at the center.
                        self._notice('temporary configuration network timeout; verified worker retained')
                        return  # finally reaps prepare and bounds the retry.
                    if self.preparing.returncode != 0:
                        raise ValueError('file preparation failed')
                    body = self.preparing.stdout.read(16385)
                    if len(body) > 16384:
                        raise ValueError('file preparation response limit')
                    ready = json.loads(body)
                    self.bound_identity = ready['identity']
                    worker_key = _FilePackage.canonical(ready)
                    if not ready['roots']:
                        self._stop(self.worker); self.worker = None
                        self.worker_key = None
                    elif worker_key != self.worker_key or self.worker is None:
                        self._stop(self.worker); self.worker = None
                        if now >= self.next_worker:
                            self.worker = self._spawn(Path(ready['path']) / 'stella_agent.py', '--file-child',
                                dict(self.spec, **ready, allow_loopback=self.allow_loopback))
                            self.worker_key = worker_key
                            self._notice('managed worker started')
                except Exception:
                    self._notice('configuration/package refused')
                    self._stop(self.worker); self.worker = None
                finally:
                    self._stop(self.preparing); self.preparing = None
                    self.next_prepare = now + self.refresh
        if self.preparing is None and now >= self.next_prepare:
            self.preparing = self._spawn(Path(__file__).absolute(), '--file-prepare',
                dict(self.spec, binding=self.spec.get('binding') or self.bound_identity,
                     allow_loopback=self.allow_loopback), output=True)


def _file_parent_guard(fd, parent):
    """Linux parent-death SIGKILL plus pipe EOF guard closes startup/exec races."""
    import ctypes
    import signal
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('root Linux file subprocess required')
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
        raise ValueError('file parent disappeared')
    def watch():
        try:
            while os.read(fd, 1):
                pass
        finally:
            os._exit(70)
    threading.Thread(target=watch, name='file-parent-guard', daemon=True).start()


class _FileNetworkTimeout(TimeoutError):
    """Only a bootstrap network timeout; never HTTP/TLS/package/load refusal."""


def _file_fetcher(spec):
    from urllib.parse import urlsplit
    from urllib.error import HTTPError, URLError
    import urllib.request
    origin, token = spec['origin'], spec['token']
    p = urlsplit(origin)
    if (p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password
            or p.path not in ('', '/') or p.query or p.fragment
            or (p.scheme != 'https' and not (spec.get('allow_loopback') is True and p.hostname in ('127.0.0.1', '::1')))
            or not isinstance(token, str) or not token or any(c in token for c in '\r\n\x00')):
        raise ValueError('file transport refused')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    def fetch(path, limit):
        request = urllib.request.Request(origin.rstrip('/') + path,
            headers={'Authorization': 'Bearer ' + token, 'Accept-Encoding': 'identity'})
        try:
            with opener.open(request, timeout=3) as response:
                if response.status != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('file HTTP refused')
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError('file HTTP size exceeded')
                return body
        except HTTPError:
            raise  # Includes 401/403, never a temporary authorization failure.
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise _FileNetworkTimeout() from exc
            raise  # In particular certificate validation and DNS/refused errors.
        except TimeoutError as exc:
            raise _FileNetworkTimeout() from exc
    return fetch


def _file_prepare(spec):
    from urllib.error import HTTPError
    from pathlib import Path
    fetch = _file_fetcher(spec)
    identity = json.loads(fetch('/agent/identity', 8192))
    identity = {k: identity[k] for k in ('center_id', 'node_id')}
    if (not isinstance(identity['center_id'], str) or not re.fullmatch('[a-f0-9]{64}', identity['center_id'])
            or type(identity['node_id']) is not int or identity['node_id'] <= 0):
        raise ValueError('invalid file identity')
    binding = spec.get('binding')
    if binding and any(identity[k] != binding[k] for k in identity):
        raise ValueError('file identity changed')
    try:
        config = json.loads(fetch('/agent/files/config', 8192))
    except HTTPError as exc:
        if exc.code != 404:
            raise
        config = None  # Old centers never imply a root grant.
    roots = _file_roots(config, spec.get('legacy'))
    ready = {'identity': identity, 'roots': roots, 'revision': config.get('revision') if isinstance(config, dict) else None, 'path': None}
    if roots:
        manifest = _FilePackage.manifest(json.loads(fetch('/agent/files/release', 8192)))
        if tuple(map(int, manifest['version'].split('.'))) < tuple(map(int, AGENT_VERSION.split('.'))):
            raise ValueError('file package downgrade refused')
        # Same Agent version is immutable; modules have their own explicit version.
        import hashlib
        if manifest['version'] == AGENT_VERSION and manifest['files']['stella_agent.py']['sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError('same version file Agent changed')
        ready['path'] = str(_FilePackage(spec['store']).install(manifest, fetch))
    return ready


class _FileHTTPClient:
    """Small stdlib streaming transport for the existing file protocol only."""
    def __init__(self, spec):
        import urllib.request
        _file_fetcher(spec)  # Same strict origin/token validation as bootstrap.
        self.origin, self.token = spec['origin'].rstrip('/'), spec['token']
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)

    class Response:
        def __init__(self, raw):
            self.raw = raw
        def raise_for_status(self):
            if self.raw.status != 200:
                raise ValueError('file protocol HTTP refused')
        def json(self):
            try:
                body = self.raw.read(2 * 1024 * 1024 + 1)
                if len(body) > 2 * 1024 * 1024:
                    raise ValueError('file protocol response limit')
                return json.loads(body)
            finally:
                self.raw.close()
        def iter_bytes(self, size):
            while True:
                body = self.raw.read(size)
                if not body:
                    break
                yield body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            self.raw.close()

    def stream(self, method, path, *, params=None, json=None, content=None, headers=None):
        from urllib.parse import urlencode
        import urllib.request
        if not path.startswith('/agent/files/') or '?' in path or '#' in path:
            raise ValueError('file protocol path refused')
        url = self.origin + path + ('?' + urlencode(params) if params else '')
        hdr = {'Authorization': 'Bearer ' + self.token, 'Accept-Encoding': 'identity'}
        hdr.update(headers or {})
        if json is not None:
            content = _FilePackage.canonical(json); hdr['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=content, headers=hdr, method=method)
        raw = self.opener.open(request, timeout=10)
        if raw.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raw.close(); raise ValueError('file protocol encoding refused')
        return self.Response(raw)

    def get(self, path, **kwargs):
        return self.stream('GET', path, **kwargs)
    def post(self, path, **kwargs):
        return self.stream('POST', path, **kwargs)
    def put(self, path, **kwargs):
        return self.stream('PUT', path, **kwargs)
    def close(self):
        pass  # urllib responses own and close their connections.


def _file_child(spec):
    import signal
    import types
    from pathlib import Path
    path = Path(__file__).absolute().parent
    if str(path) != spec['path']:
        raise ValueError('file child package mismatch')
    package = _FilePackage(spec['store'])
    manifest = package.manifest(json.loads((path / 'manifest.json').read_bytes()))
    import hashlib
    if path.parent != package.root or path.name != hashlib.sha256(package.canonical(manifest)).hexdigest():
        raise ValueError('file child release mismatch')
    package.verify(path, manifest)
    # Verify identity again immediately before claim, never fallback across nodes.
    identity = json.loads(_file_fetcher(spec)('/agent/identity', 8192))
    if any(identity[k] != spec['identity'][k] for k in ('center_id', 'node_id')):
        raise ValueError('file child identity mismatch')
    module = types.ModuleType('_stella_owned_files')
    module.__file__ = str(path / 'node_files.py')
    exec(compile((path / 'node_files.py').read_bytes(), module.__file__, 'exec'), module.__dict__)
    worker = module.FileWorker(spec['origin'], spec['token'], module.Sandbox(spec['roots']), client=_FileHTTPClient(spec))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        while not stop.is_set():
            try:
                worker.tick()
            except Exception as exc:
                # URLs, lease IDs, roots and tokens are deliberately not logged.
                print('[files] worker error: ' + type(exc).__name__, file=sys.stderr, flush=True)
            stop.wait(.5)
    finally:
        worker.client.close()


def _file_internal_main():
    try:
        _file_parent_guard(int(sys.argv[2]), int(sys.argv[3]))
        body = sys.stdin.buffer.read(32769)
        if len(body) > 32768:
            raise ValueError('file stdin limit')
        spec = json.loads(body)
        if sys.argv[1] == '--file-prepare':
            print(json.dumps(_file_prepare(spec)), flush=True)
        else:
            _file_child(spec)
    except Exception as exc:
        print('[files] child refused: ' + type(exc).__name__, file=sys.stderr, flush=True)
        raise SystemExit(75 if sys.argv[1] == '--file-prepare' and isinstance(exc, _FileNetworkTimeout) else 1)


def _parse_entry_scope(targets, ranges):
    """Parse the entire bounded scope before membership; None means trusted absence."""
    import ipaddress
    if targets is not None and (not isinstance(targets, list) or len(targets) > 64):
        raise ValueError('invalid entry targets')
    if not isinstance(ranges, list) or len(ranges) > 16:
        raise ValueError('invalid entry ranges')
    exact = []
    for value in targets if targets is not None else []:
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or '%' in value:
            raise ValueError('invalid entry target')
        ipaddress.ip_address(value)
        exact.append(value)  # Preserve the existing canonical-string exact match.
    networks = []
    for value in ranges:
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or '%' in value:
            raise ValueError('invalid entry range')
        networks.append(ipaddress.ip_network(value, strict=True))
    return None if targets is None else exact, networks


def _entry_scope(scope):
    """Raw envelopes distinguish absent targets from explicit invalid null."""
    if not isinstance(scope, dict) or ('targets' in scope and scope['targets'] is None):
        raise ValueError('invalid raw entry scope')
    return _parse_entry_scope(scope.get('targets'), scope.get('approved_ranges', []))


def _entry_ip_allowed(value, targets, ranges):
    """Numeric-only pinning. Never permit metadata/special-purpose destinations."""
    import ipaddress
    try:
        exact_targets, networks = _parse_entry_scope(targets, ranges)
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or '%' in value:
            return False
        ip = ipaddress.ip_address(value)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast
                or ip.is_reserved or str(ip) in {'100.100.100.200', '168.63.129.16', 'fd00:ec2::254'}):
            return False
        exact = exact_targets is not None and str(ip) in exact_targets
        approved = any(ip in network for network in networks if network.version == ip.version)
        if exact_targets is not None and not (exact or approved):
            return False
        private = ip in ipaddress.ip_network('10.0.0.0/8') if ip.version == 4 else ip in ipaddress.ip_network('fc00::/7')
        if ip.version == 4:
            private = private or ip in ipaddress.ip_network('172.16.0.0/12') or ip in ipaddress.ip_network('192.168.0.0/16')
        return (ip.is_global or private) and (not private or exact or approved)
    except (ValueError, TypeError):
        return False

STORAGE_INTERVAL = 60
HARDWARE_INTERVAL = 30    # Cached background hardware collection, never heartbeat IO
REPORT_INTERVAL = 5       # 流量上报间隔（秒）
SYS_INTERVAL = 60         # 系统指标上报间隔（秒）
MTR_INTERVAL = 1800       # 监控项定时 MTR 周期（30 分钟）
MTR_FAIL_DEBOUNCE = 600   # 失败触发 MTR 防抖（10 分钟）
POLL_INTERVAL = 1         # 任务轮询间隔（秒）——打流领取要快，1s 让图表几乎秒出
UPDATE_CHECK_INTERVAL = 300  # 版本自更新检查间隔（秒）
QUEUE_MAX = 24 * 3600 // REPORT_INTERVAL  # 队列上限 = 24h 的采样点数


def _agent_urlopen(request, timeout, context=None):
    import urllib.request
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    handlers = [NoRedirect(), urllib.request.ProxyHandler({})]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


class _BackgroundScheduler:
    """Bounded, single-flight lanes with no pending queue.

    Closing stops admission, not running subprocesses. Daemon workers finish their
    existing batch/result reporting; Python cannot safely interrupt these calls.
    """
    def __init__(self, max_workers=2):
        self._limit = max_workers
        self._lock = threading.Lock()
        self._threads = {}
        self._closed = False

    def submit(self, key, operation):
        with self._lock:
            if self._closed or key in self._threads or len(self._threads) >= self._limit:
                return False

            def work():
                try:
                    operation()
                except Exception as exc:
                    print(f"[error] 后台任务 {key}: {exc}", file=sys.stderr)
                finally:
                    with self._lock:
                        self._threads.pop(key, None)

            thread = threading.Thread(target=work, name=f"stella-{key}", daemon=True)
            self._threads[key] = thread
            try:
                thread.start()
            except Exception:
                self._threads.pop(key, None)
                raise
            return True

    def idle(self):
        with self._lock:
            return not self._threads

    def close(self, timeout=1):
        with self._lock:
            self._closed = True
            threads = list(self._threads.values())
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))


_MAP_WG_FIELDS = ('public-key', 'peers', 'endpoints', 'allowed-ips',
                  'latest-handshakes', 'transfer')
_MAP_OUTPUT_LIMIT = 131072


def _map_key_id(key):
    if len(key) != 44 or len(base64.b64decode(key, validate=True)) != 32:
        raise ValueError('invalid public key')
    return hashlib.sha256(key.encode('ascii')).hexdigest()


def _parse_map_wireguard(outputs, addresses):
    """Only public-field stdout is accepted; partial/racy data is not no-peers."""
    interfaces = {}
    seen = set()
    for field in _MAP_WG_FIELDS:
        text = outputs[field]
        if len(text) > _MAP_OUTPUT_LIMIT:
            raise ValueError('oversized output')
        previous_interface = None
        for line in text.splitlines():
            parts = line.split()
            # Older wg-tools prints the interface prefix only on the first
            # endpoint row; accept continuation ONLY within that field/group.
            if field == 'endpoints' and len(parts) == 2:
                if previous_interface is None:
                    raise ValueError('endpoint continuation without interface')
                _map_key_id(parts[0])
                parts.insert(0, previous_interface)
            if field == 'endpoints' and len(parts) == 3:
                previous_interface = parts[0]
            if not parts or len(parts) < 2:
                raise ValueError('invalid row')
            name, key = parts[:2]
            if not re.fullmatch(r'[A-Za-z0-9_.:=+\-]{1,64}', name):
                raise ValueError('invalid interface')
            if field == 'public-key':
                if len(parts) != 2 or name in interfaces:
                    raise ValueError('duplicate interface')
                interfaces[name] = {'name': name, 'public_key_id': _map_key_id(key),
                                    'addresses': addresses.get(name, []), 'peers': {}}
                continue
            if name not in interfaces:
                raise ValueError('interface changed')
            identity = _map_key_id(key)
            marker = (field, name, identity)
            if marker in seen:
                raise ValueError('duplicate peer row')
            seen.add(marker)
            peers = interfaces[name]['peers']
            if field == 'peers':
                if len(parts) != 2:
                    raise ValueError('invalid peer')
                peers[identity] = {'public_key_id': identity}
                continue
            if identity not in peers:
                raise ValueError('peer changed')
            peer = peers[identity]
            value = parts[2:]
            if field == 'endpoints':
                if len(value) != 1:
                    raise ValueError('invalid endpoint')
                endpoint = value[0]
                if endpoint != '(none)':
                    host, port = endpoint.rsplit(':', 1)
                    ipaddress.ip_address(host.strip('[]'))
                    if not 0 < int(port) <= 65535:
                        raise ValueError('invalid port')
                peer['endpoint'] = None if endpoint == '(none)' else endpoint
            elif field == 'allowed-ips':
                peer['allowed_ips'] = [] if value == ['(none)'] else [
                    str(ipaddress.ip_network(v, strict=False)) for v in value]
            else:
                count = 2 if field == 'transfer' else 1
                if len(value) != count or any(not v.isdecimal() or len(v) > 20 for v in value):
                    raise ValueError('invalid counter')
                if field == 'transfer':
                    peer['rx_bytes'], peer['tx_bytes'] = map(int, value)
                else:
                    peer['latest_handshake_at'] = int(value[0])
    for iface in interfaces.values():
        for peer in iface['peers'].values():
            if len(peer) != 6:
                raise ValueError('incomplete peer')
        iface['peers'] = list(iface['peers'].values())
    return {'status': 'ok', 'interfaces': list(interfaces.values())}


def _map_command(args, timeout=3, allowed_returncodes=(0,)):
    """Bound both runtime and output. Never log command output or exceptions."""
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
    env['LC_ALL'] = 'C'
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          env=env) as proc:
        output = bytearray()
        oversized = threading.Event()
        def drain():
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if len(output) + len(chunk) > _MAP_OUTPUT_LIMIT:
                    oversized.set()
                    proc.kill()
                    break
                output.extend(chunk)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            reader.join(1)
            raise ValueError('command timeout') from None
        reader.join(1)
        if oversized.is_set() or reader.is_alive():
            raise ValueError('output limit')
        text = output.decode('utf-8', errors='strict')
        if proc.returncode not in allowed_returncodes:
            if 'permission denied' in text.lower() or 'operation not permitted' in text.lower() or 'access is denied' in text.lower():
                raise PermissionError('read denied')
            raise ValueError('command failed')
        return text


def _map_addresses():
    result = {}
    if psutil:
        for name, entries in psutil.net_if_addrs().items():
            addresses = []
            for entry in entries:
                if entry.family not in (socket.AF_INET, socket.AF_INET6) or not entry.netmask:
                    continue
                address = entry.address.split('%')[0]
                mask = ipaddress.ip_address(entry.netmask.split('%')[0])
                bits = bin(int(mask))[2:].zfill(mask.max_prefixlen)
                if '01' in bits:
                    continue
                addresses.append(str(ipaddress.ip_interface(f'{address}/{bits.count("1")}')))
            result[name] = sorted(set(addresses))
        return result
    ip = shutil.which('ip')
    if ip and platform.system() == 'Linux':
        for row in json.loads(_map_command([ip, '-j', 'address', 'show'])):
            result[row['ifname']] = [str(ipaddress.ip_interface(f'{x["local"]}/{x["prefixlen"]}'))
                                     for x in row.get('addr_info', []) if x.get('family') in ('inet', 'inet6')]
    return result


def _collect_map_wireguard():
    binary = shutil.which('wg') or (shutil.which('wg.exe') if platform.system() == 'Windows' else None)
    if not binary:
        return {'status': 'unavailable', 'interfaces': []}
    try:
        try:
            outputs = {field: _map_command([binary, 'show', 'all', field]) for field in _MAP_WG_FIELDS}
        except PermissionError:
            sudo = shutil.which('sudo') if platform.system() == 'Linux' else None
            if not sudo:
                raise
            outputs = {field: _map_command([sudo, '-n', binary, 'show', 'all', field])
                       for field in _MAP_WG_FIELDS}
        return _parse_map_wireguard(outputs, _map_addresses())
    except PermissionError:
        return {'status': 'permission_denied', 'interfaces': []}
    except Exception:
        return {'status': 'unavailable', 'interfaces': []}


def _map_physical_iface():
    if platform.system() != 'Linux' or not shutil.which('ip'):
        raise ValueError('physical_interface_unverified')
    routes = json.loads(_map_command([shutil.which('ip'), '-j', 'route', 'show', 'default']))
    candidates = []
    for route in routes:
        name = route.get('dev', '')
        if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', name)
                or not os.path.exists(f'/sys/class/net/{name}/device')):
            continue
        if route.get('nexthops') or 'linkdown' in route.get('flags', []):
            raise ValueError('physical_interface_conflict')
        ipaddress.ip_address(route['gateway'])
        candidates.append((int(route.get('metric', 0)), name))
    if not candidates:
        raise ValueError('physical_interface_unverified')
    best = min(x[0] for x in candidates)
    names = {name for metric, name in candidates if metric == best}
    if len(names) != 1:
        raise ValueError('physical_interface_conflict')
    return names.pop()


def _collect_map_location():
    """NAT egress geolocation, never server physical location or WG endpoint lookup."""
    unknown = {'status': 'unknown', 'source': 'unknown', 'public_ip': None,
               'label': None, 'latitude': None, 'longitude': None, 'reason': 'physical_interface_unverified'}
    try:
        iface = _map_physical_iface()
        addresses = _map_addresses().get(iface, [])
        curl = shutil.which('curl')
        if not curl or not addresses:
            unknown['reason'] = 'binding_unavailable'
            return unknown
        unknown['reason'] = 'bound_geo_request_failed'
        # -q FIRST disables curlrc (which could silently enable a proxy).
        # if! forces device binding, not hostname/address interpretation.
        raw = _map_command([curl, '-q', '--silent', '--show-error', '--fail',
                            '--ipv4', '--interface', 'if!' + iface, '--noproxy', '*',
                            '--proxy', '', '--connect-timeout', '2', '--max-time', '4',
                            '--max-filesize', '16384', '--proto', '=https',
                            '--write-out', '\n%{local_ip}', 'https://api.ip2location.io/'], timeout=5)
        body, local_ip = raw.rsplit('\n', 1)
        if ipaddress.ip_address(local_ip) not in {ipaddress.ip_interface(x).ip for x in addresses}:
            unknown['reason'] = 'binding_source_mismatch'
            return unknown
        data = json.loads(body)
        public_ip = ipaddress.ip_address(data['ip'])
        lat, lon = data['latitude'], data['longitude']
        if (data.get('error') or not public_ip.is_global
                or isinstance(lat, bool) or isinstance(lon, bool)
                or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError('invalid geolocation')
        label = ', '.join(dict.fromkeys(x for x in (data.get('city_name'), data.get('region_name'), data.get('country_name')) if isinstance(x, str) and x))[:256]
        return {'status': 'located', 'source': 'nat', 'public_ip': str(public_ip),
                'label': label or None, 'latitude': lat, 'longitude': lon, 'reason': None,
                'provider': 'ip2location'}
    except Exception:
        return unknown


def _valid_manual_map_target(wg, iface, item, address):
    """Configuration can select existing private WG routes, never create them."""
    if (set(item) != {'interface', 'interface_key_id', 'peer_key_id', 'target', 'manual'}
            or item['interface_key_id'] != iface['public_key_id']
            or not re.fullmatch(r'[0-9a-f]{64}', item['peer_key_id'])
            or not any(address in ipaddress.ip_network(p) for p in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))):
        return False
    locals_ = [ipaddress.ip_interface(p) for i in wg['interfaces'] for p in i['addresses']]
    if (any(p.ip == address for p in locals_)
            or not any(ipaddress.ip_interface(p).version == 4 for p in iface['addresses'])):
        return False
    prefixes = [ipaddress.ip_network(p, strict=False) for p in iface['addresses']]
    prefixes += [ipaddress.ip_network(p, strict=False) for peer in iface['peers']
                 if peer['public_key_id'] == item['peer_key_id'] for p in peer['allowed_ips']]
    return not any(p.version == 4 and p.prefixlen < 31 and address in (p.network_address, p.broadcast_address) for p in prefixes)


def _probe_map_targets(wg, targets, deadline=None):
    """Two workers, eight targets, hard admission deadline; no sudo or shell."""
    from concurrent.futures import ThreadPoolExecutor
    deadline = deadline if deadline is not None else time.monotonic() + 14
    if wg.get('status') != 'ok' or not isinstance(targets, list):
        return
    jobs, seen = [], set()
    for item in targets[:8]:
        try:
            name, key = item['interface'], item['peer_key_id']
            address = ipaddress.ip_address(item['target'])
            if (not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', name)
                    or address.version != 4 or address.is_unspecified or address.is_multicast
                    or address.is_loopback or address.is_reserved or int(address) == 0xffffffff):
                continue
            if ('manual' in item and item['manual'] is not True) or ('interface_key_id' in item and 'manual' not in item):
                continue
            manual = item.get('manual') is True
            identity = (name, key, str(address)) if manual else (name, key)
            interfaces = [i for i in wg['interfaces'] if i['name'] == name]
            if len(interfaces) != 1 or identity in seen:
                continue
            if manual and not _valid_manual_map_target(wg, interfaces[0], item, address):
                continue
            candidates = []
            for peer in interfaces[0]['peers']:
                lengths = [net.prefixlen for p in peer['allowed_ips']
                           if (net := ipaddress.ip_network(p, strict=False)).version == 4 and address in net]
                if lengths:
                    candidates.append((max(lengths), peer))
            best = max((n for n, _ in candidates), default=-1)
            owners = [p for n, p in candidates if n == best]
            if len(owners) != 1 or owners[0]['public_key_id'] != key:
                continue
            jobs.append((name, str(address), owners[0], manual, interfaces[0]))
            seen.add(identity)
        except (ValueError, KeyError, TypeError):
            continue
    binary = shutil.which('ping') if platform.system() == 'Linux' else None
    def work(job):
        name, target, peer, manual, iface = job
        result = dict(checked_at=datetime.now(timezone.utc).isoformat(), status='unknown',
                      sent=0, received=0, loss_pct=None, rtt_ms=None, target=target, reason='ping_unavailable')
        try:
            remaining = deadline - time.monotonic()
            if not binary:
                return result
            if remaining < .1:
                result['reason'] = 'probe_budget_exhausted'
                return result
            if manual:
                result['reason'] = 'kernel_route_unverified'
                ip_binary = shutil.which('ip')
                if not ip_binary:
                    return result
                routes = json.loads(_map_command([ip_binary, '-j', '-4', 'route', 'get', target],
                    timeout=min(2, remaining)))
                sources = {str(ipaddress.ip_interface(a).ip) for a in iface['addresses']}
                if (not isinstance(routes, list) or len(routes) != 1
                        or routes[0].get('dev') != name or routes[0].get('type', 'unicast') != 'unicast'
                        or routes[0].get('prefsrc', routes[0].get('src')) not in sources):
                    return result
                remaining = deadline - time.monotonic()
                if remaining < .1:
                    result['reason'] = 'probe_budget_exhausted'
                    return result
            result['reason'] = 'ping_failed_or_unparseable'
            text = _map_command([binary, '-n', '-I', name, '-c', '5', '-i', '0.2', '-W', '1', target],
                                timeout=min(5, remaining), allowed_returncodes=(0, 1))
            match = re.search(r'(\d+) packets transmitted,\s*(\d+) (?:packets )?received', text)
            if not match:
                return result
            sent, received = map(int, match.groups())
            if sent != 5 or not 0 <= received <= sent:
                return result
            rtt = re.search(r'(?:rtt|round-trip) [^=]+ = [\d.]+/([\d.]+)/', text)
            avg = float(rtt[1]) if rtt else None
            if avg is not None and not math.isfinite(avg):
                return result
            result.update(status='ok' if received == 5 else ('degraded' if received else 'failed'),
                          sent=sent, received=received, loss_pct=100.0*(sent-received)/sent,
                          rtt_ms=avg, reason=None if received == 5 else ('icmp_packet_loss' if received else 'icmp_no_response'))
        except Exception:
            pass
        finally:
            result['checked_at'] = datetime.now(timezone.utc).isoformat()
        return result
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='wg-probe') as pool:
        for job, result in zip(jobs, pool.map(work, jobs)):
            if job[3]:
                job[2].setdefault('manual_probes', []).append(result)
            else:
                job[2]['probe'] = result


def _hardware_number(value):
    """Unsupported, boolean, non-finite and sentinel readings become JSON null."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _hardware_read(path, limit=8192):
    """Read fixed local public metadata paths, with a cap and no privilege escalation."""
    try:
        with open(path, 'rb') as stream:
            raw = stream.read(limit + 1)
        return raw.decode('utf-8', errors='replace') if len(raw) <= limit else None
    except (OSError, ValueError):
        return None


def _hardware_positive_int(value):
    number = _hardware_number(value)
    return int(number) if number is not None and number > 0 and number.is_integer() else None


def _memory_devices(text):
    modules = []
    for block in (text or '').split('Memory Device')[1:]:
        fields = dict(re.findall(r'^\s*([^:\n]+):\s*([^\n]*)$', block, re.M))
        size = fields.get('Size', '')
        if 'No Module Installed' in size:
            continue
        match = re.fullmatch(r'(\d+) (kB|KB|MB|GB|TB)', size)
        capacity = int(match[1]) * (1024 ** {'kB': 1, 'KB': 1, 'MB': 2, 'GB': 3, 'TB': 4}[match[2]]) if match else None
        def speed(key):
            match = re.fullmatch(r'(\d+) (?:MT/s|MHz)', fields.get(key, ''))
            return _hardware_positive_int(match[1]) if match else None
        modules.append({'slot': _hardware_text(fields.get('Locator')),
                        'capacity_bytes': capacity, 'speed_mts': speed('Speed'),
                        'configured_speed_mts': speed('Configured Memory Speed') or speed('Configured Clock Speed'),
                        'vendor': _hardware_text(fields.get('Manufacturer')),
                        'part_number': _hardware_text(fields.get('Part Number'))})
    return modules[:256] or None


def _hardware_text(value):
    """Small public product metadata only; never stringify arbitrary CIM objects."""
    if not isinstance(value, str):
        return None
    value = re.sub(r'[\x00-\x1f\x7f]', '', value).strip()[:128]
    if value.lower() in ('', 'none', 'unknown', 'not specified', 'default string',
                         'to be filled by o.e.m.', 'system product name', 'system manufacturer'):
        return None
    return value


def _classify_machine(vendor=None, model=None, container=None, vm=None, virt_none=False,
                      windows=False, hypervisor_present=False):
    """Conservative evidence hierarchy; GPU/sensors never imply bare metal."""
    vendor, model = _hardware_text(vendor), _hardware_text(model)
    kind, virtualization, evidence = 'unknown', None, []
    product = ((vendor or '') + ' ' + (model or '')).lower()
    vm_products = (('vmware', 'vmware'), ('virtualbox', 'oracle'), ('innotek', 'oracle'),
                   ('qemu', 'qemu'), ('kvm', 'kvm'), ('xen', 'xen'), ('hvm domu', 'xen'),
                   ('virtual machine', 'hyperv'), ('parallels', 'parallels'),
                   ('bhyve', 'bhyve'), ('bochs', 'bochs'), ('amazon ec2', 'amazon'),
                   ('google compute engine', 'google'), ('openstack', 'kvm'))
    if container:
        kind, virtualization = 'container', _hardware_text(container)
        evidence = ['container marker:' + (virtualization or 'present')]
    elif vm:
        kind, virtualization = 'virtual', _hardware_text(vm)
        evidence = ['systemd-detect-virt:vm:' + (virtualization or 'present')]
    else:
        for marker, engine in vm_products:
            if marker in product:
                kind, virtualization = 'virtual', engine
                evidence = ['DMI/CIM virtual product:' + marker]
                break
        if kind == 'unknown':
            real_vendors = ('asus', 'asustek', 'lenovo', 'dell', 'hewlett-packard', 'hp',
                            'hpe', 'supermicro', 'gigabyte', 'micro-star', 'msi', 'asrock',
                            'acer', 'apple', 'fujitsu', 'intel', 'samsung', 'huawei',
                            'maxsun', 'biostar', 'framework', 'raspberry pi', 'microsoft')
            real_vendor = vendor and any(re.search(r'\b' + re.escape(v) + r'\b', vendor.lower())
                                         for v in real_vendors)
            if vendor and model and real_vendor and (windows or virt_none):
                kind = 'physical'
                evidence = ['CIM physical product' if windows else 'systemd-detect-virt:none',
                            'recognized hardware vendor/product']
                if windows and hypervisor_present:
                    evidence.append('HypervisorPresent:true (host/VBS is not VM evidence)')
            else:
                evidence = ['insufficient machine evidence']
    return {'kind': kind, 'vendor': vendor, 'model': model, 'virtualization': virtualization,
            'evidence': [e[:128] for e in evidence],
            'detected_at': datetime.now(timezone.utc).isoformat()}


class Agent:
    def _installation_binding(self):
        """Only installer-owned metadata can select lifecycle targets."""
        from pathlib import Path
        iid = os.environ.get('STELLA_INSTANCE_ID')
        raw = os.environ.get('STELLA_INSTANCE_MANIFEST')
        source = Path(os.path.abspath(__file__))
        windows = platform.system() == 'Windows'
        if not iid and not raw:
            if '/stella-agents/' in source.as_posix():
                raise ValueError('instance metadata missing')
            return None  # Legacy collection/update stays compatible, no migration.
        if not iid or not re.fullmatch('[a-f0-9]{24}', iid) or not raw:
            raise ValueError('invalid installation metadata')
        path = Path(raw)
        if windows:
            if path != source.with_name('instance.json'):
                raise ValueError('foreign installation manifest')
        else:
            if path != Path('/etc/stella-agents') / iid / 'instance.json' or source.parent != Path('/opt/stella-agents') / iid:
                raise ValueError('foreign installation paths')
            for part in [*reversed(path.parents), path]:
                st = part.lstat()
                if part.is_symlink() or st.st_uid != 0 or st.st_mode & 0o022:
                    raise ValueError('untrusted installation manifest')
        if path.is_symlink() or source.is_symlink() or len(path.read_bytes()) > 4096:
            raise ValueError('untrusted installation files')
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or set(value) != {'format','center_id','node_id','instance_id','service','slot'}:
            raise ValueError('invalid installation manifest')
        slot = value['slot']
        if (value['format'] != 1 or not isinstance(slot, str) or (slot and not re.fullmatch('[a-z0-9][a-z0-9-]{0,31}', slot))
                or not re.fullmatch('[a-f0-9]{64}', str(value['center_id'])) or type(value['node_id']) is not int or value['node_id'] <= 0):
            raise ValueError('invalid installation binding')
        derived = hashlib.sha256(('stella-instance-v1:' + value['center_id'] + (':slot:' + slot if slot else '')).encode()).hexdigest()[:24]
        service = ('StellaAgent-' if windows else 'stella-agent-') + iid
        if derived != iid or value['instance_id'] != iid or value['service'] != service:
            raise ValueError('installation binding mismatch')
        return value

    def _assert_instance_identity(self):
        binding = getattr(self, '_installation', None)
        if binding is None:
            return
        identity = self._get('/agent/identity', token=self.token)
        if identity.get('center_id') != binding['center_id'] or identity.get('node_id') != binding['node_id']:
            raise ValueError('center/node does not own this installed instance')

    def _instance_uninstall_argv(self):
        from pathlib import Path
        binding = self._installation_binding()
        if binding is None:
            # Unknown/manual source copies must never remove the production unit.
            if platform.system() == 'Linux' and Path(os.path.abspath(__file__)) == Path('/opt/stella-agent/stella_agent.py'):
                return None  # Exact legacy lifecycle retained below, never adopted.
            raise ValueError('unscoped uninstall refused')
        if platform.system() == 'Windows':
            powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            return [powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(Path(__file__).with_name('uninstall-instance.ps1'))]
        return ['sudo', '-n', str(Path('/usr/local/libexec') / binding['service']), '--schedule']

    def __init__(self, url: str, token: str):
        if "://" not in url:
            url = "https://" + url
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or any(c in url for c in '\r\n')):
            raise ValueError('center URL must be http(s), without credentials/query/fragment')
        if not token or any(c in token for c in '\r\n'):
            raise ValueError('invalid agent token')
        self.url = url.rstrip("/")
        self.token = token
        self._installation = self._installation_binding()
        # Preserve 0.6.14's verified CA store reuse, not connections/cookies.
        self._ssl_context = httpx.create_ssl_context() if httpx else None
        if self._ssl_context is None:
            import ssl
            self._ssl_context = ssl.create_default_context()
        self._channel_init()
        self.queue = deque(maxlen=QUEUE_MAX)  # 内存队列：补传用
        self.last_net = None  # 上次网卡累计字节 {iface: (rx, tx)}
        self.monitored_ifaces = None  # 兼容中心显示偏好，不过滤流量采集
        self.monitors_version = 0  # 监控项配置版本号（心跳 diff 用）
        self.monitors = {}  # monitor_id -> {type, target, interval, timeout, next_run}
        self._hardware_scheduler = _BackgroundScheduler(max_workers=1)
        self._hardware_cache = None
        self._hardware_cached_at = 0
        self._hardware_next_sample = 0
        self._storage_scheduler = _BackgroundScheduler(max_workers=1)
        self._storage_cache = None
        self._storage_next_sample = 0
        self._storage_status = {'state': 'collecting', 'sampled_at': None, 'attempted_at': None}
        self._check_deps()

    def collect_map_snapshot(self):
        now = time.monotonic()
        cached = getattr(self, '_map_location_cache', None)
        if cached is None or now >= cached[0]:
            try:
                location = _collect_map_location()
            except Exception:
                location = {'status': 'unknown', 'source': 'unknown', 'reason': 'location_collection_failed'}
            self._map_location_cache = (now + (900 if location['status'] == 'located' else 60), location)
        wireguard = _collect_map_wireguard()
        if wireguard.get('status') == 'ok':
            wireguard['manual_probe_version'] = 1
        return {'observed_at': datetime.now(timezone.utc).isoformat(),
                'location': dict(self._map_location_cache[1]),
                'wireguard': wireguard}

    def _get_map_targets(self):
        # A separate bounded read, not the generic unbounded JSON helper.
        import urllib.request
        import urllib.parse
        url = self.url + '/agent/map-targets'
        headers = {**self._auth_headers({}), 'Accept-Encoding': 'identity'}
        if httpx:
            with httpx.stream('GET', url, timeout=2, follow_redirects=False,
                              headers=headers, verify=self._ssl_context, trust_env=False) as response:
                response.raise_for_status()
                raw = bytearray()
                deadline = time.monotonic() + 3
                for chunk in response.iter_raw():
                    raw.extend(chunk)
                    if len(raw) > 16384 or time.monotonic() > deadline:
                        raise ValueError('target response limit')
        else:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    raise ValueError('target redirect refused')
            opener = urllib.request.build_opener(NoRedirect())
            request = urllib.request.Request(url, headers=headers)
            with opener.open(request, timeout=2) as response:
                raw = bytearray()
                deadline = time.monotonic() + 3
                while True:
                    chunk = response.read1(4096)
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > 16384 or time.monotonic() > deadline:
                        raise ValueError('target response limit')
        return json.loads(raw)['targets']

    def _report_map_snapshot(self):
        # Independent latest-state report: never overwrite OS metadata defaults.
        # Fixed error handling keeps tokens/keys out of scheduler exception logs.
        try:
            snapshot = self.collect_map_snapshot()
            if snapshot['wireguard']['status'] == 'ok' and snapshot['wireguard']['interfaces']:
                try:
                    deadline = time.monotonic() + 14
                    _probe_map_targets(snapshot['wireguard'], self._get_map_targets(), deadline=deadline)
                except Exception:
                    pass  # Probe/config failure must not discard the WG inventory.
            self._post('/agent/report', json_body={'metrics': [],
                       'map_snapshot': snapshot}, token=self.token)
        except Exception:
            pass  # Next scheduled collection retries; no unbounded history queue.

    def _check_deps(self):
        """依赖检查：httpx / psutil 缺失只降级，不 crash。"""
        if httpx is None:
            print("[warn] httpx 未安装，用 urllib 兜底", file=sys.stderr)
        if psutil is None:
            print("[warn] psutil 未安装，系统指标/网卡清单降级", file=sys.stderr)

    def _agent_bin(self) -> str:
        """agent 目录下的 bin/（install.sh 已 chown 给 stella，可写，放代装的单文件组件）。"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")

    def _check_components(self) -> dict:
        """检测打流相关组件 + 防火墙是否安装（前端显示绿/红，未装可代装）。
        0.6.2 起简单布尔升级为 {installed, version}（前端显示版本号），防火墙/ docker 维持旧结构。"""
        iperf3_bin = shutil.which("iperf3")
        st_bin = self._throughput_speedtest_exe()
        mtr_bin = shutil.which("mtr")
        return {"iperf3": {"installed": bool(iperf3_bin), "version": self._comp_version(iperf3_bin, ["--version"])},
                "speedtest": {"installed": bool(st_bin), "version": self._comp_version(st_bin, ["--version"])},
                "monitoring": self._monitoring_capability(),
                "firewall": self._check_firewall(),
                "docker": self._check_docker(),
                "mtr": {"installed": bool(mtr_bin), "version": self._comp_version(mtr_bin, ["--version"])}}

    def _monitoring_capability(self) -> dict:
        """Only advertise ICMP after a real local check; no remote discovery."""
        types = ['tcp']
        ping = shutil.which('ping')
        if ping:
            try:
                flags = ['-n','1','-w','1000'] if platform.system() == 'Windows' else ['-c','1','-W','1']
                result = subprocess.run([ping, *flags, '127.0.0.1'],
                                        capture_output=True, timeout=2)
                if result.returncode == 0:
                    types.append('ping')
            except (OSError, subprocess.SubprocessError):
                pass
        return {'ready': True, 'types': types}

    @staticmethod
    def _comp_version(binary: str | None, args: list) -> str:
        """取组件版本号（首行前 40 字符，提取 x.y.z 样式的版本串），失败返回空串。"""
        if not binary:
            return ""
        try:
            r = subprocess.run([binary] + args, capture_output=True, text=True, timeout=5)
            line = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
            if not line:
                return ""
            m = re.search(r"\d+(\.\d+)+", line[0])
            return m.group(0) if m else ""
        except Exception:
            return ""

    def _check_docker(self) -> dict:
        """检测 Docker：是否安装 + 版本 + 守护进程是否运行（--version/is-active 查询不需要 root）。"""
        # Linux Docker path is pinned, including this non-privileged version read.
        docker_bin = '/usr/bin/docker' if os.path.isfile('/usr/bin/docker') else None
        installed = docker_bin is not None
        running = False
        if installed:
            try:
                r = subprocess.run(["/usr/bin/systemctl", "is-active", "docker"], capture_output=True, text=True, timeout=5)
                running = (r.stdout or "").strip() == "active"
            except Exception:
                pass
        return {"installed": installed, "running": running,
                "version": self._comp_version(docker_bin, ["--version"])}

    _FW_CACHE_TTL = 300  # ufw status 要 sudo，5s 心跳每次调会把 auth 日志刷爆（8.20 HK 实锤）→ 5min 缓存

    def _check_firewall(self) -> dict:
        """检测防火墙：ufw / iptables 是否安装 + ufw 是否启用 + ufw 版本。
        ufw status 要 root（sudo -n，install.sh 白名单已放），不带 sudo 会误报未启用。"""
        now = time.time()
        cached = getattr(self, "_fw_cache", None)
        if cached and now - cached[0] < self._FW_CACHE_TTL:
            return cached[1]
        ufw_bin = shutil.which("ufw")
        ufw_installed = ufw_bin is not None
        ufw_active = False
        ufw_version = ""
        if ufw_installed:
            try:
                r = subprocess.run(["sudo", "-n", "ufw", "status"], capture_output=True, text=True, timeout=5)
                ufw_active = "Status: active" in (r.stdout or "")
            except Exception:
                pass
            ufw_version = self._comp_version(ufw_bin, ["version"])
        iptables_installed = shutil.which("iptables") is not None
        result = {"ufw": {"installed": ufw_installed, "active": ufw_active, "version": ufw_version},
                  "iptables": {"installed": iptables_installed}}
        self._fw_cache = (now, result)
        return result

    def _probe_public_ip(self) -> dict | None:
        """探测本机出口公网 IP + 地区（中文）。双服务 fallback：ip-api.com → ipinfo.io。"""
        UA = {"User-Agent": "Mozilla/5.0 (Stella)"}  # ip-api 对默认 python UA 反爬
        # 主：ip-api.com（lang=zh-CN 直接返回中文）
        try:
            if httpx:
                d = httpx.get("http://ip-api.com/json/?lang=zh-CN&fields=status,country,regionName,city,query", timeout=5, headers=UA, verify=self._ssl_context).json()
            else:
                import urllib.request
                req = urllib.request.Request("http://ip-api.com/json/?lang=zh-CN&fields=status,country,regionName,city,query", headers=UA)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    d = json.loads(resp.read())
            if d.get("status") == "success" and d.get("query"):
                return {"public_ip": d["query"], "ip_version": "IPv4",
                        "region": d.get("city") or d.get("country") or ""}
        except Exception:
            pass
        # 备：ipinfo.io（英文 region/country）
        try:
            if httpx:
                d = httpx.get("https://ipinfo.io/json", timeout=5, headers=UA, verify=self._ssl_context).json()
            else:
                import urllib.request
                req = urllib.request.Request("https://ipinfo.io/json", headers=UA)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    d = json.loads(resp.read())
            if d.get("ip"):
                return {"public_ip": d["ip"], "ip_version": "IPv4",
                        "region": d.get("city") or d.get("country") or ""}
        except Exception:
            pass
        return None

    # ── Report channels: installed origin remains authoritative at bootstrap ──
    def _channel_init(self, load_cache=True):
        self._channel_lock = threading.RLock()
        self._channel_probe_lock = threading.Lock()
        self._installed_url = self.url
        self._channel_policy = None
        self._channel_sequence = 0
        self._channel_state = 'pending'
        self._channel_error = None
        self._channel_next_probe = 0
        self._channel_switched_at = time.monotonic()
        self._channel_samples = {}
        self._channel_streaks = {}
        self._channel_failures = 0
        self._report_not_before = 0
        self._channel_report_failures = 0
        if load_cache:
            self._channel_load()

    @staticmethod
    def _channel_origin(value):
        from urllib.parse import urlsplit
        if not isinstance(value, str) or len(value) > 256:
            raise ValueError('invalid channel origin')
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None
                or p.path or p.query or p.fragment or value != 'https://' + p.netloc
                or any(c.isspace() for c in value) or p.port == 443):
            raise ValueError('exact HTTPS channel origin required')
        return value

    def _channel_validate(self, cfg):
        if not isinstance(cfg, dict) or set(cfg) != {'revision','epoch','nonce','center_id','token_binding','node_id','mode','selected_entry_id','entries'}:
            raise ValueError('invalid channel configuration')
        if (type(cfg['revision']) is not int or cfg['revision'] < 0 or
                type(cfg['node_id']) is not int or cfg['node_id'] < 1 or
                not isinstance(cfg['epoch'], str) or not 1 <= len(cfg['epoch']) <= 64 or
                cfg['mode'] not in ('default','fixed','auto') or cfg['selected_entry_id'] not in ('public','private')):
            raise ValueError('invalid channel selection')
        for key in ('center_id','token_binding','nonce'):
            if not isinstance(cfg[key], str) or not re.fullmatch('[a-f0-9]{64}', cfg[key]):
                raise ValueError('invalid channel binding')
        if not isinstance(cfg['entries'],list) or not 1 <= len(cfg['entries']) <= 2:
            raise ValueError('channel entry budget')
        ids, origins = set(), set()
        for entry in cfg['entries']:
            if not isinstance(entry, dict) or set(entry) != {'entry_id','origin'} or entry['entry_id'] not in ('public','private'):
                raise ValueError('invalid channel entry')
            origin = self._channel_origin(entry['origin'])
            if origin in origins or entry['entry_id'] in ids:
                raise ValueError('duplicate channel entry')
            ids.add(entry['entry_id']); origins.add(origin)
        if 'public' not in ids or cfg['selected_entry_id'] not in ids or (cfg['mode']=='auto' and len(ids)<2):
            raise ValueError('missing channel entry')
        binding = getattr(self, '_installation', None)
        if binding and (cfg['center_id'] != binding['center_id'] or cfg['node_id'] != binding['node_id']):
            raise ValueError('channel differs from installation binding')
        old = self._channel_policy
        if old and (cfg['center_id']!=old['center_id'] or cfg['token_binding']!=old['token_binding'] or cfg['node_id']!=old['node_id'] or cfg['revision']<old['revision']):
            raise ValueError('channel identity changed')
        return json.loads(json.dumps(cfg))

    def _channel_probe(self, origin, cfg):
        # OS getaddrinfo is not guaranteed to obey socket timeouts. Bound caller
        # admission and allow only one outstanding resolver/HTTP worker. A late
        # result cannot switch anything; it only fills its abandoned local queue.
        import queue
        self._channel_origin(origin)
        started = time.monotonic()
        def failed():
            return dict(ok=False,duration_ms=(time.monotonic()-started)*1000,
                        sampled_at=datetime.now(timezone.utc).isoformat())
        if not self._channel_probe_lock.acquire(blocking=False):
            return failed()
        result = queue.Queue(maxsize=1)
        def work():
            try:
                sample = self._channel_probe_transaction(origin,cfg)
            except Exception:
                sample = failed()
            finally:
                self._channel_probe_lock.release()
            result.put(sample)
        try:
            threading.Thread(target=work,daemon=True).start()
        except RuntimeError:
            self._channel_probe_lock.release()
            return failed()
        try:
            return result.get(timeout=4)
        except queue.Empty:
            return failed()

    def _channel_probe_transaction(self, origin, cfg):
        # Full new DNS/TCP/TLS/HTTP transaction, NOT ping, connection pooling or
        # a second metric report. No redirects, proxy env, cookies or CA bypass.
        import urllib.request
        from datetime import datetime, timezone
        self._channel_origin(origin)
        started = time.monotonic()
        try:
            if httpx:
                with httpx.Client(verify=self._ssl_context, timeout=2, follow_redirects=False, trust_env=False) as client:
                    with client.stream('GET', origin + '/agent/entry-probe', headers=self._auth_headers({})) as r:
                        r.raise_for_status()
                        raw = bytearray()
                        for chunk in r.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>4096 or time.monotonic()-started>3:
                                raise ValueError('probe response budget')
            else:
                request = urllib.request.Request(origin+'/agent/entry-probe',headers=self._auth_headers({}))
                with _agent_urlopen(request, timeout=2, context=self._ssl_context) as r:
                    raw = bytearray()
                    while True:
                        chunk = r.read1(4097 - len(raw))
                        raw.extend(chunk)
                        if len(raw)>4096 or time.monotonic()-started>3:
                            raise ValueError('probe response budget')
                        if not chunk:
                            break
            value = json.loads(raw)
            if value != dict(center_id=cfg['center_id'],node_id=cfg['node_id'],token_binding=cfg['token_binding'],origin=origin):
                raise ValueError('probe identity mismatch')
            ok = True
        except Exception:
            ok = False
        return dict(ok=ok,duration_ms=(time.monotonic()-started)*1000,
                    sampled_at=datetime.now(timezone.utc).isoformat())

    def _channel_apply(self, cfg):
        if cfg is None:
            return  # old centers must not reset the installed URL or cached policy
        with self._channel_lock:
            cfg = self._channel_validate(cfg)
            if self._channel_policy == cfg:
                return
            # Only a TLS-authenticated installed/already-approved origin may
            # delegate token trust. An old HTTP install stays pinned, not upgraded.
            self._channel_origin(self.url)
            if self._channel_policy and self.url not in ({e['origin'] for e in self._channel_policy['entries']} | {self._installed_url}):
                raise ValueError('unapproved configuration source')
            if self._channel_policy is None and self.url != self._installed_url:
                raise ValueError('unapproved bootstrap source')
            selected = next(e['origin'] for e in cfg['entries'] if e['entry_id']==cfg['selected_entry_id'])
            target = self.url if cfg['mode']=='auto' and self.url in {e['origin'] for e in cfg['entries']} else selected
            sample = self._channel_probe(target,cfg)
            self._channel_policy = cfg
            self._channel_streaks = {}
            self._channel_failures = 0
            self._channel_state = 'applied' if sample['ok'] else 'failed'
            self._channel_error = None if sample['ok'] else 'probe_failed'
            if sample['ok']:
                self.url = target
                self._channel_switched_at = time.monotonic()
            # Failed default/fixed remains at its old endpoint only to fetch
            # config/report failure; never silently calls this the selected entry.
            self._channel_save()

    def _channel_tick(self, now=None):
        if not hasattr(self, '_channel_lock'):
            return
        now = time.monotonic() if now is None else now
        with self._channel_lock:
            cfg = self._channel_policy
            if cfg is None or now < self._channel_next_probe:
                return
            self._channel_next_probe = now + 30  # initial conservative defaults
            observed_origin = self.url
            retry = self._channel_state == 'failed'
        # Readiness must not hold the heartbeat/task origin lock while DNS/TLS
        # stalls. Admit the result only if this exact policy + origin still own it.
        if cfg['mode'] != 'auto':
            if retry:
                self._channel_apply_retry(cfg)
            return
        samples = {e['origin']:self._channel_probe(e['origin'],cfg) for e in cfg['entries']}
        with self._channel_lock:
            if self._channel_policy != cfg or self.url != observed_origin:
                return
            self._channel_samples = samples  # readiness timing, not report latency
            current = samples.get(self.url, {'ok':False})
            if current['ok'] and (self._channel_state != 'applied' or self._channel_error is not None):
                # Confirmation can recover at the same origin; dwell only gates
                # switching. The full policy/origin fence above owns this result.
                self._channel_state,self._channel_error = 'applied',None
                self._channel_save()
            self._channel_failures = 0 if current['ok'] else self._channel_failures + 1
            for origin,sample in samples.items():
                faster = (sample['ok'] and origin!=self.url and current['ok'] and
                          current['duration_ms']-sample['duration_ms']>=20 and
                          sample['duration_ms']<=current['duration_ms']*.8)
                self._channel_streaks[origin] = self._channel_streaks.get(origin,0)+1 if faster else 0
            if now-self._channel_switched_at < 60:
                return
            alternatives = [(s['duration_ms'],o) for o,s in samples.items() if o!=self.url and s['ok'] and
                            (self._channel_failures>=3 or self._channel_report_failures>=3 or self._channel_streaks[o]>=3)]
            if alternatives:
                self.url = min(alternatives)[1]
                self._channel_state,self._channel_error = 'applied',None
                self._channel_switched_at = now
                self._channel_streaks = {}; self._channel_failures=0
                self._channel_report_failures = 0
                self._channel_save()
            elif not any(s['ok'] for s in samples.values()):
                # Retain the current entry and queue, with bounded probe backoff.
                self._channel_next_probe = now + min(300,30*2**min(self._channel_failures,3))

    def _channel_apply_retry(self, cfg):
        target = next(e['origin'] for e in cfg['entries'] if e['entry_id']==cfg['selected_entry_id'])
        sample = self._channel_probe(target,cfg)
        with self._channel_lock:
            if self._channel_policy != cfg or not sample['ok']:
                return
            self.url = target
            self._channel_state,self._channel_error = 'applied',None
            self._channel_switched_at = time.monotonic()
            self._channel_save()

    def _channel_receipt(self):
        cfg = self._channel_policy
        if cfg is None or self.url not in {e['origin'] for e in cfg['entries']}:
            return None
        self._channel_sequence += 1
        self._channel_save()
        return dict(revision=cfg['revision'],epoch=cfg['epoch'],nonce=cfg['nonce'],center_id=cfg['center_id'],
                    sequence=self._channel_sequence,origin=self.url,state=self._channel_state,error=self._channel_error)

    def _channel_cache_path(self):
        from pathlib import Path
        # Fixed install-owned location, never a server/config-supplied path.
        return Path(__file__).resolve().with_name('report-channel-cache.json')

    def _channel_save(self):
        import hashlib, hmac
        try:
            body=json.dumps(dict(installed=self._installed_url,policy=self._channel_policy,current=self.url,
                sequence=self._channel_sequence,state=self._channel_state,error=self._channel_error),sort_keys=True,separators=(',',':'))
            value=json.dumps(dict(body=body,mac=hmac.new(self.token.encode(),body.encode(),hashlib.sha256).hexdigest()))
            path=self._channel_cache_path()
            # Exclusive no-follow temporary write; atomic rename, no secret CA/key export.
            temp=path.with_name(path.name+'.'+str(os.getpid())+'.new')
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                with os.fdopen(fd,'w') as f:
                    f.write(value);f.flush();os.fsync(f.fileno())
                os.replace(temp,path)
            finally:
                if temp.exists():temp.unlink()
        except OSError:
            pass  # in-memory approved cache still permits outage switching

    def _channel_load(self):
        import hashlib, hmac, stat
        try:
            path=self._channel_cache_path()
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd) as f:
                info=os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size>16384 or (os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077)):
                    return
                value=json.loads(f.read(16385))
            body=value['body']
            if not hmac.compare_digest(value['mac'],hmac.new(self.token.encode(),body.encode(),hashlib.sha256).hexdigest()):
                return
            cached=json.loads(body)
            cfg=self._channel_validate(cached['policy'])
            if cached['installed']!=self._installed_url or cached['current'] not in ({e['origin'] for e in cfg['entries']} | {self._installed_url}):
                return
            if cached['state'] not in ('applied','failed') or cached['error'] not in (None,'probe_failed','invalid_config'):
                return
            target = next(e['origin'] for e in cfg['entries'] if e['entry_id']==cfg['selected_entry_id'])
            if cached['state']=='applied' and cfg['mode']!='auto' and cached['current']!=target:
                return
            self._channel_policy=cfg
            self.url=cached['current']
            self._channel_sequence=int(cached['sequence'])
            self._channel_state=cached['state']
            self._channel_error=cached['error']
        except (OSError,ValueError,TypeError,KeyError):
            return

    # ── HTTP 基础 ──
    def _auth_headers(self, params):
        # Keep existing call sites compatible, but never serialize token in URLs.
        params.pop('token', None)
        return {'Authorization': 'Bearer ' + self.token}

    def _get(self, path: str, **params):
        from contextlib import nullcontext
        with getattr(self, '_channel_lock', nullcontext()):
            return self._get_current(path, **params)

    def _get_current(self, path: str, **params):
        headers = self._auth_headers(params)
        if httpx:
            r = httpx.get(self.url + path, params=params, headers=headers, timeout=10, verify=self._ssl_context, follow_redirects=False, trust_env=False)
            r.raise_for_status()
            return r.json()
        import urllib.request
        import urllib.parse
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(self.url + path + ("?" + q if q else ""), headers=headers)
        with _agent_urlopen(req, timeout=10, context=self._ssl_context) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, json_body=None, **params):
        from contextlib import nullcontext
        with getattr(self, '_channel_lock', nullcontext()):
            return self._post_current(path, json_body=json_body, **params)

    def _post_current(self, path: str, json_body=None, **params):
        if path == '/agent/report':
            return self._post_report_transaction(json_body)
        headers = self._auth_headers(params)
        if httpx:
            r = httpx.post(self.url + path, json=json_body, params=params, headers=headers, timeout=10, verify=self._ssl_context, follow_redirects=False, trust_env=False)
            r.raise_for_status()
            return r.json()
        import urllib.request
        import urllib.parse
        q = urllib.parse.urlencode(params)
        data = json.dumps(json_body).encode() if json_body is not None else b""
        req = urllib.request.Request(
            self.url + path + ("?" + q if q else ""),
            data=data,
            headers={**headers, "Content-Type": "application/json"},
        )
        with _agent_urlopen(req, timeout=10, context=self._ssl_context) as resp:
            return json.loads(resp.read())

    def _post_report_transaction(self, body):
        from contextlib import nullcontext
        with getattr(self, '_channel_lock', nullcontext()):
            return self._post_report_current(body)

    def _post_report_current(self, body):
        """Exactly one normal report, timed after preparation through JSON parse."""
        import urllib.request
        import urllib.error
        from urllib.parse import urlsplit
        url = self.url + '/agent/report'
        p = urlsplit(self.url)
        origin = p.scheme + '://' + p.netloc
        if getattr(self, '_channel_policy', None):
            body = {**body, 'channel_receipt': self._channel_receipt()}
        measurement_entries = getattr(self, '_channel_policy', None) or getattr(self, '_entry_manifest', {})
        entry = next((e['entry_id'] for e in measurement_entries.get('entries', [])
                      if e['origin'] == origin), None)
        headers = self._auth_headers({})
        status, error, client = None, None, None
        if httpx:
            client = httpx.Client(verify=self._ssl_context, timeout=10, follow_redirects=False, trust_env=False)
            request = client.build_request('POST', url, json=body, headers=headers)
        else:
            request = urllib.request.Request(url, data=json.dumps(body).encode(),
                headers={**headers, 'Content-Type':'application/json'})
        started = time.monotonic()
        try:
            if client:
                response = client.send(request)
                status = response.status_code
                response.raise_for_status()
                result = response.json()
            else:
                with _agent_urlopen(request, timeout=10, context=self._ssl_context) as response:
                    status = response.status
                    result = json.loads(response.read())
            if not isinstance(result, dict) or result.get('ok') is not True:
                error = 'invalid_response'
                raise ValueError('invalid report acknowledgement')
            self._channel_report_failures = 0
            return result
        except Exception as exc:
            self._channel_report_failures = getattr(self, '_channel_report_failures', 0) + 1
            status = status or getattr(exc, 'code', None)
            if error is None:
                error = ('invalid_response' if isinstance(exc, ValueError) else
                         'http' if status is not None and not 200 <= status < 300 else
                         'timeout' if isinstance(exc, TimeoutError) or (httpx and isinstance(exc, httpx.TimeoutException))
                         else 'transport')
            raise
        finally:
            self._last_report_transaction = dict(entry_id=entry, origin=origin,
                duration_ms=(time.monotonic()-started)*1000, status='error' if error else 'ok',
                http_status=status, error=error, sampled_at=datetime.now(timezone.utc).isoformat())
            if client:
                client.close()

    # ── 采集 ──
    def detect_default_iface(self) -> str | None:
        """默认出口网卡 = 默认路由指向的网卡。Linux 读 /proc/net/route。"""
        if platform.system() == "Linux":
            try:
                with open("/proc/net/route") as f:
                    best = None
                    for line in f.read().splitlines()[1:]:
                        parts = line.split()
                        if len(parts) < 11:
                            continue
                        iface, dest, _, flags, _, _, _, metric = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6], parts[7]
                        if dest == "00000000" and flags == "0003":  # 默认路由 + up
                            m = int(metric)
                            if best is None or m < best[1]:
                                best = (iface, m)
                    return best[0] if best else None
            except OSError:
                return None
        return None

    def _is_physical_iface(self, name: str) -> bool:
        """物理网卡 = /sys/class/net/{name}/device 存在（有 PCI 设备）。虚拟口（veth/br/docker/tun 等）无 device。"""
        try:
            return os.path.isdir(f"/sys/class/net/{name}/device")
        except OSError:
            return False

    def _is_docker_iface(self, name: str) -> bool:
        """docker/容器虚拟网卡：docker0、veth*、br-*（docker bridge）、cni*。默认前端隐藏。"""
        if name == "docker0":
            return True
        return name.startswith(("veth", "br-", "cni", "docker", "virbr"))

    def _iface_ip(self, name: str) -> str | None:
        """网卡的 IPv4 地址（有则返回，无则 None）。"""
        try:
            if psutil:
                for addr in psutil.net_if_addrs().get(name, []):
                    if addr.family == socket.AF_INET:
                        return addr.address
        except Exception:
            pass
        return None

    def list_interfaces(self) -> dict:
        """枚举所有网卡 + 默认出口标记 + 物理/虚拟 + IP。虚拟口也报（中心决定是否监控）。"""
        default = self.detect_default_iface()
        ifaces = {}
        if psutil:
            for name, stats in psutil.net_if_stats().items():
                ifaces[name] = {
                    "is_default": name == default,
                    "up": bool(stats.isup),
                    "is_physical": self._is_physical_iface(name),
                    "docker": self._is_docker_iface(name),
                    "ip": self._iface_ip(name),
                }
        else:
            # 无 psutil：Linux 读 /proc/net/dev 兜底
            try:
                with open("/proc/net/dev") as f:
                    for line in f.read().splitlines()[2:]:
                        name = line.split(":")[0].strip()
                        ifaces[name] = {
                            "is_default": name == default,
                            "up": True,
                            "is_physical": self._is_physical_iface(name),
                            "docker": self._is_docker_iface(name),
                            "ip": self._iface_ip(name),
                        }
            except OSError:
                pass
        return ifaces

    def read_net_bytes(self) -> dict:
        """读各网卡累计字节 {iface: (rx, tx)}。"""
        result = {}
        if psutil:
            for name, io in psutil.net_io_counters(pernic=True).items():
                result[name] = (io.bytes_recv, io.bytes_sent)
        else:
            try:
                with open("/proc/net/dev") as f:
                    for line in f.read().splitlines()[2:]:
                        name, rest = line.split(":")
                        cols = rest.split()
                        result[name.strip()] = (int(cols[0]), int(cols[8]))
            except OSError:
                pass
        return result

    def collect_metrics(self) -> list:
        """上报所有网卡的流量增量；monitored_ifaces 仅为中心图表显示偏好。"""
        now_net = self.read_net_bytes()
        now = datetime.now(timezone.utc)
        tick = time.monotonic()
        previous_wall = getattr(self, "last_net_wall", None)
        previous_tick = getattr(self, "last_net_tick", None)
        self.last_net_wall, self.last_net_tick = now, tick
        elapsed = tick - previous_tick if previous_tick is not None else None
        points = []
        if self.last_net is None:
            self.last_net = now_net
            return []
        for iface, (rx, tx) in now_net.items():
            prev = self.last_net.get(iface)
            if prev is None:
                continue
            rx_delta = rx - prev[0]
            tx_delta = tx - prev[1]
            if rx_delta < 0 or tx_delta < 0:
                continue  # 计数器重置（网卡重启），跳过
            points.append({
                "iface": iface,
                "ts": now.isoformat(),
                "rx_delta": rx_delta,
                "tx_delta": tx_delta,
                "interval_start": previous_wall.isoformat() if previous_wall else None,
                "elapsed_seconds": elapsed,
                "quality": "valid" if previous_wall and elapsed and 0 < elapsed <= 300
                    and abs((now - previous_wall).total_seconds() - elapsed) <= max(0.1, elapsed * 0.02)
                    else "clock_skew",
            })
        self.last_net = now_net
        return points

    def collect_sys(self) -> dict:
        """系统指标。"""
        now = datetime.now(timezone.utc).isoformat()
        cpu = mem = disk = None
        if psutil:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
        return {"ts": now, "cpu_pct": cpu, "mem_pct": mem, "disk_pct": disk}

    # os_info 缓存：os_name/kernel/cpu_model/cpu_cores 基本不变，只读一次；负载/开机时间每次现算
    _os_static_cache: dict | None = None

    def _os_info(self) -> dict:
        """采集 OS 信息：发行版名/内核/CPU 型号/核数/负载/开机时间（前端基本信息面板用）。"""
        if self._os_static_cache is None:
            static: dict = {}
            if platform.system() == "Linux":
                # PRETTY_NAME：/etc/os-release 里的发行版友好名（如 "Arch Linux" / "Ubuntu 22.04 LTS"）
                try:
                    with open("/etc/os-release", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("PRETTY_NAME="):
                                static["os_name"] = line.split("=", 1)[1].strip().strip('"')
                                break
                except OSError:
                    pass
                # CPU 型号：/proc/cpuinfo 第一颗的 model name
                try:
                    with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.lower().startswith("model name"):
                                static["cpu_model"] = line.split(":", 1)[1].strip()
                                break
                except OSError:
                    pass
            else:
                # Windows：platform.platform() 给 "Windows-11-10.0.22631-SP0" 这类串
                static["os_name"] = platform.platform()
                static["cpu_model"] = platform.processor() or None
            static.setdefault("os_name", None)
            static.setdefault("cpu_model", None)
            static["kernel"] = platform.release() or None
            static["arch"] = platform.machine() or None
            static["cpu_cores"] = (psutil.cpu_count(logical=False) if psutil else None) or None
            static["cpu_logical_cores"] = (psutil.cpu_count(logical=True) if psutil else os.cpu_count()) or None
            self._os_static_cache = static
        info = dict(self._os_static_cache)
        # 动态：负载（仅 Linux 有 getloadavg）+ 开机时间（前端算 uptime）
        try:
            la = os.getloadavg()
            info["load1"], info["load5"], info["load15"] = round(la[0], 2), round(la[1], 2), round(la[2], 2)
        except (OSError, AttributeError):
            info["load1"] = info["load5"] = info["load15"] = None
        info["boot_time"] = psutil.boot_time() if psutil else None
        info["hardware"] = dict(self._hardware_info())
        info["hardware"]["memory"] = self._system_memory((info["hardware"].get('machine') or {}).get('kind'))
        info["storage_status"] = dict(self._storage_status)
        if info["hardware"]["cpu"].get("model"):
            info["cpu_model"] = info["hardware"]["cpu"]["model"]
        for key, field in (("cpu_cores", "physical_cores"), ("cpu_logical_cores", "logical_cores")):
            if info["hardware"]["cpu"].get(field) is not None:
                info[key] = info["hardware"]["cpu"][field]
        return info

    def _system_memory(self, kind=None) -> dict:
        """Cheap OS memory sample, independent of slow inventory and mem_pct time."""
        scope = 'host_visible' if kind == 'container' else 'os_visible'
        total, available, used, source = None, None, None, None
        def valid(value, positive=False):
            number = _hardware_number(value)
            return int(number) if number is not None and number.is_integer() and (number > 0 if positive else number >= 0) else None
        try:
            if psutil:
                sample = psutil.virtual_memory()
                total = valid(sample.total, True)
                available, used = valid(sample.available), valid(sample.used)
                source = 'psutil.virtual_memory'
        except Exception:
            pass
        if total is None and platform.system() == 'Linux':
            text = _hardware_read('/proc/meminfo', limit=32768) or ''
            fields = {key: int(value) * 1024 for key, value in re.findall(
                r'^(MemTotal|MemAvailable):\s+(\d+) kB\s*$', text, re.M)}
            total, available = valid(fields.get('MemTotal'), True), valid(fields.get('MemAvailable'))
            used = total - available if total is not None and available is not None and available <= total else None
            source = '/proc/meminfo'
        completed = datetime.now(timezone.utc).isoformat()
        if total is None:
            previous = getattr(self, '_memory_sample', None)
            result = dict(previous) if previous and previous['scope'] == scope else {
                'total_bytes': None, 'available_bytes': None, 'used_bytes': None,
                'source': None, 'scope': scope, 'sampled_at': None}
            result.update(state='query_failed', attempted_at=completed)
            if kind == 'container' and platform.system() == 'Linux':
                result['cgroup'] = self._cgroup_memory()
            return result
        result = {'total_bytes': total,
                  'available_bytes': available if available is not None and available <= total else None,
                  'used_bytes': used if used is not None and used <= total else None,
                  'source': source, 'scope': scope, 'state': 'available',
                  'sampled_at': completed, 'attempted_at': completed}
        self._memory_sample = dict(result)
        if kind == 'container' and platform.system() == 'Linux':
            result['cgroup'] = self._cgroup_memory()
        return result

    def _cgroup_memory(self) -> dict:
        """Visible cgroup hierarchy limit, not host capacity or exclusive quota.

        Read only the current membership under a verified mount. All visible
        ancestors must be readable; hidden ancestors cannot be claimed unlimited.
        The usage belongs to the limiting group (possibly shared with siblings).
        """
        result = {'total_bytes': None, 'used_bytes': None, 'available_bytes': None,
                  'source': None, 'scope': 'cgroup', 'state': 'query_failed', 'sampled_at': None}
        try:
            memberships = (line.split(':', 2) for line in (_hardware_read('/proc/self/cgroup', limit=32768) or '').splitlines())
            groups = {('v2' if not row[1] else 'v1'): row[2] for row in memberships
                      if len(row) == 3 and (not row[1] or 'memory' in row[1].split(','))}
            mounts = (_hardware_read('/proc/self/mountinfo', limit=65536) or '').splitlines()
            for line in mounts[:512]:
                before, after = line.split(' - ', 1)
                left, right = before.split(), after.split()
                version = 'v2' if right[0] == 'cgroup2' else 'v1' if right[0] == 'cgroup' and 'memory' in right[2].split(',') else None
                if version not in groups:
                    continue
                root, mount, group = left[3], left[4], groups[version]
                if any('\\' in p or '..' in p.split('/') or not p.startswith('/') for p in (root, mount, group)):
                    continue
                if root != '/' and group != root and not group.startswith(root.rstrip('/') + '/'):
                    continue
                relative = group[len(root):].lstrip('/') if root != '/' else group.lstrip('/')
                if len(relative.split('/')) > 32:
                    continue
                path = os.path.join(mount, relative).rstrip('/')
                candidates = []
                limit_file, used_file = ('memory.max', 'memory.current') if version == 'v2' else ('memory.limit_in_bytes', 'memory.usage_in_bytes')
                while True:
                    raw = _hardware_read(path + '/' + limit_file, limit=128)
                    if raw is None:
                        raise ValueError('unreadable hierarchy')
                    raw = raw.strip()
                    unlimited = raw == 'max' if version == 'v2' else raw.isdigit() and int(raw) >= 2 ** 60
                    if not unlimited:
                        if not raw.isdigit():
                            raise ValueError('invalid limit')
                        usage = _hardware_read(path + '/' + used_file, limit=128)
                        used = int(usage.strip()) if usage and usage.strip().isdigit() else None
                        candidates.append((int(raw), used))
                    if path == mount.rstrip('/'):
                        break
                    path = os.path.dirname(path)
                result.update(source='cgroup.' + version, state='unlimited' if root == '/' else 'unknown')
                if candidates:
                    total, used = min(candidates, key=lambda row: row[0])
                    result.update(total_bytes=total, used_bytes=used,
                                  available_bytes=max(0, total - used) if used is not None else None,
                                  state='available')
                result['sampled_at'] = datetime.now(timezone.utc).isoformat()
                self._cgroup_memory_sample = dict(result)
                break
        except (ValueError, IndexError, OSError):
            pass
        if result['state'] == 'query_failed':
            result = dict(getattr(self, '_cgroup_memory_sample', result))
            result['state'] = 'query_failed'
        result['attempted_at'] = datetime.now(timezone.utc).isoformat()
        return result

    def _machine_static_info(self) -> dict:
        """Worker-only static inventory, including failures, cached for five minutes."""
        now = time.monotonic()
        cached = getattr(self, '_machine_static_cache', None)
        if cached is not None and now < cached[0]:
            return cached[1]
        result = {'machine': _classify_machine(), 'physical_inventory': None, 'processors': []}
        try:
            if platform.system() == 'Linux':
                result = self._linux_machine_static()
            elif platform.system() == 'Windows':
                result = self._windows_machine_static()
        except Exception:
            # Never return exception strings / raw command output to the server.
            pass
        self._machine_static_cache = (time.monotonic() + 300, result)
        return result

    def _linux_machine_static(self) -> dict:
        dmi = {key: _hardware_text(_hardware_read('/sys/class/dmi/id/' + key))
               for key in ('sys_vendor', 'product_name')}
        container, vm, virt_none, container_none = None, None, False, False
        binary = shutil.which('systemd-detect-virt')
        if binary:
            try:
                value = _map_command([binary, '--container'], timeout=3, allowed_returncodes=(0, 1)).strip()
                container_none = value == 'none'
                if re.fullmatch(r'[a-z0-9-]{1,32}', value) and value != 'none':
                    container = value
            except Exception:
                pass
            try:
                value = _map_command([binary, '--vm'], timeout=3, allowed_returncodes=(0, 1)).strip()
                if value == 'none':
                    virt_none = True
                elif re.fullmatch(r'[a-z0-9-]{1,32}', value):
                    vm = value
            except Exception:
                pass
        if os.path.exists('/.dockerenv'):
            container = container or 'docker'
        if os.path.exists('/run/.containerenv'):
            container = container or 'podman'
        cgroup = _hardware_read('/proc/1/cgroup', limit=32768) or ''
        for marker, engine in (('docker', 'docker'), ('kubepods', 'kubernetes'),
                               ('libpod', 'podman'), ('lxc', 'lxc'), ('containerd', 'containerd')):
            if marker in cgroup.lower():
                container = container or engine
        machine = _classify_machine(vendor=dmi['sys_vendor'], model=dmi['product_name'],
                                    container=container, vm=vm, virt_none=virt_none and container_none)
        physical = None
        if machine['kind'] == 'physical':
            dmi.update({key: _hardware_text(_hardware_read('/sys/class/dmi/id/' + key))
                        for key in ('board_vendor', 'board_name', 'bios_vendor', 'bios_version')})
            physical = {'board': {'vendor': dmi['board_vendor'], 'model': dmi['board_name']},
                        'bios': {'vendor': dmi['bios_vendor'], 'version': dmi['bios_version']},
                        'memory_modules': None, 'disks': None}
            # Run only with existing process permissions. dmidecode returns failure
            # for unreadable DMI; no sudo, capabilities or permission changes.
            decoder = shutil.which('dmidecode')
            if decoder:
                try:
                    physical['memory_modules'] = _memory_devices(_map_command(
                        [decoder, '--type', '17'], timeout=3))
                except Exception:
                    pass
            lsblk = shutil.which('lsblk')
            if lsblk:
                try:
                    data = json.loads(_map_command([lsblk, '-d', '-b', '-J', '-o',
                                                   'NAME,MODEL,SIZE,TRAN,ROTA'], timeout=3))
                    disks = []
                    for row in data.get('blockdevices', [])[:256]:
                        if not isinstance(row, dict):
                            continue
                        disks.append({'name': _hardware_text(row.get('name')),
                                      'model': _hardware_text(row.get('model')),
                                      'size_bytes': _hardware_positive_int(row.get('size')),
                                      'bus': _hardware_text(row.get('tran')),
                                      'rotational': (bool(row['rota']) if isinstance(row.get('rota'), (bool, int))
                                                     and row['rota'] in (0, 1) else None)})
                    physical['disks'] = disks
                except Exception:
                    pass
        dmi.update({key: _hardware_text(_hardware_read('/sys/class/dmi/id/' + key))
                    for key in ('board_vendor', 'board_name', 'bios_vendor', 'bios_version')})
        public = {'board': {'vendor': dmi['board_vendor'], 'model': dmi['board_name']},
                  'bios': {'vendor': dmi['bios_vendor'], 'version': dmi['bios_version']},
                  'memory_modules': None, 'disks': None, 'source': 'sysfs.dmi',
                  'scope': 'host_visible' if machine['kind'] == 'container' else 'platform_reported',
                  'state': 'available', 'sampled_at': datetime.now(timezone.utc).isoformat()}
        return {'machine': machine, 'physical_inventory': physical,
                'platform_inventory': public if any(dmi[key] for key in ('board_vendor', 'board_name', 'bios_vendor', 'bios_version')) else None,
                'processors': []}

    def _windows_machine_static(self) -> dict:
        # One process, one three-second wall-clock budget for all CIM branches.
        # Both preference forms suppress progress on Windows PowerShell versions.
        script = ("$ProgressPreference='SilentlyContinue'; $ProgressPreference=0; "
                  '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; '
                  '$ErrorActionPreference="Stop"; '
                  '$cs=Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,HypervisorPresent; '
                  '$cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,CurrentClockSpeed,'
                  'MaxClockSpeed,NumberOfCores,NumberOfLogicalProcessors); '
                  '$container=($env:DOTNET_RUNNING_IN_CONTAINER -eq "true" -or '
                  '[bool]$env:CONTAINER_SANDBOX_MOUNT_POINT -or '
                  '@(Get-CimInstance Win32_Container -ErrorAction SilentlyContinue | '
                  'Select-Object -First 1 -Property State).Count -gt 0); '
                  '$physical=(!$container -and $cs.Manufacturer -match '
                  '"(?i)\\b(asus|asustek|lenovo|dell|hewlett-packard|hp|hpe|supermicro|gigabyte|micro-star|msi|asrock|'
                  'acer|apple|fujitsu|intel|samsung|huawei|maxsun|biostar|framework|raspberry pi|microsoft)\\b" '
                  '-and $cs.Model -and ($cs.Manufacturer+" "+$cs.Model) -notmatch '
                  '"(?i)vmware|virtualbox|innotek|qemu|kvm|xen|hvm domu|virtual machine|parallels|bhyve|bochs|amazon ec2|google compute engine|openstack"); '
                  '$board=$null; $bios=$null; $memory=$null; $disks=$null; '
                  'if($physical){ '
                  '$board=Get-CimInstance Win32_BaseBoard -ErrorAction SilentlyContinue | Select-Object -First 1 Manufacturer,Product; '
                  '$bios=Get-CimInstance Win32_BIOS -ErrorAction SilentlyContinue | Select-Object -First 1 Manufacturer,SMBIOSBIOSVersion; '
                  '$memory=@(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | '
                  'Select-Object DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,Manufacturer,PartNumber); '
                  '$disks=@(Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue | Select-Object Index,Model,Size,InterfaceType); }; '
                  + self._windows_gpu_query() +
                  '@{computer_system=$cs; processors=$cpu; board=$board; bios=$bios; memory=$memory; '
                  'disks=$disks; container=$container; gpus=$r} | ConvertTo-Json -Depth 5 -Compress')
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        powershell = shutil.which('powershell') or 'powershell.exe'
        data = json.loads(_map_command([powershell, '-NoProfile', '-NonInteractive',
                                       '-EncodedCommand', encoded], timeout=3).lstrip('\ufeff'))
        if not isinstance(data, (dict, list)):
            raise ValueError('invalid CIM inventory')
        # Accept historical CPU-only fixtures/output, never infer a machine from CPU.
        if isinstance(data, list) or 'computer_system' not in data:
            processors = data if isinstance(data, list) else [data]
            return {'machine': _classify_machine(), 'physical_inventory': None,
                    'processors': [p for p in processors if isinstance(p, dict)]}
        system = data.get('computer_system')
        system = system if isinstance(system, dict) else {}
        machine = _classify_machine(vendor=system.get('Manufacturer'), model=system.get('Model'),
                                    windows=True, hypervisor_present=system.get('HypervisorPresent') is True,
                                    container='windows' if data.get('container') is True else None)
        def rows(key):
            value = data.get(key)
            return [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, dict)][:256]
        physical = None
        if machine['kind'] == 'physical':
            board = (rows('board') or [{}])[0]
            bios = (rows('bios') or [{}])[0]
            physical = {'board': {'vendor': _hardware_text(board.get('Manufacturer')),
                                  'model': _hardware_text(board.get('Product'))},
                        'bios': {'vendor': _hardware_text(bios.get('Manufacturer')),
                                 'version': _hardware_text(bios.get('SMBIOSBIOSVersion'))},
                        'memory_modules': [{'slot': _hardware_text(m.get('DeviceLocator')),
                            'capacity_bytes': _hardware_positive_int(m.get('Capacity')),
                            'speed_mts': _hardware_positive_int(m.get('Speed')),
                            'configured_speed_mts': _hardware_positive_int(m.get('ConfiguredClockSpeed')),
                            'vendor': _hardware_text(m.get('Manufacturer')),
                            'part_number': _hardware_text(m.get('PartNumber'))} for m in rows('memory')] or None,
                        'disks': [{'name': ('disk' + str(d['Index']) if isinstance(d.get('Index'), int)
                                           and not isinstance(d['Index'], bool) else _hardware_text(d.get('Name'))),
                            'model': _hardware_text(d.get('Model')),
                            'size_bytes': _hardware_positive_int(d.get('Size')),
                            'bus': _hardware_text(d.get('InterfaceType')), 'rotational': None}
                            for d in rows('disks')] or None}
        return {'machine': machine, 'physical_inventory': physical, 'processors': rows('processors'),
                'gpus': self._windows_gpu_inventory(data['gpus']) if isinstance(data.get('gpus'), list) else None}

    @staticmethod
    def _gpu_row(identity, name, vendor, kind, source, status, pci_bus=None):
        return {'id': identity, 'name': name, 'vendor': vendor, 'kind': kind,
                'source': source, 'telemetry_status': status, 'pci_bus': pci_bus,
                **{key: None for key in ('temperature_c', 'graphics_clock_mhz',
                   'memory_clock_mhz', 'utilization_pct', 'memory_used_mib',
                   'memory_total_mib', 'power_w', 'fan_pct')}}

    def _gpu_static_info(self):
        now = time.monotonic()
        cached = getattr(self, '_gpu_inventory_cache', None)
        if cached is not None and now < cached[0]:
            return cached[1]
        try:
            system = platform.system()
            rows = (self._linux_gpu_inventory() if system == 'Linux' else
                    self._machine_static_info().get('gpus') if system == 'Windows' else None)
        except Exception:
            rows = None  # Failure/unsupported is unknown, not proof of no GPU.
        self._gpu_inventory_cache = (now + 300, rows)
        return rows

    @staticmethod
    def _gpu_kind(name, vendor_id, device_id):
        if (vendor_id, device_id) in (('8086', '3185'), ('1002', '13c0')):
            return 'integrated'
        if re.search(r'GeForce (?:RTX|GTX)|Radeon (?:RX|PRO)', name, re.I):
            return 'discrete'
        if re.search(r'Intel.*(?:UHD|HD Graphics|Iris Xe)|AMD Radeon\(TM\) Graphics', name, re.I):
            return 'integrated'
        return 'unknown'

    @staticmethod
    def _windows_gpu_query():
        return ("$r=$null; try { $r=@(Get-CimInstance Win32_VideoController | ForEach-Object { "
                "$loc=$null; try { $loc=Get-PnpDeviceProperty -InstanceId $_.PNPDeviceID "
                "-KeyName DEVPKEY_Device_LocationInfo -ErrorAction SilentlyContinue } catch {}; "
                "[PSCustomObject]@{Name=$_.Name; PNPDeviceID=$_.PNPDeviceID; "
                "ConfigManagerErrorCode=$_.ConfigManagerErrorCode; Location=$loc.Data} }); "
                "} catch { $r=$null }; ")

    def _windows_gpu_inventory(self, data=None):
        if data is None:
            script = ("$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
                      "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
                      + self._windows_gpu_query() + "ConvertTo-Json -InputObject $r -Depth 4 -Compress")
            encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
            data = json.loads(_map_command([shutil.which('powershell') or 'powershell.exe',
                             '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], timeout=3).lstrip('\ufeff'))
        if not isinstance(data, list) or len(data) > 64:
            raise ValueError('invalid display inventory')
        rows, seen = [], set()
        for item in data:
            name, identity = _hardware_text(item.get('Name')), item.get('PNPDeviceID') or ''
            match = re.match(r'PCI\\VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})', identity, re.I)
            if not match or not name or re.search(r'todesk|zako|virtual display', name, re.I):
                continue
            # Only publish vendor/device and slot identity, never the PNP suffix.
            ven, dev = (part.lower() for part in match.groups())
            if identity in seen:
                continue
            seen.add(identity)
            location = re.search(r'PCI bus (\d+), device (\d+), function (\d+)',
                                 str(item.get('Location') or ''), re.I)
            pci_bus = ('0000:%02x:%02x.%x' % tuple(map(int, location.groups()))) if location else None
            public_id = ('pci:' + pci_bus if pci_bus else 'display:' + str(len(rows)) + ':' + ven + ':' + dev)
            rows.append(self._gpu_row(public_id, name,
                {'8086': 'Intel', '10de': 'NVIDIA', '1002': 'AMD'}.get(ven, 'Unknown'),
                self._gpu_kind(name, ven, dev), 'Win32_VideoController',
                'unsupported' if item.get('ConfigManagerErrorCode') == 0 else 'driver_missing', pci_bus))
        return rows

    def _linux_gpu_inventory(self, pci_root='/sys/bus/pci/devices'):
        entries = sorted(os.listdir(pci_root))
        if len(entries) > 512:
            raise ValueError('PCI inventory limit')
        rows = []
        for bdf in entries:
            path = os.path.join(pci_root, bdf)
            display_class = _hardware_read(path + '/class')
            if display_class is None:
                raise ValueError('incomplete PCI enumeration')
            if int(display_class, 16) >> 16 != 3:
                continue
            vendor_id = (_hardware_read(path + '/vendor') or '').strip().lower()
            device_id = (_hardware_read(path + '/device') or '').strip().lower()
            if not vendor_id or not device_id:
                raise ValueError('incomplete display identity')
            vendor = {'0x8086': 'Intel', '0x10de': 'NVIDIA', '0x1002': 'AMD'}.get(vendor_id, 'Unknown')
            name, kind = vendor + ' ' + device_id, 'unknown'
            if (vendor_id, device_id) == ('0x8086', '0x3185'):
                name, kind = 'Intel UHD Graphics 600', 'integrated'
            rows.append(self._gpu_row('pci:' + bdf, name, vendor, kind, 'PCI/sysfs',
                        'unsupported' if os.path.islink(path + '/driver') else 'driver_missing', bdf))
        lspci = shutil.which('lspci')
        if rows and lspci:
            try:
                output = _map_command([lspci, '-Dnn'], timeout=3)
                names = {}
                for line in output.splitlines():
                    match = re.match(r'^(\S+)\s+.+?:\s+(.+)$', line)
                    if match:
                        names[match[1]] = match[2]
                for row in rows:
                    if row['pci_bus'] in names:
                        row['name'] = names[row['pci_bus']][:256]
                        row['kind'] = self._gpu_kind(row['name'], '', '') if row['kind'] == 'unknown' else row['kind']
            except Exception:
                pass  # IDs remain useful inventory when names are unavailable.
        return rows

    def _linux_gpu_readings(self, rows, drm_root='/sys/class/drm'):
        """Optional finite public DRM readings; never privilege escalation."""
        try:
            cards = [name for name in os.listdir(drm_root) if re.fullmatch(r'card[0-9]+', name)][:32]
        except OSError:
            return
        for card in cards:
            path = os.path.join(drm_root, card)
            bdf = os.path.basename(os.path.realpath(path + '/device'))
            gpu = next((row for row in rows if row.get('pci_bus') == bdf), None)
            if gpu is None or gpu['vendor'] == 'NVIDIA' or gpu['telemetry_status'] == 'driver_missing':
                continue
            measurements = {}
            for field, filename in (('graphics_clock_mhz', 'gt_cur_freq_mhz'),
                                    ('utilization_pct', 'device/gpu_busy_percent')):
                value = _hardware_number(_hardware_read(path + '/' + filename))
                if value is not None and value >= 0 and (field != 'utilization_pct' or value <= 100):
                    measurements[field] = value
            if measurements:
                gpu.update(measurements)
                gpu.update(source='DRM/sysfs', telemetry_status='available',
                           sampled_at=datetime.now(timezone.utc).isoformat())

    def _empty_hardware(self, reason) -> dict:
        """Complete null-valued contract for pending/failed collection."""
        cpu: dict = {key: None for key in (
            'model', 'physical_cores', 'logical_cores', 'frequency_mhz',
            'max_frequency_mhz', 'base_frequency_mhz', 'base_frequency_source',
            'temperature_c', 'temperature_source', 'frequency_source', 'sampled_at')}
        cpu['model'] = (self._os_static_cache or {}).get('cpu_model')
        static = getattr(self, '_machine_static_cache', (0, None))[1]
        machine = static['machine'] if static else {
            'kind': 'unknown', 'vendor': None, 'model': None, 'virtualization': None,
            'evidence': ['machine detection pending'], 'detected_at': None}
        hardware = {'sampled_at': None, 'sensors_sampled_at': None,
                    'machine': machine, 'physical_inventory': static['physical_inventory'] if static else None,
                    'cpu': cpu, 'gpus': [], 'sensors': [],
                    'availability': {'cpu_temperature': reason,
                                     'gpu_presence': 'unknown',
                                     'gpu': 'collection_failed' if reason == 'collection_failed' else 'unknown'}}
        return hardware

    def _hardware_info(self) -> dict:
        now = time.monotonic()
        if self._hardware_cache is None:
            self._hardware_cache = self._empty_hardware('collecting')
            self._hardware_cached_at = now
        if now >= self._hardware_next_sample:
            # Reserve before submission: an immediately finishing worker cannot
            # trigger a duplicate collection from the next heartbeat.
            self._hardware_next_sample = now + HARDWARE_INTERVAL
            def refresh():
                try:
                    sample = self._collect_hardware()
                except Exception:
                    sample = self._empty_hardware('collection_failed')
                self._hardware_cache = sample
                self._hardware_cached_at = time.monotonic()
            try:
                self._hardware_scheduler.submit('hardware', refresh)
            except Exception:
                self._hardware_cache = self._empty_hardware('collection_failed')
                self._hardware_cached_at = now
        if now - self._hardware_cached_at > 120:
            return self._empty_hardware('stale')
        return self._expire_hardware_readings(self._hardware_cache)

    def _expire_hardware_readings(self, sample) -> dict:
        """Source-age checks also run on cache hits, without I/O or cache mutation."""
        import copy
        def stale(value):
            if not isinstance(value, str):
                return False
            try:
                timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - timestamp).total_seconds()
                return not -30 <= age <= 120
            except (ValueError, TypeError):
                return True
        cpu_stale = stale(sample['cpu'].get('sampled_at'))
        sensors_stale = stale(sample.get('sensors_sampled_at'))
        wmi_stale = (sample['cpu'].get('frequency_source') ==
                     'Win32_Processor.CurrentClockSpeed (WMI; not measured boost)'
                     and stale((sample.get('machine') or {}).get('detected_at')))
        if not cpu_stale and not sensors_stale and not wmi_stale:
            return sample
        result = copy.deepcopy(sample)
        if wmi_stale:
            result['cpu']['frequency_mhz'] = None
            result['cpu']['frequency_source'] = None
        if cpu_stale:
            for key in ('temperature_c', 'frequency_mhz', 'temperature_source', 'frequency_source'):
                result['cpu'][key] = None
            result['availability']['cpu_temperature'] = ('sensors_file_stale'
                if platform.system() == 'Windows' else 'stale')
        if sensors_stale:
            result['sensors'] = []
        return result

    def _collect_hardware(self) -> dict:
        """Latest hardware sample; executed only by the hardware worker."""
        hardware = self._empty_hardware('unavailable')
        collection_time = datetime.now(timezone.utc).isoformat()
        hardware['sampled_at'] = collection_time
        inventory = self._gpu_static_info()
        hardware['gpus'] = [dict(row) for row in inventory or []]
        hardware['availability']['gpu_presence'] = ('present' if inventory else
                                                    'none' if inventory == [] else 'unknown')
        if platform.system() == 'Linux':
            self._linux_gpu_readings(hardware['gpus'])
        hardware['availability']['gpu'] = ('inventory_only' if inventory else
                                          'no_gpu' if inventory == [] else 'unknown')
        static = self._machine_static_info()
        hardware['machine'] = static['machine']
        hardware['physical_inventory'] = static['physical_inventory']
        hardware['platform_inventory'] = static.get('platform_inventory')
        cpu = hardware['cpu']
        if psutil:
            for logical, key in ((False, 'physical_cores'), (True, 'logical_cores')):
                try:
                    cpu[key] = psutil.cpu_count(logical=logical)
                except Exception:
                    pass
            if platform.system() == 'Linux':
                try:
                    frequency = psutil.cpu_freq()
                    if frequency:
                        cpu['frequency_mhz'] = _hardware_number(frequency.current)
                        cpu['max_frequency_mhz'] = _hardware_number(frequency.max)
                        for key in ('frequency_mhz', 'max_frequency_mhz'):
                            if cpu[key] is not None and cpu[key] <= 0:
                                cpu[key] = None
                        if cpu['frequency_mhz'] is not None:
                            cpu['frequency_source'] = 'psutil.cpu_freq'
                except Exception:
                    pass
                cpu_temperatures = []
                for method, kind, unit in (('sensors_temperatures', 'temperature', '°C'),
                                           ('sensors_fans', 'fan', 'RPM')):
                    try:
                        readings = getattr(psutil, method)()
                        for chip, entries in readings.items():
                            for entry in entries:
                                value = _hardware_number(entry.current)
                                if value is None:
                                    continue
                                label = entry.label or chip
                                source = 'psutil:' + chip
                                hardware['sensors'].append({'name': label, 'kind': kind,
                                                           'value': value, 'unit': unit, 'source': source})
                                if (kind == 'temperature' and not chip.lower().startswith('acpi')
                                        and (chip.lower() in ('coretemp', 'k10temp', 'zenpower')
                                             or re.search(r'(?:^|[^a-z])cpu(?:[^a-z]|$)', chip + ' ' + label, re.I))):
                                    cpu_temperatures.append((value, source))
                    except Exception:
                        pass
                if cpu_temperatures:
                    cpu['temperature_c'], cpu['temperature_source'] = max(cpu_temperatures)
                    hardware['availability']['cpu_temperature'] = 'available'
        if platform.system() == 'Linux':
            if cpu['temperature_c'] is not None or cpu['frequency_mhz'] is not None:
                cpu['sampled_at'] = collection_time
            if hardware['sensors']:
                hardware['sensors_sampled_at'] = collection_time
        if platform.system() == 'Windows':
            try:
                processors = static['processors']
                if processors:
                    names = list(dict.fromkeys(p['Name'].strip() for p in processors
                                              if isinstance(p.get('Name'), str) and p['Name'].strip()))
                    if names:
                        cpu['model'] = ' / '.join(names)
                    for field, key in (('NumberOfCores', 'physical_cores'),
                                       ('NumberOfLogicalProcessors', 'logical_cores')):
                        values = [_hardware_number(p.get(field)) for p in processors]
                        if all(v is not None and v > 0 and v.is_integer() for v in values):
                            cpu[key] = int(sum(v for v in values if v is not None))
                    cpu['frequency_mhz'] = _hardware_positive_int(processors[0].get('CurrentClockSpeed'))
                    cpu['base_frequency_mhz'] = _hardware_positive_int(processors[0].get('MaxClockSpeed'))
                    if cpu['base_frequency_mhz'] is not None:
                        cpu['base_frequency_source'] = 'Win32_Processor.MaxClockSpeed (WMI nominal metadata; not measured base/boost)'
                    if cpu['frequency_mhz'] is not None:
                        cpu['frequency_source'] = 'Win32_Processor.CurrentClockSpeed (WMI; not measured boost)'
                        cpu['sampled_at'] = static['machine']['detected_at']
                        cpu.update(self._expire_hardware_readings(hardware)['cpu'])
            except Exception:
                pass
            sensor_failure = 'sensors_file_invalid'
            try:
                path = os.environ.get('STELLA_HARDWARE_SENSORS_FILE', 'C:/stella-agent/hardware-sensors.json')
                import stat
                metadata = os.stat(path)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 131072:
                    raise ValueError('sensor file limit')
                with open(path, 'rb') as stream:
                    raw = stream.read(131073)
                if len(raw) > 131072:
                    raise ValueError('sensor file limit')
                data = json.loads(raw.decode('utf-8-sig'))
                sampled_at = datetime.fromisoformat(data['sampled_at'].replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                if sampled_at.tzinfo is None:
                    raise ValueError('sensor timestamp needs timezone')
                age = (now - sampled_at).total_seconds()
                mtime_age = now.timestamp() - metadata.st_mtime
                if not -30 <= age <= 120 or not -30 <= mtime_age <= 120:
                    sensor_failure = 'sensors_file_stale'
                    raise ValueError('stale sensor file')
                source_timestamp = sampled_at.astimezone(timezone.utc).isoformat()
                for field, key, source_key in (
                        ('cpu_temperature_c', 'temperature_c', 'temperature_source'),
                        ('cpu_frequency_mhz', 'frequency_mhz', 'frequency_source')):
                    raw_value = data.get(field)
                    value = _hardware_number(raw_value) if isinstance(raw_value, (int, float)) else None
                    if value is not None:
                        cpu[key] = value
                        cpu['sampled_at'] = source_timestamp
                        source = data.get('cpu_' + source_key)
                        cpu[source_key] = source[:256] if isinstance(source, str) and source else 'LibreHardwareMonitor'
                entries = data.get('sensors', [])
                if not isinstance(entries, list):
                    entries = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    kind, name = entry.get('kind'), entry.get('name')
                    raw_value = entry.get('value')
                    value = _hardware_number(raw_value) if isinstance(raw_value, (int, float)) else None
                    unit = {'temperature': '°C', 'fan': 'RPM'}.get(kind) if isinstance(kind, str) else None
                    if (unit is None or entry.get('unit') != unit or value is None
                            or not isinstance(name, str) or not name.strip()):
                        continue
                    source = entry.get('source')
                    hardware['sensors'].append({'name': name[:128], 'kind': kind, 'value': value,
                                                'unit': unit, 'source': source[:256] if isinstance(source, str) and source else 'LibreHardwareMonitor'})
                hardware['sensors_sampled_at'] = source_timestamp
                if cpu['temperature_c'] is not None:
                    hardware['availability']['cpu_temperature'] = 'available'
            except FileNotFoundError:
                hardware['availability']['cpu_temperature'] = 'sensors_file_missing'
            except PermissionError:
                hardware['availability']['cpu_temperature'] = 'sensors_file_permission_denied'
            except (ValueError, TypeError, KeyError, AttributeError):
                hardware['availability']['cpu_temperature'] = sensor_failure
            except Exception:
                hardware['availability']['cpu_temperature'] = 'sensors_file_unavailable'
        nvidia = shutil.which('nvidia-smi')
        if nvidia:
            try:
                import csv
                import io
                fields = ('uuid', 'name', 'temperature.gpu', 'clocks.current.graphics',
                          'clocks.current.memory', 'utilization.gpu', 'memory.used',
                          'memory.total', 'power.draw', 'fan.speed', 'pci.bus_id')
                output = _map_command([nvidia, '--query-gpu=' + ','.join(fields),
                                       '--format=csv,noheader,nounits'], timeout=3)
                gpu_sampled_at = datetime.now(timezone.utc).isoformat()
                keys = ('temperature_c', 'graphics_clock_mhz', 'memory_clock_mhz',
                        'utilization_pct', 'memory_used_mib', 'memory_total_mib', 'power_w', 'fan_pct')
                telemetry, seen = [], set()
                for row in csv.reader(io.StringIO(output), skipinitialspace=True):
                    if not row:
                        continue
                    if len(row) not in (10, 11) or not row[0].strip() or not row[1].strip():
                        raise ValueError('invalid gpu row')
                    identity = row[0].strip()
                    if identity in seen:
                        raise ValueError('duplicate GPU UUID')
                    seen.add(identity)
                    bdf = None
                    if len(row) == 11:
                        match = re.search(r'([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7])$', row[-1], re.I)
                        bdf = match[1].lower() if match else None
                    item = self._gpu_row(identity, row[1].strip(), 'NVIDIA',
                                         self._gpu_kind(row[1].strip(), '', ''), 'nvidia-smi', 'available', bdf)
                    item.update({key: _hardware_number(value) for key, value in zip(keys, row[2:10])})
                    measured = any(item[key] is not None for key in keys)
                    item['sampled_at'] = gpu_sampled_at if measured else None
                    if not measured:
                        item['telemetry_status'] = 'unsupported'
                    telemetry.append(item)
                if not telemetry:
                    raise ValueError('empty NVIDIA telemetry')
                hardware['availability']['gpu_query'] = 'available'
                # UUID identifies samples; PCI bus binds them to the physical inventory.
                matched = set()
                for item in telemetry:
                    candidates = [i for i, gpu in enumerate(hardware['gpus'])
                        if i not in matched and gpu['vendor'] == 'NVIDIA' and
                        ((item['pci_bus'] and gpu.get('pci_bus') == item['pci_bus']) or
                         (not gpu.get('pci_bus') and gpu['name'].casefold() == item['name'].casefold()))]
                    if len(candidates) == 1:
                        index = candidates[0]
                        matched.add(index)
                        kind = hardware['gpus'][index]['kind']
                        hardware['gpus'][index].update(item)
                        if kind != 'unknown':
                            hardware['gpus'][index]['kind'] = kind
                    elif not any(gpu['vendor'] == 'NVIDIA' for gpu in inventory or []):
                        hardware['gpus'].append(item)
                    # Ambiguous identity: do not copy telemetry or invent extra cards.
                for gpu in hardware['gpus']:
                    if (gpu['vendor'] == 'NVIDIA' and gpu['telemetry_status'] == 'unsupported'
                            and gpu['id'] not in seen):
                        gpu['telemetry_status'] = 'query_failed'
            except Exception:
                # A failed installed tool is a fact even without inventory rows.
                hardware['availability']['gpu_query'] = 'query_failed'
                for gpu in hardware['gpus']:
                    if gpu['vendor'] == 'NVIDIA' and gpu['telemetry_status'] != 'driver_missing':
                        gpu['telemetry_status'] = 'query_failed'
        if any(gpu['telemetry_status'] == 'available' for gpu in hardware['gpus']):
            hardware['availability']['gpu'] = 'available'
        elif hardware['gpus']:
            hardware['availability']['gpu'] = 'inventory_only'
        elif hardware['availability'].get('gpu_query') == 'query_failed':
            hardware['availability']['gpu'] = 'collection_failed'
        if hardware['gpus']:
            hardware['availability']['gpu_presence'] = 'present'
        for sensor in hardware['sensors']:
            sensor['scope'] = 'host_visible' if hardware['machine']['kind'] == 'container' else 'os_visible'
        return hardware

    def _storage_info(self):
        """Return last successful snapshot immediately; None never erases storage."""
        now = time.monotonic()
        if now >= self._storage_next_sample:
            self._storage_next_sample = now + STORAGE_INTERVAL
            def refresh():
                # Only an admitted worker starts an attempt; busy is not failure.
                attempted_at = datetime.now(timezone.utc).isoformat()
                sampled_at = self._storage_status['sampled_at']
                self._storage_status = {'state': 'collecting', 'sampled_at': sampled_at,
                                        'attempted_at': attempted_at}
                try:
                    sample = self.list_storage()
                    if not isinstance(sample, list):
                        raise ValueError('invalid storage snapshot')
                    self._storage_cache = sample
                    self._storage_status = {'state': 'available',
                                            'sampled_at': datetime.now(timezone.utc).isoformat(),
                                            'attempted_at': attempted_at}
                except Exception:
                    self._storage_status = {'state': 'query_failed', 'sampled_at': sampled_at,
                                            'attempted_at': attempted_at}
            try:
                self._storage_scheduler.submit('storage', refresh)
            except Exception:
                self._storage_status = {'state': 'query_failed',
                                        'sampled_at': self._storage_status['sampled_at'],
                                        'attempted_at': datetime.now(timezone.utc).isoformat()}
        return self._storage_cache

    def _windows_storage(self) -> list:
        """Public Storage cmdlets: physical capacity and unique filesystem usage."""
        script = ("$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
                  "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
                  "$d=@(Get-Disk | Select-Object Number,FriendlyName,Size,@{n='BusType';e={[string]$_.BusType}}); "
                  "$p=@(Get-Partition | ForEach-Object { "
                  "$v=$_ | Get-Volume -ErrorAction SilentlyContinue; "
                  "[PSCustomObject]@{DiskNumber=$_.DiskNumber; VolumeId=$v.Path; AccessPaths=@($_.AccessPaths)} }); "
                  "$v=@(Get-Volume | Select-Object Path,DriveLetter,FileSystem,Size,SizeRemaining); "
                  "@{disks=$d; partitions=$p; volumes=$v} | ConvertTo-Json -Depth 6 -Compress")
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        data = json.loads(_map_command([shutil.which('powershell') or 'powershell.exe',
                         '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], timeout=5).lstrip('\ufeff'))
        if not isinstance(data, dict) or not all(isinstance(data.get(k), list)
                                               for k in ('disks', 'partitions', 'volumes')):
            raise ValueError('invalid storage inventory')
        timestamp = datetime.now(timezone.utc).isoformat()
        volumes, owners, mounts = {}, {}, {}
        for part in data['partitions']:
            identity = part.get('VolumeId')
            if identity:
                owners.setdefault(identity, set()).add(part.get('DiskNumber'))
                mounts.setdefault(identity, set()).update(x for x in part.get('AccessPaths', [])
                    if isinstance(x, str) and not x.startswith('\\\\?\\'))
        for row in data['volumes']:
            identity = row.get('Path')
            total = _hardware_positive_int(row.get('Size'))
            if not identity or not total or not row.get('FileSystem') or identity in volumes:
                continue
            letter = row.get('DriveLetter')
            paths = sorted(mounts.get(identity, set()))
            if not letter and not paths:
                continue  # GUID-only EFI/recovery volumes are not mounted user filesystems.
            mount = str(letter).rstrip(':') + ':/' if letter else (paths[0] if paths else identity)
            free = _hardware_number(row.get('SizeRemaining'))
            used = int(total - free) if free is not None and 0 <= free <= total else None
            volumes[identity] = {'device': identity, 'mount': mount, 'fstype': row['FileSystem'],
                'kind': 'volume', 'total': total, 'used': used,
                'percent': round(used / total * 100, 1) if used is not None else None,
                'usage_scope': 'measured' if used is not None else 'unmeasured', 'sampled_at': timestamp}
        disks = []
        seen = set()
        for row in data['disks']:
            number, total = row.get('Number'), _hardware_positive_int(row.get('Size'))
            if number in seen or not total:
                continue
            seen.add(number)
            related = sorted(v['mount'] for k, v in volumes.items() if number in owners.get(k, set()))
            pooled = sorted(v['mount'] for k, v in volumes.items()
                            if number in owners.get(k, set()) and len(owners[k]) > 1)
            device = 'disk' + str(number)
            disks.append({'device': device, 'mount': device, 'fstype': '', 'kind': 'physical',
                'total': total, 'used': None, 'percent': None,
                'model': _hardware_text(row.get('FriendlyName')), 'bus': _hardware_text(row.get('BusType')),
                'volume_mounts': related, 'pool_mounts': pooled,
                'usage_scope': 'shared_pool' if pooled else 'unmeasured', 'sampled_at': timestamp})
        return disks + list(volumes.values())

    def _physical_disks(self) -> list:
        """Compatibility view: inventory only; usage belongs to filesystems."""
        return [row for row in self.list_storage() if row['kind'] == 'physical']

    def list_storage(self) -> list:
        """Worker-only platform collection. Failures raise, preserving cached data."""
        if platform.system() == 'Windows':
            return self._windows_storage()
        if not psutil:
            raise RuntimeError('storage requires psutil')
        data = json.loads(_map_command(['lsblk', '-b', '-J', '-o',
                         'NAME,SIZE,TYPE,MOUNTPOINTS,MODEL,TRAN,MAJ:MIN,FSTYPE'], timeout=5))
        if not isinstance(data, dict) or not isinstance(data.get('blockdevices'), list):
            raise ValueError('invalid block inventory')
        timestamp = datetime.now(timezone.utc).isoformat()
        disks, mount_owners = [], {}
        for disk in data['blockdevices']:
            total = _hardware_positive_int(disk.get('size'))
            if disk.get('type') != 'disk' or not total:
                continue
            device = '/dev/' + disk['name']
            mounts = set()
            def walk(node):
                paths = node.get('mountpoints') or [node.get('mountpoint')]
                for mount in paths:
                    if isinstance(mount, str) and mount.startswith('/'):
                        mounts.add(mount)
                        mount_owners.setdefault(mount, set()).add(device)
                for child in node.get('children', []):
                    walk(child)
            walk(disk)
            disks.append({'device': device, 'mount': device, 'fstype': '', 'kind': 'physical',
                'total': total, 'used': None, 'percent': None,
                'model': _hardware_text(disk.get('model')), 'bus': _hardware_text(disk.get('tran')),
                'volume_mounts': sorted(mounts), 'pool_mounts': [],
                'usage_scope': 'unmeasured', 'sampled_at': timestamp})
        for disk in disks:
            shared = [mp for mp in disk['volume_mounts'] if len(mount_owners[mp]) > 1]
            disk['pool_mounts'] = shared
            if shared:
                disk['usage_scope'] = 'shared_pool'
        noise = {'tmpfs', 'proc', 'sysfs', 'devtmpfs', 'devpts', 'securityfs',
                 'cgroup', 'cgroup2', 'pstore', 'bpf', 'autofs', 'hugetlbfs',
                 'mqueue', 'tracefs', 'configfs', 'debugfs', 'fusectl',
                 'binfmt_misc', 'nsfs', 'overlay', 'ramfs'}
        seen, volumes = set(), []
        # Prefer canonical lsblk mountpoints over later bind aliases.
        partitions = sorted(psutil.disk_partitions(all=True),
                            key=lambda p: (p.mountpoint not in mount_owners, p.mountpoint))
        for part in partitions:
            dev, fs, mount = part.device or '', part.fstype or '', part.mountpoint
            if fs in noise or not fs or not mount:
                continue
            if ':/' in dev or dev.startswith('//'):
                kind = 'network'
            elif dev.startswith('/dev/mapper/') or dev.startswith('/dev/md'):
                kind = 'virtual'
            elif dev.startswith('/dev/'):
                kind = 'volume'
            else:
                continue
            # Canonical block identity dedupes btrfs subvolumes (which can have
            # different synthetic st_dev); mount st_dev also dedupes bind aliases.
            identities = {('dev', os.path.realpath(dev))}
            try:
                identities.add(('fs', os.stat(mount).st_dev))
            except OSError:
                pass
            if seen.intersection(identities):
                continue
            try:
                usage = psutil.disk_usage(mount)
            except OSError:
                raise RuntimeError('filesystem usage unavailable') from None
            seen.update(identities)
            volumes.append({'device': dev, 'mount': mount, 'fstype': fs, 'kind': kind,
                'total': int(usage.total), 'used': int(usage.used),
                'percent': round(float(usage.percent), 1),
                'usage_scope': 'measured', 'sampled_at': timestamp})
        return disks + volumes

    # ── 上报（含补传）──
    def report(self, metrics: list, sys_metrics: list):
        """上报流量 + 系统指标。失败时压入队列，成功时先补传队列再发当前。"""
        # 当前数据也进队列（发送成功才出队，保证不丢）；带组件检测状态（which 很便宜）
        self.queue.append(zlib.compress(json.dumps({
            "metrics": metrics, "sys_metrics": sys_metrics,
            "components": self._check_components(),
            "os_info": self._os_info(),
            "storage": self._storage_info(),
        }, separators=(',', ':'), ensure_ascii=False).encode('utf-8')))

        # One POST per round, up to twelve queued samples in that transaction.
        # Unknown outcomes are never immediately retried at another entry.
        if self.queue and time.monotonic() >= getattr(self, '_report_not_before', 0):
            count = min(len(self.queue), 12)
            pending = [json.loads(zlib.decompress(self.queue[i])) for i in range(count)]
            batch = {**pending[-1], 'metrics': [m for p in pending for m in p['metrics']],
                     'sys_metrics': [m for p in pending for m in p['sys_metrics']]}
            # Send the previous completed transaction, not a queued historical copy.
            previous = getattr(self, "_last_report_transaction", None)
            icmp = getattr(self, "_entry_samples", [])
            if previous is not None or icmp:
                batch["control_channel"] = {"report": previous, "icmp": icmp}
            try:
                resp = self._post("/agent/report", json_body=batch, token=self.token)
                for _ in range(count):
                    self.queue.popleft()  # only the explicitly acknowledged batch
                self._report_failures = 0
                # 心跳响应带版本号：变了就拉配置 diff
                ver = resp.get("monitors_version")
                if ver is not None and ver != self.monitors_version:
                    self.refresh_config()
                channel_ver = resp.get('channel_revision')
                if channel_ver is not None and channel_ver != (getattr(self, '_channel_policy', None) or {}).get('revision'):
                    self.refresh_config()
            except Exception:
                self._report_failures = getattr(self, '_report_failures', 0) + 1
                self._report_not_before = time.monotonic() + min(60, 5 * 2**min(self._report_failures-1,4))

    def _file_tick(self):
        """One managed Linux/root child, never the historical inline worker."""
        if sys.platform != 'linux' or os.geteuid() != 0:
            return  # Windows/nonroot collectors retain their existing behavior.
        if not hasattr(self, '_file_supervisor'):
            self._file_supervisor = _FileSupervisor(self._file_snapshot)
        self._file_supervisor.tick()

    def _file_snapshot(self):
        from pathlib import Path
        binding = self._installation_binding()
        if binding != getattr(self, '_installation', None):
            raise ValueError('file instance binding changed')
        return {'origin': self.url, 'token': self.token, 'binding': binding,
                'legacy': os.environ.get('STELLA_FILE_ROOTS'),
                'store': str(Path(__file__).absolute().parent / '.file-releases')}

    # ── 任务执行 ──
    def poll_and_execute(self):
        """轮询待办任务，执行并回传结果。"""
        try:
            self._assert_instance_identity()
            tasks = self._get("/agent/tasks", token=self.token)
        except Exception:
            return

        # 卸载指令：优先处理（执行后不再跑其他任务）
        if tasks.get("uninstall"):
            self._run_uninstall()
            return

        for t in tasks.get("iperf_tasks", []):
            self._run_iperf(t)
        for t in tasks.get("mtr_tasks", []):
            self._run_mtr(t)
        for c in tasks.get("commands", []):
            self._run_command(c)
        for c in tasks.get("component_installs", []):
            self._run_component_install(c)
        for t in tasks.get("net_tasks", []):
            self._run_net_task(t)

    def _run_uninstall(self):
        """卸载自己：后台脚本停服务 + 删文件，先回传结果再自删。"""
        print("[uninstall] 收到卸载指令", file=sys.stderr, flush=True)
        try:
            argv = self._instance_uninstall_argv()
            if argv is not None:
                # The root-owned helper validates exact binding and detaches from
                # this service/task before deleting only its own installation.
                subprocess.run(argv, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                self._post('/agent/uninstall/result', token=self.token, status='done')
                return
            # 后台脚本：sleep 留时间回传结果，再停服务删文件（停了服务 agent 就没法回传了）
            script = (
                "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
                "sleep 3; "
                "sudo systemctl disable stella-agent 2>/dev/null; "
                "sudo rm -f /etc/systemd/system/stella-agent.service; "
                "sudo systemctl daemon-reload; "
                "sudo rm -rf /opt/stella-agent; "
                "sudo systemctl stop stella-agent 2>/dev/null; "
            )
            subprocess.Popen(["nohup", "sh", "-c", script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            self._post("/agent/uninstall/result", token=self.token, status="done")
            print("[uninstall] 已回传 done", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[uninstall] 回传失败: {e!r}", file=sys.stderr, flush=True)
            try:
                self._post("/agent/uninstall/result", token=self.token, status="failed", error=str(e))
            except Exception:
                pass

    def _entry_resolve(self, hostname, timeout):
        """At most one outstanding OS resolver per Agent, even on DNS hangs."""
        import queue
        if not hasattr(self, '_entry_dns_lock'):
            self._entry_dns_lock = threading.Lock()
        if not self._entry_dns_lock.acquire(blocking=False):
            raise TimeoutError('resolver busy')
        result = queue.Queue(maxsize=1)
        def resolve():
            try:
                records = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_DGRAM)
                result.put(sorted({r[4][0] for r in records}))
            except Exception as exc:
                result.put(exc)
            finally:
                self._entry_dns_lock.release()
        threading.Thread(target=resolve, daemon=True).start()
        try:
            value = result.get(timeout=max(.001, timeout))
        except queue.Empty:
            raise TimeoutError('resolver deadline') from None
        if isinstance(value, Exception):
            raise value
        return value

    def _entry_ping(self, ip, budget):
        import ipaddress
        family = ipaddress.ip_address(ip).version
        windows = platform.system() == 'Windows'
        argv = ['ping', '-'+str(family)] + (['-n','1','-w','1000'] if windows else ['-n','-c','1','-W','1']) + [ip]
        value = dict(ip=ip, family=family, status='unavailable', latency_ms=None, loss_pct=None)
        try:
            run = subprocess.run(argv, capture_output=True, text=True,
                timeout=min(1.5, budget), env={**os.environ, 'LC_ALL':'C'})
            out = run.stdout + run.stderr
            loss = re.search(r'(\d+(?:\.\d+)?)%\s*(?:packet\s*)?loss', out)
            rtt = re.search(r'(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/', out)
            if windows:
                rtt = re.search(r'(?:Average|平均)\s*=\s*(\d+)\s*ms', out)
            value['loss_pct'] = float(loss.group(1)) if loss else None
            value['latency_ms'] = float(rtt.group(1)) if rtt else None
            if value['loss_pct'] is not None:
                value['status'] = 'up' if run.returncode == 0 and value['latency_ms'] is not None and value['loss_pct'] < 100 else 'down' if value['loss_pct'] == 100 else 'unavailable'
        except (OSError, subprocess.TimeoutExpired):
            pass
        return value

    def run_entry_probes(self):
        """Automatic management ICMP; separate from manual probes and report IO."""
        now = time.monotonic()
        if now < getattr(self, '_next_entry_probe', 0):
            return
        self._next_entry_probe = now + 60
        manifest = getattr(self, '_entry_manifest', {})
        try:
            _entry_scope(manifest)
            scope_valid = True
        except (ValueError, TypeError):
            scope_valid = False
        if not isinstance(manifest, dict):
            self._entry_samples = []
            return
        entries = manifest.get('entries', [])
        if not isinstance(entries, list) or len(entries) > 4:
            self._entry_samples = []
            return
        deadline, samples, cache = now + 12, [], {}
        for entry in entries:
            sample = dict(entry_id=entry['entry_id'], version=entry['version'],
                hostname=entry['hostname'], sampled_at=datetime.now(timezone.utc).isoformat(),
                status='complete', results=[])
            try:
                remaining = deadline - time.monotonic()
                if not scope_valid:
                    sample['status'] = 'outside_scope'
                elif manifest.get('icmp_available') is not True:
                    sample['status'] = 'unavailable'
                elif remaining <= 0:
                    sample['status'] = 'budget_exceeded'
                else:
                    ips = self._entry_resolve(entry['hostname'], min(2, remaining))
                    if len(ips) > 4:
                        sample['status'] = 'too_many_ips'
                    elif not ips:
                        sample['status'] = 'dns_error'
                    elif not all(_entry_ip_allowed(ip, manifest.get('targets'), manifest.get('approved_ranges', [])) for ip in ips):
                        sample['status'] = 'outside_scope'
                    else:
                        for ip in ips:
                            remaining = deadline - time.monotonic()
                            if remaining <= .05:
                                sample['status'] = 'budget_exceeded'
                                break
                            if ip not in cache:
                                cache[ip] = self._entry_ping(ip, remaining)
                            sample['results'].append(cache[ip])
                        if sample['status']=='complete' and any(r['status']=='unavailable' for r in sample['results']):
                            sample['status']='unavailable'
            except TimeoutError:
                sample['status'] = 'dns_timeout'
            except (OSError, ValueError, KeyError, TypeError):
                sample['status'] = 'dns_error'
            samples.append(sample)
        self._entry_samples = samples

    # ── 监控项探测（agent 自探测）──
    def run_due_probes(self):
        """到点的监控项执行探测，结果上报中心。"""
        self.run_entry_probes()
        now = time.time()
        # Config refresh may add/remove monitors on the heartbeat thread.
        for mid, m in list(self.monitors.items()):
            # MTR 定时通道（与探测节奏解耦）
            if now >= m.get("next_mtr", float("inf")):
                m["next_mtr"] = now + MTR_INTERVAL
                self._run_mtr_for_monitor(mid, m, "periodic")
            if now < m["next_run"]:
                continue
            m["next_run"] = now + m["interval"]  # 先排下次，避免探测慢堆积
            success, latency, loss = self.probe(m["type"], m["target"], m["timeout"])
            # Unknown ping source is not a remote failure or a fresh check.
            # next_run and the independent periodic MTR were already advanced.
            if success is None:
                continue
            # 失败触发 MTR（防抖 10 分钟，挂了立刻有路径快照）
            if not success and now - m.get("last_fail_mtr", 0) > MTR_FAIL_DEBOUNCE:
                m["last_fail_mtr"] = now
                m["next_mtr"] = now + MTR_INTERVAL  # 失败这次顶掉定时那次
                self._run_mtr_for_monitor(mid, m, "failure")
            try:
                self._post("/agent/monitor-check", json_body={
                    "monitor_id": mid, "ts": datetime.now(timezone.utc).isoformat(),
                    "success": success, "latency_ms": latency, "loss_pct": loss,
                }, token=self.token)
            except Exception:
                pass

    def probe(self, mtype: str, target: str, timeout: int):
        """执行一次探测；ping 源不可验证时 success=None，不上报普通 check。"""
        try:
            if mtype == "tcp":
                return self._probe_tcp(target, timeout)
            if mtype in ("http", "https"):
                return self._probe_http(target, timeout, mtype)
            if mtype == "ping":
                return self._probe_ping(target, timeout)
            if mtype == "udp":
                return self._probe_udp(target, timeout)
        except Exception:
            # A broken local ping source is not evidence of remote packet loss.
            return (None, None, None) if mtype == "ping" else (False, None, None)
        return (False, None, None)

    @staticmethod
    def _split_host_port(target: str):
        # 输入容错：全角冒号/空白（后端已规范化，这里是存量配置的兜底）
        target = target.replace("：", ":").strip()
        if "[" in target or "]" in target:
            # Brackets delimit an IPv6 literal, but are not part of a socket host.
            import ipaddress
            match = re.fullmatch(r"\[([^\[\]]+)\]:([0-9]+)", target)
            if not match or "%" in match[1]:
                raise ValueError("invalid bracketed IPv6 target")
            host, port = match[1], int(match[2])
            ipaddress.IPv6Address(host)
            if not 1 <= port <= 65535:
                raise ValueError("invalid IPv6 target port")
            return host, port
        if ":" in target:
            host, port = target.rsplit(":", 1)
            return host, int(port)
        return target, 80

    def _probe_tcp(self, target, timeout):
        host, port = self._split_host_port(target)
        start = time.time()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                latency = (time.time() - start) * 1000
            return (True, latency, None)
        except OSError:
            return (False, (time.time() - start) * 1000, None)

    def _probe_http(self, target, timeout, scheme):
        import urllib.error
        target = target.replace("：", ":").strip()  # 全角冒号兜底
        url = target if target.startswith("http") else f"{scheme}://{target}"
        start = time.time()
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                latency = (time.time() - start) * 1000
                return (resp.status < 500, latency, None)
        except urllib.error.HTTPError as exc:
            # urlopen raises for 4xx too. A received HTTP response follows the
            # same availability contract as the non-exception path, not 2xx-only.
            exc.close()
            return (exc.code < 500, (time.time() - start) * 1000, None)
        except Exception:
            return (False, (time.time() - start) * 1000, None)

    def _probe_ping(self, target, timeout):
        """10 packets; None success means no trustworthy sample (never post it)."""
        unknown = (None, None, None)
        windows = platform.system() == "Windows"
        cmd = (["ping", "-n", "10", "-w", str(int(timeout * 1000)), target] if windows
               else ["ping", "-c", "10", "-W", str(timeout), target])
        try:
            # POSIX ping honors LC_ALL; Windows uses its own localized output.
            env = dict(os.environ)
            if not windows:
                env['LC_ALL'] = 'C'
            r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                               timeout=timeout * 10 + 5)
            out = r.stdout + '\n' + r.stderr
            if windows:
                summaries = re.findall(
                    r'(?:Packets|数据包)\s*:\s*(?:Sent|已发送)\s*=\s*(\d+)\s*[,，]\s*'
                    r'(?:Received|已接收)\s*=\s*(\d+)\s*[,，]\s*'
                    r'(?:Lost|丢失)\s*=\s*(\d+)\s*\(([^%\s]+)%\s*(?:loss|丢失)\)', out)
                rtts = re.findall(r'(?:Average|平均)\s*=\s*([^\s,，]+)\s*ms', out)
            else:
                summaries = re.findall(
                    r'^\s*(\d+) packets transmitted,\s*(\d+)(?: packets)? received,\s*'
                    r'(?:\+\d+ errors,\s*)?([^%\s]+)%\s*packet loss', out, re.M)
                rtts = re.findall(r'(?:rtt|round-trip)[^\n]*?=\s*[^/\s]+/([^/\s]+)/', out)
            if len(summaries) != 1 or len(rtts) > 1:
                return unknown
            summary = summaries[0]
            sent, received = int(summary[0]), int(summary[1])
            loss = float(summary[-1])
            if (not 0 < sent <= 10 or not 0 <= received <= sent
                    or not math.isfinite(loss) or not 0 <= loss <= 100
                    or (received == 0) != (loss == 100)
                    or (received == sent) != (loss == 0)
                    or not math.isclose(loss, (sent - received) * 100 / sent, abs_tol=.5)):
                return unknown
            if windows and int(summary[2]) != sent - received:
                return unknown
            latency = float(rtts[0]) if rtts else None
            if latency is not None and (not math.isfinite(latency) or latency < 0):
                return unknown
            # Exit errors or contradictory stats cannot become a remote down.
            # Windows may count ICMP errors as received; require echo RTT for up.
            if r.returncode == 0 and loss < 100 and latency is not None:
                return (True, latency, loss)
            if r.returncode == 1 and loss == 100:
                return (False, latency, loss)
            return unknown
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return unknown

    def _probe_udp(self, target, timeout):
        host, port = self._split_host_port(target)
        start = time.monotonic()
        deadline = start + timeout
        try:
            addresses = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_DGRAM)
        except OSError:
            return (False, None, None)
        # Bound multi-A/AAAA retries; all socket I/O shares one remaining budget.
        # System getaddrinfo itself has no portable timeout; charge its elapsed time.
        for family, socktype, proto, _, address in addresses[:8]:
            if time.monotonic() >= deadline:
                break
            if family not in (socket.AF_INET, socket.AF_INET6) or socktype != socket.SOCK_DGRAM:
                continue
            try:
                s = socket.socket(family, socktype, proto)
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return (False, None, None)
                    s.settimeout(remaining)
                    s.sendto(b"\x00", address)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return (False, None, None)
                    s.settimeout(remaining)
                    try:
                        s.recvfrom(1024)
                    except socket.timeout:
                        # No application reply is not evidence of availability.
                        # Keep loss unknown: one UDP probe is not packet-loss sampling.
                        return (False, None, None)
                finally:
                    s.close()
                return (True, (time.monotonic() - start) * 1000, None)
            except OSError:
                continue  # Explicit local/send/receive errors may try the next address.
        return (False, None, None)

    def _run_iperf(self, task):
        """执行 iperf3 打流。role=server 起 -s，role=client 起 -c（流式回传进度）。"""
        tid = task["id"]
        try:
            if self._throughput_terminal(tid):
                return
            if task["mode"] == "speedtest":
                result = self._run_speedtest(task)
            elif task["role"] == "server":
                result = self._iperf_server(task)
            else:
                result = self._iperf_client(task)
                # 跨海 UDP/TCP 偶发「控制连接 reset」（端口协商失败）。server 端此时保持监听，
                # 这里自动重试（最多 2 次），每次回传重试事件给前端显示「xx原因，重试第x次」。
                attempt = 0
                while (isinstance(result, dict) and result.get("error")
                       and self._is_retryable_error(result["error"]) and attempt < 2):
                    if self._throughput_terminal(tid):
                        return
                    attempt += 1
                    self._emit_retry_event(tid, attempt, result["error"])
                    time.sleep(2)  # 给 server 端时间从 reset 恢复回监听，再重试
                    if self._throughput_terminal(tid):
                        return
                    result = self._iperf_client(task)
            if self._throughput_terminal(tid):
                return
            if isinstance(result, dict): result["role"] = task.get("role", "client")
            if isinstance(result, dict) and result.get("error"):
                self._post(f"/agent/iperf-tasks/{tid}/result",
                           json_body=result, token=self.token, status="failed")
            else:
                self._post(f"/agent/iperf-tasks/{tid}/result",
                           json_body=result, token=self.token, status="done")
        except Exception as e:
            if self._throughput_terminal(tid):
                return
            self._post(f"/agent/iperf-tasks/{tid}/result",
                       json_body={"error": str(e), "role": task.get("role", "client")}, token=self.token, status="failed")

    def _iperf_server(self, task) -> dict:
        """Own one server child, stream receiver data, stop on task terminal/budget.

        No port-pattern pkill: another centre may own the listener. Bind failure is
        surfaced instead. Persistent -s survives harmless readiness TCP probes.
        """
        proc = subprocess.Popen(["iperf3", "-s", "-p", str(task.get("port", 5201)), "--forceflush"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        budget = 3900 if task.get("bytes") else task["duration"] + task.get("omit", 0) + 360
        threading.Thread(target=self._watch_cancel, args=(task["id"], proc, budget), daemon=True).start()

        def _watch():
            diagnostic = ""
            try:
                accepted = False
                if proc.stdout is None:
                    diagnostic = "无法读取 iperf3 server 输出"
                else:
                    for line in proc.stdout:
                        # Probe cookie errors are not real-client failures.
                        if "error" in line.lower() and "cookie" not in line.lower():
                            diagnostic = (diagnostic + line.strip())[-500:]
                        if "Accepted connection" in line:
                            accepted = True
                        elif "Server listening" in line:
                            accepted = False
                            if self._throughput_terminal(task["id"]):
                                break
                        elif accepted:
                            self._emit_server_progress(task["id"], line, task.get("parallel", 1))
            except Exception as e:
                diagnostic = str(e)[-500:]
            finally:
                self._terminate_proc(proc)
                if not self._throughput_terminal(task["id"]):
                    # Auxiliary success must not finish a task; real server failure must.
                    try:
                        self._post(f"/agent/iperf-tasks/{task['id']}/result", token=self.token, status="failed",
                                   json_body={"role": "server", "error": diagnostic or "iperf3 server 已提前退出或超时"})
                    except Exception:
                        pass
        threading.Thread(target=_watch, daemon=True).start()
        return {"role": "server"}

    def _emit_server_progress(self, task_id: int, line: str, parallel: int = 1) -> None:
        """server 端（接收端）每秒回传接收速率 + 真实丢包/抖动（正向 UDP 实时丢包）。

        server 的 receiver interval 行：`1.22 MBytes  10.2 Mbits/sec  0.023 ms  0/39 (0%)`，
        带真实 jitter + lost/total（client 端是 sender 视角，看不到丢包）。"""
        # 过滤汇总行（末尾带 receiver/sender 标记，是 0-N 秒的汇总，不是每秒 interval）
        if "receiver" in line or "sender" in line:
            return
        if parallel > 1 and "[SUM]" not in line:
            return
        if "(omitted)" in line:
            return
        # 过滤末尾不完整秒行：跨海延迟导致结束瞬间多吐一行（interval 不足 1 秒）。
        # 正向接收端是 "20.00-20.00"（起始==结束），反向发送端是 "10.00-10.05"（起始≠结束），
        # 所以不能只看起始==结束，统一用「interval 长度 < 1 秒」判断才对两种方向都生效。
        iv = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*sec', line)
        if iv:
            _s = float(iv.group(1)); _e = float(iv.group(2))
            if _e - _s < 0.99:
                return
        m = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
        if not m:
            return
        bits = self._to_bits(float(m.group(1)), m.group(2))
        jm = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
        jitter = float(jm.group(1)) if jm else None
        lm = re.search(r'(\d+)/(\d+)\s*\(', line)
        lost = (int(lm.group(1)) / int(lm.group(2)) * 100.0) if lm and int(lm.group(2)) else None
        ts = datetime.now(timezone.utc).isoformat()
        params = {"ts": ts, "bitrate": bits, "role": "server", "token": self.token}
        if lost is not None:
            params["lost_pct"] = lost
        if jitter is not None:
            params["jitter_ms"] = jitter
        try:
            self._post(f"/agent/iperf-tasks/{task_id}/progress", **params)
        except Exception:
            pass  # 进度回传失败不致命


    def _throughput_terminal(self, task_id: int) -> bool:
        try:
            return self._get(f"/agent/iperf-tasks/{task_id}/status", token=self.token).get("status") in ("done", "failed", "cancelled")
        except Exception:
            return False  # transient control-plane loss does not fabricate cancellation

    def _terminate_proc(self, proc) -> None:
        """Terminate only the owned child; kill if needed, and always reap it."""
        try:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        except OSError:
            pass

    def _watch_cancel(self, task_id: int, proc, timeout: float = 3600) -> None:
        """后台线程：检测任务被中止（前端点中止 → status=cancelled），则 terminate iperf3 进程。

        iperf3 client/server 进程在跑时主线程阻塞在流式读 stdout，没法轮询任务状态，
        所以用独立线程每 2s 查一次，cancel 了就把 iperf3 杀掉，让主线程读 stdout 到 EOF 退出。"""
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if self._throughput_terminal(task_id) or time.monotonic() >= deadline:
                self._terminate_proc(proc)
                break
            time.sleep(2)

    def _iperf_client(self, task) -> dict:
        """iperf3 client（流式）：--interval 1 --forceflush 逐行读 stdout，每秒解析吞吐回传 progress，结束返回汇总。"""
        if self._throughput_terminal(task["id"]):
            return {"error": "测速任务已结束或已取消"}
        server = task.get("server_host")
        if not server:
            return {"error": "无 server host"}
        if shutil.which("iperf3") is None:
            return {"error": "本节点未安装 iperf3，请先在服务器列表代装"}
        port = task.get("port", 5201)
        # 先等 server 的 iperf3 端口就绪（server agent 可能还在轮询领取，没起 -s）
        # server 端 iperf3 -s 监听 TCP 控制端口（UDP 模式也一样，控制连接走 TCP），探测通用
        if not self._wait_server_ready(server, port=port, task_id=task["id"]):
            return {"error": f"等待 server {server}:{port} 就绪超时（server 未起 iperf3）"}
        if self._throughput_terminal(task["id"]):
            return {"error": "测速任务已结束或已取消"}
        cmd = ["iperf3", "-c", server, "--interval", "1", "--forceflush",
               "-p", str(port), "-P", str(task["parallel"])]
        # 数据量（-n）与时长（-t）二选一：bytes 有值按数据量，否则按时长
        if task.get("bytes"):
            cmd += ["-n", self._norm_units(task["bytes"])]
        else:
            cmd += ["-t", str(task["duration"])]
        if task.get("direction") == "reverse":
            cmd.append("-R")
        if task.get("udp"):
            cmd.append("-u")
            # UDP 必填目标带宽，空则默认 100M（否则 iperf3 默认 1Mbps，大数据量会卡十几分钟）
            cmd += ["-b", self._norm_units(task.get("bitrate")) or "100M"]
        elif task.get("bitrate"):
            # TCP 可选限速：填了 -b 就限速发送
            cmd += ["-b", self._norm_units(task["bitrate"])]
        if task.get("window"):
            cmd += ["-w", task["window"]]
        if task.get("length"):
            cmd += ["-l", task["length"]]
        if task.get("omit"):
            cmd += ["-O", str(task["omit"])]
        if task.get("zerocopy"):
            cmd.append("-Z")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
        except FileNotFoundError:
            return {"error": "iperf3 未安装"}

        # 检测中止：前端点中止 → terminate iperf3 client，读 stdout 到 EOF 退出
        budget = 3600 if task.get("bytes") else task["duration"] + task.get("omit", 0) + 60
        try:
            threading.Thread(target=self._watch_cancel, args=(task["id"], proc, budget), daemon=True).start()
            return self._iperf_client_stream(task, proc)
        finally:
            self._terminate_proc(proc)

    def _iperf_client_stream(self, task, proc) -> dict:
        points: list = []
        if proc.stdout is None:
            return {"error": "无法读取 iperf3 输出"}

        # 流式解析：interval 行（每秒吞吐，多流按秒聚合）；sender/receiver 行记录最终汇总
        # UDP interval 行带 jitter(ms) + lost/total(x%)：正向时是 sender 视角（恒 0），
        # 反向(-R) 时 client 是接收端，interval 行是 receiver 视角（真实丢包/抖动）——所以反向才实时可见。
        cur_key: str | None = None
        cur_bits = 0.0
        cur_lost = 0      # 该秒丢包数（分子，多流累加）
        cur_total = 0     # 该秒总包数（分母，多流累加）
        cur_jitter_sum = 0.0
        cur_jitter_n = 0
        sender_line = ""    # 发送端汇总（TCP 重传在这）
        receiver_line = ""  # 接收端汇总（UDP 真实丢包/抖动/接收速率在这）
        diagnostic = ""

        def emit(bits: float, lost_pct=None, jitter_ms=None):
            ts = datetime.now(timezone.utc).isoformat()
            p = {"ts": ts, "bitrate": bits}
            params = {"ts": ts, "bitrate": bits, "token": self.token}
            if lost_pct is not None:
                p["lost_pct"] = lost_pct
                params["lost_pct"] = lost_pct
            if jitter_ms is not None:
                p["jitter_ms"] = jitter_ms
                params["jitter_ms"] = jitter_ms
            points.append(p)
            try:
                self._post(f"/agent/iperf-tasks/{task['id']}/progress", **params)
            except Exception:
                pass  # 进度回传失败不致命，继续采

        for line in proc.stdout:
            line = line.strip()
            if "error" in line.lower():
                diagnostic = (diagnostic + line)[-500:]
            if "(omitted)" in line or (task["parallel"] > 1 and "[SUM]" not in line):
                continue
            if "sender" in line:
                sender_line = line  # 发送端汇总（最后一条是最终 SUM）
                continue
            if "receiver" in line:
                receiver_line = line  # 接收端汇总（UDP 真实数据在这里）
                continue
            m = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
            if not m:
                continue
            bits = self._to_bits(float(m.group(1)), m.group(2))
            iv = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*sec', line)
            if not iv:
                continue
            key = iv.group(1)
            # 过滤末尾不完整秒行（interval 长度 < 1 秒）：正向 "20.00-20.00"、反向 "10.00-10.05"，
            # 都是结束瞬间的残留，回传会多一个点撑长 x 轴。用长度判断对正反向都生效。
            if float(iv.group(2)) - float(iv.group(1)) < 0.99:
                continue
            if cur_key is None:
                cur_key = key
            if key != cur_key:
                # 换到下一秒，回传上一秒聚合值
                lost = (cur_lost / cur_total * 100.0) if cur_total else None
                jit = (cur_jitter_sum / cur_jitter_n) if cur_jitter_n else None
                emit(cur_bits, lost, jit)
                cur_key = key
                cur_bits = 0.0
                cur_lost = 0; cur_total = 0; cur_jitter_sum = 0.0; cur_jitter_n = 0
            cur_bits += bits
            # UDP interval 行带 jitter + lost/total；TCP 行无此字段，正则匹配不到即跳过
            jm = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if jm:
                cur_jitter_sum += float(jm.group(1)); cur_jitter_n += 1
            lm = re.search(r'(\d+)/(\d+)\s*\(', line)
            if lm:
                cur_lost += int(lm.group(1)); cur_total += int(lm.group(2))
        if cur_key is not None:
            lost = (cur_lost / cur_total * 100.0) if cur_total else None
            jit = (cur_jitter_sum / cur_jitter_n) if cur_jitter_n else None
            emit(cur_bits, lost, jit)

        proc.wait(timeout=5)
        err = diagnostic
        if proc.returncode != 0:
            return {"error": err[-500:] or "iperf3 连接失败"}
        interval = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*sec', receiver_line)
        if diagnostic or not interval:
            return {"error": diagnostic or "iperf3 未返回接收端汇总，无法确认测速结果"}

        # Final receiver summary is duration-weighted and also works for subsecond
        # byte-limited runs with no full-second intervals. Peak is independent.
        recv = self._parse_receiver_line(receiver_line)
        avg = recv.get("recv_bitrate")
        total_bytes = recv.get("total_bytes")
        if avg is None or total_bytes is None:
            return {"error": "iperf3 接收端汇总缺少速率或数据量"}
        peak = max((p["bitrate"] for p in points), default=None) if task.get("direction") == "reverse" else None
        lost_pct = recv.get("lost_pct") if task.get("udp") else None
        jitter_ms = recv.get("jitter_ms") if task.get("udp") else None
        retransmits = None if task.get("udp") else self._parse_sender_line(sender_line).get("retransmits")
        # 发送端平均速率（基准虚线）：sender 汇总行的 bitrate（sender 永远是发送端）
        send_avg = self._parse_sender_line(sender_line).get("bitrate")
        result = {
            "role": "client",
            "avg_bitrate": avg,
            "peak_bitrate": peak,
            "send_avg_bitrate": send_avg,
            "total_bytes": total_bytes,
            "lost_pct": lost_pct,
            "jitter_ms": jitter_ms,
            "retransmits": retransmits,
            "duration": float(interval.group(2)) - float(interval.group(1)),
            "parallel": task["parallel"],
            "direction": task.get("direction", "forward"),
            "udp": bool(task.get("udp")),
        }
        # An arbitrary 1Gbps ceiling is not evidence of corrupted counters.
        return result

    @staticmethod
    def _to_bits(val: float, unit: str) -> float:
        return val * {"bits": 1.0, "Kbits": 1e3, "Mbits": 1e6, "Gbits": 1e9}.get(unit, 1.0)

    @staticmethod
    def _is_retryable_error(err: str) -> bool:
        """判断 iperf3 错误是否值得重试（跨海 UDP 偶发的控制连接 reset / 端口协商失败）。"""
        if not err:
            return False
        return any(k in err for k in (
            "unable to receive control message",
            "Connection reset",
            "Transport endpoint is not connected",
            "unable to read from stream socket",
            "unable to start listener",
        ))

    def _emit_retry_event(self, task_id: int, attempt: int, reason: str) -> None:
        """回传重试事件（前端显示「xx原因，重试第x次」）。

        存进 progress_json，用 retry=True 标记区分普通吞吐点，bitrate=0 占位。
        前端按 retry 标记单独提取显示，不画进吞吐曲线。"""
        try:
            self._post(f"/agent/iperf-tasks/{task_id}/progress",
                       ts=datetime.now(timezone.utc).isoformat(),
                       bitrate=0, role="client", retry=True,
                       attempt=attempt, reason=reason.strip()[-120:],
                       token=self.token)
        except Exception:
            pass  # 重试事件回传失败不致命

    @staticmethod
    def _norm_units(val, default_unit: str = "M") -> str | None:
        """Bare product values default to M; retain explicit CLI suffixes.

        iperf3 uses base 1000 for -b and base 1024 for -n. Converting 1G
        to 1000M changes a byte budget, so never normalize across suffixes.
        """
        if not val:
            return None
        val = str(val).strip().upper()
        m = re.match(r'^(\d+(?:\.\d+)?)\s*(K|M|G)?$', val)
        if not m:
            return val  # 非标准格式，原样交给 iperf3 报错
        return m.group(1) + (m.group(2) or default_unit)

    @staticmethod
    def _to_bytes(val: float, unit: str) -> float:
        return val * {"Bytes": 1.0, "KBytes": 1024.0, "MBytes": 1024.0**2, "GBytes": 1024.0**3}.get(unit, 1.0)

    @staticmethod
    def _parse_sender_line(line: str) -> dict:
        """解析 iperf3 sender 汇总行：总数据量 + 丢包/抖动(UDP) + 重传(TCP)。"""
        if not line:
            return {}
        r: dict = {}
        m = re.search(r'(\d+(?:\.\d+)?)\s*(GBytes|MBytes|KBytes|Bytes)', line)
        if m:
            r["total_bytes"] = Agent._to_bytes(float(m.group(1)), m.group(2))
        b = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
        if b:
            r["bitrate"] = Agent._to_bits(float(b.group(1)), b.group(2))
        if "ms" in line:
            # UDP：抖动 + 丢包率
            j = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if j:
                r["jitter_ms"] = float(j.group(1))
            packets = re.search(r'(\d+)\s*/\s*(\d+)\s*\(', line)
            if packets:
                lost, total = map(int, packets.groups())
                r["lost_pct"] = lost / total * 100.0 if total > 0 and lost <= total else None
        else:
            # TCP：重传次数（sender 前一个字段）
            rt = re.search(r'(\d+)\s+sender', line)
            if rt:
                r["retransmits"] = int(rt.group(1))
        return r

    @staticmethod
    def _parse_receiver_line(line: str) -> dict:
        """解析 iperf3 receiver 汇总行：接收端真实数据（接收数据量/接收速率/丢包/抖动）。"""
        if not line:
            return {}
        r: dict = {}
        m = re.search(r'(\d+(?:\.\d+)?)\s*(GBytes|MBytes|KBytes|Bytes)', line)
        if m:
            r["total_bytes"] = Agent._to_bytes(float(m.group(1)), m.group(2))
        b = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
        if b:
            r["recv_bitrate"] = Agent._to_bits(float(b.group(1)), b.group(2))
        if "ms" in line:
            j = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if j:
                r["jitter_ms"] = float(j.group(1))
            packets = re.search(r'(\d+)\s*/\s*(\d+)\s*\(', line)
            if packets:
                lost, total = map(int, packets.groups())
                r["lost_pct"] = lost / total * 100.0 if total > 0 and lost <= total else None
        return r

    def _wait_server_ready(self, server: str, port: int = 5201, timeout: float = 30.0, task_id: int | None = None) -> bool:
        """等 server 的 iperf3 端口就绪（TCP connect），最多 timeout 秒。server agent 可能还没起 -s。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if task_id is not None and self._throughput_terminal(task_id):
                return False
            try:
                with socket.create_connection((server, port), timeout=2):
                    return True
            except OSError:
                time.sleep(1)
        return False

    def _emit_stage_note(self, task_id: int, note: str) -> None:
        """回传阶段提示点（speedtest 无秒级数据，用 note 点让前端显示进行到哪一步）。"""
        try:
            self._post(f"/agent/iperf-tasks/{task_id}/progress", token=self.token,
                       ts=datetime.now(timezone.utc).isoformat(), bitrate=0,
                       role="client", note=note)
        except Exception:
            pass

    def _proxy_reachable(self, proxy_url: str) -> bool:
        """探测本机 socks5 代理端口是否可达（127.0.0.1:1080 之类）。"""
        try:
            host_port = proxy_url.split("://", 1)[1]
            host, _, port = host_port.rpartition(":")
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except Exception:
            return False

    def _run_speedtest_once(self, exe: str, task, proxy: str | None) -> dict:
        """speedtest-go JSON is final-only; drain both pipes while polling cancellation."""
        cmd = [exe, "--json"]
        if task.get("speedtest_server"):
            cmd += ["-s", str(task["speedtest_server"])]
        if proxy:
            cmd += ["--proxy", proxy]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        start = time.monotonic()
        next_note = 15
        try:
            while True:
                # communicate(timeout) drains BOTH pipes, unlike poll()+sleep().
                try:
                    out, err_out = proc.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self._throughput_terminal(task["id"]):
                    return {"error": "测速任务已结束或已取消"}
                elapsed = time.monotonic() - start
                if elapsed >= 90:
                    return {"error": "speedtest 超时（90s）"}
                if elapsed >= next_note:
                    self._emit_stage_note(task["id"], f"测速运行中（CLI 尚未返回阶段数据），已进行 {int(elapsed)}s")
                    next_note += 15
            if proc.returncode != 0:
                return {"error": f"speedtest 失败：{(err_out or out).strip()[-300:] or f'exit {proc.returncode}'}"}
            try:
                result = json.loads(out)
            except (json.JSONDecodeError, ValueError):
                return {"error": "speedtest 输出不是有效 JSON"}
            servers = result.get("servers") if isinstance(result, dict) else None
            if not isinstance(result, dict) or 'error' in result:
                return {"error": (result.get('error') if isinstance(result, dict) else None) or "speedtest 返回错误结果"}
            if not isinstance(servers, list) or not servers:
                return {"error": "speedtest 未返回有效服务器测速结果"}
            def valid_number(value):
                try:
                    return (not isinstance(value, bool) and isinstance(value, (float, int))
                            and math.isfinite(value) and value >= 0)
                except OverflowError:
                    return False

            def valid_duration(value):
                if isinstance(value, dict):
                    # Pinned Go struct: four non-omitempty *time.Duration
                    # fields, numeric nanoseconds or null. Never flatten it.
                    return (set(value) == {'ping', 'download', 'upload', 'total'}
                            and all(v is None or valid_number(v) for v in value.values()))
                # Preserve the pre-existing optional/scalar contract.
                return value is None or valid_number(value)

            if not valid_duration(result.get('test_duration')):
                return {"error": "speedtest 未返回有效 test_duration"}
            for server in servers:
                if not isinstance(server, dict) or 'error' in server:
                    return {"error": "speedtest 返回无效服务器结果"}
                for key in ("dl_speed", "ul_speed", "latency", "jitter"):
                    value = server.get(key)
                    if key not in ("dl_speed", "ul_speed") and value is None:
                        continue
                    if not valid_number(value):
                        return {"error": f"speedtest 未返回有效 {key}"}
                if not valid_duration(server.get('test_duration')):
                    return {"error": "speedtest 未返回有效 test_duration"}
                if task.get('speedtest_server') is not None and str(server.get('id')) != str(task['speedtest_server']):
                    return {"error": "speedtest 返回服务器与指定 ID 不一致"}
            return result
        finally:
            self._terminate_proc(proc)

    def _throughput_speedtest_exe(self) -> str | None:
        """One capability, one executable preference for inventory and execution."""
        local = os.path.join(self._agent_bin(), "speedtest-go")
        if os.path.isfile(local) and os.access(local, os.X_OK):
            return local
        return shutil.which("speedtest-go")

    def _run_speedtest(self, task) -> dict:
        """Only speedtest-go has this CLI/JSON contract. Never silently change path/vendor."""
        exe = self._throughput_speedtest_exe()
        if not exe:
            return {"error": "未安装 speedtest-go（其他同名测速工具不兼容此参数/结果契约）"}
        if self._throughput_terminal(task["id"]):
            return {"error": "测速任务已结束或已取消"}
        server = task.get("speedtest_server")
        self._emit_stage_note(task["id"], "选择测速服务器…" if not server else f"连接指定服务器 #{server}…")
        try:
            return self._run_speedtest_once(exe, task, None)
        except OSError as e:
            return {"error": f"无法执行 speedtest-go：{e}"}

    def _run_component_install(self, task):
        """代装组件：iperf3 用 sudo 包管理器；speedtest 下载 speedtest-go 单文件。"""
        tid = task["id"]
        comp = task["component"]
        try:
            if comp == "iperf3":
                err = self._install_iperf3()
            elif comp == "speedtest":
                err = self._install_speedtest_go()
            elif comp in ("ufw", "docker", "mtr"):
                err = self._install_pkg(comp)
            else:
                err = f"未知组件 {comp}"
            if err:
                self._post(f"/agent/component-installs/{tid}/result",
                           token=self.token, status="failed", error=err)
            else:
                self._post(f"/agent/component-installs/{tid}/result",
                           token=self.token, status="done")
        except Exception as e:
            self._post(f"/agent/component-installs/{tid}/result",
                       token=self.token, status="failed", error=str(e))

    def _install_iperf3(self) -> str | None:
        """用系统包管理器装 iperf3（需要 install.sh 给的 sudo 白名单）。返回错误信息或 None=成功。"""
        pkgs = [("apt-get", ["sudo", "-n", "apt-get", "install", "-y", "iperf3"]),
                ("dnf", ["sudo", "-n", "dnf", "install", "-y", "iperf3"]),
                ("yum", ["sudo", "-n", "yum", "install", "-y", "iperf3"]),
                ("apk", ["sudo", "-n", "apk", "add", "iperf3"]),
                ("pacman", ["sudo", "-n", "pacman", "-S", "--noconfirm", "iperf3"])]
        for mgr, cmd in pkgs:
            if shutil.which(mgr):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if out.returncode == 0 and shutil.which("iperf3"):
                        return None
                    return (out.stderr or out.stdout)[-500:] or "iperf3 安装失败"
                except Exception as e:
                    return str(e)
        return "未识别包管理器，无法代装 iperf3（请手动安装）"

    def _install_pkg(self, pkg: str) -> str | None:
        """通用包代装（ufw / docker / mtr）：sudo 白名单按「包管理器+包名」精确匹配，装不上报真实原因。"""
        # docker 在 Debian/Ubuntu 仓库里叫 docker.io；mtr 在 Debian/Ubuntu 叫 mtr-tiny
        names = {"docker": {"apt-get": "docker.io"}, "ufw": {}, "mtr": {"apt-get": "mtr-tiny"}}
        binname = pkg  # 装完验证用的二进制名
        pkgs = [("apt-get", ["sudo", "-n", "apt-get", "install", "-y"]),
                ("dnf", ["sudo", "-n", "dnf", "install", "-y"]),
                ("yum", ["sudo", "-n", "yum", "install", "-y"]),
                ("apk", ["sudo", "-n", "apk", "add"]),
                ("pacman", ["sudo", "-n", "pacman", "-S", "--noconfirm"])]
        last = None
        for mgr, base in pkgs:
            if not shutil.which(mgr):
                continue
            pkgname = names.get(pkg, {}).get(mgr, pkg)
            try:
                out = subprocess.run(base + [pkgname], capture_output=True, text=True, timeout=600)
                if out.returncode == 0 and shutil.which(binname):
                    if pkg == "docker":
                        # 装完顺手拉起守护进程（enable 失败不致命）
                        subprocess.run(["sudo", "-n", "systemctl", "enable", "--now", "docker"],
                                       capture_output=True, text=True, timeout=30)
                    return None
                last = (out.stderr or out.stdout)[-500:] or f"{pkg} 安装失败"
            except Exception as e:
                last = str(e)
        return last or f"未识别包管理器，无法代装 {pkg}（请手动安装）"

    def _install_speedtest_go(self) -> str | None:
        """下载 speedtest-go 到 agent 目录 bin/。先 GitHub 直链，被限流则从后端兜底。"""
        try:
            if platform.system() != "Linux":
                return "Windows 暂不支持代装 speedtest-go"
            arch = platform.machine() or "x86_64"
            arch_map = {"x86_64": "x86_64", "aarch64": "arm64", "armv7l": "armv7",
                        "armv6l": "armv6", "i686": "i386"}
            go_arch = arch_map.get(arch, "x86_64")
            dest_dir = self._agent_bin()
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "speedtest-go")

            # 1) GitHub 直链（资产名带版本号 speedtest-go_<tag>_Linux_<arch>.tar.gz）
            tag = "v1.7.11"  # 兜底
            try:
                r = subprocess.run(
                    ["curl", "-sSL", "-o", "/dev/null", "-w", "%{url_effective}",
                     "https://github.com/showwin/speedtest-go/releases/latest"],
                    capture_output=True, text=True, timeout=30)
                tail = (r.stdout or "").strip().rstrip("/").split("/")[-1]
                if tail.startswith("v"):
                    tag = tail
            except Exception:
                pass
            url = (f"https://github.com/showwin/speedtest-go/releases/download/{tag}/"
                   f"speedtest-go_{tag}_Linux_{go_arch}.tar.gz")
            tarball = os.path.join(dest_dir, "speedtest-go.tar.gz")
            try:
                # 带浏览器 UA：GitHub release 下载对 curl 默认 UA 会返回 404
                subprocess.run(["curl", "-sSL", "-A", "Mozilla/5.0", url, "-o", tarball],
                               check=True, timeout=120)
                # 有效 tar.gz 约 3MB；404 错误页只有几字节，据此判断下载是否真成功
                if os.path.getsize(tarball) > 100_000:
                    subprocess.run(["tar", "-xzf", tarball, "-C", dest_dir], check=True, timeout=60)
                    os.chmod(dest, 0o755)
            except Exception:
                pass
            try:
                os.remove(tarball)
            except OSError:
                pass

            # 2) 兜底：GitHub 直链被限流（下载到 404 页）时，从后端下载预置二进制
            if not (os.path.exists(dest) and os.path.getsize(dest) > 100_000):
                try:
                    # Keep credentials out of subprocess argv and reject redirects.
                    import urllib.request
                    class NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, *args, **kwargs):
                            raise ValueError('component redirect refused')
                    opener = urllib.request.build_opener(NoRedirect())
                    request = urllib.request.Request(self.url + '/agent/component/speedtest-go',
                                                     headers=self._auth_headers({}))
                    deadline = time.monotonic() + 120
                    with opener.open(request, timeout=30) as response, open(dest, 'wb') as output:
                        size = 0
                        while True:
                            chunk = response.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > 32 * 1024 * 1024 or time.monotonic() > deadline:
                                raise ValueError('component download limit')
                            output.write(chunk)
                    os.chmod(dest, 0o755)
                except Exception:
                    try:
                        os.remove(dest)
                    except OSError:
                        pass

            if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
                return None
            return "speedtest-go 下载失败（GitHub 直链被限流且后端无预置二进制），稍后重试"
        except Exception as e:
            return str(e)

    @staticmethod
    def _mtr_cmd(target: str, proto: str, params: dict | None = None) -> list[str]:
        """组 mtr 命令（--raw 流式输出，逐包解析做实时显示）。
        target 可带端口（host:port，tcp/udp 用）；icmp 忽略端口。
        params: count(-c 包数)/interval(-i 秒)/max_hops(-m)/psize(-s 字节)，后端已校验范围。"""
        p = params or {}
        host, port = target, None
        if ":" in target:
            h, _, ps = target.rpartition(":")
            if h and ps.isdigit():
                host, port = h, int(ps)
        cmd = ["mtr", "--raw", "-c", str(int(p.get("count", 10)))]
        if p.get("interval"):
            # mtr 限制：非 root 用户 -i 最小 1.0 秒，钳住防失败
            cmd += ["-i", str(max(float(p["interval"]), 1.0))]
        if p.get("max_hops"):
            cmd += ["-m", str(int(p["max_hops"]))]
        if p.get("psize"):
            cmd += ["-s", str(int(p["psize"]))]
        if proto in ("udp", "tcp"):
            cmd += ["--" + proto, "-P", str(port or 80)]
        cmd.append(host)
        return cmd

    def _mtr_stream(self, target: str, proto: str, params: dict | None = None,
                    live_cb=None) -> dict:
        """跑 mtr --raw 并流式聚合逐跳统计（x=发包 h=主机 d=DNS名 p=回包，rtt 单位 µs）。

        返回 mtr --json 兼容结构（hub 多带 name/last/stdev，前端终端式表格直接用）。
        live_cb(hubs) 每 ~2s 回调一次最新快照（工具页实时逐跳表）。"""
        p = params or {}
        count = int(p.get("count", 10))
        interval = float(p.get("interval", 1.0))
        cmd = self._mtr_cmd(target, proto, params)
        # 解析目标 IP：raw 流里目的跳被应答后，mtr 会往「目的+1」再发一个幻影探针
        # （同 IP、只发一次），后处理要靠它把幻影跳剔掉
        target_host = cmd[-1]
        target_ips: set[str] = set()
        try:
            for fam, _, _, _, sa in socket.getaddrinfo(target_host, None):
                if fam in (socket.AF_INET, socket.AF_INET6):
                    target_ips.add(str(sa[0]))
        except OSError:
            pass
        hops: dict[int, dict] = {}

        def snapshot() -> list[dict]:
            hubs = []
            for idx in sorted(hops):
                h = hops[idx]
                rtts = h["rtts"]
                snt = h["sent"]
                recv = len(rtts)
                hubs.append({
                    "count": idx + 1,
                    "host": h.get("name") or h.get("host") or "???",
                    "loss%": round((snt - recv) / snt * 100, 1) if snt else 0.0,
                    "snt": snt,
                    "last": round(rtts[-1], 3) if rtts else None,
                    "avg": round(sum(rtts) / recv, 3) if rtts else None,
                    "best": round(min(rtts), 3) if rtts else None,
                    "wrst": round(max(rtts), 3) if rtts else None,
                    "stdev": round(statistics.pstdev(rtts), 3) if recv > 1 else (0.0 if rtts else None),
                })
            return hubs

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)
        assert proc.stdout is not None
        deadline = time.time() + count * max(interval, 1.0) + 45
        last_emit = 0.0
        completed = False  # 正常跑完（raw 模式对目的跳有少打 x/p 行的怪癖，跑完才能按 count 校准 Snt）
        try:
            while True:
                if time.time() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd, int(deadline))
                # select 1s 轮询读行：readline 裸阻塞会让 deadline 失效
                r, _, _ = select.select([proc.stdout], [], [], 1.0)
                if not r:
                    if proc.poll() is not None:
                        completed = True  # 进程结束且管道已读空
                        break
                    continue
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        completed = True
                        break
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                kind = parts[0]
                try:
                    idx = int(parts[1])
                except ValueError:
                    continue
                h = hops.setdefault(idx, {"host": None, "name": None, "sent": 0, "rtts": []})
                if kind == "x":
                    h["sent"] += 1
                elif kind == "h" and len(parts) >= 3:
                    if not h["host"]:
                        h["host"] = parts[2]
                elif kind == "d" and len(parts) >= 3:
                    h["name"] = parts[2]
                elif kind == "p" and len(parts) >= 3:
                    try:
                        h["rtts"].append(int(parts[2]) / 1000.0)  # µs → ms
                    except ValueError:
                        pass
                now = time.time()
                if live_cb and now - last_emit >= 2.0:
                    last_emit = now
                    live_cb(snapshot())
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        if completed:
            # 剔幻影跳：raw 流里目的跳被应答后，mtr 会往「目的+1」多发一个探针
            # （同 IP、只发一次）。找到第一个主机==目标 IP（或解析名==目标）的跳，
            # 它后面的都是幻影，直接丢掉（幻影的回包不并入目的跳，否则 recv>snt）。
            if target_ips and hops:
                dest_idx = None
                for idx in sorted(hops):
                    h = hops[idx]
                    if (h.get("host") in target_ips) or (h.get("name") in target_ips) \
                            or (h.get("name") == target_host) or (h.get("host") == target_host):
                        dest_idx = idx
                        break
                if dest_idx is not None:
                    for idx in [i for i in hops if i > dest_idx]:
                        del hops[idx]
            # 正常跑完：每一跳的发包数都等于 count（对照 mtr -r 的 Snt 列语义）。
            # raw 流对目的跳只打 1 行 x/p（mtr 自身怪癖），不校准会把末跳 Snt 显示成 1。
            for h in hops.values():
                h["sent"] = count
        err = ""
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        hubs = snapshot()
        if proc.returncode not in (0, None) and not hubs:
            raise RuntimeError((err or f"mtr exit {proc.returncode}")[-500:])
        result = {"report": {"mtr": {"dst": target, "tos": 0,
                                     "psize": int(p.get("psize", 64)),
                                     "bitpattern": 0, "tests": count},
                             "hubs": hubs}}
        return result

    def _run_mtr(self, task):
        """执行 mtr（--raw 流式：边跑边回传实时快照，结束回传完整结果）。"""
        tid = task["id"]

        def live(hubs):
            try:
                self._post(f"/agent/mtr-tasks/{tid}/live",
                           json_body={"hops": hubs}, token=self.token)
            except Exception:
                pass  # 实时快照丢了不致命，下一秒还会再发

        try:
            result = self._mtr_stream(task["target"], task.get("protocol", "icmp"),
                                      task.get("params"), live_cb=live)
            self._post(f"/agent/mtr-tasks/{tid}/result",
                       json_body=result, token=self.token, status="done")
        except (subprocess.TimeoutExpired, FileNotFoundError, RuntimeError) as e:
            self._post(f"/agent/mtr-tasks/{tid}/result",
                       json_body={"error": str(e)}, token=self.token, status="failed")

    def _run_mtr_for_monitor(self, mid: int, m: dict, trigger: str):
        """监控项的定时/失败触发 MTR：单独线程跑（10 包 ~15s，不阻塞探测循环），结果走 mtr-report。"""
        target = f"{m['mtr_host']}:{m['mtr_port']}" if m.get("mtr_port") else m["mtr_host"]
        proto = m.get("mtr_proto", "icmp")

        def _job():
            try:
                if shutil.which("mtr") is None:
                    raise RuntimeError("未安装 MTR，请在探测节点下发 MTR 组件安装")
                result = self._mtr_stream(target, proto)
                self._post("/agent/mtr-report", json_body={
                    "monitor_id": mid, "trigger": trigger, "ok": True, "result_json": result},
                    token=self.token)
            except Exception as e:
                try:
                    self._post("/agent/mtr-report", json_body={
                        "monitor_id": mid, "trigger": trigger, "ok": False, "error": str(e)},
                        token=self.token)
                except Exception:
                    pass

        threading.Thread(target=_job, daemon=True).start()

    def _run_command(self, task):
        """执行命令，回传 stdout/stderr/exit_code。"""
        cid = task["id"]
        cmd = task["command"]
        # Per-command instance context (no configuration writes): use the trusted
        # __file__-relative selector shared by inventory/throughput. Never accept a
        # task-supplied path/env or inherit a stale selector; empty means unavailable.
        env = os.environ.copy()
        env["STELLA_SPEEDTEST_GO"] = self._throughput_speedtest_exe() or ""
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, env=env)
            self._post(f"/agent/commands/{cid}/result",
                       json_body={"status": "done", "stdout": out.stdout[-5000:],
                                  "stderr": out.stderr[-5000:], "exit_code": out.returncode})
        except subprocess.TimeoutExpired:
            self._post(f"/agent/commands/{cid}/result",
                       json_body={"status": "failed", "stdout": "",
                                  "stderr": "timeout", "exit_code": -1})

    # ── 网络操作任务（改 IP 回退 / 防火墙修改）──
    def _run_net_task(self, task):
        """执行网络操作任务。kind=ip_change 走回退流程；kind=firewall_scan 结构化采集防火墙。"""
        tid = task["id"]
        try:
            if task["kind"] == "ip_change":
                result = self._run_ip_change(task)
            elif task["kind"] == "firewall_scan":
                result = self._firewall_scan()
            elif task["kind"] == "docker_scan":
                result = self._docker_scan()
            elif task["kind"] == "docker_ctl":
                result = self._docker_ctl(task.get("payload") or {})
            elif task["kind"] == "pbr_scan":
                result = self._pbr_scan()
            elif task["kind"] == "docker_logs":
                result = self._docker_logs(task.get("payload") or {})
            elif task["kind"] == "docker_inspect":
                result = self._docker_inspect(task.get("payload") or {})
            else:
                result = {"error": f"未知任务类型 {task['kind']}"}
            if isinstance(result, dict) and result.get("error"):
                self._post(f"/agent/net-tasks/{tid}/result",
                           token=self.token, status="failed", json_body=result)
            else:
                self._post(f"/agent/net-tasks/{tid}/result",
                           token=self.token, status="done", json_body=result)
        except Exception as e:
            self._post(f"/agent/net-tasks/{tid}/result",
                       token=self.token, status="failed", json_body={"error": str(e)})

    # ── 防火墙结构化采集（一期：只读展示，不写规则）──
    def _firewall_scan(self) -> dict:
        """采集 ufw + iptables 结构化状态。ufw 用 status numbered/verbose，iptables 用 iptables-save 解析五表。"""
        return {"ufw": self._scan_ufw(), "iptables": self._scan_iptables()}

    @staticmethod
    def _sudo_run(cmd: list[str], timeout: int = 10) -> str | None:
        """sudo 只读命令：成功返回 stdout，失败返回 None（不抛异常，采集器各自降级）。"""
        try:
            r = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout if r.returncode == 0 else None
        except Exception:
            return None

    # ── Docker 面板：容器列表 + 启停重启 ──
    @staticmethod
    def _docker_run(args, timeout):
        # No PATH lookup, direct Docker fallback, or root bypass of validation.
        prefix = [] if hasattr(os, 'geteuid') and os.geteuid() == 0 else ['/usr/bin/sudo', '-n']
        return subprocess.run(prefix + ['/usr/local/libexec/stella-docker-helper'] + args,
                              capture_output=True, text=True, timeout=timeout, shell=False)

    def _docker_read(self, args, timeout):
        try:
            result = self._docker_run(args, timeout)
            return result.stdout if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _docker_scan(self) -> dict:
        """容器列表：docker ps -a --format json 逐行 JSON 解析。"""
        if not os.path.isfile('/usr/bin/docker'):
            return {"installed": False}
        out = self._docker_read(['ps'], timeout=20)
        if out is None:
            return {"installed": True, "error": "Docker helper 未部署或权限不足"}
        containers = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                containers.append({
                    "id": j.get("ID"), "name": j.get("Names"), "image": j.get("Image"),
                    "status": j.get("Status"), "state": j.get("State"),
                    "ports": j.get("Ports") or "", "created": j.get("CreatedAt") or j.get("RunningFor") or "",
                })
            except json.JSONDecodeError:
                continue
        return {"installed": True, "containers": containers}

    def _docker_ctl(self, payload: dict) -> dict:
        """容器启停重启。action 白名单 + 容器名校验（防注入）。"""
        action = payload.get("action")
        name = str(payload.get("container") or "")
        if action not in ("start", "stop", "restart"):
            return {"error": f"不支持的操作 {action}"}
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", name):
            return {"error": "容器名不合法"}
        try:
            r = self._docker_run([action, name], timeout=70)
            if r.returncode == 0:
                return {"ok": True, "action": action, "container": name}
            return {"error": (r.stderr or r.stdout).strip()[-300:]}
        except Exception as e:
            return {"error": str(e)}

    def _docker_logs(self, payload: dict) -> dict:
        """读容器最近日志（默认 150 行，上限 500）。strip ANSI 控制符。"""
        name = str(payload.get("container") or "")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", name):
            return {"error": "容器名不合法"}
        tail = max(1, min(int(payload.get("tail") or 150), 500))
        try:
            r = self._docker_run(['logs', name, str(tail)], timeout=70)
            text = (r.stdout or "") + (r.stderr or "")
            text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)  # 去 ANSI 颜色码
            return {"container": name, "lines": text[-20000:], "tail": tail}
        except Exception as e:
            return {"error": str(e)}

    def _docker_inspect(self, payload: dict) -> dict:
        """容器配置摘要：镜像/命令/环境变量/挂载/端口/重启策略/网络/创建时间（竖向展示用）。"""
        name = str(payload.get("container") or "")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", name):
            return {"error": "容器名不合法"}
        out = self._docker_read(['inspect', name], timeout=70)
        if out is None:
            return {"error": "docker inspect 失败（容器不存在或权限不足）"}
        try:
            info = json.loads(out)[0]
            cfg = info.get("Config") or {}
            host = info.get("HostConfig") or {}
            net = info.get("NetworkSettings") or {}
            mounts = [{"source": m.get("Source"), "target": m.get("Destination"),
                       "mode": m.get("Mode"), "rw": m.get("RW")} for m in (info.get("Mounts") or [])]
            ports = []
            for k, v in (net.get("Ports") or {}).items():
                for b in (v or []):
                    ports.append({"container": k, "host": f"{b.get('HostIp')}:{b.get('HostPort')}"})
            return {
                "container": name,
                "image": cfg.get("Image"),
                "created": info.get("Created"),
                "cmd": " ".join(cfg.get("Cmd") or []) or None,
                "entrypoint": " ".join(cfg.get("Entrypoint") or []) or None,
                "env": cfg.get("Env") or [],
                "mounts": mounts,
                "ports": ports,
                "restart_policy": (host.get("RestartPolicy") or {}).get("Name"),
                "networks": list((net.get("Networks") or {}).keys()),
                "state": (info.get("State") or {}).get("Status"),
            }
        except Exception as e:
            return {"error": f"inspect 解析失败: {e}"}

    def _pbr_scan(self) -> dict:
        """PBR 结构化采集：ip rule（优先级/标记→路由表）+ 各路由表路由 + mangle 打标链。全只读。"""
        rules = []
        try:
            r = subprocess.run(["ip", "rule"], capture_output=True, text=True, timeout=8)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                m = re.match(r"^(\d+):\s+(.+)$", line)
                if not m:
                    continue
                pref, rest = m.group(1), m.group(2)
                mark = re.search(r"fwmark (\S+)", rest)
                table = re.search(r"(?:lookup|table)\s+(\S+)", rest)
                src = re.search(r"from (\S+)", rest)
                rules.append({"pref": int(pref), "mark": mark.group(1) if mark else None,
                              "table": table.group(1) if table else None,
                              "from": src.group(1) if src and src.group(1) != "all" else None,
                              "raw": line})
        except Exception as e:
            rules = [{"error": str(e)}]

        tables: dict = {}
        try:
            r = subprocess.run(["ip", "route", "show", "table", "all"], capture_output=True, text=True, timeout=8)
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if not line or " linkdown" in line:
                    continue
                tm = re.search(r"\btable (\S+)", line)
                tname = tm.group(1) if tm else "main"
                dm = re.match(r"^(\S+)", line)
                via = re.search(r"\bvia (\S+)", line)
                dev = re.search(r"\bdev (\S+)", line)
                scope = re.search(r"\bscope (\S+)", line)
                tables.setdefault(tname, []).append({
                    "dst": dm.group(1) if dm else line,
                    "via": via.group(1) if via else None,
                    "dev": dev.group(1) if dev else None,
                    "scope": scope.group(1) if scope else None,
                    "raw": line})
        except Exception:
            pass

        marks = []
        raw = self._sudo_run(["iptables", "-t", "mangle", "-S"], timeout=10) or ""
        for line in raw.splitlines():
            if "MARK" not in line:
                continue
            chain = re.search(r"^-A (\S+)", line)
            uid = re.search(r"--uid-owner (\S+)", line)
            mark = re.search(r"--set-x?mark (\S+)", line)
            marks.append({"chain": chain.group(1) if chain else None,
                          "uid": uid.group(1) if uid else None,
                          "mark": mark.group(1) if mark else None,
                          "raw": line.strip()})
        return {"rules": rules, "tables": tables, "marks": marks}

    def _scan_ufw(self) -> dict:
        if not shutil.which("ufw"):
            return {"installed": False}
        verbose = self._sudo_run(["ufw", "status", "verbose"]) or ""
        numbered = self._sudo_run(["ufw", "status", "numbered"]) or ""
        active = "Status: active" in verbose
        # Default: deny (incoming), allow (outgoing), disabled (routed)
        m = re.search(r"^Default:\s*(.+)$", verbose, re.M)
        defaults = m.group(1).strip() if m else None
        m = re.search(r"^Logging:\s*(.+)$", verbose, re.M)
        logging = m.group(1).strip() if m else None
        # 规则行：[ 1] 22/tcp  ALLOW IN  Anywhere   /  [ 2] Anywhere  ALLOW OUT  22/tcp  (out)  / 尾部可能有 (v6)
        rules = []
        for line in numbered.splitlines():
            rm = re.match(r"^\[\s*(\d+)\]\s+(\S+(?:\s+\S+?)?)\s{2,}(ALLOW IN|ALLOW OUT|DENY IN|DENY OUT|LIMIT IN|LIMIT OUT|REJECT IN|REJECT OUT)\s{2,}(.+?)(\s+\(v6\))?\s*$", line)
            if rm:
                rules.append({
                    "num": int(rm.group(1)),
                    "to": rm.group(2).strip(),
                    "action": rm.group(3),
                    "from": rm.group(4).strip(),
                    "v6": bool(rm.group(5)),
                })
        return {"installed": True, "active": active, "defaults": defaults, "logging": logging,
                "rules": rules, "raw": (numbered or verbose)[-4000:]}

    def _scan_iptables(self) -> dict:
        if not shutil.which("iptables-save"):
            return {"installed": False}
        raw = self._sudo_run(["iptables-save"], timeout=15)
        if raw is None:
            return {"installed": True, "error": "iptables-save 需要 root（sudo 白名单未生效）"}
        tables: dict = {}
        cur: str | None = None
        for line in raw.splitlines():
            if line.startswith("*"):
                cur = line[1:].strip()
                tables[cur] = {"chains": [], "rules": []}
            elif line.startswith(":") and cur:
                # :INPUT ACCEPT [123:4567]  —— 链名 策略 [包:字节]；策略为 "-" 的是自定义链
                m = re.match(r"^:(\S+)\s+(\S+)\s+\[(\d+):(\d+)\]", line)
                if m:
                    tables[cur]["chains"].append({
                        "name": m.group(1), "policy": None if m.group(2) == "-" else m.group(2),
                        "packets": int(m.group(3)), "bytes": int(m.group(4)),
                    })
            elif line.startswith("-A") and cur:
                tables[cur]["rules"].append(self._parse_iptables_rule(line))
        return {"installed": True, "tables": tables, "raw": raw[-4000:]}

    @staticmethod
    def _parse_iptables_rule(line: str) -> dict:
        """把 -A 规则拆成列：链/目标/协议/端口/源/目的/入出接口。raw 保留完整原文。"""
        toks = line.split()
        d: dict = {"raw": line, "chain": toks[1] if len(toks) > 1 else None,
                   "target": None, "proto": None, "sport": None, "dport": None,
                   "source": None, "dest": None, "in_iface": None, "out_iface": None}
        i = 2
        while i < len(toks):
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if t == "-j": d["target"] = nxt; i += 1
            elif t == "-p": d["proto"] = nxt; i += 1
            elif t == "-s": d["source"] = nxt; i += 1
            elif t == "-d": d["dest"] = nxt; i += 1
            elif t == "-i": d["in_iface"] = nxt; i += 1
            elif t == "-o": d["out_iface"] = nxt; i += 1
            elif t == "--dport": d["dport"] = nxt; i += 1
            elif t == "--sport": d["sport"] = nxt; i += 1
            i += 1
        return d

    @staticmethod
    def _ping(target: str, count: int = 3, timeout: int = 2, iface: str = "") -> bool:
        # iface 非空时（改 IP 验证）用 sudo + 绑接口：agent 进程被 owner-mark 打标走 table 100/eno1，
        # 直连探测永远摸不到 wlan0 侧网关（8.20 改 wlan0 IP 误判失败实锤）；root 身份绕过 mark
        if iface:
            try:
                r = subprocess.run(["sudo", "-n", "ping", "-I", iface,
                                    "-c", str(count), "-W", str(timeout), target],
                                   capture_output=True, text=True, timeout=count * timeout + 5)
                if r.returncode == 0:
                    return True
                if "password" in (r.stderr or ""):
                    pass  # sudoers 未放行则落回普通 ping
                else:
                    return False  # sudo 通了但 ping 不通 = 真不通
            except Exception:
                pass
        try:
            r = subprocess.run(["ping", "-c", str(count), "-W", str(timeout), target],
                               capture_output=True, text=True, timeout=count * timeout + 5)
            return r.returncode == 0
        except Exception:
            return False

    def _detect_persist_backend(self) -> str | None:
        """检测 IP 持久化后端：netplan → NetworkManager → networkd（netplan 优先，其后端可能是 networkd）。"""
        try:
            import glob as _glob
            if shutil.which("netplan") and _glob.glob("/etc/netplan/*.yaml"):
                return "netplan"
            if shutil.which("nmcli"):
                r = subprocess.run(["nmcli", "-t", "-f", "DEVICE", "device"],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    return "networkmanager"
            if _glob.glob("/etc/systemd/network/*.network"):
                return "networkd"
        except Exception:
            pass
        return None

    def _persist_ip(self, iface: str, new_ip: str, prefix: int, gateway: str | None) -> bool:
        """写持久化配置（尽力而为，失败返回 False，不阻塞回退流程）。"""
        backend = self._detect_persist_backend()
        cidr = f"{new_ip}/{prefix}"
        try:
            if backend == "netplan":
                import glob as _glob
                for yf in _glob.glob("/etc/netplan/*.yaml"):
                    with open(yf) as f:
                        content = f.read()
                    if iface in content:
                        subprocess.run(["cp", yf, yf + ".bak"], timeout=5)
                        r = subprocess.run(["sudo", "netplan", "set", f"ethernets.{iface}.addresses=[\"{cidr}\"]"],
                                           capture_output=True, timeout=20)
                        if r.returncode == 0:
                            if gateway:
                                subprocess.run(["sudo", "netplan", "set", f"ethernets.{iface}.routes=[{{\"to\":\"default\",\"via\":\"{gateway}\"}}]"],
                                               capture_output=True, timeout=20)
                            subprocess.run(["sudo", "netplan", "apply"], capture_output=True, timeout=40)
                            return True
            elif backend == "networkmanager":
                # 找到 iface 对应的连接名，改 ipv4.addresses
                r = subprocess.run(["nmcli", "-t", "-f", "DEVICE,CONNECTION", "device", "status"],
                                   capture_output=True, text=True, timeout=10)
                conn = None
                for line in r.stdout.splitlines():
                    if line.startswith(iface + ":"):
                        conn = line.split(":", 1)[1].strip()
                        break
                if conn:
                    r = subprocess.run(["sudo", "nmcli", "con", "mod", conn, "ipv4.addresses", cidr,
                                        "ipv4.method", "manual"],
                                       capture_output=True, timeout=20)
                    if gateway:
                        subprocess.run(["sudo", "nmcli", "con", "mod", conn, "ipv4.gateway", gateway],
                                       capture_output=True, timeout=20)
                    subprocess.run(["sudo", "nmcli", "con", "up", conn], capture_output=True, timeout=40)
                    return True
            elif backend == "networkd":
                import glob as _glob
                for nf in _glob.glob(f"/etc/systemd/network/*{iface}*.network"):
                    with open(nf) as f:
                        content = f.read()
                    subprocess.run(["cp", nf, nf + ".bak"], timeout=5)
                    # 简化：写一个新的 .network 覆盖（Address= 行替换）
                    lines = []
                    for line in content.splitlines():
                        if line.startswith("Address="):
                            lines.append(f"Address={cidr}")
                        elif line.startswith("Gateway=") and gateway:
                            lines.append(f"Gateway={gateway}")
                        else:
                            lines.append(line)
                    with open(nf, "w") as f:
                        f.write("\n".join(lines) + "\n")
                    subprocess.run(["networkctl", "reload"], capture_output=True, timeout=20)
                    return True
        except Exception:
            pass
        return False

    def _run_ip_change(self, task) -> dict:
        """改 IP + ping 回退（本地自包含：改 IP 后即使断网，agent 常驻进程也能回退，不依赖中心下发）。

        流程：备份旧 IP → 临时 ip addr 改 → 等 3s → ping 测试 → 通写持久化 / 不通本地回退。"""
        payload = task["payload"] or {}
        iface = payload.get("iface")
        new_ip = payload.get("new_ip")
        prefix = payload.get("prefix", 24)
        gateway = payload.get("gateway")
        ping_target = payload.get("ping_target")
        if not iface or not new_ip or not ping_target:
            return {"error": "参数缺失（iface/new_ip/ping_target）"}

        old_ip = self._iface_ip(iface)
        if not old_ip:
            return {"error": f"无法获取 {iface} 当前 IP"}
        if old_ip == new_ip:
            return {"error": f"新 IP 与当前 IP 相同（{new_ip}）"}

        def _addr(action: str, ip: str):
            subprocess.run(["sudo", "ip", "addr", action, f"{ip}/{prefix}", "dev", iface],
                           capture_output=True, timeout=10)

        # 1. 临时改 IP
        try:
            _addr("del", old_ip)
            _addr("add", new_ip)
        except Exception as e:
            # 改失败，恢复旧 IP
            try:
                _addr("add", old_ip)
            except Exception:
                pass
            return {"error": f"临时改 IP 失败: {e}", "rolled_back": True, "old_ip": old_ip}

        # 2. 改网关（可选）
        if gateway:
            subprocess.run(["sudo", "ip", "route", "del", "default"], capture_output=True, timeout=10)
            subprocess.run(["sudo", "ip", "route", "add", "default", "via", gateway], capture_output=True, timeout=10)

        # 3. 等网络生效
        time.sleep(3)

        # 4. ping 测试（sudo+绑接口，绕 PBR 打标，探目标接口真实连通性）
        if self._ping(ping_target, iface=iface):
            # 通 → 写持久化
            persisted = self._persist_ip(iface, new_ip, prefix, gateway)
            return {"ok": True, "old_ip": old_ip, "new_ip": new_ip,
                    "persisted": persisted, "backend": self._detect_persist_backend()}
        else:
            # 不通 → 本地回退（不是中心下发，因可能断网）
            try:
                _addr("del", new_ip)
                _addr("add", old_ip)
            except Exception:
                pass
            if gateway:
                subprocess.run(["sudo", "ip", "route", "add", "default", "via", gateway], capture_output=True, timeout=10)
            return {"error": f"ping {ping_target} 不通，已回退旧 IP {old_ip}",
                    "rolled_back": True, "old_ip": old_ip, "new_ip": new_ip}

    # ── 拉配置 ──
    def refresh_config(self):
        from contextlib import nullcontext
        with getattr(self, '_channel_lock', nullcontext()):
            return self._refresh_config_current()

    def _refresh_config_current(self):
        """拉中心下发的配置：监控网卡 + 负责的监控项 + 版本号。"""
        try:
            self._assert_instance_identity()
            cfg = self._get("/agent/config", token=self.token)
            if getattr(self, '_installation', None) and cfg.get('node_id') != self._installation['node_id']:
                raise ValueError('config binding mismatch')
            self.monitored_ifaces = cfg.get("monitored_ifaces")
            self.monitors_version = cfg.get("monitors_version", 0)
            self._apply_monitors(cfg.get("monitors", []))
            self._entry_manifest = cfg.get("entry_monitoring") or {}
            if hasattr(self, '_channel_lock'):
                self._channel_apply(cfg.get('report_channel'))
        except Exception:
            pass

    def _apply_monitors(self, monitors: list):
        """diff 监控项：新增/更新 → 起定时器，删除 → 移除。"""
        now = time.time()
        new_ids = set()
        for m in monitors:
            mid = m["id"]
            new_ids.add(mid)
            cur = self.monitors.get(mid)
            if cur is None:
                self.monitors[mid] = {
                    "type": m["type"], "target": m["target"],
                    "interval": m["interval"], "timeout": m["timeout"],
                    "mtr_host": m.get("mtr_host", m["target"]),
                    "mtr_proto": m.get("mtr_proto", "icmp"),
                    "mtr_port": m.get("mtr_port"),
                    "next_run": now,  # 立即探测一次
                    "next_mtr": now + 60,  # 首次 MTR 错开 1 分钟（避免和首批探测挤一起）
                }
            else:
                cur["type"] = m["type"]
                cur["target"] = m["target"]
                cur["interval"] = m["interval"]
                cur["timeout"] = m["timeout"]
                cur["mtr_host"] = m.get("mtr_host", m["target"])
                cur["mtr_proto"] = m.get("mtr_proto", "icmp")
                cur["mtr_port"] = m.get("mtr_port")
        for mid in list(self.monitors.keys()):
            if mid not in new_ids:
                del self.monitors[mid]

    # ── 版本自更新 ──
    @staticmethod
    def _release_version(value):
        if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
            return None
        return tuple(int(part) for part in value.split('.'))

    def check_update(self):
        """Only strictly newer canonical numeric releases may replace this agent."""
        try:
            self._assert_instance_identity()
            info = self._get("/agent/version")
            latest = info.get("version", "")
            target = self._release_version(latest)
            current = self._release_version(AGENT_VERSION)
            if target is None or current is None or target <= current:
                return
            print(f"[update] 检测到新版本 {latest}（当前 {AGENT_VERSION}），自更新中", file=sys.stderr, flush=True)
            self._download_and_restart(info)
        except Exception as e:
            print(f"[update] 版本检查失败：{e!r}", file=sys.stderr)

    def _download_and_restart(self, info):
        """Serialize only this instance with its installer; preserve legacy updater."""
        binding = getattr(self, '_installation', None)
        if binding is None:
            return self._download_and_restart_owned(info)
        lock = handle = None
        try:
            if platform.system() == 'Windows':
                import ctypes
                from ctypes import wintypes
                api = ctypes.WinDLL('kernel32', use_last_error=True)
                api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                api.CreateMutexW.restype = wintypes.HANDLE
                api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                api.ReleaseMutex.argtypes = [wintypes.HANDLE]
                api.CloseHandle.argtypes = [wintypes.HANDLE]
                handle = api.CreateMutexW(None, False, 'Global\\StellaInstall-' + binding['instance_id'])
                if not handle or api.WaitForSingleObject(handle, 0) != 0:
                    if handle: api.CloseHandle(handle)
                    handle = None
                    return
            else:
                import fcntl
                from pathlib import Path
                path = Path(__file__).with_name('.update.lock')
                lock = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._download_and_restart_owned(info)
        except (OSError, ValueError):
            return  # installer/update in flight; existing process remains intact
        finally:
            if lock is not None: os.close(lock)
            if handle is not None:
                api.ReleaseMutex(handle); api.CloseHandle(handle)

    def _download_and_restart_owned(self, info):
        import ast
        me = os.path.abspath(__file__)
        try:
            target = info.get('version')
            version = self._release_version(target)
            current = self._release_version(AGENT_VERSION)
            digest = info.get('sha256')
            size = info.get('size')
            limit = 2 * 1024 * 1024
            if (version is None or current is None or version <= current
                    or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                    or type(size) is not int or not 0 < size <= limit):
                raise ValueError('invalid or missing update manifest')
            headers = {'Authorization': 'Bearer ' + self.token, 'Accept-Encoding': 'identity'}
            body = bytearray()
            deadline = time.monotonic() + 30

            def append(chunk):
                if time.monotonic() > deadline or len(body) + len(chunk) > size:
                    raise ValueError('update download budget exceeded')
                body.extend(chunk)

            if httpx:
                with httpx.stream('GET', self.url + '/agent/script', headers=headers,
                                  timeout=30, follow_redirects=False, verify=self._ssl_context, trust_env=False) as resp:
                    resp.raise_for_status()
                    if resp.status_code != 200:
                        raise ValueError('unexpected update HTTP status')
                    if resp.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                        raise ValueError('encoded update response refused')
                    for chunk in resp.iter_raw(chunk_size=65536):
                        append(chunk)
            else:
                import urllib.request
                request = urllib.request.Request(self.url + '/agent/script', headers=headers)
                with _agent_urlopen(request, timeout=30) as resp:
                    if resp.status != 200:
                        raise ValueError('unexpected update HTTP status')
                    if resp.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                        raise ValueError('encoded update response refused')
                    while True:
                        chunk = resp.read1(min(65536, size - len(body) + 1))
                        if not chunk:
                            break
                        append(chunk)
            if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
                raise ValueError('update size/hash mismatch')
            code = bytes(body).decode('utf-8')
            tree = ast.parse(code, filename=me)
            compile(tree, me, 'exec')
            declarations = [node.value.value for node in tree.body
                            if isinstance(node, ast.Assign) and len(node.targets) == 1
                            and isinstance(node.targets[0], ast.Name)
                            and node.targets[0].id == 'AGENT_VERSION'
                            and isinstance(node.value, ast.Constant)]
            if declarations != [target]:
                raise ValueError('update target version mismatch')
        except Exception as e:
            print(f"[update] 下载校验失败：{type(e).__name__}", file=sys.stderr)
            return
        # Load with the same interpreter before replacing, then load the actual
        # installed path before exec. Never ask systemd to kill the live process.
        import stat
        import tempfile
        tmp = backup = None
        installed = False
        try:
            original = os.lstat(me)
            if not stat.S_ISREG(original.st_mode):
                raise ValueError('update target must be a regular file')
            fd, tmp = tempfile.mkstemp(prefix='.stella-update-', suffix='.py', dir=os.path.dirname(me))
            with os.fdopen(fd, 'wb') as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, stat.S_IMODE(original.st_mode))
            if hasattr(os, 'chown'):
                os.chown(tmp, original.st_uid, original.st_gid)
            self._validate_update_load(tmp, target)
            fd, backup = tempfile.mkstemp(prefix='.stella-rollback-', suffix='.py', dir=os.path.dirname(me))
            os.close(fd)
            shutil.copy2(me, backup)
            if hasattr(os, 'chown'):
                os.chown(backup, original.st_uid, original.st_gid)
            with open(backup, 'r+b') as f:
                os.fsync(f.fileno())
            # Backup reads may legitimately advance atime on relatime mounts.
            # Keep inode/ownership/mode/size and nanosecond edit timestamps pinned.
            stable_fields = ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid',
                             'st_gid', 'st_mtime_ns', 'st_ctime_ns')
            current_stat = os.lstat(me)
            if any(getattr(current_stat, field) != getattr(original, field)
                   for field in stable_fields):
                raise ValueError('update target changed during staging')
            os.replace(tmp, me)
            tmp = None
            installed = True
            with open(me, 'rb') as f:
                if hashlib.sha256(f.read(limit + 1)).hexdigest() != digest:
                    raise ValueError('installed update hash mismatch')
            self._validate_update_load(me, target)
            print('[update] 已验证新脚本，exec 重启（旧脚本备份：' + backup + '）', file=sys.stderr, flush=True)
            os.execv(sys.executable, [sys.executable, me] + sys.argv[1:])
            installed = False  # exec never returns; lets test doubles clean up.
        except Exception as e:
            if installed and backup is not None:
                try:
                    os.replace(backup, me)
                    backup = None
                    installed = False
                except OSError:
                    # Keep the recovery copy if the filesystem will not restore.
                    print('[update] 回退失败，旧脚本保留于：' + str(backup), file=sys.stderr, flush=True)
            print(f'[update] 安装失败，原进程继续运行：{type(e).__name__}', file=sys.stderr)
        finally:
            for path in (tmp, backup if not installed else None):
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    @staticmethod
    def _validate_update_load(path, target):
        # run_name is not __main__: importing must not start the agent. This is
        # a load/entrypoint check, not a sandbox or a runtime health guarantee.
        probe = ("import os,runpy,sys; sys.path[0]=os.path.dirname(sys.argv[1]); "
                 "m=runpy.run_path(sys.argv[1],run_name='stella_update_probe'); "
                 "sys.exit(73 if m.get('AGENT_VERSION')==sys.argv[2] and "
                 "callable(m.get('Agent')) and callable(m.get('main')) else 1)")
        result = subprocess.run([sys.executable, '-B', '-c', probe, path, target],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10)
        if result.returncode != 73:
            raise ValueError('update load/entrypoint validation failed')

    # ── 主循环 ──
    def run(self, stop_event=None):
        self._assert_instance_identity()  # no heartbeat/control before owning identity
        print(f"[stella-agent {AGENT_VERSION}] 启动，中心 {self.url}", file=sys.stderr)
        # 首次上报网卡清单（含默认出口）+ 存储视图 + 拉配置
        try:
            self._post("/agent/report", json_body={
                "metrics": [], "sys_metrics": [],
                "interfaces": self.list_interfaces(),
                "agent_version": AGENT_VERSION,
                "storage": self._storage_info(),
                "components": self._check_components(),
                "os_info": self._os_info(),
                "public_ip_info": self._probe_public_ip(),
            }, token=self.token)
        except Exception as e:
            print(f"[warn] 首次上报失败：{e}", file=sys.stderr)
        self.refresh_config()

        stop_event = stop_event or threading.Event()
        scheduler = _BackgroundScheduler(max_workers=2)
        map_scheduler = _BackgroundScheduler(max_workers=1)
        channel_scheduler = _BackgroundScheduler(max_workers=1)
        last_map = None
        last_sys = 0
        last_refresh = 0
        last_update = 0
        last_report = 0
        try:
            while not stop_event.is_set():
                try:
                    now = time.time()

                    map_now = time.monotonic()
                    channel_scheduler.submit('channels', self._channel_tick)
                    self._file_tick()  # nonblocking; all file/network work is owned child IO
                    if last_map is None or map_now - last_map >= 60:
                        if map_scheduler.submit('map', self._report_map_snapshot):
                            last_map = map_now

                    # 流量：5s 采样上报（主循环 1s 一圈，流量上报仍保持 5s 粒度）
                    if now - last_report >= REPORT_INTERVAL:
                        metrics = self.collect_metrics()
                        sys_metrics = []
                        if now - last_sys >= SYS_INTERVAL:
                            sys_metrics = [self.collect_sys()]
                            last_sys = now
                        if metrics or sys_metrics:
                            self.report(metrics, sys_metrics)
                        last_report = now

                    # 配置：60s 拉一次
                    if now - last_refresh >= 60:
                        self.refresh_config()
                        last_refresh = now

                    # 版本自更新：每 5 分钟检查一次
                    if now - last_update >= UPDATE_CHECK_INTERVAL and scheduler.idle():
                        self.check_update()
                        last_update = now

                    # 监控项探测：到点的探测并上报
                    scheduler.submit("probes", self.run_due_probes)

                    # 任务：1s 轮询（打流领取要快）
                    scheduler.submit("tasks", self.poll_and_execute)

                except Exception as e:
                    print(f"[error] 主循环异常：{e}", file=sys.stderr)

                stop_event.wait(POLL_INTERVAL)
        finally:
            scheduler.close()
            map_scheduler.close()
            channel_scheduler.close()
            if hasattr(self, '_file_supervisor'):
                self._file_supervisor.close()
            self._hardware_scheduler.close()
            self._storage_scheduler.close()


def main():
    if len(sys.argv) == 4 and sys.argv[1] in ('--file-prepare', '--file-child'):
        _file_internal_main()
        return
    parser = argparse.ArgumentParser(description="Stella Agent")
    parser.add_argument("--url", default=os.environ.get("STELLA_URL", "http://127.0.0.1:12031"))
    parser.add_argument("--token", default=os.environ.get("STELLA_TOKEN", ""))
    args = parser.parse_args()

    if not args.token:
        print("错误：缺少 --token（或 STELLA_TOKEN 环境变量）", file=sys.stderr)
        sys.exit(1)

    Agent(args.url, args.token).run()


if __name__ == "__main__":
    main()
