"""Run the real installer with an apt-only fake PATH and relocated writes.

No host package/user/service operations or networking are permitted.
Run: python3 -m unittest discover -s tests_isolated -p test_agent_installer.py -v
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'agent/install.sh'
FAKE = r'''#!PYTHON
import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['SANDBOX'])
# Never log curl arguments: they may contain credentials.
with (root / 'calls').open('a') as f:
    f.write(name + (' ' + ' '.join(args) if name not in ('curl',) else '') + '\n')
mode = os.environ.get('MODE', '')
if name == 'id':
    print('1000' if mode == 'nonroot' and args == ['-u'] else '0')
elif name == 'python3':
    if args == ['--version']: print('Python 3.12.3')
    elif args[:2] == ['-m', 'pip']:
        if mode == 'no-pip': sys.exit(1)
        if 'install' in args: sys.exit(1)  # PEP 668 managed Python
        print('pip (externally managed)')
    elif args[:1] == ['-c'] and args[1] in ('import httpx', 'import psutil'):
        sys.exit(0 if (root / 'deps').exists() else 1)
    else:
        os.execv(sys.executable, [sys.executable] + args)
elif name == 'apt-get':
    if mode == 'apt-failure': sys.exit(1)
    if 'python3-httpx' in args or 'python3-psutil' in args: (root / 'deps').touch()
elif name == 'curl':
    if any('/agent/config' in arg for arg in args):
        print('401' if mode == 'unauthorized' else '503' if mode == 'unavailable' else '200', end='')
    else:
        assert '-fsSL' in args or '--fail' in args, 'download must fail on HTTP errors'
        if mode == 'download-failure': sys.exit(22)
        target = args[args.index('-o') + 1]
        pathlib.Path(target).write_text('<html>login</html>' if mode == 'html' else '' if mode == 'empty' else '#!/usr/bin/env python3\nprint("agent")\n')
elif name == 'systemctl' and (mode == 'service-failure' or (mode == 'service-crash' and 'is-active' in args)): sys.exit(1)
'''


class AgentInstallerTest(unittest.TestCase):
    def run_install(self, mode='', deps: str | None = '--deps', missing=()):
        with tempfile.TemporaryDirectory(prefix='stella-installer-') as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            for directory in ('opt/stella-agent', 'etc/sudoers.d', 'etc/systemd/system', 'usr/local/bin'):
                (root / directory).mkdir(parents=True, exist_ok=True)
            old = root / 'opt/stella-agent/stella_agent.py'
            old.write_text('# old working agent\n')
            script = SOURCE.read_text()
            for prefix in ('/opt/stella-agent', '/etc/sudoers.d', '/etc/systemd/system', '/usr/local/bin'):
                script = script.replace(prefix, str(root) + prefix)
            installer = root / 'install.sh'
            installer.write_text(script)
            for name in ('cat', 'chmod', 'mkdir', 'mktemp', 'mv', 'rm', 'head'):
                executable = shutil.which(name)
                assert executable, name
                (bindir / name).symlink_to(executable)
            for name in ('id', 'useradd', 'chown', 'systemctl', 'apt-get', 'python3', 'curl', 'iperf3', 'speedtest-go', 'sleep'):
                if name in missing:
                    continue
                stub = bindir / name
                stub.write_text(FAKE.replace('#!PYTHON', '#!' + sys.executable))
                stub.chmod(0o755)
            env = dict(os.environ, PATH=str(bindir), SANDBOX=tmp, MODE=mode)
            # Feeding the installer over stdin reproduces curl|bash. No controlling tty.
            result = subprocess.run(['/bin/bash', '-s', '--', '--url', 'https://example.invalid', '--token', 'secret-regression-token'] + ([deps] if deps else []), input=script, text=True, capture_output=True, env=env, start_new_session=True, timeout=15)
            output = result.stdout + result.stderr
            self.assertNotIn('secret-regression-token', output)
            self.assertFalse(list((root / 'opt/stella-agent').glob('.stella_agent.*')))
            self.assertFalse((root / 'opt/stella-agent/__pycache__').exists())
            return result.returncode, output, old.read_text(), (root / 'calls').read_text(), (root / 'etc/systemd/system/stella-agent.service').exists()

    def test_apt_only_reaches_completion_and_managed_python_dependencies(self):
        code, output, agent, calls, service = self.run_install()
        self.assertEqual(code, 0, output)
        self.assertIn('安装完成', output)
        self.assertIn('python3-httpx', calls)
        self.assertIn('python3-psutil', calls)
        self.assertNotIn('pip install', calls)
        self.assertIn('print("agent")', agent)
        self.assertTrue(service)
        self.assertIn('systemctl restart stella-agent', calls)

    def test_no_deps_reaches_completion_without_package_installs(self):
        code, output, _, calls, service = self.run_install('no-pip', deps='--no-deps')
        self.assertEqual(code, 0, output)
        self.assertTrue(service)
        self.assertNotIn('apt-get install', calls)
        self.assertIn('安装完成', output)

    def test_bad_download_never_overwrites_or_starts_service(self):
        for mode in ('html', 'empty', 'download-failure'):
            with self.subTest(mode=mode):
                code, output, agent, calls, service = self.run_install(mode)
                self.assertNotEqual(code, 0, output)
                self.assertIn('错误', output)
                self.assertEqual(agent, '# old working agent\n')
                self.assertFalse(service)
                self.assertNotIn('systemctl restart', calls)

    def test_token_errors_abort_even_with_auto_dependencies(self):
        for mode in ('unauthorized', 'unavailable'):
            with self.subTest(mode=mode):
                code, output, agent, calls, service = self.run_install(mode)
                self.assertNotEqual(code, 0, output)
                self.assertIn('错误', output)
                self.assertEqual(agent, '# old working agent\n')
                self.assertFalse(service)
                self.assertNotIn('systemctl restart', calls)

    def test_mandatory_prerequisites_are_explicit(self):
        for mode, missing in (('nonroot', ()), ('', ('systemctl',)), ('', ('curl',))):
            with self.subTest(mode=mode, missing=missing):
                code, output, _, calls, _ = self.run_install(mode, missing=missing)
                self.assertNotEqual(code, 0, output)
                self.assertIn('错误', output)
                self.assertNotIn('apt-get install', calls)

    def test_unexpected_failure_has_safe_stage_diagnostic(self):
        code, output, _, _, _ = self.run_install('service-failure')
        self.assertNotEqual(code, 0)
        self.assertIn('错误', output)
        self.assertIn('systemd', output)
        self.assertNotIn('安装完成', output)

    def test_started_then_crashed_service_is_not_success(self):
        code, output, _, calls, _ = self.run_install('service-crash')
        self.assertNotEqual(code, 0)
        self.assertIn('systemctl restart stella-agent', calls)
        self.assertIn('错误', output)
        self.assertNotIn('安装完成', output)

    def test_no_tty_does_not_consume_piped_installer(self):
        code, output, _, _, service = self.run_install(deps=None)
        self.assertEqual(code, 0, output)
        self.assertTrue(service)
        self.assertIn('安装完成', output)
        self.assertNotIn('/dev/tty:', output)

    def test_optional_dependency_failures_remain_optional(self):
        for mode in ('no-pip', 'apt-failure'):
            with self.subTest(mode=mode):
                code, output, _, calls, _ = self.run_install(mode, deps=None)
                self.assertEqual(code, 0, output)
                self.assertIn('安装完成', output)
                self.assertNotIn('--break-system-packages', calls)


if __name__ == '__main__':
    unittest.main()
