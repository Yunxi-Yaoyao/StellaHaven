"""CI safety contract; requires PyYAML and Docker Compose, never a daemon."""
from pathlib import Path
import importlib.util
import subprocess
import unittest
import yaml
from test_release import ROOT, IMAGE, OLD, FakeTransport, load


class CIContractTests(unittest.TestCase):
    def test_production_only_protected_master_with_legacy_target(self):
        ci = yaml.safe_load((ROOT.parents[1] / '.gitlab-ci.yml').read_text())
        rules = ci['deploy-k3s']['rules']
        self.assertEqual(rules, [{'when': 'never'}])
        self.assertEqual(ci['deploy-k3s']['resource_group'], 'stella-production')
        self.assertNotIn('local-ha-apply', ci)
        self.assertEqual(ci['local-ha-live-readonly']['rules'], [{'when': 'never'}])
        self.assertEqual(ci['local-ha-live-readonly']['environment']['action'], 'verify')

    def test_latest_shell_guard_matrix(self):
        ci = yaml.safe_load((ROOT.parents[1] / '.gitlab-ci.yml').read_text())
        self.assertEqual(ci['build-images']['script'], ['sh deploy/ci/runner-isolation/build-rootless.sh'])
        script = (ROOT.parents[1] / 'deploy/ci/runner-isolation/build-rootless.sh').read_text()
        self.assertNotIn(':latest', script)
        self.assertNotIn('SHORT_SHA', script)
        self.assertIn('$CI_COMMIT_SHA', script)
        self.assertIn('buildctl-daemonless.sh build', script)
        self.assertNotIn('docker build', script)
        self.assertNotIn('--network=host', script)

    def test_readonly_inventory_and_current_primary_guards(self):
        live = load('validate_live')
        inventory = {'scope': 'stella-local-ha-v1', 'environment': 'nonproduction', 'current_primary': 'nyarch'}
        result = live.validate(inventory, FakeTransport(), IMAGE)
        self.assertFalse(result['deployment_authorized'])
        self.assertEqual(result['apply_status'], 'blocked')
        for bad in [dict(inventory, environment='production'), dict(inventory, current_primary='nas'), {}]:
            with self.assertRaises(ValueError):
                live.validate(bad, FakeTransport(), IMAGE)

    def test_ssh_writes_remain_blocked_even_with_valid_images(self):
        release = load('release')
        transport = release.SSHTransport({'nyarch': 'test-nyarch', 'nas': 'test-nas'})
        with self.assertRaises(ValueError):
            transport.update('nas', IMAGE, OLD)
        with self.assertRaises(ValueError):
            release.SSHTransport({'nyarch': '-oProxyCommand=unsafe', 'nas': 'test-nas'})


# Mandatory existing local-ha-contract gate, with no new job or shard commands.
_prewarm_spec = importlib.util.spec_from_file_location(
    'ci_prewarm_contract', ROOT.parents[1] / 'deploy/ci/runner-isolation/test_prewarm.py')
assert _prewarm_spec is not None and _prewarm_spec.loader is not None
_prewarm = importlib.util.module_from_spec(_prewarm_spec)
_prewarm_spec.loader.exec_module(_prewarm)
PrewarmContract = _prewarm.PrewarmContract
PrewarmShellTests = _prewarm.PrewarmShellTests

# Existing mandatory discovery also owns the documentation gate/renderer delta.
_documentation_spec = importlib.util.spec_from_file_location(
    'ci_documentation_contract', ROOT.parents[1] / 'deploy/ci/runner-isolation/test_documentation.py')
assert _documentation_spec is not None and _documentation_spec.loader is not None
_documentation = importlib.util.module_from_spec(_documentation_spec)
_documentation_spec.loader.exec_module(_documentation)
DocumentationCIContract = _documentation.DocumentationCIContract

# Keep browser preparation/hash negatives inside mandatory local-ha discovery.
_browser_spec = importlib.util.spec_from_file_location(
    'ci_browser_dependencies', ROOT.parents[1] / 'deploy/ci/runner-isolation/test_browser_dependencies.py')
assert _browser_spec is not None and _browser_spec.loader is not None
_browser = importlib.util.module_from_spec(_browser_spec)
_browser_spec.loader.exec_module(_browser)
BrowserDependencies = _browser.BrowserDependencies

# Backend APT cannot spend the runner's 20m ceiling before the first test.
_backend_dependencies_spec = importlib.util.spec_from_file_location(
    'ci_backend_dependencies', ROOT.parents[1] / 'deploy/ci/runner-isolation/test_backend_dependencies.py')
assert _backend_dependencies_spec is not None and _backend_dependencies_spec.loader is not None
_backend_dependencies = importlib.util.module_from_spec(_backend_dependencies_spec)
_backend_dependencies_spec.loader.exec_module(_backend_dependencies)
BackendDependencies = _backend_dependencies.BackendDependencies
