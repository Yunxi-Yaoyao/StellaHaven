#!/usr/bin/env python3
"""One explicitly approved Nyarch/node19 Agent canary. Default is read-only plan.

Never changes center announcements, environment, units, privileges or other nodes.
Only fixed 0.6.15 -> exact production 0.6.18 bytes; no version rewriting.
Local activation is NOT proof of center heartbeat or successful ICMP sampling.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import Any

MACHINE_ID = '3b4efaebf3f64b3082f1c0014ac67eca'
NODE_ID = 19
TARGET = Path('/opt/stella-agent/stella_agent.py')
ENV_FILE = Path('/etc/stella-agent/agent.env')
UNIT = Path('/etc/systemd/system/stella-agent.service')
INTERPRETER = '/usr/bin/python3.14'
OLD_SHA256 = '515303074b3bb533baa5363ac5abc53310f7951710caa5d4a638260f2627e63a'
NEW_SHA256 = '25bc5e8c4f8e6ec262b89118098ea6d7b796f0bf3e75d8b10bd9a0aab070208b'
NEW_SIZE = 232703
CENTER = 'https://stella.xiya.live'
PARKED_VERSION = '0.6.15'  # .11 is an explicit existing-image emergency hold, never an arbitrary pin.
STABLE = ('machine_id', 'node_id', 'service_user', 'interpreter', 'unit_sha256', 'env_sha256', 'runtime_url')


def sha(body):
    return hashlib.sha256(body).hexdigest()


def regular_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('regular file required')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            return f.read(2 * 1024 * 1024 + 1)
    finally:
        os.close(fd)


def require_root():
    if os.geteuid() != 0:
        raise ValueError('run locally as already-authorized root; no privilege expansion')


def command(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if result.returncode:
        # Never include command, environment, unit or stderr in a public error.
        raise RuntimeError('local service command failed')
    return result.stdout.strip()


def service(action):
    if action not in ('stop', 'start'):
        raise ValueError('invalid service action')
    command(['/usr/bin/systemctl', action, 'stella-agent.service'])


def service_pids():
    root = Path('/sys/fs/cgroup/system.slice/stella-agent.service')
    if not root.exists():
        return []
    paths = [root / 'cgroup.procs', *root.glob('**/cgroup.procs')]
    return sorted({int(pid) for path in paths for pid in path.read_text().split()})


def inspect_local() -> dict[str, Any]:
    require_root()
    if Path('/etc/machine-id').read_text().strip() != MACHINE_ID:
        raise ValueError('wrong machine: this tool is only for Nyarch/node19')
    raw = command(['/usr/bin/systemctl', 'show', 'stella-agent.service',
                   '-p', 'User', '-p', 'ActiveState', '-p', 'MainPID', '-p', 'ExecStart', '-p', 'FragmentPath', '-p', 'KillMode', '-p', 'ControlGroup'])
    fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    if fields['User'] != 'stella' or fields['FragmentPath'] != str(UNIT) or fields['KillMode'] != 'control-group':
        raise ValueError('service ownership/unit/kill-mode drift')
    if fields['ControlGroup'] not in ('', '/system.slice/stella-agent.service'):
        raise ValueError('service cgroup drift')
    if str(TARGET) not in fields['ExecStart']:
        raise ValueError('service entrypoint drift')
    pid = int(fields['MainPID'])
    if pid:
        if str(Path(f'/proc/{pid}/exe').resolve()) != INTERPRETER:
            raise ValueError('service interpreter drift')
        if str(TARGET).encode() not in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0'):
            raise ValueError('service command drift')
    return dict(machine_id=MACHINE_ID, node_id=NODE_ID, service_user=fields['User'],
                interpreter=INTERPRETER, unit_sha256=sha(regular_bytes(UNIT)),
                env_sha256=sha(regular_bytes(ENV_FILE)), target_sha256=sha(regular_bytes(TARGET)),
                active=fields['ActiveState'] == 'active', pid=pid, pids=service_pids(), runtime_url=CENTER)


def check_center():
    # Tokens stay inside this process; do not print file text, request headers or
    # caught exceptions. TLS verification is enabled and redirects are refused.
    env = {}
    for line in regular_bytes(ENV_FILE).decode().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            words = shlex.split(value)
            if len(words) == 1:
                env[key] = words[0]
    if env.get('STELLA_URL', '').rstrip('/') != CENTER or not env.get('STELLA_TOKEN'):
        raise ValueError('agent center/token binding unavailable')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    def get(path, authenticated=False):
        headers = {'Authorization': 'Bearer ' + env['STELLA_TOKEN']} if authenticated else {}
        try:
            with opener.open(urllib.request.Request(CENTER + path, headers=headers), timeout=10) as response:
                if response.status != 200:
                    raise ValueError('center metadata unavailable')
                return json.loads(response.read(16385))
        except urllib.error.HTTPError as error:
            raise ValueError('center ' + path + ' HTTP ' + str(error.code)) from None
        except (OSError, ValueError):
            raise ValueError('center metadata transport/JSON unavailable') from None
    identity = get('/agent/identity', True)
    if identity.get('node_id') != NODE_ID:
        raise ValueError('token is not bound to node19')
    if (identity.get('source_version'), identity.get('source_sha256'), identity.get('source_size')) != ('0.6.18', NEW_SHA256, NEW_SIZE):
        raise ValueError('center identity source drift')
    if PARKED_VERSION not in ('0.6.11', '0.6.15'):
        raise ValueError('unsupported parked policy')
    if get('/agent/version') != {'version': PARKED_VERSION}:
        raise ValueError('exact parked announcement required; fleet release is forbidden')
    release = get('/agent/release')
    if release != dict(source_version='0.6.18', source_sha256=NEW_SHA256, source_size=NEW_SIZE,
                       announcement_version=PARKED_VERSION, rollout_policy='pinned'):
        raise ValueError('source/announcement metadata drift')
    return dict(node_id=NODE_ID, version='0.6.18')


def validate_artifact(path):
    body = regular_bytes(path)
    if len(body) != NEW_SIZE or sha(body) != NEW_SHA256:
        raise ValueError('artifact differs from approved exact .18 bytes')
    tree = ast.parse(body)
    versions = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'AGENT_VERSION']
    if versions != ['0.6.18']:
        raise ValueError('artifact version mismatch')
    probe = ('import runpy,sys; '
             'sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError("network refused")) if e in '
             '("socket.connect","socket.bind","socket.getaddrinfo") else None); '
             'm=runpy.run_path(sys.argv[1],run_name="canary_load_only"); '
             'sys.exit(73 if m.get("AGENT_VERSION")=="0.6.18" and callable(m.get("Agent")) and callable(m.get("main")) else 1)')
    result = subprocess.run([INTERPRETER, '-I', '-B', '-c', probe, str(path.resolve())],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if result.returncode != 73:
        raise ValueError('artifact cannot load in actual service interpreter')
    return body


def assert_stable(before, after):
    if any(before[k] != after[k] for k in STABLE):
        raise ValueError('machine/unit/environment binding changed')


def plan(artifact) -> dict[str, Any]:
    validate_artifact(artifact)
    before = inspect_local()
    if before['target_sha256'] != OLD_SHA256 or not before['active'] or before['pid'] <= 0:
        raise ValueError('original .15 active process required')
    check_center()
    return dict(node_id=NODE_ID, source_sha256=NEW_SHA256, source_size=NEW_SIZE,
                action='single-node-only; explicit execute flag required', before=before)


def write_private(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(body); f.flush(); os.fsync(f.fileno())


def receipt(backup, value):
    path = backup / 'receipt.json'
    fd, temporary = tempfile.mkstemp(prefix='.receipt-', dir=backup)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(temporary, path)


def replace_source(body, metadata):
    fd, temporary = tempfile.mkstemp(prefix='.canary-', suffix='.py', dir=TARGET.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(body); f.flush(); os.fsync(f.fileno())
        os.chown(temporary, metadata['uid'], metadata['gid'])
        os.chmod(temporary, metadata['mode'])
        os.replace(temporary, TARGET)
        directory = os.open(TARGET.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def apply(artifact, backup):
    require_root()
    prepared = plan(artifact)
    body = validate_artifact(artifact)
    before = prepared['before']
    original = regular_bytes(TARGET)
    st = TARGET.stat()
    if sha(original) != OLD_SHA256:
        raise ValueError('resident changed before backup')
    backup.mkdir(mode=0o700)  # exclusive; never reuse or overwrite backups
    write_private(backup / 'original.py', original)
    state = dict(phase='prepared', before=before, source_sha256=NEW_SHA256,
                 metadata=dict(uid=st.st_uid, gid=st.st_gid, mode=stat.S_IMODE(st.st_mode)))
    receipt(backup, state)
    try:
        service('stop')
        stopped = inspect_local()
        assert_stable(before, stopped)
        if stopped['active'] or stopped['pid'] != 0 or stopped['pids'] or stopped['target_sha256'] != OLD_SHA256:
            raise ValueError('service did not stop cleanly or resident drifted')
        replace_source(body, state['metadata'])
        service('start')
        after = inspect_local()
        assert_stable(before, after)
        if after['target_sha256'] != NEW_SHA256 or not after['active'] or after['pid'] <= 0 or after['pid'] == before['pid']:
            raise ValueError('new local process activation failed')
        state.update(phase='active', after=after)
        receipt(backup, state)
    except Exception:
        rollback(backup)
        raise
    return dict(phase='active', node_id=NODE_ID, backup=str(backup),
                next='parent must verify fresh reported version/capability/samples; no fleet release')


def rollback(backup):
    require_root()
    if backup.is_symlink() or backup.stat().st_uid != os.geteuid() or backup.stat().st_mode & 0o077:
        raise ValueError('private original backup required')
    state = json.loads(regular_bytes(backup / 'receipt.json'))
    body = regular_bytes(backup / 'original.py')
    if sha(body) != OLD_SHA256 or state.get('source_sha256') != NEW_SHA256:
        raise ValueError('backup provenance mismatch')
    current = inspect_local()
    assert_stable(state['before'], current)
    if current['target_sha256'] not in (NEW_SHA256, OLD_SHA256):
        raise ValueError('refuse overwriting unrelated newer source')
    service('stop')
    stopped = inspect_local()
    assert_stable(state['before'], stopped)
    if stopped['active'] or stopped['pid'] != 0 or stopped['pids'] or stopped['target_sha256'] not in (NEW_SHA256, OLD_SHA256):
        raise ValueError('rollback stop/drift check failed; keep private backup')
    replace_source(body, state['metadata'])
    service('start')
    after = inspect_local()
    assert_stable(state['before'], after)
    if after['target_sha256'] != OLD_SHA256 or not after['active'] or after['pid'] <= 0:
        raise ValueError('rollback activation failed; keep private backup')
    state.update(phase='rolled_back', rollback=after)
    receipt(backup, state)
    return dict(phase='rolled_back', node_id=NODE_ID, backup=str(backup))


def main():
    global PARKED_VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'apply', 'rollback'), nargs='?', default='plan')
    parser.add_argument('--artifact', type=Path, default=Path(__file__).resolve().parents[1] / 'agent/stella_agent.py')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--parked-version', choices=('0.6.11', '0.6.15'), default='0.6.15')
    parser.add_argument('--execute-node19', action='store_true', help='explicit operator approval; NOT fleet approval')
    args = parser.parse_args()
    PARKED_VERSION = args.parked_version
    if args.action != 'plan' and (not args.execute_node19 or args.backup is None):
        parser.error('writes require --execute-node19 and a fresh root-private --backup path')
    try:
        result = plan(args.artifact) if args.action == 'plan' else apply(args.artifact, args.backup) if args.action == 'apply' else rollback(args.backup)
        print(json.dumps(result, indent=2))
    except Exception as error:
        # Errors from this module contain fixed safe text, never private headers.
        print(json.dumps({'blocked': True, 'reason': str(error) if isinstance(error, ValueError) else type(error).__name__}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
