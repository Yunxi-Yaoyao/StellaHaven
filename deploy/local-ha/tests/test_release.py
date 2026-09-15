"""Isolated stdlib tests; never import the application's DB conftest."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

IMAGE = 'registry.invalid/stella@sha256:' + 'a' * 64
OLD = 'registry.invalid/stella@sha256:' + 'b' * 64


def sample():
    return {
        'scope': 'stella-local-ha-v1', 'profile': 'manual',
        'nodes': [
            {'name': 'nyarch', 'primary_http': 200, 'in_recovery': False,
             'read_only': False, 'resources_ok': True, 'app_ok': True,
             'image': OLD, 'signing_key_id': 'same-secret-version', 'bundle_id': 'bundle-v1'},
            {'name': 'nas', 'primary_http': 503, 'in_recovery': True,
             'read_only': True, 'resources_ok': True, 'app_ok': True,
             'image': OLD, 'signing_key_id': 'same-secret-version', 'bundle_id': 'bundle-v1'},
        ],
    }


class PlanningTests(unittest.TestCase):
    def test_plans_only_live_standby_and_never_auto_promotes(self):
        self.assertTrue((ROOT / 'release.py').exists(), 'release planner missing')
        release = load('release')
        result = release.plan(sample(), IMAGE)
        self.assertEqual(result['primary'], 'nyarch')
        self.assertEqual(result['actions'], [{'op': 'update-app', 'node': 'nas', 'image': IMAGE, 'original_image': OLD}])
        self.assertFalse(result['automatic_failover'])
        self.assertEqual(result['next'], 'operator-planned-switchover-required')

    def test_rejects_unsafe_snapshots_and_mutable_images(self):
        release = load('release')
        changes = [
            lambda s: s.update(profile='automatic'),
            lambda s: s.update(scope='stella-pg'),
            lambda s: s['nodes'][1].update(primary_http=200, in_recovery=False, read_only=False),
            lambda s: s['nodes'][0].update(primary_http=503),
            lambda s: s['nodes'][1].update(in_recovery=False),
            lambda s: s['nodes'][1].update(resources_ok=False),
            lambda s: s['nodes'][1].update(signing_key_id='different'),
            lambda s: s['nodes'][1].update(bundle_id='different'),
            lambda s: s['nodes'][1].update(name='nyarch'),
        ]
        for change in changes:
            snapshot = sample()
            change(snapshot)
            with self.subTest(snapshot=snapshot), self.assertRaises(release.Refused):
                release.plan(snapshot, IMAGE)
        for image in ['repo:latest', IMAGE + '\n', IMAGE.upper()]:
            with self.assertRaises(release.Refused):
                release.plan(sample(), image)


class FakeTransport:
    def __init__(self, fail=False, role_drift=False):
        self.state = sample()
        self.calls = []
        self.fail = fail
        self.role_drift = role_drift
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        if self.role_drift and self.reads == 2:
            for n in self.state['nodes']:
                primary = n['name'] == 'nas'
                n.update(primary_http=200 if primary else 503,
                         in_recovery=not primary, read_only=not primary)
        return json.loads(json.dumps(self.state))

    def update(self, node, image, expected_image):
        self.calls.append((node, image, expected_image))
        target = next(n for n in self.state['nodes'] if n['name'] == node)
        target['image'] = image
        target['app_ok'] = not (self.fail and image == IMAGE)


class ExecutionTests(unittest.TestCase):
    def test_execute_verifies_image_and_only_mutates_standby(self):
        release = load('release')
        self.assertTrue(hasattr(release, 'run'), 'controlled runner missing')
        transport = FakeTransport()
        result = release.run(transport, IMAGE, apply=True, compatible=True)
        self.assertEqual(result['status'], 'standby-updated')
        self.assertEqual(transport.calls, [('nas', IMAGE, OLD)])
        self.assertGreaterEqual(transport.reads, 3)

    def test_failure_rolls_back_original_image_and_verifies(self):
        release = load('release')
        transport = FakeTransport(fail=True)
        result = release.run(transport, IMAGE, apply=True, compatible=True)
        self.assertEqual(result['status'], 'rolled-back')
        self.assertEqual(transport.calls, [('nas', IMAGE, OLD), ('nas', OLD, IMAGE)])
        self.assertEqual(result['rollback']['image'], OLD)

    def test_no_schema_compatibility_or_role_drift_means_no_write(self):
        release = load('release')
        for transport, compatible in [(FakeTransport(), False), (FakeTransport(role_drift=True), True)]:
            with self.assertRaises(release.Refused):
                release.run(transport, IMAGE, apply=True, compatible=compatible)
            self.assertEqual(transport.calls, [])

    def test_plan_never_writes(self):
        release = load('release')
        transport = FakeTransport()
        self.assertEqual(release.run(transport, IMAGE)['status'], 'planned')
        self.assertEqual(transport.calls, [])


if __name__ == '__main__':
    unittest.main()
