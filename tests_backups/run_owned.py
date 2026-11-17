"""Run a bounded test command in the exact owned fixture network namespace."""
import json
import os
from pathlib import Path
import subprocess
import sys

PYTHON = '/opt/hermes-workstation/stella-ui-notes-integration-20261017/.venv/bin/python'
ROOT = Path(__file__).resolve().parents[1]


def main():
    private = Path(sys.argv[1])
    receipt = json.loads(private.read_text())
    actual = json.loads(subprocess.check_output(['docker', 'inspect', receipt['id']]))[0]
    assert actual['Id'] == receipt['id']
    assert actual['Config']['Labels']['io.stella.test.owner'] == receipt['owner']
    assert actual['HostConfig']['NetworkMode'] == 'none'
    assert actual['State']['Pid'] == receipt['pid'] and actual['State']['Running']
    assert not actual['NetworkSettings']['Ports']
    root = Path(receipt['root'])
    home = root / 'home'
    home.mkdir(exist_ok=True)
    assert not (root / '.env').exists()
    env = {'PATH': str(root / 'pg18/bin') + ':/usr/bin:/usr/sbin:/bin',
           'LD_LIBRARY_PATH': str(root / 'pg18/lib'), 'HOME': str(home),
           'TMPDIR': str(root), 'PYTHONPATH': str(ROOT),
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'POSTGRES_HOST': '127.0.0.1',
           'POSTGRES_PORT': '5432', 'POSTGRES_DB': receipt['database'],
           'POSTGRES_USER': receipt['user'], 'POSTGRES_PASSWORD': receipt['password'],
           'STELLA_SECRET_KEY': 'isolated-backup-test-signing-key-not-production',
           'STELLA_SHARED_STATE': 'postgres', 'STELLA_BLOB_STORAGE': 'postgres',
           'STELLA_MAIN_ORIGIN': 'http://testserver', 'STELLA_TRUSTED_ORIGINS': 'http://testserver',
           'STELLA_COOKIE_SECURE': 'false', 'STELLA_BACKUP_FIXTURE': str(private),
           'STELLA_BACKUP_DATA_ROOT': str(root / 'data'),
           'STELLA_BACKUP_PG_BIN': str(root / 'pg18/bin')}
    args = sys.argv[2:] or ['-m', 'pytest', '--noconftest', str(ROOT / 'tests_backups'), '-q']
    number = len(list(root.glob('run-*.log'))) + 1
    log = root / f'run-{number:03d}.log'
    result = subprocess.run(['nsenter', '-t', str(receipt['pid']), '-n', PYTHON, *args],
                            cwd=root, env=env, capture_output=True, text=True, timeout=240)
    header = json.dumps({'argv':args,'python':PYTHON,'cwd':str(root),'network':'none',
                         'fixture_id':receipt['id'],'owner':receipt['owner'],'published_ports':{},
                         'postgres_host':'127.0.0.1','postgres_port':5432,'database':receipt['database'],
                         'user':receipt['user'],'inherited_environment':'scrubbed','env_file_present':False})
    text = header + '\n' + result.stdout + result.stderr
    text = text.replace(receipt['password'], '<redacted>')
    log.write_text(text)
    print(text)
    print(json.dumps({'log': str(log), 'exit_code': result.returncode, 'network': 'none',
                      'python': PYTHON, 'cwd': str(root), 'config_env': 'explicit-test-only'}))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
