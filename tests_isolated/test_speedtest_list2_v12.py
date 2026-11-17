"""Real command-channel subprocess fixtures; no Agent bootstrap, network or DB."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def frontend_command():
    baseline = os.environ.get('SPEEDTEST_LIST2_BASELINE')
    source = (Path(baseline) / 'tools.before.vue' if baseline else ROOT / 'frontend/src/modules/servers/ToolsView.vue').read_text()
    area = source.split('async function fetchStServers()', 1)[1]
    return json.loads(re.search(r'command:\s*("(?:[^"\\]|\\.)*")', area).group(1))


@pytest.fixture
def channel(tmp_path, monkeypatch):
    # Include shell metacharacters and spaces: path values must never become shell source.
    instance = tmp_path / "own instance ' $(not-a-command)"
    (instance / 'bin').mkdir(parents=True)
    path_bin = tmp_path / 'path-bin'
    path_bin.mkdir()
    monkeypatch.setenv('PATH', str(path_bin))
    monkeypatch.setenv('STELLA_SPEEDTEST_GO', '/forged/inherited/speedtest-go')
    baseline = os.environ.get('SPEEDTEST_LIST2_BASELINE')
    tree = ast.parse((Path(baseline) / 'agent.before.py' if baseline else ROOT / 'agent/stella_agent.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Agent')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in
               {'_agent_bin', '_throughput_speedtest_exe', '_run_command', 'poll_and_execute'}]
    ns = dict(os=os, shutil=shutil, subprocess=subprocess, __file__=str(instance / 'stella_agent.py'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
        name='FixtureAgent', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])),
        str(ROOT / 'agent/stella_agent.py'), 'exec'), ns)
    agent = ns['FixtureAgent']()
    reports = []
    agent._post = lambda path, **kw: reports.append((path, kw['json_body']))
    calls = tmp_path / 'calls.jsonl'

    def executable(path, label, code=0, stdout=None, stderr=''):
        payload = stdout if stdout is not None else f'[ 1345] 1.25km 2.50ms  {label} by fixture'
        path.write_text(f'#!{sys.executable}\nimport json,sys\n'
                        f'with open({str(calls)!r}, "a") as f: f.write(json.dumps([{label!r},sys.argv[1:]])+"\\n")\n'
                        f'print({payload!r})\nprint({stderr!r},file=sys.stderr,end="")\nsys.exit({code})\n')
        path.chmod(0o755)
        return path

    def run(command=None):
        selected_command = command or frontend_command()
        # Legacy negative controls must never reach a resident absolute binary.
        # The original positive RED is safe because fixture PATH exits zero; broader
        # legacy negatives are intentionally blocked rather than run on this host.
        if '/opt/stella-agent/' in selected_command:
            if os.environ.get('SPEEDTEST_LIST2_BASELINE'):
                pytest.skip('legacy absolute fallback is unsafe outside a full exec sandbox')
            raise AssertionError('unsafe resident absolute fallback in candidate command')
        task = {'id': 31, 'command': selected_command,
                'bin': '/forged/task/bin', 'env': {'STELLA_SPEEDTEST_GO': '/forged/task/go'}}
        agent.token = 'fixture-token-not-a-credential'
        agent._assert_instance_identity = lambda: None  # no resident identity/config access
        def get(path, **kw):
            assert path == '/agent/tasks'
            assert kw == {'token': agent.token}
            return {'commands': [task]}
        agent._get = get  # transport boundary only; actual dispatcher and handler below
        agent.poll_and_execute()
        assert reports[-1][0] == '/agent/commands/31/result'
        return reports[-1][1]

    return SimpleNamespace(agent=agent, instance=instance, path_bin=path_bin, calls=calls,
                           executable=executable, run=run,
                           invocations=lambda: [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else [])


def test_actual_frontend_command_prefers_this_instance_not_path(channel):
    channel.executable(channel.instance / 'bin/speedtest-go', 'local')
    channel.executable(channel.path_bin / 'speedtest-go', 'path')
    selected = channel.agent._throughput_speedtest_exe()
    result = channel.run()
    assert selected == str(channel.instance / 'bin/speedtest-go')
    assert result['exit_code'] == 0
    assert 'local by fixture' in result['stdout']
    assert channel.invocations() == [['local', ['--list']]]


def test_local_failure_keeps_exact_error_exit_and_never_executes_path_copy(channel):
    channel.executable(channel.instance / 'bin/speedtest-go', 'local', 23,
                       stdout='[ 1345] 1.25km 2.50ms  Partial table by fixture',
                       stderr='dial tcp: synthetic refusal\n')
    channel.executable(channel.path_bin / 'speedtest-go', 'path')
    result = channel.run()
    # Generic channel means done=command exited, not success. UI must check exit_code.
    assert result == dict(status='done', exit_code=23,
                         stdout='[ 1345] 1.25km 2.50ms  Partial table by fixture\n',
                         stderr='dial tcp: synthetic refusal\n')
    assert channel.invocations() == [['local', ['--list']]]


@pytest.mark.parametrize('local_state', ['absent', 'nonexecutable', 'directory'])
def test_path_go_only_when_local_go_is_not_executable(channel, local_state):
    local = channel.instance / 'bin/speedtest-go'
    if local_state == 'nonexecutable':
        channel.executable(local, 'local').chmod(0o644)
    elif local_state == 'directory':
        local.mkdir()
    channel.executable(channel.path_bin / 'speedtest-go', 'path')
    assert channel.agent._throughput_speedtest_exe() == str(channel.path_bin / 'speedtest-go')
    result = channel.run()
    assert result['exit_code'] == 0
    assert 'path by fixture' in result['stdout']
    assert channel.invocations() == [['path', ['--list']]]


def test_only_other_vendors_is_missing_and_does_not_execute_anything(channel):
    for name in ['speedtest', 'speedtest-cli']:
        channel.executable(channel.path_bin / name, name)
    assert channel.agent._throughput_speedtest_exe() is None
    result = channel.run()
    assert result['exit_code'] == 127
    assert result['stdout'] == ''
    assert '未提供可用 speedtest-go' in result['stderr']
    assert channel.invocations() == []


def test_path_failure_is_not_retried_or_replaced_by_other_vendor(channel):
    channel.executable(channel.path_bin / 'speedtest-go', 'path', 28, stderr='network timed out\n')
    channel.executable(channel.path_bin / 'speedtest', 'wrong-vendor')
    result = channel.run()
    assert result['exit_code'] == 28
    assert result['stderr'] == 'network timed out\n'
    assert channel.invocations() == [['path', ['--list']]]


def test_existing_arbitrary_command_and_parent_environment_are_preserved(channel):
    channel.executable(channel.instance / 'bin/speedtest-go', 'local')
    before = dict(os.environ)
    result = channel.run('printf arbitrary-command; printf exact-stderr >&2; exit 19')
    assert result == dict(status='done', stdout='arbitrary-command', stderr='exact-stderr', exit_code=19)
    assert os.environ == before
    assert channel.invocations() == []


def test_context_is_derived_from_file_not_task_or_inherited_value(channel):
    channel.executable(channel.instance / 'bin/speedtest-go', 'local')
    result = channel.run('printf \'%s\' "$STELLA_SPEEDTEST_GO"')
    assert result['stdout'] == channel.agent._throughput_speedtest_exe()
    assert '/forged/' not in result['stdout']
    assert result['exit_code'] == 0


def test_old_agent_without_selector_context_fails_closed_instead_of_using_path(channel):
    channel.executable(channel.path_bin / 'speedtest-go', 'path')
    env = dict(os.environ)
    env.pop('STELLA_SPEEDTEST_GO', None)
    command = frontend_command()
    assert '/opt/stella-agent/' not in command, 'unsafe legacy absolute fallback'
    result = subprocess.run(command, shell=True, capture_output=True, text=True,
                            timeout=3, env=env)
    assert result.returncode == 127
    assert 'Agent 版本' in result.stderr
    assert result.stdout == ''
    assert channel.invocations() == []
