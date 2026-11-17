"""Backend subprocess runtime contracts, including activated and rendered CI."""
import copy
import importlib.util
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
SETUP = '. deploy/ci/runner-isolation/prepare-backend-browser.sh'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackendBrowserContract(unittest.TestCase):
    def test_active_and_renderer_install_the_runtime_without_budget_or_gate_changes(self):
        ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        renderer = load(HERE / 'render_candidate.py', 'browser_renderer')
        for candidate in (ci, renderer.compile_ci(ci)):
            self.check(candidate)
            for mutation in (
                lambda c: c['backend-test']['before_script'].remove(SETUP),
                lambda c: c['backend-test'].update(timeout='16m'),
                lambda c: c['backend-test'].update(allow_failure=True),
                lambda c: c['backend-test'].update(parallel=3),
                lambda c: c['backend-test'].update(parallel=4),
                lambda c: c['backend-test'].update(parallel=5),
                lambda c: c['backend-test'].update(parallel=6),
                lambda c: c['backend-test'].update(parallel=8),
                lambda c: c['build-images']['needs'].remove('backend-test'),
                lambda c: c['backend-test']['script'].pop(),
            ):
                broken = copy.deepcopy(candidate)
                mutation(broken)
                with self.assertRaises(AssertionError):
                    self.check(broken)
        without_setup = copy.deepcopy(ci)
        without_setup['backend-test']['before_script'].remove(SETUP)
        self.check(renderer.compile_ci(without_setup))

    def check(self, ci):
        b = ci['backend-test']
        self.assertEqual(b['before_script'].count(SETUP), 1)
        self.assertEqual(b['before_script'][-1], SETUP)
        self.assertIn('Deployment credentials must not enter', b['before_script'][0])
        self.assertNotIn('environment', b)
        self.assertEqual(b['timeout'], '25m')
        self.assertEqual(b['parallel'], 7)
        self.assertFalse(b.get('allow_failure', False))
        self.assertEqual(b['cache'], [])
        self.assertEqual(b['tags'], ['stella-isolated-test'])
        self.assertEqual(b['script'][-2:], ['.venv/bin/python deploy/ci/create-test-db.py', '.venv/bin/python deploy/ci/run-backend-shard.py'])
        self.assertEqual(ci['build-images']['needs'], ['backend-test', 'frontend-build', 'local-ha-contract', 'experience-gate'])

    def test_preparation_is_shard_local_lock_installed_and_bounded(self):
        path = HERE / 'prepare-backend-browser.sh'
        self.assertTrue(path.is_file(), 'backend browser prerequisites absent')
        text = path.read_text()
        subprocess.run(['sh', '-n', str(path)], check=True)
        self.assertIn('python3 deploy/ci/run-backend-shard.py --requires-browser', text)
        self.assertIn('if ! backend_browser_requirement=', text)
        self.assertNotIn('2:4|4:4)', text)
        self.assertIn('npm ci --prefix frontend --ignore-scripts --include=dev --prefer-offline', text)
        self.assertIn('python3 deploy/ci/runner-isolation/backend_dependencies.py npm', text)
        self.assertIn('python3 deploy/ci/runner-isolation/backend_dependencies.py playwright', text)
        self.assertNotIn('apt-get', text)
        self.assertNotIn('--with-deps', text)
        self.assertIn('node frontend/node_modules/playwright/cli.js install --only-shell chromium', text)
        # Legacy standalone bootstrap fixture names this exact executable. It
        # must resolve to this job's lock-pinned browser, not a host installation.
        self.assertIn('registry.findExecutable("chromium-headless-shell").executablePath()', text)
        self.assertIn('test ! -e /usr/sbin/google-chrome-stable', text)
        self.assertIn('ln -s "$headless_shell" /usr/sbin/google-chrome-stable', text)
        self.assertIn('export BOOTSTRAP_NODE=', text)
        self.assertIn('export BOOTSTRAP_EVIDENCE=', text)
        self.assertIn('export PLAYWRIGHT_BROWSERS_PATH="$TMPDIR/playwright"', text)
        for unsafe in ('npm install', 'npm -g', '--ignore-certificate-errors', '|| true', '/root/.cache/ms-playwright'):
            self.assertNotIn(unsafe, text)
        # Inert shards never invoke even a dependency resolver; invalid indices fail.
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'inert_browser_plan')
        required = {'tests_isolated/test_dual_entry.py', 'tests_isolated/test_web_project_html_bootstrap.py', 'tests_node_files/test_acl_browser.py', 'tests_node_files/test_build.py', 'tests_node_files/test_pipeline.py', 'tests_isolated/test_native_nav_completion_browser_pg.py'}
        inert = [i for i in range(1, 7) if not any(cmd[0] in required for cmd in planner.plan(ROOT, i, 6))]
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            bindir = Path(tmp)/'bin'
            bindir.mkdir()
            for name in ('apt-get','npm','node','ln'):
                sentinel = bindir/name
                sentinel.write_text('#!/bin/sh\nexit 91\n')
                sentinel.chmod(0o700)
            for index, total, expected in [(i, 6, 0) for i in inert] + [(0, 6, 1), (2, 201, 1)]:
                p = subprocess.run(['sh', '-ec', '. "$1"', 'sh', str(path)], cwd=ROOT,
                                   env={'PATH':str(bindir)+':/usr/local/bin:/usr/bin:/bin', 'TMPDIR':tmp, 'CI_NODE_INDEX':str(index), 'CI_NODE_TOTAL':str(total)}, capture_output=True)
                self.assertEqual(p.returncode, expected, p.stderr)

    def test_install_shards_match_actual_unconditional_browser_commands(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'browser_plan')
        required = {'tests_isolated/test_dual_entry.py', 'tests_isolated/test_web_project_html_bootstrap.py', 'tests_node_files/test_acl_browser.py', 'tests_node_files/test_build.py', 'tests_node_files/test_pipeline.py', 'tests_isolated/test_native_nav_completion_browser_pg.py'}
        needed = {index for index in range(1, 7) for command in planner.plan(ROOT, index, 6) if command[0] in required}
        self.assertEqual(planner.UNCONDITIONAL_BROWSER_TESTS, required)
        self.assertEqual({i for i in range(1, 7) if planner.browser_required(ROOT, i, 6)}, needed)
        for i in range(1, 7):
            result = subprocess.run([sys.executable, '-S', str(ROOT / 'deploy/ci/run-backend-shard.py'), '--requires-browser'],
                env={'CI_NODE_INDEX':str(i), 'CI_NODE_TOTAL':'6'}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'required' if i in needed else 'not-required')
        # PG-only full-App/runtime browsers remain behind the existing owned-PG
        # manifest gate, not enabled by installing npm or by a sibling job.
        gate = (ROOT / 'tests_isolated/test_notes_review_boundaries_pg.py').read_text()
        self.assertIn("path = os.environ.get('NOTES_BOUNDARY_PG_MANIFEST')", gate)
        self.assertIn("pytest.skip('Requires self-provisioning disposable PG launcher')", gate)
        self.assertNotIn('NOTES_BOUNDARY_PG_MANIFEST', (HERE / 'prepare-backend-browser.sh').read_text())
        for filename in ('test_full_web_project_e2e.py', 'test_web_project_renewal_browser.py',
                         'test_web_projects_pg.py', 'test_notes_timeline_contract_pg.py'):
            text = (ROOT / 'tests_isolated' / filename).read_text()
            self.assertIn('from test_notes_review_boundaries_pg import notes', text)
            self.assertNotIn('tests_isolated/' + filename, required)
        zip_browser = (ROOT / 'tests/test_notes_zip_browser.py').read_text()
        self.assertIn("os.environ.get('STELLA_LIVE_BROWSER') != '1'", zip_browser)


class BackendBrowserPlanContract(unittest.TestCase):
    def fixture(self, tmp):
        root = Path(tmp)
        for path in (ROOT / 'tests_isolated').glob('test_*.py'):
            target = root / 'tests_isolated' / path.name
            target.parent.mkdir(exist_ok=True)
            target.touch()
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'fixture_browser_plan')
        for directory in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout'):
            (root/directory).mkdir()
            for path in (ROOT/directory).glob('test_*.py'):
                (root/directory/path.name).touch()
        for cmd in planner.GROUP_COMMANDS:
            (root / cmd[0]).mkdir()
        script = root / 'deploy/ci/run-backend-shard.py'
        script.parent.mkdir(parents=True)
        script.write_bytes((ROOT / 'deploy/ci/run-backend-shard.py').read_bytes())
        for name in ('owned_inventory.py','owned-timings.json','ci178-backend-timings.json','ci182-backend-timings.json','copy-capacity-timings.json','capacity_successor.py','v23-capacity-timings.json','derivation-capacity-timings.json','servers-audit-capacity-sources.json'):
            (script.parent/name).write_bytes((ROOT/'deploy/ci'/name).read_bytes())
        setup = root / 'setup.sh'
        # The only fixture seam: legacy alias destination is scratch-owned.
        # No host alias write, no shared node_modules, no actual installer.
        setup.write_text((HERE / 'prepare-backend-browser.sh').read_text().replace(
            '/usr/sbin/google-chrome-stable', str(root / 'legacy-chrome')))
        # Own the registry target as well as the alias: /usr/bin/true exists
        # on Debian but not on the HA contract job's Alpine/BusyBox image.
        headless_shell = root / 'fake-headless-shell'
        headless_shell.write_text('#!/bin/sh\nexit 0\n')
        headless_shell.chmod(0o700)
        bindir = root / 'bin'
        bindir.mkdir()
        (bindir / 'python3').write_text('#!/bin/sh\nexec ' + sys.executable + ' -S "$@"\n')
        (bindir / 'python3').chmod(0o700)
        # APT helper is separately exercised by its owning deadline suite. This
        # shell fixture records both helper modes without apt/host mutations.
        helper = root / 'deploy/ci/runner-isolation/backend_dependencies.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text('import os,sys; os.execv(' + repr(str(bindir / 'deps')) + ', ["deps", sys.argv[1]])\n')
        for name in ('deps', 'npm', 'node', 'ln'):
            path = bindir / name
            path.write_text('#!' + sys.executable + '\n' + '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
stage = 'registry' if name == 'node' and sys.argv[1] == '-e' else 'deps-' + sys.argv[1] if name == 'deps' else name
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps({'stage':stage, 'argv':sys.argv[1:],
        'lang':os.getenv('LANG'), 'locale':os.getenv('LC_ALL'),
        'node_env':os.getenv('NODE_ENV'), 'bootstrap':os.getenv('BOOTSTRAP_NODE'),
        'evidence':os.getenv('BOOTSTRAP_EVIDENCE'),
        'browsers':os.getenv('PLAYWRIGHT_BROWSERS_PATH')}) + '\\n')
if os.getenv('FAIL_STAGE') == stage: sys.exit(73)
if stage == 'registry': print(pathlib.Path(os.environ['CALLS']).parent / 'fake-headless-shell')
''')
            path.chmod(0o700)
        return root, setup

    def run_setup(self, root, setup, index, **overrides):
        calls = root / 'calls.jsonl'
        calls.unlink(missing_ok=True)
        env = {'PATH':str(root / 'bin')+':/usr/bin:/bin', 'TMPDIR':str(root),
               'CALLS':str(calls), 'CI_NODE_INDEX':str(index), 'CI_NODE_TOTAL':'6',
               'NODE_ENV':'production', **overrides}
        proc = subprocess.run(['sh', '-ec', '. "$1"; printf completed', 'sh', str(setup)],
                              cwd=root, env=env, capture_output=True, text=True, timeout=10)
        return proc, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    def test_shell_all_six_actual_plans_and_shifted_plans_use_bounded_installers(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'shell_browser_plan')
        required = {'tests_isolated/test_dual_entry.py', 'tests_isolated/test_web_project_html_bootstrap.py', 'tests_node_files/test_acl_browser.py', 'tests_node_files/test_build.py', 'tests_node_files/test_pipeline.py', 'tests_isolated/test_native_nav_completion_browser_pg.py'}
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root, setup = self.fixture(tmp)
            for shift in range(3):
                for i in range(1, 7):
                    with self.subTest(shift=shift, shard=i):
                        needed = any(cmd[0] in required for cmd in planner.plan(root, i, 6))
                        proc, calls = self.run_setup(root, setup, i)
                        self.assertEqual(proc.returncode, 0, proc.stderr)
                        self.assertEqual(proc.stdout, 'completed')
                        self.assertEqual([c['stage'] for c in calls],
                                         ['deps-npm', 'npm', 'deps-playwright', 'node', 'registry', 'ln'] if needed else [])
                        if needed:
                            self.assertEqual(calls[0]['argv'], ['npm'])
                            self.assertEqual(calls[1]['argv'], ['ci', '--prefix', 'frontend', '--ignore-scripts', '--include=dev', '--prefer-offline'])
                            self.assertEqual(calls[2]['argv'], ['playwright'])
                            self.assertEqual(calls[3]['argv'], ['frontend/node_modules/playwright/cli.js', 'install', '--only-shell', 'chromium'])
                            self.assertEqual(calls[-1]['argv'], ['-s', str(root / 'fake-headless-shell'), str(root / 'legacy-chrome')])
                            for call in calls:
                                self.assertEqual((call['lang'], call['locale']), ('C.UTF-8', 'C.UTF-8'))
                                self.assertIsNone(call['node_env'])
                                self.assertEqual(call['bootstrap'], str(root / 'bin/node'))
                                self.assertEqual(call['evidence'], str(root / 'web-project-html-bootstrap'))
                                self.assertEqual(call['browsers'], str(root / 'playwright'))
                (root / 'tests_isolated' / f'test_000_shift_{shift}.py').touch()

    def test_missing_plan_unknown_shard_and_installer_failure_stop_before_tests(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'failing_browser_plan')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root, setup = self.fixture(tmp)
            browser_shard = next(i for i in range(1, 7) if planner.browser_required(root, i, 6))
            for value in ('0', '7', 'unknown', ''):
                proc, calls = self.run_setup(root, setup, value)
                self.assertNotEqual(proc.returncode, 0)
                self.assertNotIn('completed', proc.stdout)
                self.assertEqual(calls, [])
            for total in ('201', '-1', '0', ''):
                proc, calls = self.run_setup(root, setup, 2, CI_NODE_TOTAL=total)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(calls, [])
            for index, stage in enumerate(('deps-npm', 'npm', 'deps-playwright', 'node', 'registry', 'ln')):
                proc, calls = self.run_setup(root, setup, browser_shard, FAIL_STAGE=stage)
                self.assertEqual(proc.returncode, 73)
                self.assertNotIn('completed', proc.stdout)
                self.assertEqual(len(calls), index + 1)
            # The real executable guard still rejects a broken registry target
            # before the alias command; do not bypass it to make stubs pass.
            headless_shell = root / 'fake-headless-shell'
            for missing in (False, True):
                if missing:
                    headless_shell.unlink()
                else:
                    headless_shell.chmod(0o600)
                proc, calls = self.run_setup(root, setup, browser_shard)
                self.assertEqual(proc.returncode, 1)
                self.assertNotIn('completed', proc.stdout)
                self.assertEqual([c['stage'] for c in calls], ['deps-npm', 'npm', 'deps-playwright', 'node', 'registry'])
            (root / 'deploy/ci/run-backend-shard.py').unlink()
            proc, calls = self.run_setup(root, setup, 1)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(calls, [])

    def test_predicate_missing_inventory_and_metadata_fail_closed(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'invalid_browser_plan')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root, _ = self.fixture(tmp)
            (root / 'tests_isolated/test_dual_entry.py').unlink()
            for i in range(1, 7):
                with self.assertRaises(ValueError):
                    planner.browser_required(root, i, 6)
            for path in (root / 'tests_isolated').glob('*.py'):
                path.unlink()
            for i in range(1, 7):
                with self.assertRaises(ValueError):
                    planner.browser_required(root, i, 6)

    def test_new_browser_file_metadata_and_directory_commands_are_supported(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'new_browser_metadata')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root, _ = self.fixture(tmp)
            added = 'tests_isolated/test_00_new_browser.py'
            (root / added).write_text('import playwright  # never imported by the planner\n')
            setattr(planner, 'UNCONDITIONAL_BROWSER_TESTS', planner.UNCONDITIONAL_BROWSER_TESTS | {added})
            required = {added, 'tests_isolated/test_dual_entry.py', 'tests_isolated/test_web_project_html_bootstrap.py', 'tests_node_files/test_acl_browser.py', 'tests_node_files/test_build.py', 'tests_node_files/test_pipeline.py', 'tests_isolated/test_native_nav_completion_browser_pg.py'}
            self.assertEqual({i for i in range(1, 7) if planner.browser_required(root, i, 6)},
                             {i for i in range(1, 7) for cmd in planner.plan(root, i, 6) if cmd[0] in required})
            # A new mandatory browser under the grouped `tests` command also works.
            grouped = 'tests/test_new_browser.py'
            (root / grouped).touch()
            setattr(planner, 'UNCONDITIONAL_BROWSER_TESTS', planner.UNCONDITIONAL_BROWSER_TESTS | {grouped})
            grouped_shard = next(i for i in range(1, 7)
                                 if ['tests'] in planner.plan(root, i, 6))
            self.assertTrue(planner.browser_required(root, grouped_shard, 6))
            # Independent setup-aware oracle also covers newly owned files and
            # grouped-directory metadata. Costing and shell setup cannot split.
            commands = [list(cmd) for cmd in planner.GROUP_COMMANDS] + [
                [str(p.relative_to(root)), '--noconftest']
                for p in sorted((root / 'tests_isolated').glob('test_*.py'))] + [[str(p.relative_to(root))] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for p in sorted((root/d).glob('test_*.py'))]
            commands.sort(key=lambda cmd: (-planner.estimated_seconds(cmd), tuple(cmd)))
            expected = [[] for _ in range(6)]
            loads, browsers = [75.0] * 6, [False] * 6
            for command in commands:
                needs = any(Path(p).is_relative_to(Path(command[0]))
                            for p in required | {grouped})
                weight = planner.estimated_seconds(command)
                costs = [loads[i] + weight + (140 if needs and not browsers[i] else 0)
                         for i in range(6)]
                target = min(range(6), key=lambda i: (costs[i], i))
                expected[target].append(command)
                loads[target] = costs[target]
                browsers[target] |= needs
            actual = [planner.plan(root, i, 6) for i in range(1, 7)]
            self.assertEqual(actual, expected)
            self.assertEqual({i for i in range(1, 7) if planner.browser_required(root, i, 6)},
                             {i for i, needed in enumerate(browsers, 1) if needed})
            self.assertEqual(sum(cmd[0] == added for shard in actual for cmd in shard), 1)
            self.assertEqual(sum(cmd[0] == 'tests' for shard in actual for cmd in shard), 1)

    def test_fixed_shards_and_install_everywhere_mutations_are_rejected(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'mutated_browser_setup')
        command = 'python3 deploy/ci/run-backend-shard.py --requires-browser'
        for mutation in (
            'case "$CI_NODE_INDEX" in 2|4) printf required;; *) printf not-required;; esac',
            'case "$CI_NODE_INDEX" in 2) printf required;; *) printf not-required;; esac',
            'printf required',
            'printf not-required',
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
                root, setup = self.fixture(tmp)
                setup.write_text(setup.read_text().replace(command, mutation))
                rejected = False
                for shift in range(3):
                    observed = set()
                    for i in range(1, 7):
                        proc, calls = self.run_setup(root, setup, i)
                        self.assertEqual(proc.returncode, 0, proc.stderr)
                        if calls:
                            observed.add(i)
                    expected = {i for i in range(1, 7) if planner.browser_required(root, i, 6)}
                    rejected |= observed != expected
                    (root / 'tests_isolated' / f'test_000_shift_{shift}.py').touch()
                self.assertTrue(rejected, 'fixed/broad prerequisite policy escaped plan oracle')

    def test_renderer_binds_planner_metadata_and_setup(self):
        verifier = load(HERE / 'verify_bundle.py', 'browser_verifier')
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            subprocess.run([sys.executable, str(HERE / 'render_candidate.py'), '--out', tmp],
                           check=True, capture_output=True, timeout=10)
            path = Path(tmp) / 'source-binding.json'
            binding = json.loads(path.read_text())
            self.assertIn('backend_browser_sha256', binding)
            self.assertEqual(set(binding['backend_browser_sha256']),
                             {'deploy/ci/run-backend-shard.py', 'deploy/ci/runner-isolation/backend_dependencies.py', 'deploy/ci/runner-isolation/prepare-backend-browser.sh', 'deploy/ci/owned_inventory.py', 'deploy/ci/owned_pg.py', 'deploy/ci/owned_pytest.py', 'deploy/ci/run-owned-suite.py','deploy/ci/unified_ci.py','deploy/ci/unified-nodeids.json', 'deploy/ci/create-test-db.py', 'deploy/ci/owned-timings.json','deploy/ci/ci178-backend-timings.json','deploy/ci/ci182-backend-timings.json','deploy/ci/copy-capacity-timings.json','deploy/ci/capacity_successor.py','deploy/ci/v23-capacity-timings.json','deploy/ci/derivation-capacity-timings.json','deploy/ci/servers-audit-capacity-sources.json', 'qa/native_nav_pg_guard.py'})
            self.assertEqual(verifier.verify(tmp)['status'], 'PASS')
            for source in binding['backend_browser_sha256']:
                bad = copy.deepcopy(binding)
                bad['backend_browser_sha256'][source] = '0' * 64
                path.write_text(json.dumps(bad))
                with self.assertRaises(AssertionError):
                    verifier.verify(tmp)
            bad = copy.deepcopy(binding)
            bad['backend_browser_sha256'].clear()
            path.write_text(json.dumps(bad))
            with self.assertRaises(AssertionError):
                verifier.verify(tmp)

    def test_shell_obeys_not_required_predicate_even_on_former_browser_shard(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            bindir = Path(tmp) / 'bin'
            bindir.mkdir()
            # An explicit stdlib planner answer, no pytest or package installs.
            for name, body in {
                'python3': 'printf "%s\\n" not-required',
                'apt-get': 'printf "%s\\n" unexpected-install >&2; exit 91',
            }.items():
                executable = bindir / name
                executable.write_text('#!/bin/sh\n' + body + '\n')
                executable.chmod(0o700)
            result = subprocess.run(['sh', '-ec', '. "$1"', 'sh', str(HERE / 'prepare-backend-browser.sh')],
                cwd=ROOT, env={'PATH':str(bindir)+':/usr/bin:/bin', 'TMPDIR':tmp,
                               'CI_NODE_INDEX':'4', 'CI_NODE_TOTAL':'6'}, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            for body in ('printf unknown', 'printf ""', 'exit 3'):
                executable = bindir / 'python3'
                executable.write_text('#!/bin/sh\n' + body + '\n')
                result = subprocess.run(['sh', '-ec', '. "$1"', 'sh', str(HERE / 'prepare-backend-browser.sh')],
                    cwd=ROOT, env={'PATH':str(bindir)+':/usr/bin:/bin', 'TMPDIR':tmp,
                                   'CI_NODE_INDEX':'1', 'CI_NODE_TOTAL':'6'}, capture_output=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn(b'unexpected-install', result.stderr)

    def test_predicate_tracks_added_sorted_files_not_shard_numbers(self):
        planner = load(ROOT / 'deploy/ci/run-backend-shard.py', 'browser_dynamic_plan')
        required = {'tests_isolated/test_dual_entry.py', 'tests_isolated/test_web_project_html_bootstrap.py', 'tests_node_files/test_acl_browser.py', 'tests_node_files/test_build.py', 'tests_node_files/test_pipeline.py', 'tests_isolated/test_native_nav_completion_browser_pg.py'}
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            # Reverse creation order must not change the real sorted planner.
            for path in reversed(sorted((ROOT / 'tests_isolated').glob('test_*.py'))):
                target = root / 'tests_isolated' / path.name
                target.parent.mkdir(exist_ok=True)
                target.touch()
            for directory in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout'):
                (root/directory).mkdir()
                for path in (ROOT/directory).glob('test_*.py'):
                    (root/directory/path.name).touch()
            for args in planner.GROUP_COMMANDS:
                (root / args[0]).mkdir()
            observed = set()
            for count in range(3):
                expected = {i for i in range(1, 7) for cmd in planner.plan(root, i, 6) if cmd[0] in required}
                actual = {i for i in range(1, 7) if planner.browser_required(root, i, 6)}
                self.assertEqual(actual, expected)
                observed.update(actual)
                # Unrelated new files shift both unconditional browser commands.
                (root / 'tests_isolated' / f'test_000_added_{count}.py').touch()
            self.assertTrue(observed)
            self.assertTrue(observed <= {1, 2, 3, 4, 5, 6})
            # Force sort/load changes, not a hard-coded former modulo layout.
            for weight in (1.0, 50.0, 100.0, 250.0, 450.0, 1000.0):
                planner.ESTIMATED_SECONDS['tests_isolated/test_000_added_0.py'] = weight
                expected = {i for i in range(1, 7) for cmd in planner.plan(root, i, 6) if cmd[0] in required}
                actual = {i for i in range(1, 7) if planner.browser_required(root, i, 6)}
                self.assertEqual(actual, expected)
                observed.update(actual)
            self.assertGreater(len(observed), 2, 'weighted sort shifts must exercise changed browser shards')


if __name__ == '__main__':
    unittest.main(verbosity=2)
