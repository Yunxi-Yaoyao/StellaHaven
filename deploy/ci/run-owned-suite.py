"""Run one owning Files/Nav file on a fresh CI-service nonce database.

No Docker commands, mount operations or inherited app environment. The localhost
relay rejects every startup not naming this invocation's non-superuser role/DB.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import subprocess
import sys
import time

from owned_pg import Relay, admitted_marker, verify_admin
import socket
import struct

ROOT = Path(__file__).resolve().parents[2]


def private_job_root():
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if (os.geteuid() != 0 or not Path('/.dockerenv').exists() or int(status['CapEff'], 16) & (1 << 21)
            or status['Seccomp'].strip() != '2' or Path('/var/run/docker.sock').exists()):
        raise ValueError('nonprivileged isolated CI container required')
    base = Path('/mnt')
    info = base.lstat()
    if base.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('trusted job-private /mnt required')
    # /mnt must be the private job overlay, not a host bind/volume.
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    if not any(row[4] == '/' and row[row.index('-') + 1] == 'overlay' for row in mounts):
        raise ValueError('job-private overlay root required')
    for row in mounts:
        if Path(row[4]).is_relative_to(base):
            raise ValueError('host /mnt bind or descendant mount is not admitted')
    return {key: status[key].strip() for key in ('CapEff', 'CapBnd', 'Seccomp')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('test')
    parser.add_argument('--noconftest', action='store_true')
    args = parser.parse_args()
    args.pytest_args = ['--noconftest'] if args.noconftest else []
    # Resolve repository inventory before any DB creation. One file per command;
    # arbitrary paths/pytest flags are not a general privileged subprocess API.
    test = Path(args.test)
    if test.parent == Path('tests_agent_unified') and not args.pytest_args:
        from unified_ci import run
        return run(test)
    nav = test.parent == Path('tests_isolated') and (test.name.startswith('test_native_nav_') or test.name == 'test_homebg_references_pg.py') and test.name.endswith('_pg.py')
    files = test.parent in (Path('tests_node_files'), Path('tests_node_files_delivery'), Path('tests_agent_refresh_timeout')) and test.name.startswith('test_') and test.suffix == '.py'
    if not (nav or files) or not (ROOT / test).is_file() or (ROOT / test).is_symlink() or not (ROOT / test).resolve().is_relative_to(ROOT) or args.pytest_args not in ([], ['--noconftest']):
        raise ValueError('not an owned suite file')
    marker = admitted_marker()  # stdlib admission before importing the PG driver.
    capabilities = private_job_root()
    import psycopg2
    from psycopg2 import sql
    admin = psycopg2.connect(host=marker['address'], port=5432, user='stalla',
        password=os.environ['POSTGRES_PASSWORD'], dbname='stella_test', connect_timeout=5, sslmode='disable')
    admin.autocommit = True
    verify_admin(admin, marker)
    nonce = secrets.token_hex(16)
    name = ('navqa_' if nav else 'nodefiles_') + nonce
    password = secrets.token_hex(32)
    scratch = Path('/mnt') / ('stella-ci-' + nonce)
    scratch.mkdir(mode=0o755)
    evidence = Path(os.environ.get('STELLA_CI_EVIDENCE', str(ROOT / '.ci-owned-evidence'))) / test.with_suffix('')
    evidence.mkdir(parents=True, exist_ok=False)
    owner = json.dumps({'job': marker['job'], 'bootstrap': marker['nonce'], 'nonce': nonce}, sort_keys=True)
    receipt = {'test': str(test), 'database': name, 'nonce': nonce, 'capabilities': capabilities,
               'boundary': 'job-private overlay ancestry; real chroot for root filesystem probes; real UID65534 lifecycle children; fixture systemd', 'created_role': False, 'created_database': False}
    relay = None
    started = time.monotonic()
    try:
        with admin.cursor() as c:
            c.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 40 PASSWORD %s').format(sql.Identifier(name)), (password,))
            receipt['created_role'] = True
            c.execute(sql.SQL('COMMENT ON ROLE {} IS %s').format(sql.Identifier(name)), (owner,))
            c.execute(sql.SQL('CREATE DATABASE {} OWNER {} TEMPLATE template0').format(sql.Identifier(name), sql.Identifier(name)))
            receipt['created_database'] = True
            c.execute(sql.SQL('COMMENT ON DATABASE {} IS %s').format(sql.Identifier(name)), (owner,))
            c.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
        relay = Relay(marker['address'], name)
        port = str(relay.server_address[1])
        # Real relay/PG negatives: wrong database and role never reach PG;
        # a wrong password for the correct target reaches PG and is refused.
        rejected = []
        for user, database in ((name, 'stella_test'), ('stalla', name)):
            with socket.create_connection(('127.0.0.1', int(port)), timeout=3) as probe:
                body = struct.pack('!I', 196608) + b'user\0' + user.encode() + b'\0database\0' + database.encode() + b'\0\0'
                probe.sendall(struct.pack('!I', len(body) + 4) + body)
                if probe.recv(1):
                    raise RuntimeError('foreign startup reached upstream')
                rejected.append(True)
        try:
            psycopg2.connect(host='127.0.0.1', port=port, user=name, dbname=name, password=secrets.token_hex(32), sslmode='disable', connect_timeout=3)
        except psycopg2.OperationalError as exc:
            if 'password authentication failed' not in str(exc):
                raise
        else:
            raise RuntimeError('bad password admitted')
        with psycopg2.connect(host='127.0.0.1', port=port, user=name, dbname=name, password=password, sslmode='disable', connect_timeout=3) as probe:
            with probe.cursor() as c:
                c.execute('SELECT current_database(), current_user, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')
                if c.fetchone() != (name, name, False, False, False):
                    raise RuntimeError('owned role privilege mismatch')
        receipt['negative_controls'] = {'foreign_database_rejected': rejected[0], 'admin_role_rejected': rejected[1], 'wrong_password_rejected': True, 'non_superuser': True}
        child_receipt = scratch / ('owner-' + nonce + '.json')
        child_receipt.write_text(json.dumps({'format': 1, 'nonce': nonce, 'database': name, 'port': port, 'pid': os.getpid()}))
        child_receipt.chmod(0o600)
        env = {'PATH': os.environ['PATH'], 'HOME': str(scratch), 'TMPDIR': str(scratch),
               'PYTHONPATH': str(ROOT), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': port, 'POSTGRES_DB': name, 'POSTGRES_USER': name,
               'POSTGRES_PASSWORD': password, 'PGPASSWORD': password, 'PGSSLMODE': 'disable',
               'STELLA_SECRET_KEY': secrets.token_hex(48), 'NODE_FILES_EVIDENCE': str(evidence),
               'STELLA_CI_OWNED_NONCE': nonce, 'STELLA_CI_OWNED_RECEIPT': str(child_receipt),
               'NODE_FILES_NAMESPACE_FIXTURE': '1', 'NAV_NATIVE_PG_TEST': '1', 'NAV_ROOT': str(ROOT),
               'NAV_PG_NONCE': nonce, 'CI': 'true', 'GITLAB_CI': 'true', 'CI_JOB_ID': marker['job'],
               'STELLA_CI_PYTHON': sys.executable, 'NAV_REHEARSAL_RECEIPT': str(evidence / 'migration-rehearsal.json')}
        for key in ('PLAYWRIGHT_BROWSERS_PATH', 'CHROME_BIN', 'STELLA_CHROMIUM', 'STELLA_CI_NODE'):
            if os.environ.get(key):
                env[key] = os.environ[key]
        if test.name == 'test_homebg_references_pg.py':
            # This owning fixture seeds actual BlobObject/BlobChunk rows.
            env.update(STELLA_BLOB_STORAGE='postgres', STELLA_MAIN_ORIGIN='https://media-qa.test',
                       STELLA_TRUSTED_ORIGINS='https://media-qa.test', NAV_EVIDENCE=str(evidence))
        if test.name == 'test_native_nav_completion_browser_pg.py':
            env['NAV_BROWSER_ROOT'] = str(scratch / 'nav-browser')
            build = subprocess.run([env.get('STELLA_CI_NODE', 'node'), str(ROOT / 'qa/native_nav_completion_build.mjs')], env=env, cwd=scratch, capture_output=True, text=True, timeout=120)
            (evidence / 'browser-build.log').write_text(build.stdout + build.stderr)
            build.check_returncode()
        argv = [sys.executable, '-m', 'pytest', '-c', '/dev/null', '--rootdir', str(ROOT),
                '-p', 'no:cacheprovider', '-p', 'deploy.ci.owned_pytest', '--basetemp', str(scratch / 'pytest'),
                '--junitxml', str(evidence / 'tests.xml'), '-q', str(ROOT / test), *args.pytest_args]
        receipt['argv'] = argv
        def interrupted(signum, frame):
            raise RuntimeError('owned runner interrupted by signal ' + str(signum))
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, interrupted)
        with (evidence / 'tests.log').open('w') as log:
            result = subprocess.Popen(argv, cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                result.wait(timeout=600)
            finally:
                # Kill only this invocation's newly created process group;
                # interrupted pytest cannot leave an authenticated child behind.
                for signum in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(result.pid, signum)
                    except ProcessLookupError:
                        break
                    if result.poll() is None:
                        try:
                            result.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
                result.wait(timeout=5)
        receipt['pytest_exit_code'] = result.returncode
        print((evidence / 'tests.log').read_text(), flush=True)
        data = json.loads((evidence / 'nodeids.json').read_text())
        from owned_inventory import MANUAL_NODEIDS
        expected_manual = sorted(key for key in MANUAL_NODEIDS if key.startswith(str(test) + '::'))
        if sorted(data['manual_deselected']) != expected_manual:
            raise RuntimeError('manual gate inventory drift')
        receipt['manual_gates'] = {key: MANUAL_NODEIDS[key] for key in expected_manual}
        for key in expected_manual:
            print('MANUAL_GATE ' + key + ': ' + MANUAL_NODEIDS[key], flush=True)
        if str(test) == 'tests_agent_refresh_timeout/test_full_main.py':
            from owned_inventory import FULL_MAIN_NODEIDS
            from unified_ci import check_complete
            check_complete(data, FULL_MAIN_NODEIDS)
            receipt['exact_nodeids'] = list(FULL_MAIN_NODEIDS)
        ids = data['collected']
        if not ids or len(ids) != len(set(ids)) or set(ids) != set(data['results']):
            raise RuntimeError('empty/partial/duplicate owning nodeID inventory')
        if any(row.get('call') != 'passed' or row.get('setup') != 'passed' or row.get('teardown') != 'passed' for row in data['results'].values()):
            return result.returncode or 1
        return result.returncode
    finally:
        if relay:
            relay.close()
        # Drop only exact objects whose random owner comments still match. A
        # failure/foreign identity preserves objects and fails, never broadens.
        verify_admin(admin, marker)
        with admin.cursor() as c:
            if receipt['created_database']:
                c.execute('SELECT shobj_description(oid,\'pg_database\'), pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (name,))
                if c.fetchone() != (owner, name):
                    raise RuntimeError('foreign cleanup database refused')
                c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            if receipt['created_role']:
                c.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s", (name,))
                if c.fetchone() != (owner,):
                    raise RuntimeError('foreign cleanup role refused')
                c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
            c.execute('SELECT count(*) FROM pg_database WHERE datname=%s', (name,))
            receipt['database_absent'] = c.fetchone()[0] == 0
            c.execute('SELECT count(*) FROM pg_roles WHERE rolname=%s', (name,))
            receipt['role_absent'] = c.fetchone()[0] == 0
        admin.close()
        receipt['elapsed_seconds'] = time.monotonic() - started
        receipt['relay_closed'] = relay is None or not relay.thread.is_alive()
        (evidence / 'isolation.json').write_text(json.dumps(receipt, indent=2))
        shutil.rmtree(scratch)
        if not (receipt['database_absent'] and receipt['role_absent'] and receipt['relay_closed']):
            raise RuntimeError('cleanup not verified')


if __name__ == '__main__':
    raise SystemExit(main())
