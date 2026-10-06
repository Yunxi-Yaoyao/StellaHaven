"""Exercise actual probe program with real local files and ASGI health middleware.
Only database/Patroni boundaries are stubbed; no network socket is opened.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
# Full app dependencies are installed in the isolated backend test lane, not
# the minimal Alpine/PyYAML deploy lane. Import only offline fixture helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/local-ha/tests'))
try:
    from test_production_release import load, ROOT
    from test_production_upgrade_contract import overrides
finally:
    sys.path.pop(0)


def service(name):
    spec = importlib.util.spec_from_file_location(name, ROOT.parents[1] / 'app/services' / (name + '.py'))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ProbeContractTests(unittest.TestCase):
    def exercise(self, *, target=True, previous_bundle=False, receipt=True, unknown_receipt=False, port=25132, primary=False):
        p = load('node_production')
        security = service('request_security')
        readiness = service('ha_readiness')
        from starlette.applications import Starlette
        from starlette.testclient import TestClient
        async def checker():
            return primary
        app = security.MainSiteSecurityMiddleware(readiness.PrimaryOnlyMiddleware(Starlette(), enabled=True, checker=checker))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'resource.txt').write_text('approved resource')
            files = {'resource.txt': dict(size=17, sha256=hashlib.sha256(b'approved resource').hexdigest())}
            (root / 'backup-receipts').mkdir()
            if receipt:
                raw = b'{"timestamp":"2026-10-06T00:00:00Z","status":"verified","checksumverified":true,"restoreverified":false,"source":"postgres-dump"}'
                (root / 'backup-receipts/receipt.json').write_bytes(raw)
                files['backup-receipts/receipt.json'] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            (root / 'manifest.json').write_text(json.dumps({'files': files}))
            manifest = hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
            if unknown_receipt:
                (root / 'backup-receipts/unapproved.json').write_text('{}')
            secret = root / 'secret_key'
            secret.write_text('fixture-signing-key')
            payload = dict(node='nas', port=port, revision='new_revision', previous='old_revision',
                           manifest=('f' * 64 if previous_bundle else manifest),
                           previous_manifest=(manifest if previous_bundle else None),
                           target=target, receipt_dir='/app/data/backup-receipts' if target else None,
                           signing=hashlib.sha256(b'fixture-signing-key').hexdigest(), expected_roles=None)
            class Cursor:
                def __init__(self, host):
                    self.host = host
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def execute(self, query): pass
                def fetchone(self):
                    active = self.host == ('10.66.0.3' if primary else '10.66.0.2')
                    return not active, not active
                def fetchall(self): return [('new_revision',)]
            class Connection:
                def __init__(self, host): self.host = host
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def cursor(self): return Cursor(self.host)
            db = types.ModuleType('psycopg2')
            db.connect = lambda **kw: Connection(kw['host'])
            config = types.ModuleType('alembic.config')
            config.Config = lambda path: object()
            scripts = types.ModuleType('alembic.script')
            scripts.ScriptDirectory = types.SimpleNamespace(from_config=lambda cfg: types.SimpleNamespace(get_heads=lambda: ['new_revision' if target else 'old_revision']))
            def mapped_path(path):
                return root if path == '/app/data' else secret if path in ('/data/secret_key', '/run/secrets/app-password') else Path(path)
            class Response(io.BytesIO):
                def __init__(self, code, body):
                    super().__init__(json.dumps(body).encode())
                    self.status = code
            requests = []
            with TestClient(app) as client:
                class Opener:
                    def open(self, url, timeout):
                        from urllib.parse import urlsplit
                        from urllib.error import HTTPError
                        requests.append(url)
                        u = urlsplit(url)
                        if u.port == 24808:
                            active = u.hostname == ('10.66.0.3' if primary else '10.66.0.2')
                            code = 200 if u.path == '/patroni' or active else 503
                            return Response(code, {'state': 'running', 'role': 'primary' if active else 'replica'})
                        response = client.get(url)
                        if response.status_code >= 400:
                            raise HTTPError(url, response.status_code, 'ASGI health', {}, None)
                        return Response(response.status_code, response.json())
                stdout = io.StringIO()
                with patch.dict(sys.modules, {'psycopg2': db, 'alembic.config': config, 'alembic.script': scripts}), \
                        patch.dict(p.os.environ, overrides()), patch('sys.stdin', io.StringIO(json.dumps(payload))), \
                        patch('urllib.request.build_opener', return_value=Opener()), patch('pathlib.Path', side_effect=mapped_path), \
                        contextlib.redirect_stdout(stdout):
                    exec(compile(p.PROBE, 'probe', 'exec'), {})
            return json.loads(stdout.getvalue()), requests, manifest

    def test_previous_bundle_is_allowed_only_for_old_or_rollback_probe(self):
        result, _, actual = self.exercise(target=False, previous_bundle=True)
        self.assertEqual(result['manifest'], actual)
        with self.assertRaises(AssertionError):
            self.exercise(target=True, previous_bundle=True)

    def test_target_bundle_requires_manifest_pinned_small_receipt(self):
        with self.assertRaises(AssertionError):
            self.exercise(receipt=False)
        with self.assertRaises(AssertionError):
            self.exercise(unknown_receipt=True)

    def test_actual_health_middleware_accepts_both_loopback_authorities(self):
        for port in (25131, 25132):
            for primary in (False, True):
                result, urls, _ = self.exercise(port=port, primary=primary)
                self.assertEqual(result['http'], {'live': 200, 'ready_primary': 200 if primary else 503})
                self.assertIn('http://127.0.0.1:' + str(port) + '/live', urls)
                self.assertIn('http://127.0.0.1:' + str(port) + '/ready-primary', urls)
        with self.assertRaises(AssertionError):
            self.exercise(port=25133)


if __name__ == '__main__':
    unittest.main()
