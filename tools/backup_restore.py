#!/usr/bin/env python3
"""Offline restore into a confirmed EMPTY database and NEW data directory only.

This file deliberately never imports app/config/database/main, nor reads .env.
"""
import argparse
import ctypes
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
import psycopg2


def archive_module():
    path = Path(__file__).resolve().parents[1] / 'app/services/backup_archive.py'
    spec = importlib.util.spec_from_file_location('stella_offline_backup_archive', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def regular_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('regular file required')
    return os.fdopen(fd, 'rb')


def safe_parent(path):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute output path required')
    parent = path.parent
    for node in (parent, *parent.parents):
        if node.is_symlink():
            raise ValueError('symlink output parent rejected')
    if not parent.is_dir() or path.exists() or path.is_symlink():
        raise ValueError('new data directory in existing parent required')


def publish_directory(source, destination):
    # Linux renameat2 no-replace makes the final publication race-safe too.
    libc = ctypes.CDLL(None, use_errno=True)
    operation = libc.renameat2
    operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    operation.restype = ctypes.c_int
    if operation(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    fd = os.open(Path(destination).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def restore(args):
    if not args.maintenance or args.confirm_target != f'{args.host}:{args.port}/{args.database}':
        raise ValueError('explicit maintenance and exact target confirmation required')
    if not args.host or not args.database or not args.user or not 1 <= args.port <= 65535:
        raise ValueError('explicit target fields required')
    lib = archive_module()
    budget = lib.bulk_timeout(getattr(args, 'timeout_seconds', None), default=7200)
    data = Path(args.data_directory)
    safe_parent(data)
    with regular_file(args.password_file) as secret:
        if os.fstat(secret.fileno()).st_mode & 0o077:
            raise ValueError('password file must be private 0600')
        password = secret.read(4097).decode().rstrip('\r\n')
        if len(password) > 4096:
            raise ValueError('password file oversized')
    with regular_file(args.archive) as archive:
        expected = args.sha256
        if (not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected)
                or not hmac.compare_digest(hashlib.file_digest(archive,'sha256').hexdigest(),expected)):
            raise ValueError('independently recorded archive checksum required')
        archive.seek(0)
        manifest = lib.validate_archive(archive)
        if manifest['scope'] != 'all':
            raise ValueError('full archive required')
        archive.seek(0)
        with zipfile.ZipFile(archive) as z:
            for name in manifest['entries']:
                if name != 'database.dump' and not (name.startswith('files/assets/') or name.startswith('files/attachments/')
                        or name.startswith('files/oidc/') or name in ('files/secret_key', 'files/email_config.json')):
                    raise ValueError('unexpected full restore resource')
            # Explicit libpq values override all routing from the environment.
            connect = dict(host=args.host, port=args.port, user=args.user, password=password,
                           dbname=args.database, connect_timeout=5, options='-c statement_timeout=180000')
            for key in list(os.environ):
                if key.startswith('PG'):
                    del os.environ[key]
            conn = psycopg2.connect(**connect)
            try:
                with conn.cursor() as cur:
                    cur.execute('SELECT current_database(), current_user, pg_is_in_recovery()')
                    if cur.fetchone() != (args.database, args.user, False):
                        raise ValueError('target identity mismatch/not writable')
                    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f','S'))")
                    if cur.fetchone()[0]:
                        raise ValueError('target database is not empty')
                    cur.execute('SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid())')
                    if cur.fetchone()[0]:
                        raise ValueError('target has active sessions; stop application first')
                conn.rollback()
            finally:
                conn.close()
            binary = Path(os.getenv('STELLA_BACKUP_PG_BIN', '/usr/lib/postgresql/18/bin')) / 'pg_restore'
            tool_env = dict(os.environ)
            if os.getenv('STELLA_BACKUP_PG_LIB'):
                tool_env['LD_LIBRARY_PATH'] = os.environ['STELLA_BACKUP_PG_LIB']
            version = subprocess.run([str(binary), '--version'], capture_output=True, timeout=10, env=tool_env)
            if version.returncode or b'(PostgreSQL) 18.' not in version.stdout:
                raise ValueError('PG18 restore client required')
            stage = Path(tempfile.mkdtemp(prefix='.stella-restore-', dir=data.parent))
            checkpoint = data.parent / ('.stella-restore-' + manifest['id'] + '.json')
            state = 'staging'
            checkpoint_fd = os.open(checkpoint, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            def save_checkpoint():
                raw = json.dumps({'state': state, 'staging_directory': str(stage), 'archive_id': manifest['id'],
                                  'database': args.database, 'data_directory': str(data)}).encode()
                os.lseek(checkpoint_fd, 0, os.SEEK_SET)
                os.ftruncate(checkpoint_fd, 0)
                os.write(checkpoint_fd, raw)
                os.fsync(checkpoint_fd)
            save_checkpoint()
            try:
                with tempfile.TemporaryFile(dir=stage) as dump:
                    with z.open('database.dump') as source:
                        shutil.copyfileobj(source, dump, 256 * 1024)
                    for name in manifest['entries']:
                        if not name.startswith('files/'):
                            continue
                        destination = stage / name[len('files/'):]
                        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                        with os.fdopen(fd, 'wb') as out, z.open(name) as source:
                            shutil.copyfileobj(source, out, 256 * 1024)
                            out.flush()
                            os.fsync(out.fileno())
                    dump.seek(0)
                    env = dict(tool_env, PGHOST=args.host, PGPORT=str(args.port), PGDATABASE=args.database,
                               PGUSER=args.user, PGPASSWORD=password, PGCONNECT_TIMEOUT='5',
                               PGOPTIONS=f'-c statement_timeout={budget * 1000}')
                    result = subprocess.run([str(binary), '--single-transaction', '--exit-on-error', '--no-owner', '--no-acl',
                                             '--dbname=' + args.database], stdin=dump, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, env=env, timeout=budget)
                    if result.returncode:
                        raise RuntimeError('PG18 restore failed; target remains transactionally unchanged')
                state = 'database_restored_files_pending'
                save_checkpoint()
                publish_directory(stage, data)
                state = 'succeeded'
                save_checkpoint()
                print(json.dumps({'state': state, 'archive_id': manifest['id'], 'data_directory': str(data),
                                  'note': 'ZIP integrity and actual restore completed; configure identity file paths before starting web'}))
            finally:
                if state == 'staging':
                    shutil.rmtree(stage)
                    state = 'failed_or_interrupted_transaction'
                save_checkpoint()
                os.close(checkpoint_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'host', 'user', 'database', 'password-file', 'data-directory', 'confirm-target','sha256'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=7200,
                        help='finite pg_restore bulk deadline, 1..14400 seconds; default 7200')
    parser.add_argument('--maintenance', action='store_true')
    args = parser.parse_args()
    try:
        restore(args)
    except Exception as exc:
        # Exception strings can contain SQL/passwords/connection metadata.
        print(json.dumps({'state': 'failed', 'error': type(exc).__name__,
                          'message': 'Restore refused/failed. Require a valid all ZIP, exact maintenance confirmation, empty idle target, new data directory and PG18 client.'}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
