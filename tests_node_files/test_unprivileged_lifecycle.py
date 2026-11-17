"""Dropped-UID acceptance in private mount+noncePG namespaces only."""
import json
import os
import sys
from pathlib import Path
import pwd
import subprocess

from tests_node_files.test_lifecycle_protocol import make_fixture, real_identity_transport


def test_actual_instance_uid_staging_notify_worker_and_private_credentials(system, tmp_path, monkeypatch):
    assert os.environ.get('NODE_FILES_NAMESPACE_FIXTURE') == '1', 'run with owned runner --owned-mount; never chmod host ancestors'
    assert tmp_path.is_relative_to('/mnt')
    account = pwd.getpwnam('nobody')
    assert account.pw_uid != 0
    lc, lifecycle, adapter, main_unit, env = make_fixture(system, tmp_path, monkeypatch)
    for path in (tmp_path, *tmp_path.parents, lifecycle.code.parent, lifecycle.config.parent, lifecycle.config):
        if path == Path('/mnt') or path.is_relative_to('/mnt'):
            path.chmod(0o755)
    os.chown(lifecycle.code, account.pw_uid, account.pw_gid)
    os.chown(lifecycle.code / 'stella_agent.py', account.pw_uid, account.pw_gid)
    monkeypatch.setattr(lc.pwd, 'getpwnam', lambda name: account)
    lifecycle = lc.Lifecycle(lifecycle.iid, code_base=lifecycle.code.parent, config_base=lifecycle.config.parent, unit_base=lifecycle.unit.parent, systemd=adapter, allow_loopback=True)
    adapter.uid, adapter.gid = account.pw_uid, account.pw_gid
    package = tmp_path / 'uid-package.tar'
    info = lc.build_package(Path(lc.__file__).parent, package)
    try:
        result = lifecycle.install(package, info['sha256'], info['release'], sys.executable)
        assert result['authenticated_ready'] and result['integrity']
        proc = dict(line.split(':', 1) for line in Path(f'/proc/{adapter.process.pid}/status').read_text().splitlines() if ':' in line)
        assert set(proc['Uid'].split()) == {str(account.pw_uid)}
        assert (lifecycle.base / 'releases/current.json').stat().st_uid == account.pw_uid
        assert (lifecycle.code / '.update.lock').stat().st_uid == account.pw_uid, 'installer-created shared update lock must remain available to main Agent UID'
        assert Path(lifecycle.state()['runtime']).stat().st_uid == 0
        denied = subprocess.run([sys.executable, '-I', '-B', '-c', 'import sys;open(sys.argv[1],"rb").read(1)', str(lifecycle.config / 'agent.env')], env=lc.clean_env(), cwd='/', preexec_fn=lc.demote(account.pw_uid, account.pw_gid), capture_output=True)
        assert denied.returncode == 1 and b'PermissionError' in denied.stderr
        from app.database import sessionLocal
        from app.models.node_file import FileAgent
        with sessionLocal() as db:
            assert db.get(FileAgent, 930001).roots == {}
        stopped = lifecycle.stop()
        assert stopped['systemd']['ActiveState'] == 'inactive'
        (Path(os.environ['NODE_FILES_EVIDENCE']) / 'actual-uid.json').write_text(json.dumps({'uid': account.pw_uid, 'gid': account.pw_gid, 'worker_pid': adapter.process.pid, 'ready': True, 'stage_store_uid': (lifecycle.base / 'releases/current.json').stat().st_uid, 'runtime_uid': Path(lifecycle.state()['runtime']).stat().st_uid, 'credentials_unreadable_to_worker': True, 'systemd_boundary': 'fixture adapter; real setgroups/setgid/setuid child + real sd_notify datagram', 'stopped': True}, indent=2))
    finally:
        adapter.halt()
