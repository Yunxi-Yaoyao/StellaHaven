import ast
from copy import deepcopy
import yaml
import pytest
from app.services.website_check import safe_address
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_explicit_ipv6_loopback_is_valid_self_hosted_target():
    assert safe_address('::1')=='::1'
@pytest.mark.parametrize('address',['::','fe80::1','fd00:ec2::254','169.254.169.254','100.100.100.200','2001:db8::1'])
def test_loopback_exception_does_not_allow_metadata_or_reserved(address):
    with pytest.raises(ValueError):safe_address(address)
def _assert_ci_installs_real_js_checker(ci, helper_source):
    job = ci['backend-test']
    command = 'python3 deploy/ci/runner-isolation/backend_dependencies.py backend'
    # Exact executable command, not a comment/string mention or `|| true`.
    assert job['before_script'].count(command) == 1
    assert job.get('allow_failure', False) is False
    assert job['script'][-1] == '.venv/bin/python deploy/ci/run-backend-shard.py'
    tree = ast.parse(helper_source)
    packages, = [ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'PACKAGES' for t in node.targets)]
    assert packages == ['ffmpeg', 'sudo', 'nodejs', 'acl']
    versions, = [ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'VERSIONS' for t in node.targets)]
    assert versions['nodejs'] == ['node', '--version']


def test_runtime_and_ci_install_real_js_syntax_checker():
    assert 'install -y --no-install-recommends ffmpeg nodejs' in (ROOT/'Dockerfile').read_text()
    _assert_ci_installs_real_js_checker(
        yaml.safe_load((ROOT/'.gitlab-ci.yml').read_text()),
        (ROOT/'deploy/ci/runner-isolation/backend_dependencies.py').read_text())


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'ignored_failure', 'soft_job', 'no_nodejs', 'wrong_node_probe'])
def test_ci_js_checker_contract_rejects_broken_helper_wiring(damage):
    ci = deepcopy(yaml.safe_load((ROOT/'.gitlab-ci.yml').read_text()))
    helper = (ROOT/'deploy/ci/runner-isolation/backend_dependencies.py').read_text()
    command = 'python3 deploy/ci/runner-isolation/backend_dependencies.py backend'
    if damage == 'missing':
        ci['backend-test']['before_script'].remove(command)
    elif damage == 'duplicate':
        ci['backend-test']['before_script'].append(command)
    elif damage == 'ignored_failure':
        ci['backend-test']['before_script'] = [s+' || true' if s == command else s for s in ci['backend-test']['before_script']]
    elif damage == 'soft_job':
        ci['backend-test']['allow_failure'] = True
    elif damage == 'no_nodejs':
        helper = helper.replace("PACKAGES = ['ffmpeg', 'sudo', 'nodejs', 'acl']", "PACKAGES = ['ffmpeg', 'sudo', 'acl']")
    else:
        helper = helper.replace("'nodejs': ['node', '--version']", "'nodejs': ['true']")
    with pytest.raises(AssertionError):
        _assert_ci_installs_real_js_checker(ci, helper)
