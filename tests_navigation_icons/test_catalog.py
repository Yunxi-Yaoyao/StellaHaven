"""Pure catalog/AST checks: no application boot, database or production network."""
import ast
import json
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CatalogContract(unittest.TestCase):
    def test_backend_has_one_shared_legal_catalog(self):
        catalog = ROOT / 'app/navigation_icons.py'
        self.assertTrue(catalog.exists(), 'missing unified navigation icon catalog')
        keys = runpy.run_path(str(catalog))['NAVIGATION_ICONS']
        data = json.loads((ROOT / 'frontend/src/icons/navigation-icons.json').read_text())
        self.assertEqual(keys, {i['key'] for i in data['icons']} | set(data['aliases']))
        for filename, alias in [('integrations.py', 'ICONS'), ('website_settings.py', 'NAVIGATION_ICONS')]:
            tree = ast.parse((ROOT / 'app/services' / filename).read_text())
            imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'app.navigation_icons']
            self.assertTrue(any(a.name == 'NAVIGATION_ICONS' and (a.asname or a.name) == alias for n in imports for a in n.names), filename)

if __name__ == '__main__':
    unittest.main()
