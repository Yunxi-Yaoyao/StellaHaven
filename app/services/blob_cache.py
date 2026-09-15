"""Bounded, process-shared immutable cache (Linux local filesystem only).

STELLA_BLOB_CACHE_MAX_BYTES defaults to 256 MiB of allocated payload blocks,
including fills and pinned downloads, excluding directory/empty lock metadata.
STELLA_BLOB_CACHE_TTL_SECONDS defaults to one day; idle entries and abandoned
fills are reclaimed on the next access. Only our flat filename namespace is
managed; symlinks, subdirectories and unrelated filenames are never removed.
"""
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import time

import anyio
from fastapi import HTTPException
from starlette.responses import FileResponse

ENTRY = re.compile(r'[0-9a-f]{64}\.bin')
FILL = re.compile(r'\.fill-[a-z0-9_]{8}')


def unavailable():
    return HTTPException(503, 'Blob cache capacity unavailable', headers={'Retry-After': '5', 'Cache-Control': 'no-store'})


class Lease:
    def __init__(self, path, fd):
        self.path, self.fd = path, fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __del__(self):
        self.close()


class CachedFileResponse(FileResponse):
    def __init__(self, lease, **kwargs):
        self.lease = lease
        super().__init__(lease.path, stat_result=os.fstat(lease.fd), **kwargs)

    async def __call__(self, scope, receive, send):
        # A server's pathsend can outlive this call, so use regular file reads.
        scope = dict(scope, extensions={k:v for k,v in scope.get('extensions', {}).items() if k != 'http.response.pathsend'})
        async def guarded_send(message):
            if message['type'] == 'http.response.start' and 'cache-control' in self.headers:
                message = dict(message, headers=[(k,v) for k,v in message['headers'] if k.lower() != b'cache-control'] + [(b'cache-control', self.headers['cache-control'].encode())])
            await send(message)
        try:
            async with anyio.create_task_group() as group:
                async def disconnected():
                    while True:
                        if (await receive())['type'] == 'http.disconnect':
                            group.cancel_scope.cancel()
                            return
                group.start_soon(disconnected)
                await super().__call__(scope, receive, guarded_send)
                group.cancel_scope.cancel()
        finally:
            self.lease.close()


def _cost(info):
    return max(info.st_size, info.st_blocks * 512)


def _remove_idle(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        path.unlink()
        return True
    finally:
        os.close(fd)


def acquire(sha, size, chunks):
    """Serialize reservation+fill; pin the inode before releasing global lock."""
    if not re.fullmatch(r'[0-9a-f]{64}', sha) or size < 0:
        raise IOError('Invalid object metadata')
    cap = int(os.getenv('STELLA_BLOB_CACHE_MAX_BYTES', str(256 * 1024 * 1024)))
    ttl = max(0, int(os.getenv('STELLA_BLOB_CACHE_TTL_SECONDS', '86400')))
    root = Path(os.getenv('STELLA_BLOB_CACHE', 'data/blob-cache')).absolute()
    if root.is_symlink():
        raise IOError('Unsafe cache directory')
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = os.open(root / '.cache.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _acquire_locked(root, sha, size, chunks, cap, ttl)
        finally:
            os.close(lock)
    except OSError as exc:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            raise unavailable() from exc
        raise


def _acquire_locked(root, sha, size, chunks, cap, ttl):
    target = root / (sha + '.bin')
    entries = []
    now = time.time()
    for path in root.iterdir():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            continue
        if FILL.fullmatch(path.name):
            # Global lock is held throughout each fill; these are crash leftovers.
            path.unlink()
        elif ENTRY.fullmatch(path.name):
            if (now - info.st_mtime > ttl or (path == target and info.st_size != size)) and _remove_idle(path):
                continue
            entries.append((path, info))
    if target.is_symlink():
        raise IOError('Unsafe cache entry')
    hit = next((info for path, info in entries if path == target), None)
    if hit and hit.st_size != size:
        raise unavailable()  # Invalid but pinned by another reader: never replace.
    block = os.statvfs(root).f_frsize or 4096
    needed = 0 if hit else ((size + block - 1) // block) * block
    used = sum(_cost(info) for _, info in entries)
    for path, info in sorted(entries, key=lambda item: item[1].st_mtime):
        if used + needed <= cap:
            break
        if path != target and _remove_idle(path):
            used -= _cost(info)
    if used + needed > cap:
        raise unavailable()
    if not hit:
        fd, name = tempfile.mkstemp(prefix='.fill-', dir=root)
        try:
            with os.fdopen(fd, 'wb') as out:
                # Reserve actual disk before reading PG. ENOSPC leaves no half-cache.
                if size:
                    os.posix_fallocate(out.fileno(), 0, size)
                digest, total = hashlib.sha256(), 0
                for chunk in chunks():
                    total += len(chunk)
                    if total > size:
                        raise IOError('Object integrity mismatch')
                    out.write(chunk)
                    digest.update(chunk)
                out.flush()
                os.fsync(out.fileno())
                if total != size or digest.hexdigest() != sha:
                    raise IOError('Object integrity mismatch')
                if used + _cost(os.fstat(out.fileno())) > cap:
                    raise unavailable()
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.utime(fd, None)
        return Lease(target, fd)
    except BaseException:
        os.close(fd)
        raise
