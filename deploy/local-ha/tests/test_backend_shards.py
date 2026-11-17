"""Offline sharding contracts: all gates, isolated processes, no budget waiver."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'deploy/ci/run-backend-shard.py'


class BackendShardContract(unittest.TestCase):
    def load(self):
        self.assertTrue(SCRIPT.is_file(), 'bounded complete backend shard runner is absent')
        spec = importlib.util.spec_from_file_location('backend_shards', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_all_original_commands_exactly_once(self):
        module = self.load()
        commands = [cmd for i in range(1, 7) for cmd in module.plan(ROOT, i, 6)]
        expected = [
            ['tests'], ['tests_ha', '--noconftest'],
            ['tests_notes_upgrade', '--confcutdir=tests_notes_upgrade'],
            ['tests_website_settings', '--confcutdir=tests_website_settings'],
            ['tests_generic_templates', '--noconftest'], ['tests_experience', '--noconftest'],
        ] + [[str(p.relative_to(ROOT)), '--noconftest'] for p in sorted((ROOT/'tests_isolated').glob('test_*.py'))] + [[str(p.relative_to(ROOT))] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for p in sorted((ROOT/d).glob('test_*.py'))]
        self.assertCountEqual(commands, expected)
        self.assertEqual(len(commands), len({tuple(cmd) for cmd in commands}))
        for i in range(1, 7):
            self.assertTrue(module.plan(ROOT, i, 6))
        for i, total in [(0, 4), (5, 4), (1, 201), (1, 0), ('1', 4),
                         (True, 4), (1.0, 4), (1, 4.0), (None, 4)]:
            with self.assertRaises(ValueError):
                module.plan(ROOT, i, total)

    def test_setup_aware_lpt_uses_projected_completion_and_browser_setup_once(self):
        module = self.load()
        self.assertEqual(module.COMMON_SETUP_SECONDS, 75.0)
        self.assertEqual(module.BROWSER_SETUP_SECONDS, 140.0)
        commands = [list(cmd) for cmd in module.GROUP_COMMANDS] + [
            [str(p.relative_to(ROOT)), '--noconftest']
            for p in sorted((ROOT / 'tests_isolated').glob('test_*.py'))] + [[str(p.relative_to(ROOT))] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for p in sorted((ROOT/d).glob('test_*.py'))]
        commands.sort(key=lambda cmd: (-module.estimated_seconds(cmd), tuple(cmd)))
        expected = [[] for _ in range(4)]
        loads = [75.0] * 4
        browser = [False] * 4
        charges = [0] * 4
        for command in commands:
            needs = any(Path(path).is_relative_to(Path(command[0]))
                        for path in module.UNCONDITIONAL_BROWSER_TESTS)
            weight = module.estimated_seconds(command)
            target = min(range(4), key=lambda i: (
                loads[i] + weight + (140.0 if needs and not browser[i] else 0), i))
            extra = 140.0 if needs and not browser[target] else 0
            loads[target] += weight + extra
            charges[target] += bool(extra)
            browser[target] |= needs
            expected[target].append(command)
        actual = [module.plan(ROOT, i, 4) for i in range(1, 5)]
        self.assertEqual(actual, expected)
        self.assertTrue(any(charges))
        self.assertTrue(all(charge <= 1 for charge in charges))
        for shard, load, needs in zip(actual, loads, browser):
            self.assertAlmostEqual(load, 75 + sum(module.estimated_seconds(c) for c in shard)
                                   + (140 if needs else 0))

    def test_browser_activation_cost_is_paid_once_and_ties_use_shard_index(self):
        module = self.load()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            (root / 'tests_isolated').mkdir()
            names = ['test_a.py', 'test_b.py', 'test_c.py', 'test_d.py', 'test_e.py']
            for name in reversed(names):
                (root / 'tests_isolated' / name).touch()
            paths = ['tests_isolated/' + name for name in names]
            with patch.object(module, 'GROUP_COMMANDS', ()), patch.object(
                    module, 'UNCONDITIONAL_BROWSER_TESTS', frozenset(paths[3:])), patch.object(
                    module, 'ESTIMATED_SECONDS', dict(zip(paths, [500, 400, 300, 200, 190]))):
                plans = [module.plan(root, i, 4) for i in range(1, 5)]
                self.assertEqual(plans, [[[p, '--noconftest']] for p in paths[:3]] + [
                    [[p, '--noconftest'] for p in paths[3:]]])
                # Charging the second browser 140s again would move it to shard 3.
                self.assertEqual(sum(module.estimated_seconds(c) for c in plans[3]) + 75 + 140, 605)
            with patch.object(module, 'GROUP_COMMANDS', ()), patch.object(
                    module, 'UNCONDITIONAL_BROWSER_TESTS', frozenset()), patch.object(
                    module, 'ESTIMATED_SECONDS', dict.fromkeys(paths, 10)):
                self.assertEqual([module.plan(root, i, 4) for i in range(1, 5)], [
                    [[paths[0], '--noconftest'], [paths[4], '--noconftest']],
                    [[paths[1], '--noconftest']], [[paths[2], '--noconftest']],
                    [[paths[3], '--noconftest']]])

    def test_ci168_completed_timings_and_ci170_completed_documentation(self):
        module = self.load()
        # Whole-command CI168 timestamps, with 5% and ceiling, not pytest's
        # internal test-only durations. Documentation never completed in 949;
        # CI170 job968 finally completed it: 22.710521s, 1 passed, ceiling+5%=24.
        for path, minimum in {
            'tests': 238,
            'tests_isolated/test_api_response_completion.py': 468,
            'tests_isolated/test_api_response_final_gate.py': 193,
            'tests_isolated/test_api_response_ci167_evidence.py': 63,
            'tests_isolated/test_api_response_v6_runtime.py': 30,
            'tests_isolated/test_documentation_export.py': 24,
        }.items():
            with self.subTest(path=path):
                observed = module._COPY_TIMINGS['observations'].get(path)
                if observed is None:
                    self.assertGreaterEqual(module.estimated_seconds([path]), minimum)
                else:
                    self.assertGreaterEqual(observed['old_weight'], minimum)
                    import math
                    current = module._V23_TIMINGS['observations'][path]['completed_seconds']
                    optimized = module._DERIVATION_TIMINGS['observations'].get(path) if path in module._DERIVATION_TIMINGS['modeled_replacements'] else None
                    expected_weight = math.ceil(1.20*optimized['completed_seconds']+5) if optimized else max(observed['new_weight'],math.ceil(1.20*current+5))
                    audit = module._AUDIT_TIMINGS['observations'].get(path)
                    if audit:
                        expected_weight = max(expected_weight, math.ceil(1.20*audit['completed_seconds']+5))
                    self.assertEqual(module.estimated_seconds([path]), expected_weight)

    def test_weighted_plan_balances_the_complete_original_inventory(self):
        module = self.load()
        plans = [module.plan(ROOT, i, 7) for i in range(1, 8)]
        def cost(commands):
            needs = any(Path(path).is_relative_to(Path(cmd[0]))
                        for cmd in commands for path in module.UNCONDITIONAL_BROWSER_TESTS)
            return 75 + sum(module.estimated_seconds(cmd) for cmd in commands) + (140 if needs else 0)
        loads = [cost(commands) for commands in plans]
        files = sorted((ROOT / 'tests_isolated').glob('test_*.py'))
        old = [[list(cmd) for cmd in module.GROUP_COMMANDS]] + [
            [[str(p.relative_to(ROOT)), '--noconftest']
             for n, p in enumerate(files) if n % 3 == offset] for offset in range(3)]
        old_loads = [cost(commands) for commands in old]
        self.assertGreater(max(old_loads) - min(old_loads), 500)
        # A late one-time browser activation can make LPT less even; enforce
        # current100s modeled reserve, not an arbitrary equal-load shape.
        self.assertLessEqual(max(loads), 1100, '1200s runner cap includes setup')
        self.assertLess(max(loads), max(old_loads))
        self.assertEqual(plans, [module.plan(ROOT, i, 7) for i in range(1, 8)])
        self.assertTrue(all(plans))
        self.assertTrue(all(any(cmd[0].startswith('tests_isolated/') for cmd in shard)
                            for shard in plans))
        self.assertEqual({i for i in range(1, 8) if module.browser_required(ROOT, i, 7)},
                         {i for i, commands in enumerate(plans, 1)
                          if any(cmd[0] in module.UNCONDITIONAL_BROWSER_TESTS for cmd in commands)})

    def test_unknown_files_default_ties_and_invalid_weights(self):
        module = self.load()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            (root / 'tests_isolated').mkdir()
            names = ['test_new_z.py', 'test_new_a.py', 'test_new_b.py']
            for name in names:
                (root / 'tests_isolated' / name).touch()
            expected = [list(cmd) for cmd in module.GROUP_COMMANDS] + [
                ['tests_isolated/' + name, '--noconftest'] for name in names]
            plans = [module.plan(root, i, 4) for i in range(1, 5)]
            self.assertCountEqual([cmd for shard in plans for cmd in shard], expected)
            self.assertTrue(all(plans))
            self.assertEqual(module.estimated_seconds(['tests_isolated/test_new_a.py']),
                             module.DEFAULT_ESTIMATED_SECONDS)
            for path in (root / 'tests_isolated').iterdir():
                path.unlink()
            for name in reversed(names):
                (root / 'tests_isolated' / name).touch()
            self.assertEqual(plans, [module.plan(root, i, 4) for i in range(1, 5)])
            for bad in (0, -1, float('nan'), float('inf'), True, '10', None):
                with self.subTest(weight=bad), patch.dict(module.ESTIMATED_SECONDS,
                        {'tests_isolated/test_new_a.py': bad}):
                    with self.assertRaises(ValueError):
                        module.plan(root, 1, 4)
            with patch.object(module, 'DEFAULT_ESTIMATED_SECONDS', 0):
                with self.assertRaises(ValueError):
                    module.plan(root, 1, 4)
            for path in (root / 'tests_isolated').iterdir():
                path.unlink()
            for i in range(1, 5):
                with self.assertRaises(ValueError):
                    module.plan(root, i, 4)

    def test_one_python_per_file_and_fail_fast(self):
        module = self.load()
        with patch.object(module.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(module.execute(ROOT, 2, 4), 0)
            commands = module.plan(ROOT, 2, 4)
            self.assertEqual(run.call_count, len(commands))
            for call, args in zip(run.call_args_list, commands):
                self.assertEqual(call.args[0], ([sys.executable, str(ROOT/'deploy/ci/run-owned-suite.py'), *args] if module._OWNED['owned_command'](args) else [sys.executable, '-m', 'pytest', '-q', *args]))
                self.assertEqual(call.kwargs['cwd'], ROOT)
            run.reset_mock()
            run.return_value.returncode = 7
            self.assertEqual(module.execute(ROOT, 2, 4), 7)
            self.assertEqual(run.call_count, 1)

    def test_gitlab_all_parallel_shards_remain_mandatory(self):
        import copy
        ci = yaml.safe_load((ROOT/'.gitlab-ci.yml').read_text())
        spec = importlib.util.spec_from_file_location('shard_renderer', ROOT/'deploy/ci/runner-isolation/render_candidate.py')
        assert spec is not None and spec.loader is not None
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        rendered = renderer.compile_ci(ci)
        for source in (ci, rendered):
            self.check_gate(source)
            for mutate in (
                lambda c: c['build-images']['needs'].remove('backend-test'),
                lambda c: c['build-images']['needs'].remove('experience-gate'),
                lambda c: c['backend-test'].update(parallel=3),
                lambda c: c['backend-test'].update(parallel=4),
                lambda c: c['backend-test'].update(parallel=5),
                lambda c: c['backend-test'].update(parallel=6),
                lambda c: c['backend-test'].update(parallel=8),
                lambda c: c['backend-test'].update(allow_failure=True),
                lambda c: c['backend-test'].update(timeout='16m'),
                lambda c: c['backend-test']['script'].pop(),
            ):
                bad = copy.deepcopy(source)
                mutate(bad)
                with self.assertRaises(AssertionError):
                    self.check_gate(bad)

    def check_gate(self, ci):
        backend = ci['backend-test']
        self.assertEqual(backend.get('parallel'), 7)
        self.assertEqual(backend['timeout'], '25m')
        self.assertEqual(backend['extends'], '.branch-validation')
        self.assertFalse(backend.get('allow_failure', False))
        self.assertEqual(backend['tags'], ['stella-isolated-test'])
        self.assertNotIn('environment', backend)
        self.assertEqual(backend['variables']['POSTGRES_DB'], 'stella')
        self.assertEqual(backend['services'][0]['alias'], 'postgres')
        self.assertEqual(backend['script'][-2:], [
            '.venv/bin/python deploy/ci/create-test-db.py',
            '.venv/bin/python deploy/ci/run-backend-shard.py',
        ])
        self.assertEqual(ci['build-images']['needs'], [
            'backend-test', 'frontend-build', 'local-ha-contract', 'experience-gate',
        ])


# local-ha-contract already discovers this module. Re-export the focused
# cross-language prerequisites suite so the new runtime guard is a mandatory
# CI gate too, without changing the original command multiset.
_browser_spec = importlib.util.spec_from_file_location(
    'backend_browser_prerequisites', ROOT / 'deploy/ci/runner-isolation/test_backend_browser.py')
assert _browser_spec is not None and _browser_spec.loader is not None
_browser_contract = importlib.util.module_from_spec(_browser_spec)
_browser_spec.loader.exec_module(_browser_contract)
BackendBrowserPrerequisites = _browser_contract.BackendBrowserContract
BackendBrowserPlanPrerequisites = _browser_contract.BackendBrowserPlanContract


if __name__ == '__main__':
    unittest.main()
