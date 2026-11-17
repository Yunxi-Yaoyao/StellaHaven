"""Required built documentation reading gate; offline CI/renderer contracts only."""
import copy
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOC_COMMAND = ('STELLA_CHROMIUM="$CHROME_BIN" STELLA_DOC_SKIP_BUILD=1 '
               'STELLA_DOC_OUTPUT="$CI_PROJECT_DIR/frontend/node_modules/.cache/documentation" '
               'npm run test:documentation')
# Exact pre-documentation frontend script, not a mutable total/count oracle.
OLD_FRONTEND_COMMANDS = [
    'cd frontend',
    'npm ci --ignore-scripts --include=dev --prefer-offline',
    'npm test',
    *['node node_modules/vitest/vitest.mjs run --config vitest.' + name + '.config.mjs'
      for name in ('website-key', 'settings', 'auth-provider', 'shell', 'hardware', 'overview', 'time-range')],
    'npm run test:monitor-loading',
    'CHROME_PATH="$CHROME_BIN" OVERVIEW_EVIDENCE_DIR="$CI_PROJECT_DIR/frontend/node_modules/.cache/overview" node tests/overview-browser.mjs',
    'CHROME_PATH="$CHROME_BIN" TIME_RANGE_OUTPUT="$CI_PROJECT_DIR/frontend/node_modules/.cache/time-range" node tests/timeRange-browser.mjs',
    'HARDWARE_TEST_OUTPUT="$CI_PROJECT_DIR/frontend/node_modules/.cache/hardware" CHROME_PATH="$CHROME_BIN" node src/modules/servers/hardware.visual.test.mjs',
    'npm run build',
    'node node_modules/vitest/vitest.mjs run --config vitest.login-modal.config.mjs',
    'node node_modules/vitest/vitest.mjs run --config vitest.browser-sessions.config.mjs',
    'STELLA_CHROMIUM="$CHROME_BIN" STELLA_SESSION_QA_OUTPUT="$CI_PROJECT_DIR/frontend/node_modules/.cache/browser-sessions" node node_modules/@playwright/test/cli.js test --config playwright.browser-sessions.config.ts',
    'STELLA_CHROMIUM="$CHROME_BIN" STELLA_LOGIN_QA_OUTPUT="$CI_PROJECT_DIR/frontend/node_modules/.cache/login-polish" node node_modules/@playwright/test/cli.js test --config playwright.login-modal.config.ts',
    'STELLA_CHROMIUM="$CHROME_BIN" NOTES_ARTIFACTS="$CI_PROJECT_DIR/frontend/node_modules/.cache/notes-polish" node node_modules/@playwright/test/cli.js test --config e2e/notes-polish.config.ts',
]


def load(name):
    spec = importlib.util.spec_from_file_location('documentation_' + name, HERE / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(ci):
    front = ci['frontend-build']
    assert front['script'] == OLD_FRONTEND_COMMANDS + [DOC_COMMAND], 'required documentation command missing or old commands drifted'
    assert front['timeout'] == '15m', 'frontend budget changed'
    assert not front.get('allow_failure', False), 'documentation must fail closed'
    assert front['extends'] == '.branch-validation'
    assert front['variables'] == {'CHROME_BIN': '/usr/bin/chromium', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    assert front['tags'] == ['stella-isolated-test'] and front['cache'] == []
    assert 'environment' not in front
    assert 'Deployment credentials must not enter' in front['before_script'][0]
    assert ci['build-images']['needs'] == ['backend-test', 'frontend-build', 'local-ha-contract', 'experience-gate']
    assert not ci['build-images'].get('allow_failure', False)
    assert ci['build-image-receipt']['needs'] == [{'job': 'build-images', 'artifacts': True}]
    assert not ci['build-image-receipt'].get('allow_failure', False)


class DocumentationCIContract(unittest.TestCase):
    def test_active_and_renderer_keep_every_old_command_and_require_reading_after_build(self):
        ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        renderer = load('render_candidate')
        for source in (ci, renderer.compile_ci(ci)):
            check(source)
            for mutate in (
                lambda c: c['frontend-build']['script'].pop(),
                lambda c: c['frontend-build']['script'].append(DOC_COMMAND),
                lambda c: c['frontend-build']['script'].remove('npm run build'),
                lambda c: c['frontend-build']['script'].reverse(),
                lambda c: c['frontend-build'].update(timeout='16m'),
                lambda c: c['frontend-build'].update(allow_failure=True),
                lambda c: c['build-images']['needs'].remove('frontend-build'),
                lambda c: c['build-image-receipt']['needs'].clear(),
            ):
                broken = copy.deepcopy(source)
                mutate(broken)
                with self.assertRaises(AssertionError):
                    check(broken)

    def test_renderer_adds_exactly_one_approved_command_to_pre_documentation_ci(self):
        ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        ci['frontend-build']['script'] = OLD_FRONTEND_COMMANDS.copy()
        renderer = load('render_candidate')
        rendered = renderer.compile_ci(ci)
        check(rendered)
        self.assertEqual(renderer.compile_ci(rendered), rendered)
        # Whole CI comparison: the approved addition is the only compiler delta.
        old_compiled = copy.deepcopy(rendered)
        old_compiled['frontend-build']['script'].pop()
        self.assertEqual(old_compiled, ci)

    def test_failing_documentation_command_stops_frontend_before_build_receipt(self):
        ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        check(ci)
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            # Execute the exact YAML command under Runner's fail-fast shell. Only
            # npm is a disposable command double: no browser/install/build here.
            npm = root / 'npm'
            npm.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$CALLS"\nexit "${DOC_EXIT:-0}"\n')
            npm.chmod(0o700)
            for code in (0, 73):
                result = subprocess.run(['sh', '-ec', DOC_COMMAND + '\nprintf build-receipt-reached'],
                    cwd=ROOT / 'frontend', capture_output=True, text=True,
                    env={'PATH': str(root) + ':/usr/bin:/bin', 'CHROME_BIN': '/fixture/chromium',
                         'CI_PROJECT_DIR': str(ROOT), 'CALLS': str(root / 'calls'), 'DOC_EXIT': str(code)})
                self.assertEqual(result.returncode, code)
                self.assertEqual((root / 'calls').read_text(), 'run test:documentation\n')
                self.assertEqual(result.stdout, 'build-receipt-reached' if code == 0 else '')

    def test_serialized_candidate_rejects_gate_removal_even_with_refreshed_receipt(self):
        verifier = load('verify_bundle')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            subprocess.run([sys.executable, str(HERE / 'render_candidate.py'), '--out', tmp],
                           check=True, capture_output=True, timeout=10)
            candidate = Path(tmp) / 'candidate.gitlab-ci.yml'
            receipt = Path(tmp) / 'source-binding.json'
            raw = candidate.read_bytes()
            binding = json.loads(receipt.read_text())
            ci = yaml.safe_load(raw)
            check(ci)
            self.assertEqual(verifier.verify(tmp)['status'], 'PASS')
            for mutate in (
                lambda c: c['frontend-build']['script'].pop(),
                lambda c: c['frontend-build'].update(allow_failure=True),
                lambda c: c['build-images']['needs'].remove('frontend-build'),
                lambda c: c['build-image-receipt']['needs'].clear(),
            ):
                broken = copy.deepcopy(ci)
                mutate(broken)
                changed = yaml.safe_dump(broken).encode()
                candidate.write_bytes(changed)
                updated = copy.deepcopy(binding)
                updated['candidate_ci_sha256'] = hashlib.sha256(changed).hexdigest()
                receipt.write_text(json.dumps(updated))
                with self.assertRaises(AssertionError):
                    verifier.verify(tmp)


if __name__ == '__main__':
    unittest.main(verbosity=2)
