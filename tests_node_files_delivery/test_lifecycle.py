"""Owned installer/lifecycle contracts; the systemd adapter is a fixture, not PID1."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_deployable_linux_package_is_closed_and_byte_pinned(tmp_path):
    assert importlib.util.find_spec('agent.node_files_lifecycle'), 'missing Linux companion lifecycle installer'
    from agent import node_files_lifecycle as lc
    package = lc.build_package(ROOT / 'agent', tmp_path / 'package.tar')
    admitted = lc.read_package(tmp_path / 'package.tar', package['sha256'], package['release'])
    assert set(admitted) == {'package.json', 'manifest.json', 'stella_agent.py', 'node_files.py', 'node_files_delivery.py', 'node_files_lifecycle.py'}
    for name in ('stella_agent.py', 'node_files.py', 'node_files_delivery.py', 'node_files_lifecycle.py'):
        assert admitted[name] == (ROOT / 'agent' / name).read_bytes()
    assert package['sha256'] == hashlib.sha256((tmp_path / 'package.tar').read_bytes()).hexdigest()
    assert json.loads(admitted['package.json'])['platforms'] == ['linux']
    with pytest.raises(lc.LifecycleError):
        lc.read_package(tmp_path / 'package.tar', '0' * 64, package['release'])


def test_authenticated_ready_callback_is_an_explicit_worker_boundary():
    import inspect
    from agent import node_files_delivery as d
    assert 'on_ready' in inspect.signature(d.run_worker).parameters, 'readiness must follow successful authenticated claim, not process start'
    assert 'before_tick' in inspect.signature(d.run_worker).parameters, 'companion must stop claiming when its main instance identity is removed'


def test_no_default_service_or_root_grant_and_explicit_dependency_precheck(tmp_path):
    from agent import node_files_lifecycle as lc
    result = lc.dependency_probe(sys.executable)
    assert result['httpx']
    unit = lc.unit_text('a' * 24, tmp_path / 'code', tmp_path / 'config', Path(sys.executable), tmp_path / 'runtime')
    assert 'Type=notify\n' in unit
    assert 'AmbientCapabilities=' not in unit and 'CAP_NET_RAW' not in unit
    assert 'NoNewPrivileges=yes' in unit
    assert 'node_files_lifecycle.py worker' in unit
    assert 'stella_agent.py\n' not in unit
    assert f'EnvironmentFile={tmp_path}/config/agent.env' in unit
    assert 'Environment=STELLA_FILE_ROOTS={}' in unit
    assert 'STELLA_TOKEN' not in unit
    assert not (tmp_path / 'code').exists()
    with pytest.raises(lc.LifecycleError):
        lc.dependency_probe('/nonexistent/python')


def test_windows_unsupported_before_any_service_or_filesystem_change(monkeypatch, tmp_path):
    from agent import node_files_lifecycle as lc
    monkeypatch.setattr(lc.sys, 'platform', 'win32')
    with pytest.raises(lc.LifecycleError, match='windows_unsupported'):
        lc.Lifecycle('a' * 24, code_base=tmp_path / 'code', config_base=tmp_path / 'config', unit_base=tmp_path / 'units')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('fault', ['extra', 'duplicate', 'symlink', 'missing', 'member-body', 'package-mode', 'release-pin'])
def test_outer_package_refuses_incomplete_or_mutated_bootstrap_even_with_new_tar_pin(tmp_path, fault):
    import io
    import tarfile
    from agent import node_files_lifecycle as lc
    package = tmp_path / 'package.tar'
    original = lc.build_package(ROOT / 'agent', package)
    bodies = lc.read_package(package, original['sha256'], original['release'])
    if fault == 'missing':
        del bodies['node_files_delivery.py']
    elif fault == 'member-body':
        bodies['node_files_lifecycle.py'] += b'\n# unauthorized mutation\n'
    elif fault == 'package-mode':
        meta = json.loads(bodies['package.json'])
        meta['mode'] = 'windows'
        bodies['package.json'] = json.dumps(meta).encode()
    with tarfile.open(package, 'w') as archive:
        for name, body in bodies.items():
            item = tarfile.TarInfo(name)
            item.size = len(body)
            if fault == 'symlink' and name == 'node_files.py':
                item.type, item.linkname = tarfile.SYMTYPE, '/etc/passwd'
            archive.addfile(item, io.BytesIO(body))
        if fault in ('extra', 'duplicate'):
            item = tarfile.TarInfo('../escape' if fault == 'extra' else 'node_files.py')
            archive.addfile(item, io.BytesIO(b''))
    pin = hashlib.sha256(package.read_bytes()).hexdigest()
    with pytest.raises((lc.LifecycleError, ValueError)):
        lc.read_package(package, pin, '0' * 64 if fault == 'release-pin' else original['release'])
