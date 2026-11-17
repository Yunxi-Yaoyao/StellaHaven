"""Current-source template fixture: no application bootstrap or deployment trust."""
import ast
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/experience-fixture/export_template.py'
ORIGIN = 'http://127.0.0.1:15487'


class ExportTemplateFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = io.StringIO()
        cls.modules_before = set(sys.modules)
        # A poisoned deployment environment must not become browser fixture trust.
        with patch.dict(os.environ, {
            'STELLA_SOURCE_ROOT': str(ROOT),
            'STELLA_ENTRY_REGISTRY': '[{"service_id":"stella","public":"https://live.invalid"}]',
            'STELLA_MAIN_ORIGIN': 'https://live.invalid',
        }), patch.object(sys, 'argv', [str(HELPER), ORIGIN]), redirect_stdout(output):
            cls.scope = runpy.run_path(str(HELPER))
        cls.payload = json.loads(output.getvalue())

    def test_current_export_runs_with_only_synthetic_parent_registry(self):
        self.assertTrue(self.payload['code']['enabled'])
        self.assertTrue(self.payload['provenance']['has_ready_marker'])
        registry = self.scope['safe_import']('app.services.entry_registry', fromlist=('records',))
        self.assertEqual(set(vars(registry)), {'records'})
        self.assertEqual(registry.records(), {'stella': {'public': ORIGIN}})
        registry.records()['stella']['public'] = 'https://mutated.invalid'
        self.assertEqual(registry.records(), {'stella': {'public': ORIGIN}})
        self.assertNotIn('live.invalid', self.payload['code']['js'])
        getenv = self.scope['fixture_getenv']
        self.assertEqual(getenv('STELLA_MAIN_ORIGIN'), ORIGIN)
        self.assertEqual(getenv('STELLA_BUILTIN_MAIN_ORIGIN', 'source-default'), 'source-default')
        self.assertEqual(json.loads(getenv('STELLA_ENTRY_REGISTRY')), [{'service_id': 'stella', 'public': ORIGIN}])
        for key in ['DATABASE_URL', 'STELLA_SECRET_KEY', 'UNKNOWN_FIELD']:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'AST fixture rejected environment field'):
                getenv(key)
        self.assertEqual(self.payload['provenance']['allowed_imports'], {
            'app.services.entry_registry': ['records'],
            'app.services.service_appearance': ['DEFAULTS', 'check_site'],
            'app.services.openlist_appearance': ['BACKGROUND_CSS', 'SIMPLIFIED_CSS', 'SIMPLIFIED_JS', 'THEME_CSS'],
            'app.services.openlist_compat': ['BACKGROUND_JS', 'CACHE_JS'],
        })
        self.assertEqual(self.payload['provenance']['registry_boundary'], {
            'kind': 'synthetic', 'records': {'stella': {'public': ORIGIN}},
            'deployment_environment_read': False,
        })

    def test_unknown_bootstrap_relative_and_unselected_imports_stay_rejected(self):
        importer = self.scope['safe_import']
        for name in ['unknown_fixture_module', 'app', 'app.main', 'app.config',
                     'app.database', 'socket', 'os', 'app.services.entry_registry_extra']:
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'AST fixture rejected import'):
                importer(name, fromlist=('records',))
        for fields, level in [((), 0), (('*',), 0), (('parent_context',), 0),
                              (('records', 'parent_context'), 0), (('records',), 1)]:
            with self.subTest(fields=fields, level=level), self.assertRaisesRegex(RuntimeError, 'AST fixture rejected import'):
                importer('app.services.entry_registry', fromlist=fields, level=level)
        with self.assertRaisesRegex(RuntimeError, 'AST fixture rejected import'):
            importer('app.services.service_appearance', fromlist=('read',))
        # Exercise the actual builtins installed on compiled current exports,
        # not only direct calls to the helper (no real app import can occur).
        compiled_scope = self.scope['export'].__globals__
        for statement in ['import unknown_fixture_module', 'import app.main',
                          'from app.config import settings',
                          'from app.services.entry_registry import parent_context']:
            with self.subTest(statement=statement), self.assertRaisesRegex(RuntimeError, 'AST fixture rejected import'):
                exec(compile(statement, '<fixture-negative-control>', 'exec'), dict(compiled_scope))
        newly_imported = set(sys.modules) - self.modules_before
        self.assertFalse({name for name in newly_imported if name == 'app' or name.startswith('app.')})

    def test_every_selected_ast_export_is_exact_current_source(self):
        manifest = self.payload['provenance']['ast_exports']
        self.assertEqual(set(manifest), set(self.payload['provenance']['source_sha256']))
        self.assertEqual(set(manifest['app/services/website_templates.py']), {'export_code'})
        for relative, exports in manifest.items():
            raw = (ROOT / relative).read_bytes()
            text = raw.decode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), self.payload['provenance']['source_sha256'][relative])
            for name, receipt in exports.items():
                node = next(n for n in ast.parse(text).body if
                            getattr(n, 'name', None) == name or
                            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
                selected = ast.get_source_segment(text, node)
                assert selected is not None
                self.assertEqual(receipt['source'], selected)
                self.assertEqual(receipt['sha256'], hashlib.sha256(selected.encode()).hexdigest())
                self.assertEqual(receipt['lineno'], node.lineno)
                self.assertEqual(receipt['end_lineno'], node.end_lineno)
        self.assertNotIn('app/services/entry_registry.py', manifest)
        source = manifest['app/services/website_templates.py']['export_code']['source']
        self.assertIn('from app.services.entry_registry import records', source)


if __name__ == '__main__':
    unittest.main()
