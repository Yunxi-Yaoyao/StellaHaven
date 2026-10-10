"""Load only real public script/version routes; no app/database or live routing."""
import ast
import hashlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / 'app/routers/monitor.py'


def public_client():
    tree = ast.parse(ROUTER.read_text())
    functions: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {
        'agent_version', 'agent_run_ps1', 'agent_hardware_sensors_ps1'}]
    namespace = {'__file__': str(ROUTER), 'agent_router': APIRouter(prefix='/agent'),
                 'HTTPException': HTTPException}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROUTER), 'exec'), namespace)
    app = FastAPI()
    app.include_router(namespace['agent_router'])
    return TestClient(app)


class WindowsInstallerRoutesTests(unittest.TestCase):
    def test_public_script_downloads_exact_bytes_without_auth(self):
        with public_client() as client:
            for filename in ('run-agent.ps1', 'hardware-sensors.ps1'):
                with self.subTest(filename=filename):
                    response = client.get('/agent/' + filename)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, (ROOT / 'agent' / filename).read_bytes())
                    self.assertTrue(response.headers['content-type'].startswith('text/plain'))

    def test_parked_069_returns_version_without_manifest(self):
        with patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': '0.6.9'}):
            response = public_client().get('/agent/version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'version': '0.6.9'})

    def test_current_rollout_returns_matching_manifest(self):
        import re
        body = (ROOT / 'agent/stella_agent.py').read_bytes()
        match = re.search(rb'AGENT_VERSION\s*=\s*"([^"]+)"', body)
        assert match is not None
        version = match.group(1).decode()
        with patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': version}):
            response = public_client().get('/agent/version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'version': version, 'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)})

    def test_unapproved_rollout_still_returns_503(self):
        for version in ('unapproved-version', '0.6.13', '0.6.12 ', '0.6.012'):
            with self.subTest(version=version), patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': version}):
                response = public_client().get('/agent/version')
            self.assertEqual(response.status_code, 503)

    def test_parked_0610_returns_version_without_manifest(self):
        with patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': '0.6.10'}):
            response = public_client().get('/agent/version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'version': '0.6.10'})

    def test_parked_0611_returns_version_without_manifest(self):
        with patch.dict(os.environ, {'STELLA_AGENT_ROLLOUT_VERSION': '0.6.11'}):
            response = public_client().get('/agent/version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'version': '0.6.11'})


if __name__ == '__main__':
    unittest.main()
