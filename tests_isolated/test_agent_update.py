"""Self-update contracts: scratch scripts and loopback only, never real services."""
import importlib.util
from pathlib import Path
import unittest
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_agent', ROOT / 'agent/stella_agent.py')
assert spec is not None and spec.loader is not None
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class VersionTests(unittest.TestCase):
    def test_announcement_is_strictly_newer_numeric_release(self):
        instance = agent.Agent('https://offline.invalid', 'fixture')
        self.assertEqual(agent.AGENT_VERSION, '0.6.12')
        for version in ('0.6.9', '0.6.10', '0.6.11', agent.AGENT_VERSION, '', '0.6.010', '0.6.13rc1', ' 0.6.13',
                        '0.6', '0.6.13\n', None, 7, '9' * 1000 + '.1.1'):
            with self.subTest(version=version), patch.object(instance, '_get', return_value={'version': version}), patch.object(instance, '_download_and_restart') as download:
                instance.check_update()
                download.assert_not_called()
        for version in ('0.6.13', '0.7.0', '1.0.0'):
            self.assertGreater(tuple(map(int, version.split('.'))), tuple(map(int, agent.AGENT_VERSION.split('.'))))
            with self.subTest(version=version), patch.object(instance, '_get', return_value={'version': version}), patch.object(instance, '_download_and_restart') as download:
                instance.check_update()
                download.assert_called_once()


class DownloadTests(unittest.TestCase):
    body: bytes = b''
    status: int = 200
    encoding: str = ''
    manifest: dict = {}

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        cls.seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass
            def do_GET(self):
                cls.seen.append((self.path, self.headers.get('Authorization')))
                if self.path == '/agent/version':
                    import json
                    body = json.dumps(cls.manifest).encode()
                    self.send_response(200)
                else:
                    body = cls.body
                    self.send_response(cls.status)
                    if cls.encoding:
                        self.send_header('Content-Encoding', cls.encoding)
                    if cls.status == 302:
                        self.send_header('Location', '/redirected')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.worker.join(); cls.server.server_close()

    def setUp(self):
        import tempfile
        import hashlib
        import contextlib
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='stella-update-'))
        self.me = Path(directory) / 'stella_agent.py'
        self.old = b'AGENT_VERSION = "0.6.10"\n# old working fixture\n'
        self.me.write_bytes(self.old)
        self.me.chmod(0o640)
        cls = type(self)
        cls.body = b'AGENT_VERSION = "0.6.13"\nclass Agent: pass\ndef main(): pass\n'
        cls.status = 200
        cls.encoding = ''
        cls.manifest = {'version': '0.6.13', 'sha256': hashlib.sha256(cls.body).hexdigest(), 'size': len(cls.body)}
        cls.seen.clear()
        self.instance = agent.Agent('http://127.0.0.1:' + str(cls.server.server_port), 'fixture-credential')
        self.stack.enter_context(patch.object(agent, '__file__', str(self.me)))
        # No real service or process replacement under any outcome.
        self.exec = self.stack.enter_context(patch.object(agent.os, 'execv'))
        self.restarts = []
        original_popen = agent.subprocess.Popen
        def guarded_popen(argv, *args, **kwargs):
            if argv[0] == 'systemctl':
                self.restarts.append(argv)
                raise AssertionError('service restart forbidden')
            return original_popen(argv, *args, **kwargs)
        self.stack.enter_context(patch.object(agent.subprocess, 'Popen', guarded_popen))
        self.stack.enter_context(patch.object(agent.time, 'sleep'))

    def unchanged(self):
        self.assertEqual(self.me.read_bytes(), self.old)
        self.assertEqual(self.me.stat().st_mode & 0o777, 0o640)
        self.exec.assert_not_called()
        self.assertEqual(self.restarts, [])
        self.assertEqual(sorted(p.name for p in self.me.parent.iterdir()), ['stella_agent.py'])

    def publish(self, body):
        import hashlib
        type(self).body = body
        type(self).manifest = {'version': '0.6.13', 'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)}

    def test_old_access_time_does_not_block_a_valid_update(self):
        import os
        os.utime(self.me, (1, 2))
        self.instance.check_update()
        self.assertEqual(self.me.read_bytes(), type(self).body)
        self.exec.assert_called_once()

    def _stat_drift(self, field):
        import os
        original_lstat = os.lstat
        calls = 0
        def lstat(path, *args, **kwargs):
            nonlocal calls
            value = original_lstat(path, *args, **kwargs)
            if str(path) != str(self.me):
                return value
            calls += 1
            if calls < 2:
                return value
            values = list(value)
            extra = {name: getattr(value, name) for name in
                     ('st_atime', 'st_mtime', 'st_ctime', 'st_atime_ns', 'st_mtime_ns', 'st_ctime_ns')}
            if field == 'st_atime_ns':
                values[7] += 1
                extra['st_atime'] += 1
                extra['st_atime_ns'] += 1_000_000_000
            elif field.endswith('_ns'):
                extra[field] += 1
            else:
                index = {'st_ino': 1, 'st_dev': 2, 'st_mode': 0, 'st_uid': 4,
                         'st_gid': 5, 'st_size': 6}[field]
                values[index] += 1
            return os.stat_result(values, extra)
        return patch.object(agent.os, 'lstat', lstat)

    def test_simulated_access_time_only_drift_does_not_reject_update(self):
        with self._stat_drift('st_atime_ns'):
            self.instance.check_update()
        self.assertEqual(self.me.read_bytes(), type(self).body)
        self.exec.assert_called_once()

    def test_stable_identity_and_nanosecond_edit_drift_still_reject_update(self):
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_gid',
                      'st_mtime_ns', 'st_ctime_ns'):
            with self.subTest(field=field):
                self.me.write_bytes(self.old)
                self.me.chmod(0o640)
                self.exec.reset_mock()
                with self._stat_drift(field):
                    self.instance.check_update()
                self.unchanged()

    def test_runtime_load_failure_preserves_live_old_script(self):
        self.publish(type(self).body + b'raise RuntimeError("cannot import")\n')
        self.instance.check_update()
        self.unchanged()

    def test_success_loads_staged_and_installed_before_exec_without_service_restart(self):
        import subprocess
        import sys
        calls = []
        real_run = subprocess.run
        def run(argv, **kwargs):
            path = Path(argv[-2])
            calls.append((path, path.read_bytes()))
            return real_run(argv, **kwargs)
        for transport in (agent.httpx, None):
            self.me.write_bytes(self.old); self.me.chmod(0o640)
            self.exec.reset_mock(); calls.clear()
            with patch.object(agent, 'httpx', transport), patch.object(agent.subprocess, 'run', run):
                self.instance.check_update()
            self.assertEqual(self.me.read_bytes(), type(self).body)
            self.assertEqual(self.me.stat().st_mode & 0o777, 0o640)
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0][0], self.me)
            self.assertEqual(calls[1][0], self.me)
            self.assertTrue(all(body == type(self).body for _, body in calls))
            self.exec.assert_called_once_with(sys.executable, [sys.executable, str(self.me)] + sys.argv[1:])
            self.assertEqual(self.restarts, [])
            self.assertEqual(sorted(p.name for p in self.me.parent.iterdir()), ['stella_agent.py'])
        self.assertTrue(all(auth == 'Bearer fixture-credential' for path, auth in self.seen if path == '/agent/script'))

    def test_post_replace_load_failure_restores_bytes_and_mode(self):
        real_run = agent.subprocess.run
        def run(argv, **kwargs):
            if argv[-2] == str(self.me):
                raise RuntimeError('installed script failed loading')
            return real_run(argv, **kwargs)
        with patch.object(agent.subprocess, 'run', run):
            self.instance.check_update()
        self.unchanged()

    def test_exec_failure_restores_old_script_without_killing_process(self):
        self.exec.side_effect = OSError('exec unavailable')
        self.instance.check_update()
        self.assertEqual(self.me.read_bytes(), self.old)
        self.assertEqual(self.me.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.restarts, [])
        self.exec.assert_called_once()
        self.assertEqual(sorted(p.name for p in self.me.parent.iterdir()), ['stella_agent.py'])

    def test_real_exec_runs_only_relocated_fixture_and_keeps_recovery_copy(self):
        import subprocess
        import sys
        marker = self.me.parent / 'restarted-marker'
        self.publish(('AGENT_VERSION = "0.6.13"\nclass Agent: pass\n'
                      'def main():\n    from pathlib import Path\n    Path(' + repr(str(marker)) + ').write_text("fixture-restarted")\n'
                      'if __name__ == "__main__": main()\n').encode())
        worker = self.me.parent / 'fixture_worker.py'
        worker.write_text('import importlib.util\n'
                          's=importlib.util.spec_from_file_location("fixture_agent",' + repr(str(ROOT / 'agent/stella_agent.py')) + ')\n'
                          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                          'm.__file__=' + repr(str(self.me)) + '\n'
                          'm.Agent(' + repr(self.instance.url) + ',"fixture-credential").check_update()\n')
        result = subprocess.run([sys.executable, '-B', str(worker)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), 'fixture-restarted')
        backups = list(self.me.parent.glob('.stella-rollback-*.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.me.read_bytes(), type(self).body)
        self.assertEqual(self.restarts, [])

    def test_complete_agent_source_can_load_without_running_main(self):
        self.publish((ROOT / 'agent/stella_agent.py').read_bytes().replace(f'AGENT_VERSION = "{agent.AGENT_VERSION}"'.encode(), b'AGENT_VERSION = "0.6.13"', 1))
        self.instance.check_update()
        self.assertEqual(self.me.read_bytes(), type(self).body)
        self.exec.assert_called_once()
        self.assertEqual(self.restarts, [])

    def test_atomic_replace_failure_keeps_old_script_and_cleans_staging(self):
        with patch.object(agent.os, 'replace', side_effect=OSError('filesystem refused replace')):
            self.instance.check_update()
        self.unchanged()

    def test_failed_rollback_keeps_backup_and_live_process(self):
        real_replace = agent.os.replace
        def replace(source, target):
            if '.stella-rollback-' in str(source):
                raise OSError('rollback refused')
            return real_replace(source, target)
        self.exec.side_effect = OSError('exec refused')
        with patch.object(agent.os, 'replace', replace):
            self.instance.check_update()
        backups = list(self.me.parent.glob('.stella-rollback-*.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old)
        self.assertEqual(self.restarts, [])

    def test_early_success_exit_is_not_a_load_success(self):
        self.publish(b'AGENT_VERSION = "0.6.13"\nimport sys\nsys.exit(0)\n')
        self.instance.check_update()
        self.unchanged()

    def test_optimized_interpreter_still_checks_loaded_version(self):
        import os
        self.publish(type(self).body + b'globals()["AGENT_VERSION"] = "0.6.14"\n')
        with patch.dict(os.environ, {'PYTHONOPTIMIZE': '1'}):
            self.instance.check_update()
        self.unchanged()

    def test_load_timeout_keeps_old_script(self):
        import subprocess
        with patch.object(agent.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture-probe', 10)):
            self.instance.check_update()
        self.unchanged()

    def test_compressed_responses_cannot_bypass_raw_download_budget(self):
        import gzip
        type(self).body = gzip.compress(type(self).body)
        type(self).encoding = 'gzip'
        for transport in (agent.httpx, None):
            with patch.object(agent, 'httpx', transport):
                self.instance.check_update()
            self.unchanged()

    def test_stream_exceeding_declared_budget_is_rejected(self):
        type(self).body = b'x' * 131072
        type(self).manifest['size'] = 60
        for transport in (agent.httpx, None):
            with patch.object(agent, 'httpx', transport):
                self.instance.check_update()
            self.unchanged()

    def test_invalid_artifacts_never_replace_old_script(self):
        import hashlib
        good = type(self).body
        cases = [b'', b'<html>error</html>', b'AGENT_VERSION = "0.6.13"\ndef broken(:\n',
                 good.replace(b'0.6.13', b'0.6.10'), b'AGENT_VERSION = "0.6.13"\nAGENT_VERSION = "0.6.14"\n',
                 b'AGENT_VERSION = "0.6.13"\n' + b'#' * (2 * 1024 * 1024), b'\xff']
        for transport in (agent.httpx, None):
            for body in cases:
                with self.subTest(transport=bool(transport), prefix=body[:40]), patch.object(agent, 'httpx', transport):
                    type(self).body = body
                    type(self).manifest.update(sha256=hashlib.sha256(body).hexdigest(), size=len(body))
                    self.instance.check_update()
                    self.unchanged()
            type(self).body = good
            for manifest in ({'version': '0.6.13'},
                             {'version': '0.6.13', 'sha256': '0' * 64, 'size': len(good)},
                             {'version': '0.6.13', 'sha256': hashlib.sha256(good).hexdigest(), 'size': len(good) + 1}):
                with self.subTest(manifest=manifest), patch.object(agent, 'httpx', transport):
                    type(self).manifest = manifest
                    self.instance.check_update()
                    self.unchanged()

    def test_http_errors_and_redirects_never_install_both_transports(self):
        for transport in (agent.httpx, None):
            for status in (302, 404, 503):
                with self.subTest(transport=bool(transport), status=status), patch.object(agent, 'httpx', transport):
                    type(self).status = status
                    self.instance.check_update()
                    self.unchanged()
        self.assertFalse(any(path == '/redirected' for path, _ in self.seen))


class BackendManifestTests(unittest.TestCase):
    def test_manifest_hashes_exact_served_bytes_and_respects_legacy_rollout(self):
        import ast
        import hashlib
        import os
        import tempfile
        tree = ast.parse((ROOT / 'app/routers/monitor.py').read_text())
        functions: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'agent_script', 'agent_version'}]
        for node in functions:
            assert isinstance(node, ast.FunctionDef)
            node.decorator_list = []
        with tempfile.TemporaryDirectory(prefix='stella-manifest-') as tmp:
            root = Path(tmp)
            (root / 'agent').mkdir()
            body = b'AGENT_VERSION = "0.6.12"\r\n# fixture\r\n'
            (root / 'agent/stella_agent.py').write_bytes(body)
            from fastapi import HTTPException
            namespace: dict[str, Any] = {'__file__': str(root / 'app/routers/monitor.py'), 'HTTPException': HTTPException}
            exec(compile(ast.Module(body=functions, type_ignores=[]), 'fixture-monitor', 'exec'), namespace)
            with patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': '0.6.12'}):
                manifest = namespace['agent_version']()
                self.assertEqual(manifest, {'version': '0.6.12', 'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)})
                self.assertEqual(namespace['agent_script']().body, body)
            for version in ('0.6.9', '0.6.10', '0.6.11'):
                with self.subTest(version=version), patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': version}):
                    self.assertEqual(namespace['agent_version'](), {'version': version})
            for version in ('0.6.13', '0.6.12 ', '0.6.012', 'latest'):
                with self.subTest(version=version), patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': version}):
                    with self.assertRaises(HTTPException) as rejected:
                        namespace['agent_version']()
                    self.assertEqual(rejected.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
