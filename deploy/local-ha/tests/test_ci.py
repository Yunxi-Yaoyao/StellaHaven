"""CI safety contract; requires PyYAML and Docker Compose, never a daemon."""
from pathlib import Path
import subprocess
import unittest
import yaml
from test_release import ROOT, IMAGE, OLD, FakeTransport, load


class CIContractTests(unittest.TestCase):
    def test_production_only_protected_master_with_legacy_target(self):
        ci = yaml.safe_load((ROOT.parents[1] / '.gitlab-ci.yml').read_text())
        rules = ci['deploy-k3s']['rules']
        self.assertIn('$CI_COMMIT_BRANCH == "master"', rules[0]['if'])
        self.assertIn('$CI_COMMIT_REF_PROTECTED == "true"', rules[0]['if'])
        self.assertIn('$STELLA_DEPLOY_TARGET == "k3s"', rules[0]['if'])
        self.assertEqual(rules[-1], {'when': 'never'})
        self.assertEqual(ci['deploy-k3s']['resource_group'], 'stella-production')
        self.assertNotIn('local-ha-apply', ci)
        self.assertEqual(ci['local-ha-live-readonly']['rules'][0]['when'], 'manual')
        self.assertEqual(ci['local-ha-live-readonly']['environment']['action'], 'verify')

    def test_latest_shell_guard_matrix(self):
        import os
        ci = yaml.safe_load((ROOT.parents[1] / '.gitlab-ci.yml').read_text())
        script = ci['build-images']['script']
        self.assertTrue(all(':latest' not in s for s in script[:-1]))
        self.assertTrue(any('$CI_COMMIT_SHA' in s for s in script))
        self.assertTrue(all('SHORT_SHA' not in s for s in script))
        for branch, protected, target, expected in [
            ('feature/test', 'false', 'k3s', False),
            ('feature/test', 'true', 'k3s', False),
            ('master', 'false', 'k3s', False),
            ('master', 'true', 'local-ha', False),
            ('master', 'true', 'unknown', False),
            ('master', 'true', 'k3s', True),
        ]:
            env = dict(os.environ, CI_COMMIT_BRANCH=branch, CI_COMMIT_REF_PROTECTED=protected,
                       STELLA_DEPLOY_TARGET=target, REGISTRY='invalid', CI_COMMIT_SHA='a'*40)
            output = subprocess.check_output(['sh', '-c', 'docker() { printf "DOCKER\\n"; };\n' + script[-1]], env=env, text=True)
            self.assertEqual(bool(output), expected, (branch, protected, target))

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
