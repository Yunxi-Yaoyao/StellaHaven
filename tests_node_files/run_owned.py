"""Create an owned network-none PG container, enter its netns, run tests, remove.
No existing DSN is accepted. Python and Node are pinned; inherited env discarded.
"""
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
EVIDENCE = Path('/opt/hermes-workstation/docs/records/2026-10-23-stella-production-feedback/node-files')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', default='F1')
    parser.add_argument('--evidence-subdir', default='', help='Owned child directory; existing F1/F2 evidence stays untouched')
    parser.add_argument('tests', nargs='*', default=['tests_node_files'])
    args = parser.parse_args()
    evidence = (EVIDENCE / args.evidence_subdir).resolve()
    assert evidence == EVIDENCE or EVIDENCE in evidence.parents, 'evidence must stay under owned node-files records'
    evidence.mkdir(parents=True, exist_ok=True)
    key = uuid4().hex[:12]
    scratch = Path(os.environ['TMPDIR']) / ('node-files-' + key)
    scratch.mkdir(mode=0o700)
    owner = 'node-files-' + key
    name = 'stella-node-files-' + key
    user, database, password = 'nodefiles_' + key, 'nodefiles_' + key, secrets.token_urlsafe(32)
    def cmd(*argv):
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()
    cid = cmd('docker', 'run', '-d', '--name', name, '--network', 'none', '--label', 'io.stella.test.owner=' + owner, '--memory', '768m', '--tmpfs', '/var/lib/postgresql:rw,size=512m', '-e', 'POSTGRES_USER=' + user, '-e', 'POSTGRES_PASSWORD=' + password, '-e', 'POSTGRES_DB=' + database, 'postgres:18')
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
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(scratch), 'TMPDIR': str(scratch), 'PYTHONPATH': str(REPO), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': '5432', 'POSTGRES_USER': user, 'POSTGRES_PASSWORD': password, 'POSTGRES_DB': database, 'STELLA_SECRET_KEY': secrets.token_hex(48), 'NODE_FILES_EVIDENCE': str(evidence), 'PLAYWRIGHT_BROWSERS_PATH': '/root/.cache/ms-playwright'}
        argv = ['nsenter', '-t', str(data['State']['Pid']), '-n', PYTHON, '-m', 'pytest', '-c', '/dev/null', '--rootdir', str(REPO), '-p', 'no:cacheprovider', '--basetemp', str(scratch / 'pytest'), '--junitxml', str(evidence / (args.phase + '.xml')), '-q'] + [str(REPO / x) for x in args.tests]
        result = subprocess.run(argv, env=env, cwd=scratch, capture_output=True, text=True, timeout=240)
        (evidence / (args.phase + '.log')).write_text(result.stdout + result.stderr)
        (evidence / (args.phase + '-isolation.json')).write_text(json.dumps({'network': 'none', 'container': name, 'owner': owner, 'database': database, 'python': PYTHON, 'cwd': str(scratch), 'env_keys': sorted(env), 'exit_code': result.returncode}, indent=2))
        print(result.stdout, result.stderr)
        return result.returncode
    finally:
        current = json.loads(cmd('docker', 'inspect', cid))[0]
        assert current['Config']['Labels']['io.stella.test.owner'] == owner
        cmd('docker', 'rm', '-f', cid)
        assert subprocess.run(['docker', 'inspect', cid], capture_output=True).returncode != 0


if __name__ == '__main__':
    raise SystemExit(main())
