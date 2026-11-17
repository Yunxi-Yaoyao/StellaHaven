"""All mutating canary tests own scratch paths and fake the service adapter."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'deploy/agent_nyarch_canary.py'


def test_tool_present_for_canary_and_rollback():
    assert TOOL.exists(), 'Missing scoped single-node canary/rollback tool'


@pytest.fixture
def tool(tmp_path, monkeypatch):
    assert TOOL.exists(), 'Missing scoped single-node canary/rollback tool'
    spec = importlib.util.spec_from_file_location('owned_canary_tool', TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This fixture owns a synthetic service, not Nyarch's Python 3.14 unit.
    # Keep the production binding unchanged; load real payloads with CI's Python.
    assert module.INTERPRETER == '/usr/bin/python3.14'
    monkeypatch.setattr(module, 'INTERPRETER', sys.executable)
    target = tmp_path / 'resident/stella_agent.py'
    target.parent.mkdir()
    import gzip
    target.write_bytes(gzip.decompress((ROOT / 'tests_isolated/fixtures/agent_rollout/nyarch_0.6.15.py.gz').read_bytes()))
    target.chmod(0o640)
    monkeypatch.setattr(module, 'TARGET', target)
    monkeypatch.setattr(module, 'require_root', lambda: None)
    module.test_calls = []
    module.test_state = {'active': True, 'pid': 100, 'fail_start': False}
    def service(op):
        module.test_calls.append(op)
        module.test_state['active'] = op == 'start'
        if op == 'stop':
            module.test_state['pid'] = 0
        if op == 'start':
            module.test_state['pid'] += 1
            if module.test_state['fail_start']:
                module.test_state['fail_start'] = False
                raise RuntimeError('fixture service start failed')
    monkeypatch.setattr(module, 'service', service)
    def inspect_local():
        return dict(machine_id=module.MACHINE_ID, node_id=19, service_user='stella',
                    interpreter=sys.executable, unit_sha256='1'*64, env_sha256='2'*64,
                    target_sha256=module.sha(target.read_bytes()), active=module.test_state['active'],
                    pid=module.test_state['pid'], pids=[module.test_state['pid']] if module.test_state['active'] else [], runtime_url='https://stella.xiya.live')
    monkeypatch.setattr(module, 'inspect_local', inspect_local)
    module.test_real_check_center = module.check_center
    monkeypatch.setattr(module, 'check_center', lambda: dict(node_id=19, version='0.6.18'))
    module.test_target = target
    module.test_backup = tmp_path / 'private-canary'
    # This helper remains pinned to the approved 25bc canary, not new 728b.
    from nav_files_evidence_fixture import frozen
    module.test_artifact = tmp_path / 'historical-center/agent/stella_agent.py'
    module.test_artifact.parent.mkdir(parents=True)
    module.test_artifact.write_bytes(frozen('agent/stella_agent.py',module.NEW_SHA256))
    return module


@pytest.mark.parametrize('pin', ['0.6.15', '0.6.11'])
def test_center_accepts_only_explicit_expected_parked_pin(tool, monkeypatch, tmp_path, pin):
    from fastapi.testclient import TestClient
    from test_agent_rollout_compat import release_app
    env = tmp_path / 'agent.env'
    env.write_text('STELLA_URL=https://stella.xiya.live\nSTELLA_TOKEN=synthetic-fixture\n')
    monkeypatch.setattr(tool, 'ENV_FILE', env)
    monkeypatch.setattr(tool, 'PARKED_VERSION', pin, raising=False)
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION', pin)
    class Reply:
        status = 200
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return self.body[:limit]
    class Opener:
        def open(self, request, **kw):
            path = request.full_url.removeprefix(tool.CENTER)
            if path == '/agent/identity':
                assert request.get_header('Authorization') == 'Bearer synthetic-fixture'
                return Reply(json.dumps(dict(node_id=19, source_version='0.6.18', source_sha256=tool.NEW_SHA256, source_size=tool.NEW_SIZE)).encode())
            with TestClient(release_app(tool.test_artifact.parents[1])) as client:
                response = client.get(path)
                assert response.status_code == 200
                return Reply(response.content)
    monkeypatch.setattr(tool.urllib.request, 'build_opener', lambda *a: Opener())
    assert tool.test_real_check_center() == dict(node_id=19, version='0.6.18')


def test_plan_has_no_service_or_file_side_effects(tool):
    before = tool.test_target.read_bytes()
    result = tool.plan(tool.test_artifact)
    assert result['node_id'] == 19
    assert result['source_sha256'] == tool.NEW_SHA256
    assert tool.test_calls == [] and tool.test_target.read_bytes() == before
    assert not tool.test_backup.exists()


def test_apply_and_rollback_restore_exact_original_bytes_mode_and_owner(tool):
    old = tool.test_target.read_bytes()
    st = tool.test_target.stat()
    tool.apply(tool.test_artifact, tool.test_backup)
    assert tool.test_target.read_bytes() == tool.test_artifact.read_bytes()
    receipt = json.loads((tool.test_backup / 'receipt.json').read_text())
    assert receipt['phase'] == 'active' and receipt['after']['pid'] != receipt['before']['pid']
    assert tool.test_backup.stat().st_mode & 0o777 == 0o700
    assert (tool.test_backup / 'original.py').stat().st_mode & 0o777 == 0o600
    tool.rollback(tool.test_backup)
    assert tool.test_target.read_bytes() == old
    after = tool.test_target.stat()
    assert (after.st_uid, after.st_gid, after.st_mode) == (st.st_uid, st.st_gid, st.st_mode)
    assert tool.test_calls == ['stop', 'start', 'stop', 'start']
    assert json.loads((tool.test_backup / 'receipt.json').read_text())['phase'] == 'rolled_back'


def test_failed_start_automatically_restores_original(tool):
    old = tool.test_target.read_bytes()
    tool.test_state['fail_start'] = True
    with pytest.raises(RuntimeError, match='fixture service start failed'):
        tool.apply(tool.test_artifact, tool.test_backup)
    assert tool.test_target.read_bytes() == old
    assert tool.test_state['active'] is True
    assert json.loads((tool.test_backup / 'receipt.json').read_text())['phase'] == 'rolled_back'


def test_wrong_artifact_is_rejected_before_backup_or_service(tool, tmp_path):
    artifact = tmp_path / 'forged.py'
    artifact.write_bytes(tool.test_artifact.read_bytes().replace(b'0.6.18', b'0.6.19', 1))
    with pytest.raises(ValueError): tool.apply(artifact, tool.test_backup)
    assert tool.test_calls == [] and not tool.test_backup.exists()


def test_drifted_resident_is_not_replaced(tool):
    tool.test_target.write_bytes(b'# drift')
    with pytest.raises(ValueError): tool.apply(tool.test_artifact, tool.test_backup)
    assert tool.test_calls == [] and not tool.test_backup.exists()


def test_rollback_does_not_overwrite_unknown_new_source(tool):
    tool.apply(tool.test_artifact, tool.test_backup)
    tool.test_target.write_bytes(b'# unrelated update')
    calls = list(tool.test_calls)
    with pytest.raises(ValueError): tool.rollback(tool.test_backup)
    assert tool.test_target.read_bytes() == b'# unrelated update'
    assert tool.test_calls == calls


def test_reused_backup_is_rejected_without_stopping_service(tool):
    tool.test_backup.mkdir()
    with pytest.raises(FileExistsError): tool.apply(tool.test_artifact, tool.test_backup)
    assert tool.test_calls == []


def test_surviving_cgroup_children_block_source_replacement(tool, monkeypatch):
    original = tool.inspect_local
    def inspect():
        value = original()
        if not value['active']:
            value['pids'] = [999]
        return value
    monkeypatch.setattr(tool, 'inspect_local', inspect)
    before = tool.test_target.read_bytes()
    with pytest.raises(ValueError):
        tool.apply(tool.test_artifact, tool.test_backup)
    assert tool.test_target.read_bytes() == before
    assert (tool.test_backup / 'original.py').read_bytes() == before


def test_rollback_rejects_tampered_backup(tool):
    tool.apply(tool.test_artifact, tool.test_backup)
    (tool.test_backup / 'original.py').write_bytes(b'# tampered')
    calls = list(tool.test_calls)
    with pytest.raises(ValueError): tool.rollback(tool.test_backup)
    assert tool.test_calls == calls


def test_new_optional_files_artifact_is_not_the_approved_canary(tool):
    from nav_files_evidence_fixture import current_agent
    current,previous=current_agent()
    assert tool.test_artifact.read_bytes()==previous and current!=previous
    with pytest.raises(ValueError,match='artifact differs from approved exact'):
        tool.apply(ROOT/'agent/stella_agent.py',tool.test_backup)
    assert tool.test_calls==[] and not tool.test_backup.exists()
