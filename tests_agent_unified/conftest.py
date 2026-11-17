"""Fail-closed OS fixture admission; never turn missing isolation into a skip."""
import os
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line('markers', 'unified_root_fixture: fabricated root/installer in an admitted OS sandbox')


def require_os_fixture():
    assert os.geteuid() == 0, 'real root subprocess acceptance required'
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    # Task-local runner makes the host root read-only, with private /mnt and net.
    if os.environ.get('UNIFIED_ROOTFS') == '1':
        assert any(row[4] == '/' and 'ro' in row[5].split(',') for row in mounts)
        import socket
        assert {name for _, name in socket.if_nameindex()} <= {'lo', 'gre0', 'gretap0', 'erspan0'}
        assert not Path('/proc/net/route').read_text().splitlines()[1:], 'routed host network forbidden'
        return
    # Mandatory CI uses a nonprivileged container's own overlay /mnt; it needs
    # no bwrap/unshare/mount, and retains real chroot/root UID acceptance.
    from deploy.ci.owned_pg import owned_target
    owned_target()
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    assert Path('/.dockerenv').exists() and not Path('/var/run/docker.sock').exists()
    assert not int(status['CapEff'], 16) & (1 << 21) and status['Seccomp'].strip() == '2'
    root = Path('/mnt'); info = root.lstat()
    assert not root.is_symlink() and info.st_uid == 0 and not info.st_mode & 0o022
    assert not any(row[4] == '/mnt' for row in mounts), 'host /mnt bind forbidden'


@pytest.fixture(autouse=True, scope='session')
def admitted_os_fixture():
    require_os_fixture()
