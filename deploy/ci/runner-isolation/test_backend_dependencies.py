"""Backend APT deadline, offline resolver and fail-closed owning contracts."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HELPER = 'deploy/ci/runner-isolation/backend_dependencies.py'
COMMAND = 'python3 ' + HELPER + ' backend'


def load(name='backend_dependencies'):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackendDependencies(unittest.TestCase):
    def test_active_and_rendered_mandatory_setup_preserve_images_gates_and_commands(self):
        ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        for candidate in (ci, load('render_candidate').compile_ci(ci)):
            job = candidate['backend-test']
            self.assertEqual(job['image'], 'gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/python@sha256:25e2514972115ba1714069a3facf805a8ec789bf9f896c959465dc8df6501651')
            self.assertEqual(job['before_script'].count(COMMAND), 1)
            self.assertFalse(any('apt-get' in cmd or 'ustc' in cmd for cmd in job['before_script']))
            self.assertLess(job['before_script'].index(COMMAND), job['before_script'].index('pip install uv -q'))
            self.assertEqual(job['parallel'], 7)
            self.assertEqual(job['timeout'], '25m')
            self.assertFalse(job.get('allow_failure', False))
            self.assertEqual(job['script'][:3], ['uv export --frozen --all-groups --no-emit-project -o /tmp/ci-requirements.txt', 'uv venv', 'uv pip sync --index-url "$PIP_INDEX_URL" --require-hashes /tmp/ci-requirements.txt'])
            self.assertEqual(candidate['build-images']['needs'], ['backend-test', 'frontend-build', 'local-ha-contract', 'experience-gate'])
        shell = (HERE / 'prepare-backend-browser.sh').read_text()
        self.assertNotIn('apt-get', shell)
        self.assertNotIn('--with-deps', shell)
        self.assertIn('python3 ' + HELPER + ' npm', shell)
        self.assertIn('python3 ' + HELPER + ' playwright', shell)

    def test_failed_mirrors_restore_sources_and_never_install(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'sources'
            original = 'URIs: http://deb.debian.org/debian\nSuites: trixie\nSigned-By: /key.pgp\n'
            source.write_text(original)
            with patch.object(m, 'SOURCES', source), patch.object(m, 'apt', side_effect=subprocess.TimeoutExpired('apt-get', 1)) as apt:
                with self.assertRaisesRegex(RuntimeError, 'tests must not start'):
                    m.prepare(Path(tmp), m.PACKAGES)
            self.assertEqual(apt.call_count, 2)
            self.assertLessEqual(apt.call_args_list[0].args[1], 150)
            self.assertLessEqual(apt.call_args_list[1].args[1], 90)
            self.assertTrue(all('--no-download' not in c.args[0] for c in apt.call_args_list))
            self.assertEqual(source.read_text(), original)

    def test_fallback_preserves_authenticated_index_then_offline_resolver(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'sources'
            original = 'URIs: http://deb.debian.org/debian-security\nSuites: trixie-security\nSigned-By: /key.pgp\n'
            source.write_text(original)
            calls = []
            def apt(args, timeout):
                calls.append((args, timeout, source.read_text()))
                if len(calls) == 1:
                    raise subprocess.TimeoutExpired('apt-get', 1)
            with patch.object(m, 'SOURCES', source), patch.object(m, 'apt', side_effect=apt), patch.object(m, 'preinstalled', return_value=True):
                m.prepare(Path(tmp), m.PACKAGES)
            self.assertEqual(len(calls), 4)
            self.assertIn('--download-only', calls[2][0])
            self.assertIn('--no-download', calls[3][0])
            self.assertEqual(calls[3][1], 120)
            self.assertEqual(calls[2][2], calls[3][2])
            self.assertIn(m.MIRRORS[1] + '/debian-security', calls[3][2])
            self.assertIn('Signed-By: /key.pgp', calls[3][2])
            self.assertIn('Suites: trixie-security', calls[3][2])
            self.assertEqual(source.read_text(), original)

    def test_download_deadline_is_total_not_reset_per_command(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'sources'
            source.write_text('URIs: http://deb.debian.org/debian\n')
            clock = [0.0]
            calls = []
            def apt(args, timeout):
                calls.append((args, timeout))
                clock[0] += timeout
                raise subprocess.TimeoutExpired('apt-get', timeout)
            with patch.object(m, 'SOURCES', source), patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(m, 'apt', side_effect=apt):
                with self.assertRaises(RuntimeError):
                    m.prepare(Path(tmp), m.PACKAGES)
            self.assertEqual([c[1] for c in calls], [150, 90])
            self.assertEqual(clock[0], 240)

    def test_offline_failure_restores_source_and_is_not_swallowed(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'sources'
            original = 'URIs: http://deb.debian.org/debian\n'
            source.write_text(original)
            with patch.object(m, 'SOURCES', source), patch.object(m, 'apt', side_effect=[None, None, subprocess.CalledProcessError(100, 'apt-get')]) as apt:
                with self.assertRaises(subprocess.CalledProcessError):
                    m.prepare(Path(tmp), m.PACKAGES)
                self.assertEqual(apt.call_count, 3)
            self.assertEqual(source.read_text(), original)

    def test_exact_installed_status_and_executable_versions_required_for_reuse(self):
        m = load()
        for output, expected in [('installed\n' * 4, True), ('installed\n' * 3 + 'unpacked\n', False), ('installed\n' * 3, False)]:
            with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output)), patch.object(m, 'run') as versions:
                self.assertEqual(m.preinstalled(m.PACKAGES), expected)
                self.assertEqual(versions.call_count, 4 if expected else 0)
        with patch.object(sys, 'argv', ['helper', 'backend']), patch.object(m, 'preinstalled', return_value=True), patch.object(m, 'prepare') as prepare:
            m.main()
            prepare.assert_not_called()
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'installed\n' * 4)), patch.object(m, 'run', side_effect=FileNotFoundError):
            self.assertFalse(m.preinstalled(m.PACKAGES))

    def test_playwright_dry_run_packages_only_never_execute_shell(self):
        m = load()
        command = 'sh -c "apt-get update&& apt-get install -y --no-install-recommends libnss3 libatk1.0-0t64"\n'
        with patch.object(m.subprocess, 'check_output', return_value=command):
            self.assertEqual(m.playwright_packages(), ['libnss3', 'libatk1.0-0t64'])
        for bad in ('sh -c "apt-get update&& apt-get install -y --no-install-recommends --allow-unauthenticated libnss3"', 'sh -c "apt-get update&& apt-get install -y --no-install-recommends libnss3; touch /bad"', '', command + 'echo bad\n'):
            with patch.object(m.subprocess, 'check_output', return_value=bad), self.assertRaises(ValueError):
                m.playwright_packages()

    def test_real_timeout_kills_children_and_releases_lock(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'lock'
            pid = Path(tmp) / 'pid'
            code = 'import fcntl,os,time; f=open(' + repr(str(lock)) + ',"w"); fcntl.flock(f,fcntl.LOCK_EX); open(' + repr(str(pid)) + ',"w").write(str(os.getpid())); time.sleep(30)'
            start = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                m.run([sys.executable, '-c', 'import subprocess,time; subprocess.Popen(' + repr([sys.executable, '-c', code]) + '); time.sleep(30)'], 1)
            self.assertLess(time.monotonic() - start, 3)
            import fcntl
            with lock.open('w') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            child = Path('/proc') / pid.read_text() / 'stat'
            try:
                state = child.read_text().split()[2]
            except (FileNotFoundError, ProcessLookupError):
                state = 'reaped'
            self.assertIn(state, ('Z', 'reaped'), 'child still running')

    def test_timeout_waits_for_group_resources_not_only_the_direct_parent(self):
        m = load()
        import fcntl, signal, threading
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'group-lock'
            code='import fcntl,time; f=open('+repr(str(lock))+',"w"); fcntl.flock(f,fcntl.LOCK_EX); time.sleep(30)'
            timers=[];original_killpg=os.killpg
            def delayed_group_kill(pgid,sig):
                # Model the kernel scheduling the direct parent's exit first.
                os.kill(pgid,sig)
                timer=threading.Timer(.12,original_killpg,args=(pgid,sig));timers.append(timer);timer.start()
            try:
                with patch.object(m.os,'killpg',side_effect=delayed_group_kill):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        m.run([sys.executable,'-c','import subprocess,time; subprocess.Popen('+repr([sys.executable,'-c',code])+'); time.sleep(30)'],.6)
                with lock.open('w') as handle:
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:
                for timer in timers:timer.join()

    def test_renderer_hash_missing_corrupt_and_deleted_helper_rejected(self):
        verifier = load('verify_bundle')
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(HERE / 'render_candidate.py'), '--out', tmp], check=True, capture_output=True)
            receipt = Path(tmp) / 'source-binding.json'
            binding = json.loads(receipt.read_text())
            self.assertEqual(binding['backend_browser_sha256'][HELPER], hashlib.sha256((ROOT / HELPER).read_bytes()).hexdigest())
            self.assertEqual(verifier.verify(tmp)['status'], 'PASS')
            for missing in (True, False):
                bad = copy.deepcopy(binding)
                if missing:
                    del bad['backend_browser_sha256'][HELPER]
                else:
                    bad['backend_browser_sha256'][HELPER] = '0' * 64
                receipt.write_text(json.dumps(bad))
                with self.assertRaises(AssertionError):
                    verifier.verify(tmp)
            receipt.write_text(json.dumps(binding))
            original = Path.read_bytes
            def absent(path):
                if path == ROOT / HELPER:
                    raise FileNotFoundError(str(path))
                return original(path)
            with patch.object(Path, 'read_bytes', absent), self.assertRaises(FileNotFoundError):
                verifier.verify(tmp)


if __name__ == '__main__':
    unittest.main(verbosity=2)
