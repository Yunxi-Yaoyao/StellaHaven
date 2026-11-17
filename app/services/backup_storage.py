"""Bounded authenticated ownership index, no-follow I/O and atomic ZIP publication."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import uuid
from app.services.backup_archive import create_archive, validate_archive, hash_stream, InvalidArchive

INDEX = '.stella-backups-v1.json'
JOURNAL = '.stella-backups-journal-v1.json'


class Busy(ValueError):
    pass


def ensure_private_directory(path, fence):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute default directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                fence()
                os.mkdir(part, mode=0o700, dir_fd=fd)
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
    finally:
        os.close(fd)


@contextmanager
def directory_fd(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or str(path) == '/':
        raise ValueError('absolute provisioned directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        if os.fstat(fd).st_uid != os.geteuid():
            raise ValueError('backup directory must belong to application user')
        if os.fstat(fd).st_mode & 0o022:
            raise ValueError('backup directory must not be group/world writable')
        yield fd
    finally:
        os.close(fd)


class BackupDirectory:
    def __init__(self, path, key, fence=lambda: None):
        self.path = Path(path)
        self.key = key.encode() if isinstance(key, str) else key
        self.fence = fence

    def _signature(self, payload):
        return hmac.new(self.key, json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()

    def _read(self, fd, name, default):
        try:
            f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return default
        with os.fdopen(f, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('nonregular ownership index')
            raw = stream.read(131073)
        if len(raw) > 131072:
            raise ValueError('ownership index limit')
        obj = json.loads(raw)
        if not hmac.compare_digest(obj['signature'], self._signature(obj['payload'])):
            raise ValueError('backup ownership signature mismatch')
        return obj['payload']

    def _write(self, fd, name, payload):
        self.fence()
        temp = '.stella-index-' + ('journal' if name == JOURNAL else 'records') + '-v1.tmp'
        missing = object()
        if self._read(fd, temp, missing) is not missing:
            self.fence()
            os.unlink(temp, dir_fd=fd)  # only a previously signed owned staging file
        try:
            f = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(f, 'w') as stream:
                json.dump({'payload': payload, 'signature': self._signature(payload)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self.fence()
            os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                self.fence()
                os.unlink(temp, dir_fd=fd)
            except FileNotFoundError:
                pass

    @contextmanager
    def _lock(self):
        self.fence()
        with directory_fd(self.path) as fd:
            lock = os.open('.stella-backups.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise Busy('backup directory busy') from exc
                yield fd
            finally:
                os.close(lock)

    def _rows(self, fd):
        rows = self._read(fd, INDEX, [])
        if not isinstance(rows, list) or len(rows) > 3:
            raise ValueError('ownership record limit')
        for row in rows:
            if not re.fullmatch(r'stella-(settings|all)-[0-9a-f]{32}\.zip', row['filename']) or row['id'] not in row['filename']:
                raise ValueError('invalid owned filename')
        return rows

    @contextmanager
    def _open(self, fd, row, *, verify=True):
        f = os.open(row['filename'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(f, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('nonregular backup')
            if verify:
                size, digest = hash_stream(stream)
                if (size, digest) != (row['bytes'], row['sha256']):
                    raise InvalidArchive('archive checksum mismatch')
                stream.seek(0)
                manifest = validate_archive(stream)
                if manifest['id'] != row['id'] or manifest['scope'] != row['scope']:
                    raise InvalidArchive('archive ownership mismatch')
                stream.seek(0)
            yield stream

    def records(self):
        with directory_fd(self.path) as fd:
            rows = self._rows(fd)
            result = []
            for row in rows:
                try:
                    with self._open(fd, row, verify=False):
                        result.append(row)
                except FileNotFoundError:
                    continue
            return result[:2]

    def _retain(self, fd, rows):
        self._write(fd, INDEX, rows)
        for old in rows[2:]:
            try:
                with self._open(fd, old):
                    self.fence()
                    os.unlink(old['filename'], dir_fd=fd)
                    os.fsync(fd)
            except FileNotFoundError:
                pass  # A prior owner already unlinked this authenticated old generation.
        self._write(fd, INDEX, rows[:2])

    def _recover_pending(self, fd):
        rows = self._rows(fd)
        journal = self._read(fd, JOURNAL, None)
        if journal:
            if 'pending' in journal:
                name = journal['pending']
                if not re.fullmatch(r'\.stella-backup-[0-9a-f]{32}\.tmp', name):
                    raise ValueError('invalid pending owner')
                try:
                    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(f, 'rb') as stream:
                        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                            raise ValueError('nonregular pending backup')
                    self.fence()
                    os.unlink(name, dir_fd=fd)
                except FileNotFoundError:
                    pass
            else:
                try:
                    with self._open(fd, journal):
                        if all(r['id'] != journal['id'] for r in rows):
                            rows.insert(0, journal)
                    self._retain(fd, rows)
                except FileNotFoundError:
                    pass
                pending = '.stella-backup-' + journal['id'] + '.tmp'
                self.fence()
                try:
                    os.unlink(pending, dir_fd=fd)
                except FileNotFoundError:
                    pass
            self.fence()
            os.unlink(JOURNAL, dir_fd=fd)
            rows = self._rows(fd)
        return self._rows(fd)

    def recover(self):
        with self._lock() as fd:
            self._recover_pending(fd)

    def create(self, scope, entries, warnings=()):
        with self._lock() as fd:
            rows = self._recover_pending(fd)
            identity = uuid.uuid4().hex
            temp = '.stella-backup-' + identity + '.tmp'
            filename = f'stella-{scope}-{identity}.zip'
            proc_path = Path(f'/proc/self/fd/{fd}')
            try:
                self._write(fd, JOURNAL, {'pending': temp})
                self.fence()
                manifest = create_archive(proc_path / temp, scope=scope, entries=entries, archive_id=identity, warnings=warnings)
                with (proc_path / temp).open('rb') as stream:
                    size, digest = hash_stream(stream)
                row = dict(id=identity, filename=filename, scope=scope, created_at=manifest['created_at'],
                           bytes=size, sha256=digest, verified=True)
                self._write(fd, JOURNAL, row)
                self.fence()
                os.link(temp, filename, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                os.fsync(fd)
                self._retain(fd, [row] + rows)
                self.fence()
                os.unlink(JOURNAL, dir_fd=fd)
                return row
            finally:
                try:
                    self.fence()
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass

    @contextmanager
    def open_record(self, identity, *, verify=True):
        with directory_fd(self.path) as fd:
            row = next((r for r in self._rows(fd) if r['id'] == identity), None)
            if row is None:
                raise FileNotFoundError('backup not present on this node/directory')
            with self._open(fd, row, verify=verify) as stream:
                yield row, stream

    def mark_verified(self, identity, verified):
        with self._lock() as fd:
            rows = self._rows(fd)
            row = next((r for r in rows if r['id'] == identity), None)
            if row is not None:
                row['verified'] = bool(verified)
                self._write(fd, INDEX, rows)

    def delete(self, identity, confirmation):
        with self._lock() as fd:
            rows = self._rows(fd)
            row = next((r for r in rows if r['id'] == identity), None)
            if row is None:
                raise FileNotFoundError('backup missing')
            if confirmation != row['filename']:
                raise ValueError('confirmation mismatch')
            with self._open(fd, row):
                self.fence()
                os.unlink(row['filename'], dir_fd=fd)
                os.fsync(fd)
            self._write(fd, INDEX, [r for r in rows if r['id'] != identity])
