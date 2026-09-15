import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_release import ROOT, load


class RuntimeTests(unittest.TestCase):
    def test_resource_bundle_rejects_missing_changed_and_escaping_files(self):
        self.assertTrue((ROOT / 'readiness.py').exists(), 'role-aware readiness missing')
        readiness = load('readiness')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / 'model.bin'
            asset.write_bytes(b'model-data')
            files = {'model.bin': {'size': asset.stat().st_size, 'sha256': hashlib.sha256(asset.read_bytes()).hexdigest()}}
            (root / 'manifest.json').write_text(json.dumps({'files': files}))
            self.assertTrue(readiness.check_resources(root, full=True))
            asset.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                readiness.check_resources(root, full=True)
            (root / 'manifest.json').write_text(json.dumps({'files': {'../outside': files['model.bin']}}))
            with self.assertRaises(ValueError):
                readiness.check_resources(root)

    def test_app_and_pg_entrypoint_default_denied_without_side_effects(self):
        self.assertTrue((ROOT / 'entrypoint.py').exists(), 'entrypoint guard missing')
        entry = load('entrypoint')
        with patch.dict(os.environ, {}, clear=True), patch('os.execvpe') as execute:
            for role in ('app', 'pg'):
                with self.assertRaises(ValueError):
                    entry.start(role, [])
            execute.assert_not_called()

    def test_pg_guard_requires_existing_independent_pg18_data(self):
        entry = load('entrypoint')
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with self.assertRaises(ValueError):
                entry.check_pgdata(data)
            (data / 'PG_VERSION').write_text('17')
            with self.assertRaises(ValueError):
                entry.check_pgdata(data)
            (data / 'PG_VERSION').write_text('18')
            (data / '.local-ha-independent').write_text('stella-local-ha-v1')
            entry.check_pgdata(data)
