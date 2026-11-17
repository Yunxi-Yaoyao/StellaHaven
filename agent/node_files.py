"""Dedicated Linux file protocol. No shell, privilege escalation or implicit roots.

This optional module must be installed beside stella_agent.py. Roots are a LOCAL
operator grant (STELLA_FILE_ROOTS JSON); the center cannot grant filesystem paths.
"""
import contextlib
import errno
import hashlib
import json
import os
import re
import stat
import sys

FILE_MODULE_VERSION = '1.0.0'
FILE_PROTOCOL = 1

PREVIEW_LIMIT = 256 * 1024
TRANSFER_LIMIT = 32 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
DIRECTORY_LIMIT = 2000


class FileError(ValueError):
    pass


def parts(path, empty=True):
    if not isinstance(path, str) or len(path.encode('utf-8')) > 4096 or '\\' in path or '\x00' in path:
        raise FileError('invalid_path')
    if path == '' and empty:
        return []
    result = path.split('/')
    if len(result) > 64 or any(x in ('', '.', '..') or len(x.encode()) > 255 for x in result):
        raise FileError('invalid_path')
    return result


class Sandbox:
    def __init__(self, allowed=None):
        allowed = {} if allowed is None else allowed
        if not isinstance(allowed, dict) or len(allowed) > 32:
            raise FileError('invalid_local_policy')
        self.allowed = {}
        for key, value in allowed.items():
            if (not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', key)
                    or not isinstance(value, dict) or not {'path'} <= set(value) <= {'path', 'write'}
                    or not isinstance(value['path'], str) or not value['path'].startswith('/')
                    or ('write' in value and type(value['write']) is not bool)):
                raise FileError('invalid_local_policy')
            try:
                if value['path'] != '/':
                    parts(value['path'][1:], empty=False)
            except FileError:
                raise FileError('invalid_local_policy') from None
            self.allowed[key] = {'path': value['path'], 'write': value.get('write') is True}

    @classmethod
    def from_env(cls):
        value = os.environ.get('STELLA_FILE_ROOTS', '{}')
        if len(value.encode('utf-8')) > 128 * 1024:
            raise FileError('invalid_local_policy')
        try:
            return cls(json.loads(value))
        except (ValueError, TypeError):
            raise FileError('invalid_local_policy') from None

    def roots(self):
        # NTFS/reparse-point and ACL equivalence are not implemented. Never
        # advertise configured paths as usable on Windows or other platforms.
        if sys.platform != 'linux':
            return []
        return [{'id': key, 'write': value.get('write') is True} for key, value in self.allowed.items()]

    @contextlib.contextmanager
    def directory(self, root, path=''):
        if sys.platform != 'linux' or os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW') or root not in self.allowed:
            raise FileError('root_denied')
        absolute = self.allowed[root]['path']
        if not isinstance(absolute, str) or not absolute.startswith('/'):
            raise FileError('invalid_root')
        # Resolve every root ancestor too: never realpath then reopen a raced path.
        # Only an explicitly configured / has no root ancestors to resolve.
        ancestors = [] if absolute == '/' else parts(absolute[1:], empty=False)
        fd = None
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            for name in ancestors + parts(path):
                nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            yield fd
        except OSError as exc:
            raise FileError('permission_denied' if exc.errno in (errno.EACCES, errno.EPERM) else 'path_denied') from exc
        finally:
            if fd is not None:
                os.close(fd)

    @contextlib.contextmanager
    def regular(self, root, path):
        names = parts(path, empty=False)
        with self.directory(root, '/'.join(names[:-1])) as parent:
            fd = None
            try:
                fd = os.open(names[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise FileError('regular_file_required')
                yield fd, info
            except OSError as exc:
                raise FileError('permission_denied' if exc.errno in (errno.EACCES, errno.EPERM) else 'path_denied') from exc
            finally:
                if fd is not None:
                    os.close(fd)

    def stream(self, root, path, active=lambda: True):
        with self.regular(root, path) as (fd, info):
            if info.st_size > TRANSFER_LIMIT:
                raise FileError('transfer_limit')
            total = 0
            while True:
                if not active():
                    raise FileError('inactive_request')
                chunk = os.read(fd, CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > TRANSFER_LIMIT:
                    raise FileError('transfer_limit')
                yield chunk
            after = os.fstat(fd)
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise FileError('file_changed')

    def writable(self, root):
        if root not in self.allowed or self.allowed[root].get('write') is not True:
            raise FileError('read_only_root')

    @staticmethod
    def no_replace(source_fd, source, dest_fd, dest):
        # Linux renameat2 is atomic and refuses files AND directories at target.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if not hasattr(libc, 'renameat2'):
            raise FileError('atomic_rename_unavailable')
        result = libc.renameat2(source_fd, os.fsencode(source), dest_fd, os.fsencode(dest), 1)
        if result:
            error = ctypes.get_errno()
            if error == 17:
                raise FileError('destination_exists')
            raise FileError('rename_failed')

    @staticmethod
    def no_acl(fd, attribute='system.posix_acl_access'):
        # Absence is the only supported ACL state. ENOTSUP/EPERM/IO errors
        # cannot establish equivalence and must never silently drop a deny.
        try:
            os.getxattr(fd, attribute)
        except OSError as exc:
            if exc.errno == errno.ENODATA:
                return
            raise FileError('metadata_preservation_denied') from exc
        except AttributeError as exc:
            raise FileError('metadata_preservation_denied') from exc
        raise FileError('metadata_preservation_denied')

    @classmethod
    def edit_metadata(cls, fd, original):
        info = os.fstat(fd)
        if (info.st_mode, info.st_uid, info.st_gid) != (original.st_mode, original.st_uid, original.st_gid) or info.st_nlink != 1:
            raise FileError('metadata_preservation_denied')
        cls.no_acl(fd)

    def write_stream(self, request, chunks, active=lambda: True, commit=None):
        from uuid import uuid4
        root, path, op = request['root'], request['path'], request['op']
        self.writable(root)
        names = parts(path, empty=False)
        size = request['size']
        limit = PREVIEW_LIMIT if op == 'edit' else TRANSFER_LIMIT
        if not isinstance(size, int) or size < 0 or size > limit:
            raise FileError('transfer_limit')
        with self.directory(root, '/'.join(names[:-1])) as parent:
            original, original_stat = None, None
            mode = 0o600
            if op == 'edit':
                with self.regular(root, path) as (fd, info):
                    before = os.read(fd, PREVIEW_LIMIT + 1)
                    if len(before) > PREVIEW_LIMIT or hashlib.sha256(before).hexdigest() != request.get('etag'):
                        raise FileError('cas_conflict')
                    if info.st_uid != os.geteuid() or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) & 0o7000:
                        raise FileError('metadata_preservation_denied')
                    self.edit_metadata(fd, info)
                    self.no_acl(parent, 'system.posix_acl_default')
                    original_stat = info
                    original = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    mode = stat.S_IMODE(info.st_mode)
            name = '.stella-file-' + uuid4().hex
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
            try:
                if original_stat:
                    self.edit_metadata(fd, original_stat)
                    self.no_acl(parent, 'system.posix_acl_default')
                total, sha = 0, hashlib.sha256()
                for chunk in chunks:
                    if not active():
                        raise FileError('inactive_request')
                    total += len(chunk)
                    if len(chunk) > CHUNK_SIZE or total > size:
                        raise FileError('transfer_limit')
                    sha.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        view = view[os.write(fd, view):]
                if total != size or sha.hexdigest() != request['sha256']:
                    raise FileError('transfer_mismatch')
                os.fsync(fd)
                if not active() or (commit is not None and not commit()):
                    raise FileError('inactive_request')
                if op == 'edit':
                    # Re-read by no-follow dirfd immediately before atomic replace.
                    with self.regular(root, path) as (oldfd, now):
                        current = (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns, now.st_ctime_ns)
                        if current != original or hashlib.sha256(os.read(oldfd, PREVIEW_LIMIT + 1)).hexdigest() != request['etag']:
                            raise FileError('cas_conflict')
                        self.edit_metadata(oldfd, original_stat)
                    self.edit_metadata(fd, original_stat)
                    self.no_acl(parent, 'system.posix_acl_default')
                    os.replace(name, names[-1], src_dir_fd=parent, dst_dir_fd=parent)
                else:
                    # Link-then-unlink provides atomic no-clobber creation.
                    try:
                        os.link(name, names[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    except FileExistsError:
                        raise FileError('destination_exists') from None
                os.fsync(parent)
            finally:
                os.close(fd)
                try:
                    os.unlink(name, dir_fd=parent)
                except FileNotFoundError:
                    pass
        return {'path': path, 'size': size, 'sha256': request['sha256']}

    def execute(self, request, active=lambda: True, commit=None):
        op, root, path = request['op'], request['root'], request.get('path', '')
        if not active():
            raise FileError('inactive_request')
        if op in ('create', 'mkdir', 'copy', 'move', 'rename'):
            self.writable(root)
            names = parts(path, empty=False)
            if op == 'create':
                return self.write_stream({**request, 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}, [], active, commit)
            if op == 'mkdir':
                with self.directory(root, '/'.join(names[:-1])) as parent:
                    if not active() or (commit is not None and not commit()):
                        raise FileError('inactive_request')
                    try:
                        os.mkdir(names[-1], mode=0o700, dir_fd=parent)
                    except FileExistsError:
                        raise FileError('destination_exists') from None
                    os.fsync(parent)
                return {'path': path}
            dest = request.get('destination', '')
            target = parts(dest, empty=False)
            if op == 'copy':
                with self.regular(root, path) as (fd, info):
                    if info.st_size > TRANSFER_LIMIT:
                        raise FileError('transfer_limit')
                    sha, hashed = hashlib.sha256(), 0
                    for chunk in iter(lambda: os.read(fd, CHUNK_SIZE), b''):
                        hashed += len(chunk)
                        if hashed > TRANSFER_LIMIT:
                            raise FileError('transfer_limit')
                        if not active():
                            raise FileError('inactive_request')
                        sha.update(chunk)
                return self.write_stream({**request, 'op': 'upload', 'path': dest, 'size': info.st_size, 'sha256': sha.hexdigest()}, self.stream(root, path, active), active, commit)
            with self.directory(root, '/'.join(names[:-1])) as source_fd, self.directory(root, '/'.join(target[:-1])) as dest_fd:
                info = os.stat(names[-1], dir_fd=source_fd, follow_symlinks=False)
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                    raise FileError('regular_file_required')
                if not active() or (commit is not None and not commit()):
                    raise FileError('inactive_request')
                now = os.stat(names[-1], dir_fd=source_fd, follow_symlinks=False)
                if (info.st_ino, info.st_dev, info.st_ctime_ns) != (now.st_ino, now.st_dev, now.st_ctime_ns):
                    raise FileError('file_changed')
                self.no_replace(source_fd, names[-1], dest_fd, target[-1])
                os.fsync(source_fd)
                os.fsync(dest_fd)
            return {'path': dest}
        if op == 'list':
            limit = min(DIRECTORY_LIMIT, max(1, int(request.get('limit', DIRECTORY_LIMIT))))
            entries = []
            with self.directory(root, path) as fd:
                with os.scandir(fd) as it:
                    for index, entry in enumerate(it):
                        if index >= limit:
                            raise FileError('directory_limit')
                        if entry.name.startswith('.') and not request.get('hidden', False):
                            continue
                        info = entry.stat(follow_symlinks=False)
                        kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'link' if stat.S_ISLNK(info.st_mode) else 'special'
                        entries.append({'name': entry.name, 'kind': kind, 'size': info.st_size, 'mtime': info.st_mtime, 'mode': format(stat.S_IMODE(info.st_mode), '04o'), 'uid': info.st_uid, 'gid': info.st_gid})
            sort = request.get('sort', 'name')
            if sort not in ('name', 'size', 'mtime'):
                raise FileError('invalid_sort')
            entries.sort(key=lambda x: (x[sort], x['name']), reverse=bool(request.get('descending', False)))
            entries.sort(key=lambda x: x['kind'] != 'directory')
            return {'entries': entries, 'path': path, 'root': root}
        if op == 'preview':
            with self.regular(root, path) as (fd, info):
                if info.st_size > PREVIEW_LIMIT:
                    raise FileError('preview_limit')
                data = os.read(fd, PREVIEW_LIMIT + 1)
                if len(data) > PREVIEW_LIMIT:
                    raise FileError('preview_limit')
                try:
                    text = data.decode('utf-8')
                    if '\x00' in text:
                        raise ValueError()
                except (UnicodeError, ValueError):
                    raise FileError('binary_or_encoding') from None
                return {'text': text, 'etag': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        raise FileError('unsupported_operation')


class FileWorker:
    """A single file-only worker, independently schedulable from monitor probes.

    Claim once, execute once, report once. An ambiguous ACK is queried on the
    next tick, never re-executed. Server leases are node-bound and durable.
    """
    def __init__(self, url, token, sandbox=None, *, client=None):
        if client is None:
            import httpx
            client = httpx.Client(base_url=url.rstrip('/'), headers={'Authorization': 'Bearer ' + token}, timeout=10, trust_env=False)
        self.client = client
        self.sandbox = sandbox if sandbox is not None else Sandbox.from_env()
        self.pending_ack = None

    def tick(self):
        if self.pending_ack:
            job = self.pending_ack
            state = self.client.get('/agent/files/requests/' + job['id'], params={'lease': job['lease']})
            state.raise_for_status()
            # A running/unknown request needs operator read-only reconciliation;
            # do not rerun the operation or manufacture a successful ACK.
            if state.json()['state'] in ('done', 'failed', 'cancelled', 'unknown'):
                self.pending_ack = None
            return
        hello = {'protocol': 1, 'roots': {x['id']: x['write'] for x in self.sandbox.roots()}}
        response = self.client.post('/agent/files/claim', json=hello)
        response.raise_for_status()
        job = response.json()
        if not job:
            return
        self.pending_ack = job
        params = {'lease': job['lease']}
        def active():
            r = self.client.get('/agent/files/requests/' + job['id'], params=params)
            r.raise_for_status()
            return r.json()['state'] in ('running', 'committing')
        admitted = False
        def commit():
            nonlocal admitted
            r = self.client.post('/agent/files/requests/' + job['id'] + '/admit', params=params)
            r.raise_for_status()
            admitted = r.json()['state'] == 'committing'
            return admitted
        try:
            req = job['request']
            if req.get('protocol') != 1:
                raise FileError('protocol_mismatch')
            if req['op'] == 'download':
                sha, offset = hashlib.sha256(), 0
                for chunk in self.sandbox.stream(req['root'], req['path'], active):
                    r = self.client.put('/agent/files/requests/' + job['id'] + '/bytes', params={**params, 'offset': offset}, content=chunk, headers={'Content-Type': 'application/octet-stream'})
                    r.raise_for_status()
                    sha.update(chunk)
                    offset += len(chunk)
                    if r.json()['offset'] != offset:
                        raise FileError('offset_conflict')
                result = {'size': offset, 'sha256': sha.hexdigest()}
            elif req['op'] == 'preview':
                preview = self.sandbox.execute(req, active)
                data = preview.pop('text').encode('utf-8')
                for offset in range(0, len(data), CHUNK_SIZE):
                    if not active():
                        raise FileError('inactive_request')
                    r = self.client.put('/agent/files/requests/' + job['id'] + '/bytes', params={**params, 'offset': offset}, content=data[offset:offset+CHUNK_SIZE], headers={'Content-Type': 'application/octet-stream'})
                    r.raise_for_status()
                result = preview
            elif req['op'] in ('upload', 'edit'):
                with self.client.stream('GET', '/agent/files/requests/' + job['id'] + '/upload', params=params) as source:
                    source.raise_for_status()
                    result = self.sandbox.write_stream(req, source.iter_bytes(CHUNK_SIZE), active, commit)
            else:
                result = self.sandbox.execute(req, active, commit)
            payload = {'lease': job['lease'], 'result': result}
        except (FileError, OSError) as exc:
            known = isinstance(exc, FileError) and str(exc) in ('cas_conflict', 'destination_exists', 'metadata_preservation_denied', 'rename_failed', 'file_changed')
            error = 'commit_uncertain' if admitted and not known else str(exc) if isinstance(exc, FileError) else 'filesystem_error'
            payload = {'lease': job['lease'], 'error': error}
        response = self.client.post('/agent/files/requests/' + job['id'] + '/result', json=payload)
        response.raise_for_status()
        self.pending_ack = None
