"""Keep the already deployed 0.6.14 fixes when merging new collectors."""
import ast
import importlib.util
from pathlib import Path
import unittest
from collections import deque
import json
import zlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('agent_release_continuity', ROOT / 'agent/stella_agent.py')
assert spec and spec.loader
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

class ReleaseContinuity(unittest.TestCase):
    def test_offline_queue_is_lossless_compressed_snapshot(self):
        obj = agent.Agent.__new__(agent.Agent)
        obj.queue = deque(maxlen=3)
        obj.token = 'synthetic-token'
        obj._check_components = lambda: {'test': True}
        obj._os_info = lambda: {'hardware': {'memory': {'total_bytes': 123}}}
        obj._storage_info = lambda: [{'name': 'fixture'}]
        obj._post = lambda *a, **k: (_ for _ in ()).throw(OSError('offline fixture'))
        metrics = [{'elapsed_seconds': 5.0, 'quality': 'valid'}]
        obj.report(metrics, [])
        self.assertIsInstance(obj.queue[0], bytes)
        self.assertEqual(json.loads(zlib.decompress(obj.queue[0]))['metrics'], metrics)
        metrics[0]['quality'] = 'changed'
        self.assertEqual(json.loads(zlib.decompress(obj.queue[0]))['metrics'][0]['quality'], 'valid')
        sent = []
        obj.monitors_version = 1
        obj._post = lambda *a, **kw: sent.append(kw['json_body']) or {}
        # The unknown first response now backs off before one batched retry.
        obj._report_not_before = 0
        obj.report([], [])
        self.assertEqual(len(obj.queue), 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['metrics'][0]['quality'], 'valid')
        self.assertEqual(sent[0]['os_info']['hardware']['memory']['total_bytes'], 123)

    def test_windows_backup_fsync_uses_writable_handle(self):
        tree = ast.parse((ROOT / 'agent/stella_agent.py').read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'open'
                 and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == 'backup']
        self.assertTrue(any(len(n.args) > 1 and isinstance(n.args[1], ast.Constant)
                            and n.args[1].value == 'r+b' for n in calls))

    def test_http_calls_reuse_verified_ssl_context(self):
        obj = agent.Agent.__new__(agent.Agent)
        obj.url = 'https://fixture.invalid'
        obj.token = 'synthetic-token'
        marker = object()
        obj._ssl_context = marker
        with patch.object(agent.httpx, 'get') as get:
            get.return_value.json.return_value = {}
            obj._get('/fixture')
            self.assertIs(get.call_args.kwargs.get('verify'), marker)

    def test_monotonic_release_and_new_collectors_retained(self):
        self.assertEqual(agent.AGENT_VERSION, '0.6.21')
        self.assertTrue(hasattr(agent.Agent, '_system_memory'))
        self.assertTrue(hasattr(agent.Agent, '_cgroup_memory'))

if __name__ == '__main__':
    unittest.main()
