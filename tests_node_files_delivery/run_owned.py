"""Owned network-none PostgreSQL/TCP tests, no existing DSN or production env."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

PYTHON = '/opt/Yunxi-workstation/Stella/.venv/bin/python'
REPO = Path(__file__).resolve().parents[1]
EVIDENCE = Path('/opt/hermes-workstation/docs/records/2026-10-23-stella-production-feedback/node-files-completion')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True)
    parser.add_argument('--owned-mount', action='store_true', help='Private mount namespace exposes only owned scratch at /mnt for dropped-UID workers')
    parser.add_argument('--lifecycle', action='store_true', help='Store evidence under node-files-completion/lifecycle')
    parser.add_argument('tests', nargs='+')
    args = parser.parse_args()
    assert args.phase and '/' not in args.phase and args.phase not in ('.', '..')
    evidence = (EVIDENCE / 'lifecycle' if args.lifecycle else EVIDENCE) / args.phase
    evidence.mkdir(parents=True, exist_ok=False)
    key = uuid4().hex[:12]
    scratch = Path(os.environ['TMPDIR']) / ('nfd-' + key)
    scratch.mkdir(mode=0o700)
    owner = 'node-files-delivery-' + key
    name = 'stella-node-files-delivery-' + key
    user = database = 'nodefiles_' + key
    password = secrets.token_urlsafe(32)
    def cmd(*argv):
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()
    cid = cmd('docker', 'run', '-d', '--name', name, '--network', 'none', '--label', 'io.stella.test.owner=' + owner, '--memory', '768m', '--tmpfs', '/var/lib/postgresql:rw,size=512m', '-e', 'POSTGRES_USER=' + user, '-e', 'POSTGRES_PASSWORD=' + password, '-e', 'POSTGRES_DB=' + database, 'postgres:18')
    receipt: dict[str, object] = {'owner': owner, 'container': name, 'container_id': cid, 'network': 'none', 'database': database, 'python': PYTHON, 'cwd': str(scratch), 'source': str(REPO)}
    try:
        data = json.loads(cmd('docker', 'inspect', cid))[0]
        assert data['Config']['Labels']['io.stella.test.owner'] == owner
        assert data['HostConfig']['NetworkMode'] == 'none' and not data['NetworkSettings']['Ports']
        for _ in range(120):
            if subprocess.run(['docker', 'exec', cid, 'pg_isready', '-h', '127.0.0.1', '-U', user, '-d', database], capture_output=True).returncode == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('owned PostgreSQL not ready')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(scratch), 'TMPDIR': str(scratch), 'PYTHONPATH': str(REPO), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': '5432', 'POSTGRES_USER': user, 'POSTGRES_PASSWORD': password, 'POSTGRES_DB': database, 'STELLA_SECRET_KEY': secrets.token_hex(48), 'NODE_FILES_EVIDENCE': str(evidence)}
        visible = Path('/mnt') if args.owned_mount else scratch
        env.update(HOME=str(visible), TMPDIR=str(visible))
        pytest_argv = [PYTHON, '-m', 'pytest', '-c', '/dev/null', '--rootdir', str(REPO), '-p', 'no:cacheprovider', '--basetemp', str(visible / 'pytest'), '--junitxml', str(evidence / 'tests.xml'), '-q'] + [str(REPO / x) for x in args.tests]
        argv = ['nsenter', '-t', str(data['State']['Pid']), '-n']
        if args.owned_mount:
            env['NODE_FILES_NAMESPACE_FIXTURE'] = '1'
            code = 'import os,subprocess,sys;subprocess.run(["mount","--bind",sys.argv[1],"/mnt"],check=True);os.execve(sys.argv[2],sys.argv[2:],os.environ)'
            argv += ['unshare', '--mount', '--propagation', 'private', PYTHON, '-I', '-B', '-c', code, str(scratch)]
        argv += pytest_argv
        receipt.update(env_keys=sorted(env), argv=argv)
        result = subprocess.run(argv, env=env, cwd=scratch, capture_output=True, text=True, timeout=240)
        (evidence / 'tests.log').write_text(result.stdout + result.stderr)
        receipt['exit_code'] = result.returncode
        print(result.stdout, result.stderr)
        return result.returncode
    finally:
        current = json.loads(cmd('docker', 'inspect', cid))[0]
        assert current['Config']['Labels']['io.stella.test.owner'] == owner
        cmd('docker', 'rm', '-f', cid)
        receipt['container_absent'] = subprocess.run(['docker', 'inspect', cid], capture_output=True).returncode != 0
        (evidence / 'isolation.json').write_text(json.dumps(receipt, indent=2))
        assert receipt['container_absent']


if __name__ == '__main__':
    raise SystemExit(main())
