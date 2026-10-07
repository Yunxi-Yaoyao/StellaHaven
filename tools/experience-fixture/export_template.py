"""Export real template AST without importing app/database/main/config.

STELLA_SOURCE_ROOT selects the exact tested tree. Only allowlisted pure exports
are compiled; the background protocol is never copied or rewritten by fixtures.
"""
import ast
import builtins
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(os.environ.get('STELLA_SOURCE_ROOT', Path(__file__).resolve().parents[2])).resolve()
ORIGIN = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:15487'
SOURCES, MODULES, GLOBALS = {}, {}, {}


def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in MODULES:
        raise RuntimeError('AST fixture rejected import: ' + name)
    return MODULES[name]


def extract(relative, names):
    file = ROOT / relative
    if not file.is_file():
        raise SystemExit('Missing source: ' + str(file))
    raw = file.read_bytes()
    SOURCES[relative] = hashlib.sha256(raw).hexdigest()
    selected, found = [], set()
    for node in ast.parse(raw, filename=str(file)).body:
        identifiers = ([node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                       else [target.id for target in node.targets if isinstance(target, ast.Name)] if isinstance(node, ast.Assign) else [])
        if set(identifiers) & set(names):
            selected.append(node)
            found.update(set(identifiers) & set(names))
    if found != set(names):
        raise RuntimeError(f'Missing AST exports in {file}: {set(names) - found}')
    scope = {'__builtins__': {**vars(builtins), '__import__': safe_import}, 'json': json, 'os': os, 'urlsplit': urlsplit}
    scope.update(GLOBALS)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(file), 'exec'), scope)
    result = {name: scope[name] for name in names}
    GLOBALS.update(result)
    return result


extract('app/services/integrations_injection.py', ['safe_json'])
for module, names in [
    ('service_appearance', ['DEFAULTS', 'check_site']),
    ('openlist_appearance', ['THEME_CSS', 'SIMPLIFIED_CSS', 'BACKGROUND_CSS', 'SIMPLIFIED_JS']),
    ('openlist_compat', ['CACHE_JS', 'BACKGROUND_JS']),
]:
    MODULES['app.services.' + module] = SimpleNamespace(**extract('app/services/' + module + '.py', names))
values = extract('app/services/builtin_injection.py', ['presets', 'gallery_head_loader', 'admin_notice_code', 'GALLERY_LOGO_CSS'])
GLOBALS['builtin'] = SimpleNamespace(**values)
export = extract('app/services/website_templates.py', ['export_code'])['export_code']
code = export('drive', main_origin=ORIGIN)
print(json.dumps({'code': code, 'provenance': {
    'source_root': str(ROOT),
    'commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
    'source_sha256': SOURCES,
    'css_sha256': hashlib.sha256(code['css'].encode()).hexdigest(),
    'js_sha256': hashlib.sha256(code['js'].encode()).hexdigest(),
    'has_ready_marker': '/* stella:background-ready:v1 */' in code['js'],
    'extraction': 'named AST exports with allowlisted imports; no app/database/main/config imports',
}}, ensure_ascii=False))
