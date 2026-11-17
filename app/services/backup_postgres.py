"""PG18 consistent-snapshot dump; credentials never enter argv or error text."""
from contextlib import contextmanager, ExitStack
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from sqlalchemy import text
from app.services.backup_projection import Payload, require_settings_mode
from app.services.backup_archive import safe_name, bulk_timeout
from app.backup_diagnostics import BackupFailure

FILE_ROOTS = ('assets', 'attachments', 'oidc')
FILE_SINGLE = ('secret_key', 'email_config.json')


def tool_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    library = os.getenv('STELLA_BACKUP_PG_LIB')
    if library:
        if not Path(library).is_absolute():
            raise ValueError('PG library path must be absolute')
        env['LD_LIBRARY_PATH'] = library
    return env


def pg_binary(name):
    root = os.environ.get('STELLA_BACKUP_PG_BIN', '/usr/lib/postgresql/18/bin')
    path = Path(root) / name
    if not path.is_absolute():
        raise ValueError('PG18 tool path must be absolute')
    result = subprocess.run([str(path), '--version'], capture_output=True, timeout=10, env=tool_environment())
    if result.returncode or b'(PostgreSQL) 18.' not in result.stdout:
        raise BackupFailure('pg_client_unavailable')
    return str(path)


def pg_environment(url):
    # No ambient service files, options, passwords, DSNs or hostaddr overrides.
    env = tool_environment()
    budget = bulk_timeout(os.getenv('STELLA_BACKUP_TIMEOUT_SECONDS'), default=3600)
    env.update(PGHOST=url.host or '', PGPORT=str(url.port or 5432), PGUSER=url.username or '',
               PGDATABASE=url.database or '', PGPASSWORD=url.password or '', PGCONNECT_TIMEOUT='5',
               PGOPTIONS=f'-c statement_timeout={budget * 1000}')
    return env


@contextmanager
def export_all(conn, scratch, data_root, *, backup_directory=None):
    require_settings_mode()  # legacy files have no DB/file transaction boundary
    if conn.dialect.name != 'postgresql':
        raise RuntimeError('full backup requires PostgreSQL')
    snapshot = conn.execute(text('SELECT pg_export_snapshot()')).scalar_one()
    with ExitStack() as stack:
        output = stack.enter_context(tempfile.TemporaryFile(dir=scratch))
        budget = bulk_timeout(os.getenv('STELLA_BACKUP_TIMEOUT_SECONDS'), default=3600)
        process = subprocess.run([pg_binary('pg_dump'), '--format=custom', '--no-owner', '--no-acl',
                                  '--snapshot=' + snapshot], stdout=output, stderr=subprocess.PIPE,
                                 env=pg_environment(conn.engine.url), timeout=budget)
        if process.returncode:
            raise BackupFailure('pg_dump_failed')
        output.seek(0)
        entries = {'database.dump': output}
        root = Path(data_root)
        excluded = Path(backup_directory) if backup_directory is not None else root / 'backups'
        warnings = []
        def add(path, name):
            safe_name(name)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            stream = stack.enter_context(os.fdopen(fd, 'rb'))
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('nonregular persistent resource')
            entries[name] = stream
        for folder in FILE_ROOTS:
            directory = root / folder
            if not directory.exists():
                continue
            if directory.is_symlink():
                raise ValueError('symlink persistent directory')
            for parent, directories, files in os.walk(directory, followlinks=False):
                directories[:] = [child for child in directories if Path(parent) / child != excluded and child not in ('blob-cache', 'backups')]
                if Path(parent) == excluded:
                    directories[:] = []
                    continue
                for child in directories:
                    if (Path(parent) / child).is_symlink():
                        raise ValueError('symlink persistent directory')
                for file in files:
                    if file.startswith('.stella-') or file.endswith('.lock') or (folder == 'oidc' and '/runtime' in str(parent)):
                        continue
                    path = Path(parent) / file
                    add(path, 'files/' + path.relative_to(root).as_posix())
        for name in FILE_SINGLE:
            if (root / name).exists():
                add(root / name, 'files/' + name)
        external_key = os.getenv('STELLA_OIDC_PRIVATE_KEY_FILE')
        if external_key:
            add(Path(external_key), 'files/oidc/private.json')
        # Environment-provisioned authentication key is as necessary as file keys.
        if os.getenv('STELLA_SECRET_KEY'):
            entries['files/secret_key'] = io.BytesIO(os.environ['STELLA_SECRET_KEY'].encode())
        warnings.append('External Immich/OpenList contents, environment/deployment secrets and caches are not included; stop legacy file writers during all backup')
        yield Payload(entries, warnings)
