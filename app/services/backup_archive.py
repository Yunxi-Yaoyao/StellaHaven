"""Versioned standalone ZIPs. No extraction, shell, database or app config imports."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import uuid
import zipfile
from app.backup_diagnostics import ARCHIVE_GUARDS

FORMAT = 'stella.backup.center'
VERSION = 1
CHUNK = 256 * 1024
MAX_ENTRIES = 50000
MAX_TOTAL = 64 * 1024**3
MAX_ENTRY = 32 * 1024**3
MAX_MANIFEST = 16 * 1024**2
MAX_RATIO = 1000


class InvalidArchive(ValueError):
    def __init__(self, guard='invalid backup archive'):
        self.reason_code = ARCHIVE_GUARDS.get(guard, 'archive_invalid') if isinstance(guard, str) else 'archive_invalid'
        super().__init__(guard)


def bulk_timeout(value, *, default):
    """Finite bulk-I/O budget, distinct from short metadata statement limits."""
    if value is None:
        value = default
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 14400:
        raise ValueError('bulk operation budget must be 1..14400 seconds')
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidArchive('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(InvalidArchive('nonfinite JSON')))


def safe_name(name):
    if (not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name or '\x00' in name
            or name.startswith('/') or ':' in name or any(p in ('', '.', '..') for p in name.split('/'))
            or str(PurePosixPath(name)) != name):
        raise InvalidArchive('unsafe archive entry')
    return name


def hash_stream(source):
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(CHUNK):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def create_archive(path, *, scope, entries, archive_id=None, created_at=None, warnings=()):
    if scope not in ('settings', 'all'):
        raise InvalidArchive('invalid scope')
    if not 1 <= len(entries) < MAX_ENTRIES:
        raise InvalidArchive('entry count limit')
    manifest = {'format': FORMAT, 'version': VERSION, 'id': archive_id or uuid.uuid4().hex,
                'scope': scope, 'created_at': created_at or datetime.now(timezone.utc).isoformat(),
                'entries': {}, 'warnings': list(warnings)}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as raw:
            with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                total = 0
                for name, source in entries.items():
                    safe_name(name)
                    if name == 'manifest.json':
                        raise InvalidArchive('reserved entry')
                    digest = hashlib.sha256()
                    size = 0
                    # Configuration media is already encoded. Deflating it
                    # again can turn a valid padded MP4 into a self-produced
                    # ratio bomb. Store these payloads verbatim; keep every
                    # size/hash/path/ratio validator unchanged.
                    info = zipfile.ZipInfo(name)
                    info.compress_type = (zipfile.ZIP_STORED if name.startswith('resources/')
                                          else zipfile.ZIP_DEFLATED)
                    with z.open(info, 'w', force_zip64=True) as dst:
                        while chunk := source.read(CHUNK):
                            size += len(chunk)
                            total += len(chunk)
                            if size > MAX_ENTRY or total > MAX_TOTAL:
                                raise InvalidArchive('entry limit')
                            digest.update(chunk)
                            dst.write(chunk)
                    manifest['entries'][name] = {'bytes': size, 'sha256': digest.hexdigest()}
                encoded = json.dumps(manifest, ensure_ascii=False).encode()
                if len(encoded) > MAX_MANIFEST:
                    raise InvalidArchive('manifest size limit')
                z.writestr('manifest.json', encoded)
            raw.flush()
            os.fsync(raw.fileno())
        validate_archive(path)
        return manifest
    except BaseException:
        os.unlink(path)
        raise


def validate_archive(path):
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if not 2 <= len(infos) <= MAX_ENTRIES:
                raise InvalidArchive('entry count limit')
            names = set()
            total = 0
            for info in infos:
                safe_name(info.filename)
                mode = info.external_attr >> 16
                if info.filename in names or info.is_dir() or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise InvalidArchive('duplicate or nonregular entry')
                names.add(info.filename)
                total += info.file_size
                if (info.flag_bits & 1 or info.file_size > MAX_ENTRY or total > MAX_TOTAL
                        or info.file_size > max(1, info.compress_size) * MAX_RATIO):
                    raise InvalidArchive('archive size/compression limit')
            info = z.getinfo('manifest.json')
            if info.file_size > MAX_MANIFEST:
                raise InvalidArchive('manifest size limit')
            manifest = strict_json(z.read(info))
            if manifest.get('format') != FORMAT or manifest.get('version') != VERSION or manifest.get('scope') not in ('settings', 'all'):
                raise InvalidArchive('unsupported backup format')
            if len(manifest.get('id', '')) != 32 or any(c not in '0123456789abcdef' for c in manifest['id']):
                raise InvalidArchive('invalid archive id')
            stamp = datetime.fromisoformat(manifest['created_at'])
            if stamp.tzinfo is None or set(manifest['entries']) != names - {'manifest.json'}:
                raise InvalidArchive('manifest entries mismatch')
            for name, expected in manifest['entries'].items():
                with z.open(name) as stream:
                    size, digest = hash_stream(stream)
                if expected != {'bytes': size, 'sha256': digest}:
                    raise InvalidArchive('entry checksum mismatch')
            required = 'settings.json' if manifest['scope'] == 'settings' else 'database.dump'
            if required not in names:
                raise InvalidArchive('missing required payload')
            return manifest
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, InvalidArchive):
            raise
        raise InvalidArchive('invalid backup archive') from exc
