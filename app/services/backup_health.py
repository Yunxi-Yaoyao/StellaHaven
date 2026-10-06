"""Read controlled local backup receipts, never initiate a backup/restore or expose paths."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat

FIELDS = ('timestamp', 'status', 'checksumverified', 'restoreverified', 'source')
SOURCES = {'postgres-dump', 'postgres-snapshot'}
MAX_RECEIPT_BYTES = 65536
MAX_RECEIPTS = 64

def _empty(status='missing'):
    return dict(timestamp=None, status=status, checksumverified=False, restoreverified=False, source=None)

def receipt_directory() -> Path:
    # Deployment-owned environment variable; no request-controlled path.
    return Path(os.environ.get('STELLA_BACKUP_RECEIPT_DIR', '/var/lib/stella/backup-receipts'))

def read_backup_health(directory: Path | None = None, *, now: datetime | None = None) -> dict:
    directory = directory if directory is not None else receipt_directory()
    now = now or datetime.now(timezone.utc)
    rows = []
    invalid = False
    directory_fd = None
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        names = []
        with os.scandir(directory_fd) as entries:
            for index, entry in enumerate(entries):
                if index >= 256:
                    return _empty('invalid')
                if entry.name.endswith('.json'):
                    names.append(entry.name)
                    if len(names) > MAX_RECEIPTS:
                        return _empty('invalid')
        names.sort()
        for name in names:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                with os.fdopen(fd, 'rb') as fh:
                    if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                        raise ValueError('not a regular receipt')
                    raw = fh.read(MAX_RECEIPT_BYTES + 1)
                if len(raw) > MAX_RECEIPT_BYTES:
                    raise ValueError('receipt too large')
                receipt = json.loads(raw)
                stamp = datetime.fromisoformat(receipt['timestamp'].replace('Z', '+00:00'))
                if stamp.tzinfo is None or receipt['source'] not in SOURCES:
                    raise ValueError('invalid receipt')
                if stamp > now + timedelta(minutes=5):
                    raise ValueError('future receipt')
                if type(receipt['checksumverified']) is not bool or type(receipt['restoreverified']) is not bool:
                    raise ValueError('verification flags must be bool')
                if receipt['status'] not in {'verified', 'unverified', 'failed'}:
                    raise ValueError('unknown receipt state')
                row = {key: receipt[key] for key in FIELDS}
                if row['status'] == 'verified' and not row['checksumverified']:
                    row['status'] = 'unverified'
                if now - stamp > timedelta(hours=48):
                    row['status'] = 'stale'
                rows.append((stamp, row))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
                invalid = True
    except (OSError, ValueError):
        return _empty('missing')
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    if invalid:
        return _empty('invalid')
    if not rows:
        return _empty()
    return max(rows, key=lambda item: item[0])[1]


# AppConfig single-owner bounded slot; deliberately no request/payload values.
AUDIT_KEY = 'operations_audit_v1'
AUDIT_LIMIT = 200
AUDIT_LOCK = 1937006956
AUDIT_FIELDS = frozenset({'title', 'icon', 'enabled', 'visible', 'order', 'mode', 'target', 'name',
                          'host', 'port', 'tags', 'navigation', 'injection', 'security', 'protection'})

def _audit_entries(value):
    if value is None:
        return []
    if len(value) > 524288:
        raise ValueError('audit slot oversized')
    entries = json.loads(value)
    if not isinstance(entries, list) or len(entries) > AUDIT_LIMIT:
        raise ValueError('invalid audit slot')
    keys = {'timestamp', 'action', 'actor_id', 'resource_id', 'changed_fields'}
    return [{key: entry[key] for key in keys if key in entry} for entry in entries if isinstance(entry, dict)]


def record_change(db, *, action: str, actor_id, resource_id=None, changed_fields=(), payload=None):
    """Flush an audit event in the caller transaction; never commit it separately.

    payload is accepted for backwards-compatible call sites but wholly discarded.
    PostgreSQL advisory transaction lock serializes slot creation and appends.
    """
    import re
    from uuid import UUID
    from sqlalchemy import text
    from app.models.config import AppConfig
    if not re.fullmatch(r'[a-z][a-z0-9_.]{0,63}', action):
        raise ValueError('invalid audit action')
    actor = str(UUID(str(actor_id)))
    resource = None if resource_id is None else str(UUID(str(resource_id)))
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': AUDIT_LOCK})
    row = db.get(AppConfig, AUDIT_KEY, populate_existing=True)
    entries = _audit_entries(row.value if row else None)
    event = {'timestamp': datetime.now(timezone.utc).isoformat(), 'action': action,
             'actor_id': actor, 'resource_id': resource,
             'changed_fields': sorted(set(field for field in changed_fields
                                          if isinstance(field, str) and field in AUDIT_FIELDS))}
    value = json.dumps((entries + [event])[-AUDIT_LIMIT:], separators=(',', ':'))
    if row is None:
        db.add(AppConfig(key=AUDIT_KEY, value=value))
    else:
        row.value = value
    db.flush()
    return event


def read_change_audit(db):
    from app.models.config import AppConfig
    row = db.get(AppConfig, AUDIT_KEY)
    return list(reversed(_audit_entries(row.value if row else None)))
