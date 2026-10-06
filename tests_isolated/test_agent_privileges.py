"""Offline privilege/transport contracts; never use real sudo/Docker/services."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'deploy/agent-privileges/stella-docker-helper.py'

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

agent = load(ROOT / 'agent/stella_agent.py', 'privilege_agent')

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.instance = agent.Agent('https://center.invalid', 'credential-marker')

    def test_all_generic_requests_use_bearer_not_query_both_transports(self):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'ok': True}
            def read(self): return b'{"ok":true}'
            def __enter__(self): return self
            def __exit__(self, *args): pass
        for transport in ('httpx', 'urllib'):
            for method in ('_get', '_post'):
                with self.subTest(transport=transport, method=method):
                    calls = []
                    if transport == 'httpx':
                        class Client:
                            @staticmethod
                            def get(url, **kw): calls.append((url, kw)); return Response()
                            post = get
                        cm = patch.object(agent, 'httpx', Client)
                        other = contextlib.nullcontext()
                    else:
                        cm = patch.object(agent, 'httpx', None)
                        def open_request(req, **kw):
                            calls.append((req if isinstance(req, str) else req.full_url, {'headers': {} if isinstance(req, str) else dict(req.header_items())}))
                            return Response()
                        other = patch('urllib.request.OpenerDirector.open', lambda opener, req, **kw: open_request(req, **kw))
                    with cm, other:
                        getattr(self.instance, method)('/agent/config', token=self.instance.token, status='done')
                    url, kw = calls[0]
                    self.assertNotIn('credential-marker', url)
                    self.assertNotIn('token', kw.get('params', {}))
                    self.assertEqual(kw['headers']['Authorization'], 'Bearer credential-marker')

    def test_map_target_stream_uses_header_both_transports(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_raw(self): return iter([b'{"targets":[]}'])
            def read1(self, size):
                if getattr(self, 'read_done', False): return b''
                self.read_done = True
                return b'{"targets":[]}'
        for kind in ('httpx', 'urllib'):
            calls = []
            class Client:
                @staticmethod
                def stream(method, url, **kw): calls.append((url, kw['headers'])); return Response()
            class Opener:
                def open(self, request, **kw):
                    calls.append((request if isinstance(request, str) else request.full_url, {} if isinstance(request, str) else dict(request.header_items())))
                    return Response()
            with patch.object(agent, 'httpx', Client if kind == 'httpx' else None), patch('urllib.request.build_opener', return_value=Opener()):
                self.assertEqual(self.instance._get_map_targets(), [])
            self.assertEqual(calls, [('https://center.invalid/agent/map-targets', {'Authorization': 'Bearer credential-marker', 'Accept-Encoding': 'identity'} if kind == 'httpx' else {'Authorization': 'Bearer credential-marker', 'Accept-encoding': 'identity'})])

    def test_component_download_never_exposes_token_in_url_or_child_argv(self):
        calls, requests = [], []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                if getattr(self, 'done', False): return b''
                self.done = True
                return b'x' * 100001
        class Opener:
            def open(self, req, **kw): requests.append(req); return Response()
        def run(args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, '', '')
        with tempfile.TemporaryDirectory(prefix='stella-component-') as tmp, patch.object(self.instance, '_agent_bin', return_value=tmp), patch.object(agent.subprocess, 'run', run), patch.object(agent.platform, 'system', return_value='Linux'), patch('urllib.request.build_opener', return_value=Opener()):
            result = self.instance._install_speedtest_go()
        self.assertNotIn('credential-marker', repr(calls))
        self.assertEqual(result, None)
        self.assertEqual(requests[0].full_url, 'https://center.invalid/agent/component/speedtest-go')
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer credential-marker')

    def test_urllib_authentication_does_not_follow_redirects(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.error import HTTPError
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass
            def do_GET(self):
                seen.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302); self.send_header('Location', '/received'); self.end_headers()
                else:
                    self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            instance = agent.Agent('http://127.0.0.1:' + str(server.server_port), 'credential-marker')
            with patch.object(agent, 'httpx', None), self.assertRaises(HTTPError):
                instance._get('/redirect')
            self.assertEqual(seen, ['/redirect'])
        finally:
            server.shutdown(); worker.join(); server.server_close()

    def test_importing_agent_never_starts_threads_or_main(self):
        with patch.object(threading.Thread, 'start', side_effect=AssertionError('unexpected thread start')):
            imported = load(ROOT / 'agent/stella_agent.py', 'import_only_agent')
        self.assertTrue(hasattr(imported, 'Agent'))

    def test_center_url_refuses_embedded_secrets_before_logging(self):
        for url in ('https://user:pass@center.invalid', 'https://center.invalid?token=secret', 'https://center.invalid#secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                agent.Agent(url, 'credential-marker')

    def test_installed_service_does_not_expose_token_in_process_args(self):
        shell = (ROOT / 'agent/install.sh').read_text()
        host = (ROOT / 'app/services/host.py').read_text()
        for source in (shell, host):
            exec_lines = [line for line in source.splitlines() if 'ExecStart=' in line]
            self.assertTrue(exec_lines)
            self.assertTrue(all('--token' not in line for line in exec_lines))
            self.assertIn('EnvironmentFile=', source)

    def test_new_protocol_version_and_windows_installer_header(self):
        self.assertEqual(agent.AGENT_VERSION, '0.6.10')
        script = (ROOT / 'agent/install.ps1').read_text()
        self.assertNotIn('/agent/config?token=', script)
        self.assertIn('Authorization', script)

    def test_command_output_is_bounded_json_body_not_query(self):
        requests = []
        class Response:
            def raise_for_status(self): pass
            def json(self): return {}
        class Client:
            @staticmethod
            def post(url, **kw): requests.append((url, kw)); return Response()
        # Exercise actual safe shell command execution, not sudo or Docker.
        with patch.object(agent, 'httpx', Client):
            self.instance._run_command({'id': 7, 'command': "printf 'stdout-marker'; printf 'stderr-marker' >&2"})
            with patch.object(agent.subprocess, 'run', side_effect=subprocess.TimeoutExpired('offline', 30)):
                self.instance._run_command({'id': 8, 'command': 'not-executed'})
        for url, kw in requests:
            self.assertEqual(kw['params'], {})
            self.assertNotIn('marker', url)
            self.assertEqual(kw['headers']['Authorization'], 'Bearer credential-marker')
        self.assertEqual(requests[0][1]['json'], dict(status='done', stdout='stdout-marker', stderr='stderr-marker', exit_code=0))
        self.assertEqual(requests[1][1]['json'], dict(status='failed', stdout='', stderr='timeout', exit_code=-1))

class InstallerPrivilegeTests(unittest.TestCase):
    def test_local_privilege_install_is_root_owned_and_validated_in_sandbox(self):
        installer = load(ROOT / 'app/services/agent_install.py', 'local_privileges_real')
        with tempfile.TemporaryDirectory(prefix='stella-rootfiles-') as tmp:
            base = Path(tmp)
            helper = base / 'libexec/stella-docker-helper'
            sudoers = base / 'sudoers/stella-docker'
            config = base / 'config/docker'
            with patch.object(installer, 'HELPER_PATH', helper), patch.object(installer, 'SUDOERS_PATH', sudoers), patch.object(installer, 'DOCKER_CONFIG', config):
                installer.install_privileges()
            for path, mode in ((helper, 0o755), (sudoers, 0o440)):
                self.assertEqual(path.stat().st_uid, 0)
                self.assertEqual(path.stat().st_gid, 0)
                self.assertEqual(path.stat().st_mode & 0o777, mode)
            self.assertEqual(helper.read_text(), HELPER.read_text())
            # Actual visudo parser, read-only syntax check on scratch file only.
            self.assertEqual(subprocess.run(['/usr/sbin/visudo', '-cf', str(sudoers)], capture_output=True).returncode, 0)
            helper.unlink()
            target = base / 'attacker.py'; target.write_text('unchanged')
            helper.symlink_to(target)
            with self.assertRaises(PermissionError):
                installer._root_file(helper, 'bad', 0o755)
            self.assertEqual(target.read_text(), 'unchanged')
            unsafe = base / 'unsafe'; unsafe.mkdir(); unsafe.chmod(0o777)
            with self.assertRaises(PermissionError):
                installer._root_file(unsafe / 'helper', 'bad', 0o755)
            self.assertFalse((unsafe / 'helper').exists())

    def test_legacy_docker_grant_migration_preserves_authorized_network_rules(self):
        installer = load(ROOT / 'app/services/agent_install.py', 'local_privileges_migration')
        old = '# retained\\nstella ALL=(root) NOPASSWD: /usr/bin/ip, /usr/bin/docker, /usr/sbin/ufw\\n'.replace('\\n', '\n')
        self.assertTrue(hasattr(installer, 'remove_legacy_docker_grants'), 'migration not implemented')
        cleaned = installer.remove_legacy_docker_grants(old)
        self.assertNotIn('/usr/bin/docker', cleaned)
        self.assertIn('/usr/bin/ip', cleaned)
        self.assertIn('/usr/sbin/ufw', cleaned)
        self.assertIn('# retained', cleaned)

    def test_installers_bundle_same_helper_and_per_command_sudo_rules(self):
        script = (ROOT / 'agent/install.sh').read_text()
        self.assertIn("<<'STELLA_DOCKER_HELPER'", script)
        embedded = script.split("<<'STELLA_DOCKER_HELPER'\n", 1)[1].split('\nSTELLA_DOCKER_HELPER', 1)[0] + '\n'
        self.assertEqual(embedded, HELPER.read_text())
        self.assertNotIn('_CMDS="${_CMDS}, ${_DOCKER}"', script)
        self.assertNotIn('--data-urlencode "token=$TOKEN"', script)
        self.assertIn('Authorization: Bearer $TOKEN', script)
        self.assertIn('visudo', script)
        module_path = ROOT / 'app/services/agent_install.py'
        self.assertTrue(module_path.exists(), 'local installer privilege module missing')
        installer = load(module_path, 'isolated_agent_installer')
        rules = installer.docker_sudoers()
        self.assertEqual(len(rules.splitlines()), 6)
        self.assertNotIn('/usr/bin/docker', rules)
        for action in ('ps', 'inspect', 'logs', 'start', 'stop', 'restart'):
            self.assertIn('/usr/local/libexec/stella-docker-helper ' + action, rules)
        host = (ROOT / 'app/services/host.py').read_text()
        self.assertIn('install_privileges()', host)

class AgentDockerTests(unittest.TestCase):
    def test_docker_detection_never_executes_a_path_selected_binary(self):
        instance = agent.Agent('https://center.invalid', 'credential-marker')
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, 'Docker version 27.5.1' if '--version' in argv else 'active', '')
        with patch.object(agent.shutil, 'which', return_value='/attacker/docker'), patch.object(agent.os.path, 'isfile', return_value=True), patch.object(agent.subprocess, 'run', run):
            self.assertTrue(instance._check_docker()['installed'])
        self.assertNotIn('/attacker/docker', repr(calls))
        self.assertIn(['/usr/bin/docker', '--version'], calls)

    def test_every_docker_panel_path_uses_helper_even_as_root(self):
        instance = agent.Agent('https://center.invalid', 'credential-marker')
        for uid in (0, 1001):
            calls = []
            def run(argv, **kw):
                calls.append((argv, kw))
                return subprocess.CompletedProcess(argv, 0, '[]' if 'inspect' in argv else '', '')
            with patch.object(agent.os, 'geteuid', return_value=uid), patch.object(agent.os.path, 'isfile', return_value=True), patch.object(agent.shutil, 'which', return_value='/evil/docker'), patch.object(agent.subprocess, 'run', run):
                instance._docker_scan()
                instance._docker_ctl({'action': 'restart', 'container': 'app'})
                instance._docker_logs({'container': 'app', 'tail': 999})
                instance._docker_inspect({'container': 'app'})
            prefix = [] if uid == 0 else ['/usr/bin/sudo', '-n']
            expected = [prefix + ['/usr/local/libexec/stella-docker-helper'] + args for args in (['ps'], ['restart', 'app'], ['logs', 'app', '500'], ['inspect', 'app'])]
            self.assertEqual([argv for argv, _ in calls], expected)
            self.assertTrue(all(not kw.get('shell', False) for _, kw in calls))

class DockerHelperTests(unittest.TestCase):
    def run_helper(self, args):
        self.assertTrue(HELPER.is_file(), 'root-owned Docker helper is missing')
        with tempfile.TemporaryDirectory(prefix='stella-helper-') as tmp:
            root = Path(tmp)
            fake = root / 'docker'
            fake.write_text('#!' + sys.executable + '\nimport json,os,sys\nprint(json.dumps({"argv":sys.argv[1:],"env":dict(os.environ),"cwd":os.getcwd()}))\n')
            fake.chmod(0o755)
            relocated = root / 'helper.py'
            # Relocate ONLY the fixed binary in an isolated copy. Production has no override.
            relocated.write_text(HELPER.read_text().replace('"/usr/bin/docker"', repr(str(fake))))
            env = dict(os.environ, DOCKER_HOST='tcp://evil.invalid:2375', DOCKER_CONTEXT='evil', DOCKER_CONFIG='/evil', PYTHONPATH='/evil')
            return subprocess.run([sys.executable, '-I', str(relocated)] + args, capture_output=True, text=True, timeout=5, env=env)

    def test_container_actions_are_exact_single_validated_argument(self):
        for action in ('inspect', 'start', 'stop', 'restart'):
            with self.subTest(action=action):
                result = self.run_helper([action, 'app_1.test-abc'])
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = [action, '--type', 'container', 'app_1.test-abc'] if action == 'inspect' else [action, 'app_1.test-abc']
                self.assertEqual(json.loads(result.stdout)['argv'][2:], expected)

    def test_reject_unknown_actions_options_names_and_argument_smuggling(self):
        bad = [[], ['exec', 'app', 'sh'], ['run', '--privileged', 'alpine'],
               ['context', 'use', 'evil'], ['--host', 'tcp://evil', 'ps'],
               ['ps', '-a'], ['inspect', 'app', '--format', '{{.Config}}'],
               ['start', 'app', 'other'], ['restart', '--help'], ['stop', 'app;id'],
               ['inspect', '../app'], ['inspect', '/app'], ['inspect', 'a b'],
               ['inspect', 'a\n'], ['inspect', 'a' * 129], ['logs', 'app', 'all'],
               ['logs', 'app', '0'], ['logs', 'app', '501'], ['logs', 'app', '-1'],
               ['logs', 'app', '1', '--follow']]
        for args in bad:
            with self.subTest(args=args):
                result = self.run_helper(args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '', 'fake Docker must not execute rejected requests')
                self.assertEqual(result.stderr.strip(), 'stella Docker helper: request refused')

    def test_logs_is_bounded_tail_without_follow_or_options(self):
        for tail in ('1', '150', '500'):
            result = self.run_helper(['logs', 'app', tail])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['argv'][2:], ['logs', '--tail', tail, 'app'])

    def test_ps_executes_fixed_socket_format_and_clean_environment(self):
        result = self.run_helper(['ps'])
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual['argv'], ['--host', 'unix:///var/run/docker.sock', 'ps', '-a', '--format', '{{json .}}'])
        self.assertEqual(actual['cwd'], '/')
        self.assertEqual(actual['env']['PATH'], '/usr/sbin:/usr/bin:/sbin:/bin')
        self.assertNotIn('DOCKER_HOST', actual['env'])
        self.assertNotIn('DOCKER_CONTEXT', actual['env'])
        self.assertNotIn('PYTHONPATH', actual['env'])
        self.assertEqual(actual['env']['DOCKER_CONFIG'], '/etc/stella-agent/docker')

legacy_installer_tests = load(ROOT / 'tests_isolated/test_agent_installer.py', 'legacy_installer_test_cases')

class RelocatedInstallerRegressionTests(legacy_installer_tests.AgentInstallerTest):
    """Replay EVERY existing installer acceptance case with all new writes relocated."""
    def run_install(self, mode='', deps='--deps', missing=()):
        import shutil
        with tempfile.TemporaryDirectory(prefix='stella-installer-') as tmp:
            root = Path(tmp)
            bindir = root / 'bin'; bindir.mkdir()
            prefixes = ('/opt/stella-agent', '/etc/sudoers.d', '/etc/systemd/system',
                        '/usr/local/bin', '/usr/local/libexec', '/etc/stella-agent')
            for prefix in prefixes:
                (root / prefix.lstrip('/')).mkdir(parents=True, exist_ok=True)
            old = root / 'opt/stella-agent/stella_agent.py'
            old.write_text('# old working agent\n')
            script = (ROOT / 'agent/install.sh').read_text()
            for prefix in prefixes:
                script = script.replace(prefix, str(root) + prefix)
            for name in ('cat', 'chmod', 'mkdir', 'mktemp', 'mv', 'rm', 'head'):
                executable = shutil.which(name)
                assert executable is not None
                (bindir / name).symlink_to(executable)
            (bindir / 'visudo').symlink_to('/usr/sbin/visudo')
            for name in ('id', 'useradd', 'chown', 'systemctl', 'apt-get', 'python3', 'curl', 'iperf3', 'speedtest-go', 'sleep', 'docker', 'ip', 'ufw', 'wg'):
                if name in missing: continue
                stub = bindir / name
                stub.write_text(legacy_installer_tests.FAKE.replace('#!PYTHON', '#!' + sys.executable))
                stub.chmod(0o755)
            env = dict(os.environ, PATH=str(bindir), SANDBOX=tmp, MODE=mode)
            result = subprocess.run(['/bin/bash', '-s', '--', '--url', 'https://example.invalid', '--token', 'secret-regression-token'] + ([deps] if deps else []), input=script, text=True, capture_output=True, env=env, start_new_session=True, timeout=20)
            output = result.stdout + result.stderr
            self.assertNotIn('secret-regression-token', output)
            service = root / 'etc/systemd/system/stella-agent.service'
            helper = root / 'usr/local/libexec/stella-docker-helper'
            if result.returncode == 0:
                self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
                self.assertEqual(helper.stat().st_uid, 0)
                rules = (root / 'etc/sudoers.d/stella-docker').read_text()
                self.assertNotIn(str(bindir / 'docker'), rules)
                self.assertEqual(len(rules.splitlines()), 6)
                retained = (root / 'etc/sudoers.d/stella-uninstall').read_text()
                self.assertIn(str(bindir / 'ip'), retained)
                self.assertIn(str(bindir / 'ufw'), retained)
                self.assertNotIn(str(bindir / 'docker'), retained)
                self.assertNotIn('secret-regression-token', service.read_text())
                self.assertEqual((root / 'etc/stella-agent/agent.env').stat().st_mode & 0o777, 0o600)
                self.assertIn('secret-regression-token', (root / 'etc/stella-agent/agent.env').read_text())
            self.assertFalse(list((root / 'opt/stella-agent').glob('.stella_agent.*')))
            self.assertFalse((root / 'opt/stella-agent/__pycache__').exists())
            return result.returncode, output, old.read_text(), (root / 'calls').read_text(), service.exists()

if __name__ == '__main__':
    unittest.main()
