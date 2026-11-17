"""Frozen real .19 updater installs exact .20 bytes, never a synthetic updater."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from test_agent_legacy_upgrade import center
from test_agent_rollout_compat import ROOT

OLD_SHA = 'b9905d6db3ffad43da0484e25f536a7c04535e7cc1a774123a60aa145ffc1f43'


@pytest.fixture
def old19(tmp_path):
    directory = ROOT / 'tests_isolated/fixtures/agent_refresh_timeout'
    metadata = json.loads((directory / 'provenance.json').read_text())
    body = gzip.decompress((directory / 'stella-agent-0.6.19.py.gz').read_bytes())
    assert metadata == dict(commit='d4589329ae5684633ac928662e693963de122da6', source='agent/stella_agent.py', version='0.6.19', sha256=OLD_SHA, size=257975)
    assert len(body) == 257975 and hashlib.sha256(body).hexdigest() == OLD_SHA
    path = tmp_path / 'stella_agent.py'; path.write_bytes(body); path.chmod(0o640)
    spec = importlib.util.spec_from_file_location('frozen_19', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.AGENT_VERSION == '0.6.19'
    return module, path, body


@pytest.mark.parametrize('fallback', [False, True], ids=['httpx', 'urllib'])
def test_actual_19_updater_loads_and_installs_exact_20(old19, center, monkeypatch, fallback):
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    module, path, original = old19
    if fallback: module.httpx = None
    else: assert module.httpx is not None
    candidate = (ROOT / 'agent/stella_agent.py').read_bytes()
    assert candidate.count(b'AGENT_VERSION = "0.6.20"') == 1
    loads = []; real_load = module.Agent._validate_update_load
    def load(p, version):
        assert Path(p).read_bytes() == candidate and version == '0.6.20'
        loads.append(p); return real_load(p, version)
    agent = module.Agent(center[0], 'owned-19-only')
    with patch.object(module.Agent, '_validate_update_load', staticmethod(load)), patch.object(module.os, 'execv') as execute:
        agent.check_update()
    assert path.read_bytes() == candidate and path.stat().st_mode & 0o777 == 0o640
    assert len(loads) == 2 and loads[1] == str(path)
    execute.assert_called_once_with(sys.executable, [sys.executable, str(path)] + sys.argv[1:])
    assert center[1]['seen'] == ['/agent/version', '/agent/script']


@pytest.mark.parametrize('fallback', [False, True], ids=['httpx', 'urllib'])
@pytest.mark.parametrize('failure', ['hash', 'size', 'declaration'])
def test_19_rejects_exact_downloaded_body_against_matching_current_metadata(old19, center, monkeypatch, fallback, failure):
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    module, path, original = old19
    if fallback: module.httpx = None
    else: assert module.httpx is not None
    candidate = (ROOT / 'agent/stella_agent.py').read_bytes()
    assert candidate.count(b'AGENT_VERSION = "0.6.20"') == 1
    payload = candidate.replace(b'AGENT_VERSION = "0.6.20"', b'AGENT_VERSION = "0.6.21"', 1) if failure != 'size' else candidate
    assert len(payload) == len(candidate)
    manifest = dict(version='0.6.20', size=len(candidate), sha256=hashlib.sha256(candidate).hexdigest())
    if failure == 'size': manifest['size'] += 1
    elif failure == 'declaration': manifest['sha256'] = hashlib.sha256(payload).hexdigest()
    state = center[1]; state.update(manifest=manifest, body=payload)
    hashed_bodies = []; real_hash = module.hashlib.sha256
    def observed_hash(data=b'', *args, **kwargs):
        if isinstance(data, bytearray): hashed_bodies.append(bytes(data))
        return real_hash(data, *args, **kwargs)
    agent = module.Agent(center[0], 'owned-19-only')
    with patch.object(module.hashlib, 'sha256', observed_hash), patch.object(module.Agent, '_validate_update_load') as load, patch.object(module.os, 'execv') as execute:
        agent.check_update()
    assert path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o640
    execute.assert_not_called(); load.assert_not_called()
    assert state['seen'] == ['/agent/version', '/agent/script'], 'metadata must not short-circuit the download'
    if failure != 'size':
        assert hashed_bodies == [payload], 'old updater must compare exact received body, not unrelated metadata'
        assert (real_hash(payload).hexdigest() == manifest['sha256']) is (failure == 'declaration')
    assert not list(path.parent.glob('.stella-*'))


def test_actual_19_execs_exact_20_help_and_preserves_real_backup(old19, center, monkeypatch):
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    module, path, original = old19
    code = ('import runpy,sys; p=sys.argv[1]; m=runpy.run_path(p,run_name="owned_19"); '
            'sys.argv=[p,"--help"]; m["Agent"](' + repr(center[0]) + ',"owned-19-only").check_update()')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(path)], env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '--url' in result.stdout and '--token' in result.stdout
    assert path.read_bytes() == (ROOT / 'agent/stella_agent.py').read_bytes()
    backups = list(path.parent.glob('.stella-rollback-*.py'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert backups[0].stat().st_mode & 0o777 == 0o640
    assert center[1]['seen'] == ['/agent/version', '/agent/script']
