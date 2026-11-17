"""No-DB unified Agent admission, exact collection and private-overlay execution.

Socket ownership is a parent/child token, NOT a PostgreSQL relay. No production
credentials or app environment reach pytest. Native installer commands are owned
fakes in the original fixture; real root probes chroot to fabricated data.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def expected_ids(test):
    manifest = json.loads(Path(__file__).with_name('unified-nodeids.json').read_text())
    ids = [node for node in manifest if node.startswith(str(test) + '::')]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('unregistered unified test inventory')
    return ids


def check_complete(data, expected):
    if (not expected or len(expected) != len(set(expected)) or
            sorted(data['collected']) != sorted(expected) or
            set(data['results']) != set(expected) or data['manual_deselected'] or data['exit_code'] != 0 or
            any(row != dict(setup='passed', call='passed', teardown='passed') for row in data['results'].values())):
        raise ValueError('empty/partial/duplicate/skipped/failed unified nodeID inventory')


def audit_boundary(event, args, roots):
    """Process-local tripwire; native subprocess isolation is the OS fixture."""
    if event in ('socket.connect', 'socket.bind'):
        address = args[1]
        if args[0].family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('unified external network forbidden')
    paths = []
    if event == 'open' and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        if args[0] == '/dev/null' and not args[2] & (os.O_CREAT | os.O_TRUNC):
            import stat
            info = Path('/dev/null').lstat()
            if stat.S_ISCHR(info.st_mode) and (os.major(info.st_rdev), os.minor(info.st_rdev)) == (1, 3):
                return
        paths = [(args[0], -1)]
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.chown'):
        # Audit tuples carry dir_fd last; a relative pathname must be resolved
        # against that actual directory, not the harmless-looking current cwd.
        paths = [(args[0], args[-1])]
    elif event == 'os.truncate':
        paths = [(args[0], -1)]
    elif event in ('os.rename', 'os.link'):
        paths = [(args[0], args[2]), (args[1], args[3])]
    elif event == 'os.symlink':
        paths = [(args[1], args[2])]
    for path, dir_fd in paths:
        if isinstance(path, int):
            path = os.readlink('/proc/self/fd/' + str(path))
        value = Path(os.fsdecode(path))
        if not value.is_absolute() and isinstance(dir_fd, int) and dir_fd >= 0:
            value = Path(os.readlink('/proc/self/fd/' + str(dir_fd))) / value
        value = value.absolute()
        # unlink/rename/symlink operate on the entry, not its referent. Resolve
        # only its parent so deleting a private python3 symlink is not confused
        # with modifying the read-only interpreter it points to.
        checked = (value.parent.resolve() / value.name if event in
                   ('os.remove', 'os.rename', 'os.symlink', 'os.mkdir', 'os.rmdir') else value.resolve())
        if not any(checked.is_relative_to(root.resolve()) for root in roots) or '..' in value.parts:
            raise ValueError('unified write outside private fixture: ' + str(value))


def fixture_target():
    """Verify the exact live runner parent before an installer/root fixture runs."""
    root = Path(os.environ['TMPDIR'])
    path = Path(os.environ['STELLA_CI_OWNED_RECEIPT'])
    nonce = os.environ.get('STELLA_CI_OWNED_NONCE', '')
    if (not re.fullmatch('[a-f0-9]{32}', nonce) or root != Path('/mnt/stella-unified-' + nonce)
            or root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022
            or path != root/('owner-' + nonce + '.json') or path.is_symlink()
            or path.stat().st_uid != 0 or path.stat().st_mode & 0o077):
        raise ValueError('foreign unified fixture receipt')
    data = json.loads(path.read_text())
    if (set(data) != {'format', 'kind', 'nonce', 'pid', 'job', 'port', 'test'} or
            data['format'] != 1 or data['kind'] != 'unified-no-db' or data['nonce'] != nonce or
            data['pid'] != os.getppid() or data['job'] != os.environ.get('CI_JOB_ID') or
            os.environ.get('CI') != 'true' or os.environ.get('GITLAB_CI') != 'true' or
            not re.fullmatch('[1-9][0-9]*', data['job']) or
            any(k.startswith(('POSTGRES_', 'PG')) or k in ('DATABASE_URL', 'STELLA_SECRET_KEY') for k in os.environ)):
        raise ValueError('unified fixture parent/environment mismatch')
    expected_ids(data['test'])
    port = data['port']
    if type(port) is not int or not 1024 < port < 65536:
        raise ValueError('invalid unified listener')
    inodes = {line.split()[9] for line in Path('/proc/net/tcp').read_text().splitlines()[1:]
              if line.split()[1] == f'0100007F:{port:04X}' and line.split()[3] == '0A'}
    sockets = set()
    for fd in Path(f'/proc/{os.getppid()}/fd').iterdir():
        try:
            sockets.add(os.readlink(fd))
        except FileNotFoundError:
            pass
    if not any('socket:[' + inode + ']' in sockets for inode in inodes):
        raise ValueError('unified listener is not owned by exact live parent')
    return data


def run(test):
    # Reuse the existing stdlib container and service identity admission without
    # creating a database or importing psycopg2/app for this no-DB test family.
    sys.path.insert(0, str(Path(__file__).parent))
    from owned_pg import admitted_marker
    spec = importlib.util.spec_from_file_location('owned_runner_boundary', Path(__file__).with_name('run-owned-suite.py'))
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    capabilities = boundary.private_job_root()
    marker = admitted_marker()
    for key in ('DATABASE_URL', 'STELLA_SECRET_KEY', 'STELLA_PRODUCTION_SSH_KEY', 'STELLA_PRODUCTION_INVENTORY',
                'STELLA_PRODUCTION_KNOWN_HOSTS', 'KUBECONFIG', 'KUBE_CONFIG', 'LOCAL_HA_SSH_CONFIG', 'LOCAL_HA_INVENTORY', 'PGHOST', 'PGSERVICE'):
        if os.environ.get(key):
            raise ValueError('production/foreign environment forbidden: ' + key)
    ids = expected_ids(test)
    source = ROOT/test
    if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(ROOT):
        raise ValueError('foreign unified source')
    nonce = secrets.token_hex(16)
    scratch = Path('/mnt/stella-unified-' + nonce)
    evidence = Path(os.environ.get('STELLA_CI_EVIDENCE', str(ROOT/'.ci-owned-evidence')))/Path(test).with_suffix('')
    evidence.mkdir(parents=True, exist_ok=False)
    scratch.mkdir(mode=0o755)
    receipt = dict(test=str(test), nonce=nonce, capabilities=capabilities, created_database=False, created_role=False)
    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            identity = dict(format=1, kind='unified-no-db', nonce=nonce, pid=os.getpid(), job=marker['job'],
                            port=listener.getsockname()[1], test=str(test))
            token = scratch/('owner-' + nonce + '.json')
            token.write_text(json.dumps(identity)); token.chmod(0o600)
            env = dict(PATH=os.environ['PATH'], HOME=str(scratch), TMPDIR=str(scratch), PYTHONPATH=str(ROOT),
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1',
                       CI='true', GITLAB_CI='true', CI_JOB_ID=marker['job'],
                       STELLA_CI_UNIFIED='1', STELLA_CI_OWNED_NONCE=nonce, STELLA_CI_OWNED_RECEIPT=str(token),
                       NODE_FILES_EVIDENCE=str(evidence))
            argv = [sys.executable, '-m', 'pytest', '-c', '/dev/null', '--rootdir', str(ROOT),
                    '-p', 'no:cacheprovider', '-p', 'deploy.ci.owned_pytest', '--basetemp', str(scratch/'pytest'),
                    '--junitxml', str(evidence/'tests.xml'), '-q', str(source)]
            receipt['argv'] = argv
            def interrupted(signum, frame):
                raise RuntimeError('unified runner interrupted: ' + str(signum))
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, interrupted)
            with (evidence/'tests.log').open('w') as log:
                child = subprocess.Popen(argv, cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    child.wait(timeout=600)
                finally:
                    for signum in (signal.SIGTERM, signal.SIGKILL):
                        try:
                            os.killpg(child.pid, signum)
                        except ProcessLookupError:
                            break
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass
                    child.wait(timeout=5)
            receipt['pytest_exit_code'] = child.returncode
            print((evidence/'tests.log').read_text(), flush=True)
            check_complete(json.loads((evidence/'nodeids.json').read_text()), ids)
            receipt['exact_nodeids'] = ids
            return child.returncode
    finally:
        shutil.rmtree(scratch)
        receipt['scratch_absent'] = not scratch.exists()
        (evidence/'isolation.json').write_text(json.dumps(receipt, indent=2))
