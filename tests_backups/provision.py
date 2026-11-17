"""Owned, network-none PG18 fixture. Never accepts an existing DSN/container."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import uuid


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def main():
    root = Path(os.environ['TMPDIR']) / ('stella-backup-' + uuid.uuid4().hex[:12])
    root.mkdir(mode=0o700)
    token = uuid.uuid4().hex[:12]
    name = 'stella-backup-test-' + token
    owner = 'backup-center-backend-20261017-' + token
    password = secrets.token_urlsafe(24)
    db = 'stella_backup_test_' + token
    user = 'backup_test_' + token
    cid = run('docker', 'run', '-d', '--name', name, '--network', 'none',
              '--label', 'io.stella.test.owner=' + owner, '--memory', '768m',
              '--tmpfs', '/var/lib/postgresql:rw,size=512m',
              '-e', 'POSTGRES_USER=' + user, '-e', 'POSTGRES_PASSWORD=' + password,
              '-e', 'POSTGRES_DB=' + db, 'postgres:18')
    try:
        data = json.loads(run('docker', 'inspect', cid))[0]
        assert data['Config']['Labels']['io.stella.test.owner'] == owner
        assert data['HostConfig']['NetworkMode'] == 'none'
        assert not data['NetworkSettings']['Ports']
        for _ in range(120):
            check = subprocess.run(['docker', 'exec', cid, 'pg_isready', '-h', '127.0.0.1', '-U', user, '-d', db], capture_output=True)
            if check.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('fixture not TCP ready')
        tools = root / 'pg18'
        tools.mkdir()
        run('docker', 'cp', cid + ':/usr/lib/postgresql/18/bin', str(tools / 'bin'))
        libs = tools / 'lib'
        libs.mkdir()
        run('docker', 'cp', cid + ':/usr/lib/x86_64-linux-gnu/libpq.so.5.18', str(libs / 'libpq.so.5'))
        receipt = {'root': str(root), 'id': cid, 'name': name, 'owner': owner,
                   'pid': data['State']['Pid'], 'database': db, 'user': user,
                   'password': password, 'restore_db': 'stella_backup_restore_' + token}
        fd = os.open(root / 'private.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(receipt, out)
        print(json.dumps({k: v for k, v in receipt.items() if k != 'password'}))
    except BaseException:
        run('docker', 'rm', '-f', cid)
        raise


if __name__ == '__main__':
    main()
