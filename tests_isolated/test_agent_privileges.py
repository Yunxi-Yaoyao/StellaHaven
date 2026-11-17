"""Offline privilege/transport contracts; never use real sudo/Docker/services."""
import contextlib
import ast
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
from types import ModuleType
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
        exec_lines = [line for line in shell.splitlines() if 'ExecStart=' in line]
        self.assertTrue(exec_lines)
        self.assertTrue(all('--token' not in line for line in exec_lines))
        self.assertIn('EnvironmentFile=', shell)
        # V11 host installation delegates to the same per-center installer;
        # credentials are inherited in its environment, never child arguments.
        # Execute the exact inert host transport slice; package __init__ imports
        # repositories/DB and must not be bootstrapped merely to test argv.
        host_module = ModuleType('privilege_host_transport')
        host_module.__dict__.update(__file__=str(ROOT / 'app/services/host.py'),
                                    platform=agent.platform, os=os, shutil=agent.shutil,
                                    subprocess=subprocess, Path=Path)
        nodes = [node for node in ast.parse(host).body
                 if isinstance(node, ast.FunctionDef) and node.name in {'supports_local_install', 'install_host'}
                 or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'HOST_INSTANCE' for target in node.targets)]
        self.assertEqual(len(nodes), 3)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'real-host-transport-slice', 'exec'), host_module.__dict__)
        calls = []
        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, 'stella-agent-' + 'a' * 24, '')
        with patch.object(host_module, 'supports_local_install', return_value=True), patch.object(host_module.platform, 'system', return_value='Linux'), patch.object(host_module.os, 'geteuid', return_value=0), patch.object(host_module.shutil, 'which', return_value='/fixture/tool'), patch.object(host_module.subprocess, 'run', run):
            self.assertEqual(host_module.install_host('credential-marker', 'https://center.invalid'),
                             {'installed': True, 'service': 'stella-agent-' + 'a' * 24})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ['/bin/bash', str(ROOT / 'agent/install.sh'), '--url', 'https://center.invalid', '--instance', 'host', '--no-deps'])
        self.assertNotIn('credential-marker', repr(calls[0][0]))
        self.assertEqual(calls[0][1]['env']['STELLA_TOKEN'], 'credential-marker')
        self.assertNotIn('ExecStart=', host)

    def test_new_protocol_version_and_windows_installer_header(self):
        self.assertEqual(agent.AGENT_VERSION, '0.6.20')
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
        # V11 default installation has no Docker grant at all. The fixed
        # Docker helper remains independently validated for legacy migration.
        self.assertIn("<<'STELLA_INSTANCE_INSTALLER'", script)
        self.assertNotIn('STELLA_DOCKER_HELPER', script)
        self.assertNotIn('/usr/bin/docker', script)
        self.assertNotIn('_CMDS="${_CMDS}, ${_DOCKER}"', script)
        self.assertNotIn('--data-urlencode "token=$TOKEN"', script)
        self.assertIn("headers = {'Authorization':'Bearer '+token} if token else {}", script)
        self.assertIn('visudo', script)
        module_path = ROOT / 'app/services/agent_install.py'
        self.assertTrue(module_path.exists(), 'local installer privilege module missing')
        installer = load(module_path, 'isolated_agent_installer')
        rules = installer.docker_sudoers()
        self.assertEqual(len(rules.splitlines()), 6)
        self.assertNotIn('/usr/bin/docker', rules)
        for action in ('ps', 'inspect', 'logs', 'start', 'stop', 'restart'):
            self.assertIn('/usr/local/libexec/stella-docker-helper ' + action, rules)
        self.assertEqual(installer.HELPER_SOURCE, HELPER)

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

class RelocatedInstallerRegressionTests(legacy_installer_tests.LinuxInstances):
    """Replay every current installer case; strengthen its actual install hook."""
    def install(self, extra_env=None, origin=None, extra_args=()):
        result = super().install(extra_env=extra_env, origin=origin, extra_args=extra_args)
        if result.returncode == 0:
            manifests = list((self.root / 'etc/stella-agents').glob('*/instance.json'))
            self.assertTrue(manifests)
            for manifest in manifests:
                binding = json.loads(manifest.read_text())
                iid, service = binding['instance_id'], binding['service']
                helper = self.root / 'usr/local/libexec' / service
                sudoers = self.root / 'etc/sudoers.d' / service
                envfile = manifest.parent / 'agent.env'
                unit = self.root / 'etc/systemd/system' / (service + '.service')
                # Default per-instance grants permit only scheduled self-removal,
                # not Docker, arbitrary systemctl, networking, or argument wildcards.
                self.assertEqual(sudoers.read_text(), f'sta{iid} ALL=(root) NOPASSWD: {helper} --schedule\n')
                for path, mode in ((helper, 0o755), (sudoers, 0o440), (envfile, 0o600)):
                    self.assertEqual((path.stat().st_uid, path.stat().st_gid, path.stat().st_mode & 0o777), (0, 0, mode))
                self.assertNotIn(legacy_installer_tests.TOKEN, unit.read_text())
                self.assertNotIn(legacy_installer_tests.TOKEN, helper.read_text())
                self.assertIn(legacy_installer_tests.TOKEN, envfile.read_text())
                self.assertIn('EnvironmentFile=' + str(envfile) + '\n', unit.read_text())
                self.assertEqual([line for line in unit.read_text().splitlines() if line.startswith('ExecStart=')],
                                 ['ExecStart=/usr/bin/env python3 ' + str(self.root / 'opt/stella-agents' / iid / 'stella_agent.py')])
                self.assertFalse(list(manifest.parent.glob('.install-*')))
                self.assertFalse((self.root / 'opt/stella-agents' / iid / '__pycache__').exists())
        return result

    def test_current_instance_helper_rejects_ungranted_commands_without_side_effects(self):
        self.assertEqual(self.install().returncode, 0)
        helper = self.root / 'usr/local/libexec' / ('stella-agent-' + legacy_installer_tests.instance_id(self.center))
        before, calls = self.snapshot(), self.calls()
        for args in ([], ['docker', 'ps'], ['--remove', 'other'], ['--schedule', '--remove']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-I', str(helper), *args], env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr.strip(), 'Stella instance removal refused or failed')
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.calls(), calls)

if __name__ == '__main__':
    unittest.main()
