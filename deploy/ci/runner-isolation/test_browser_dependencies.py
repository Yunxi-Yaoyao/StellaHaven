"""Offline browser prerequisite contracts; actual container replay is separate."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(name='browser_dependencies'):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrowserDependencies(unittest.TestCase):
    def test_bounded_prerequisite_is_mandatory_and_digest_image_unchanged(self):
        ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        for name, mode in [('frontend-build', 'frontend'), ('experience-gate', 'experience')]:
            job = ci[name]
            self.assertEqual(job['image'], 'gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/node@sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d')
            self.assertEqual(job['before_script'][-1], 'python3 deploy/ci/runner-isolation/browser_dependencies.py ' + mode)
            self.assertFalse(any('apt-get' in cmd for cmd in job['before_script']))
            self.assertEqual(job['timeout'], '15m')

    def test_apt_uses_wall_deadline_and_preserves_fail_fast(self):
        m = load()
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['apt-get'], 1)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                m.apt(['update'], 1)
            self.assertEqual(run.call_args.kwargs['timeout'], 1)
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertNotIn('--allow-unauthenticated', run.call_args.args[0])

    def test_both_failed_mirrors_are_bounded_restore_sources_and_never_install(self):
        m = load()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            source = Path(tmp) / 'debian.sources'
            original = 'URIs: http://deb.debian.org/debian\n'
            source.write_text(original)
            with patch.object(m, 'SOURCES', source), patch.object(m, 'apt', side_effect=subprocess.TimeoutExpired('apt-get', 1)) as apt:
                with self.assertRaisesRegex(RuntimeError, 'all bounded'):
                    m.prepare(Path(tmp), m.MODES['frontend'])
                self.assertEqual(apt.call_count, 2)
                self.assertLessEqual(apt.call_args_list[0].args[1], 150)
                self.assertLessEqual(apt.call_args_list[1].args[1], 240)
            self.assertEqual(source.read_text(), original)

    def clocked_prepare(self, stages):
        """Run the real resolver with causal elapsed time, not a call-count clock."""
        m = load()
        now = [0.0]
        calls = []
        pending = iter(stages)
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            source = Path(tmp) / 'debian.sources'
            original = 'URIs: http://deb.debian.org/debian\n'
            source.write_text(original)
            def apt(args, timeout):
                calls.append((args, now[0], timeout))
                self.assertLessEqual(len(calls), len(stages), 'APT started after its wall budget was exhausted')
                elapsed, error = next(pending)
                now[0] += elapsed
                if error:
                    raise error
                if elapsed > timeout:
                    raise subprocess.TimeoutExpired('apt-get', timeout)
            error = None
            with patch.object(m, 'SOURCES', source), patch.object(m.time, 'monotonic', side_effect=lambda: now[0]), patch.object(m, 'apt', side_effect=apt), patch.object(m.subprocess, 'check_output', return_value=m.CHROMIUM):
                try:
                    m.prepare(Path(tmp), m.MODES['experience'])
                except RuntimeError as caught:
                    error = caught
            self.assertEqual(source.read_text(), original)
        return calls, now[0], error

    def test_fast_mirror_failure_leaves_more_than_ninety_seconds_for_official(self):
        calls, elapsed, error = self.clocked_prepare([
            (5, subprocess.CalledProcessError(100, 'apt-get')),
            (20, None), (110, None), (10, None),
        ])
        self.assertIsNone(error)
        self.assertEqual([call[2] for call in calls], [150, 235, 215, 120])
        self.assertGreater(calls[2][2], 90)
        self.assertEqual(elapsed, 145)

    def test_elapsed_first_attempt_and_each_update_reduce_remaining_total(self):
        calls, elapsed, error = self.clocked_prepare([
            (40, None), (110, subprocess.TimeoutExpired('apt-get', 110)),
            (20, None), (70, None), (10, None),
        ])
        self.assertIsNone(error)
        self.assertEqual([call[2] for call in calls], [150, 110, 90, 70, 120])
        for args, started, timeout in calls[:-1]:
            self.assertGreater(timeout, 0)
            self.assertLessEqual(started + timeout, 240)
        self.assertEqual(elapsed, 250)  # Includes ten seconds of separate offline install.

    def test_update_exhaustion_never_starts_download(self):
        calls, elapsed, error = self.clocked_prepare([(150, None), (90, None)])
        self.assertRegex(str(error), 'all bounded')
        self.assertEqual([call[0] for call in calls], [['update'], ['update']])
        self.assertEqual(elapsed, 240)

    def test_total_exhaustion_never_starts_fallback(self):
        # Include timeout cleanup/scheduling elapsed time in the same wall budget.
        calls, elapsed, error = self.clocked_prepare([
            (240, subprocess.TimeoutExpired('apt-get', 150)),
        ])
        self.assertRegex(str(error), 'all bounded')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], 150)
        self.assertEqual(elapsed, 240)

    def test_causal_budget_assertions_reject_mutations_without_import_errors(self):
        source = (HERE / 'browser_dependencies.py').read_text()
        cases = [
            ('else deadline', 'else min(deadline, time.monotonic() + 90)',
             'test_fast_mirror_failure_leaves_more_than_ninety_seconds_for_official'),
            ('+ 240', '+ 241',
             'test_fast_mirror_failure_leaves_more_than_ninety_seconds_for_official'),
            ('remaining = attempt - time.monotonic()', 'remaining = attempt',
             'test_elapsed_first_attempt_and_each_update_reduce_remaining_total'),
            ('remaining <= 0', 'remaining < 0', 'test_update_exhaustion_never_starts_download'),
            ('remaining <= 0', 'False', 'test_total_exhaustion_never_starts_fallback'),
        ]
        for before, after, method in cases:
            with self.subTest(mutation=after):
                self.assertIn(before, source)
                # Execute real mutated source with its imports intact. The clock
                # fixture still resolves the actual test module's load function.
                mutant = types.ModuleType('fakebrokenbudget')
                exec(compile(source.replace(before, after, 1), str(HERE / 'browser_dependencies.py'), 'exec'), mutant.__dict__)
                result = unittest.TestResult()
                # test_ci loads this suite without registering its module name;
                # patch the real globals, never import a synthetic module alias.
                with patch.dict(globals(), {'load': lambda: mutant}):
                    type(self)(method).run(result)
                self.assertEqual(result.errors, [], result.errors)
                self.assertEqual(len(result.failures), 1, 'budget mutation escaped its original behavioral assertion')
                self.assertIn('AssertionError', result.failures[0][1])

    def test_fallback_keeps_same_authenticated_uri_until_offline_install(self):
        m = load()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            source = Path(tmp) / 'debian.sources'
            original = 'URIs: http://deb.debian.org/debian\n'
            source.write_text(original)
            calls = []
            def apt(args, timeout):
                calls.append((args, source.read_text(), timeout))
                if len(calls) == 1:
                    raise subprocess.TimeoutExpired('apt-get', 1)
            with patch.object(m, 'SOURCES', source), patch.object(m, 'apt', side_effect=apt), patch.object(m.subprocess, 'check_output', return_value=m.CHROMIUM):
                m.prepare(Path(tmp), m.MODES['frontend'])
            self.assertEqual([c[0][0] for c in calls], ['update', 'update', '-o', '-o'])
            self.assertIn('--download-only', calls[2][0])
            self.assertIn('--no-download', calls[3][0])
            self.assertEqual(calls[2][1], calls[3][1])
            self.assertIn(m.MIRRORS[1], calls[3][1])
            self.assertIn('chromium=' + m.CHROMIUM, calls[3][0])
            self.assertEqual(calls[3][2], 120)
            self.assertEqual(source.read_text(), original)

    def test_offline_installer_failure_is_not_retried_or_swallowed(self):
        m = load()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            source = Path(tmp) / 'debian.sources'
            original = 'URIs: http://deb.debian.org/debian\n'
            source.write_text(original)
            with patch.object(m, 'SOURCES', source), patch.object(m, 'apt', side_effect=[None, None, subprocess.CalledProcessError(100, 'apt-get')]) as apt:
                with self.assertRaises(subprocess.CalledProcessError):
                    m.prepare(Path(tmp), m.MODES['frontend'])
                self.assertEqual(apt.call_count, 3)
            self.assertEqual(source.read_text(), original)

    def test_preinstalled_exact_tools_reuse_missing_tool_setup_and_drift_refusal(self):
        m = load()
        for output, expected in [('installed\ninstalled\n', True), ('installed\nunpacked\n', False)]:
            with patch.object(m.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, m.CHROMIUM), subprocess.CompletedProcess([], 0, output)]):
                self.assertEqual(m.preinstalled(m.MODES['frontend']), expected)
        with patch.object(sys, 'argv', ['browser_dependencies.py', 'frontend']), patch.object(m, 'preinstalled', return_value=True), patch.object(m, 'prepare') as prepare:
            m.main()
            prepare.assert_not_called()
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'other-version')):
            with self.assertRaisesRegex(ValueError, 'preinstalled Chromium version drift'):
                m.preinstalled(m.MODES['frontend'])

    def test_renderer_binds_setup_and_rejects_missing_or_corrupt_hash(self):
        verifier = load('verify_bundle')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            subprocess.run([sys.executable, str(HERE / 'render_candidate.py'), '--out', tmp], check=True, capture_output=True)
            receipt = Path(tmp) / 'source-binding.json'
            binding = json.loads(receipt.read_text())
            self.assertEqual(verifier.verify(tmp)['status'], 'PASS')
            for value in ({}, {'deploy/ci/runner-isolation/browser_dependencies.py': '0' * 64}):
                broken = copy.deepcopy(binding)
                broken['frontend_browser_sha256'] = value
                receipt.write_text(json.dumps(broken))
                with self.assertRaises(AssertionError):
                    verifier.verify(tmp)


if __name__ == '__main__':
    unittest.main(verbosity=2)
