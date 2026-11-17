"""HTML bootstrap tests: source-extracted runtime, no app/config/DB imports.

Run directly with unittest, not the PG conftest. Browser transport is synthetic
Playwright fulfill; parsing, sandbox/CSP, script execution and URL loads are real.
"""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://stella.bootstrap.test'
TARGET = 'https://pages.bootstrap.test'
CAP = 'A' * 43
SCRIPT = f'<script src="{TARGET}/p/{CAP}/__stella_storage.js"></script>'.encode()


def runtime(files):
    path = ROOT / 'app/services/web_project_runtime.py'
    tree = ast.parse(path.read_bytes())
    functions: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'resource', 'adapter'}]
    assert len(functions) == 2
    grant = {'owner': 'fixture', 'root': 'fixture', 'source': SOURCE}
    namespace: dict[str, Any] = dict(json=json, re=re, authorize=lambda *args: (grant, {'data': {'seed': 'restored'}}),
                     projects=SimpleNamespace(uid=lambda v: v, read_file=lambda db, owner, root, path: files[path]))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
    return lambda path: namespace['resource'](None, CAP, TARGET, path)


def observe(key):
    return (f'localStorage.setItem("{key}",localStorage.getItem("seed"));'
            f'window.observed="{key}:"+localStorage.getItem("{key}");')


def fixtures():
    early = '<script>' + observe('early') + '</script>'
    return {
        'comment-head.html': (f'<!doctype html><!-- <head> fake --><html><head></head><body>{early}</body></html>'.encode(), 'text/html'),
        'pre-head.html': (f'<!doctype html>{early}<html><head></head><body>early</body></html>'.encode(), 'text/html'),
        'doctype-legacy.html': (f'<!DOCTYPE html SYSTEM "about:legacy-compat">{early}'.encode(), 'text/html'),
        'doctype-no-head.html': (f'<!DOCTYPE html>\r\n{early}<p>doctype retained</p>'.encode(), 'text/html'),
        'module.html': (b'<!doctype html><html><head><script type="module" src="./app.mjs"></script></head><body>module</body></html>', 'text/html'),
        'app.mjs': ((observe('module') + 'export {};').encode(), 'text/javascript'),
        'nested/pages/index.html': (b'\xef\xbb\xbf<!doctype html><!-- <head> fake --><html lang="zh"><head data-note=">">\r\n<link rel="stylesheet" href="../assets/site.css"><script type="module" src="../scripts/app.mjs"></script></head><body><div id="box">nested</div><img id="asset" src="../assets/pixel.svg"></body></html>', 'text/html'),
        'nested/scripts/app.mjs': (('import {value} from "./lib/value.mjs";' + observe('nested') + 'window.relativeValue=value;').encode(), 'text/javascript'),
        'nested/scripts/lib/value.mjs': (b'export const value="relative-ok";', 'text/javascript'),
        'nested/assets/site.css': (b'#box { color: rgb(12, 34, 56); background-image: url("./pixel.svg"); }', 'text/css'),
        'nested/assets/pixel.svg': (b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"><rect width="2" height="3" fill="red"/></svg>', 'image/svg+xml'),
    }


class BootstrapTests(unittest.TestCase):
    def test_insertion_is_outside_comment_and_before_first_script(self):
        files = fixtures()
        serve = runtime(files)
        for name in ('comment-head.html', 'pre-head.html', 'doctype-no-head.html'):
            with self.subTest(name=name):
                body, _, _ = serve(name)
                self.assertEqual(body.count(SCRIPT), 1)
                self.assertEqual(body.replace(SCRIPT, b'', 1), files[name][0])
                self.assertGreater(body.index(SCRIPT), body.index(b'<!') )
                self.assertLess(body.index(SCRIPT), body.index(b'<script>'))
                if name == 'comment-head.html':
                    self.assertGreater(body.index(SCRIPT), body.index(b'-->'))

    def test_prologue_boundaries_do_not_scan_raw_text_or_attributes(self):
        cases = [
            ('<!DOCTYPE\nhtml>\r\n', '<script>' + observe('early') + '</script>'),
            ('\ufeff<!doctype html>\n<HTML><HEAD title=\">\">', '<script>const text="<head>";</script>'),
            ('<!doctype html><html>', '<title>raw <head> text</title><script>1</script>'),
            ('<!doctype html>\n<!-- example <head> -->\n', '<script data-note=\"<head>\">1</script>'),
            ('<!doctype html>', '<style>/* <head> */</style><script>1</script>'),
            ('', '<textarea><head></textarea><script>1</script>'),
            ('<!doctype html>', '<!--unterminated <head>'),
            ('<!doctype html><!-- complete -->', ''),
        ]
        for prefix, suffix in cases:
            with self.subTest(prefix=prefix, suffix=suffix):
                serve = runtime({'index.html': ((prefix + suffix).encode(), 'text/html')})
                body, _, _ = serve('index.html')
                self.assertEqual(body, prefix.encode() + SCRIPT + suffix.encode())

    def test_source_bytes_headers_and_non_html_are_preserved(self):
        files = fixtures()
        files['raw.html'] = (b'<!doctype html><HTML><HEAD title=">">\r\n<title>&amp; <head></title></HEAD><body><script>const x="<head>";\r\n// &amp; untouched\n</script></body>', 'text/html')
        serve = runtime(files)
        for name, (original, mime) in files.items():
            with self.subTest(name=name):
                body, result_mime, headers = serve(name)
                self.assertEqual(body.replace(SCRIPT, b'', 1) if mime == 'text/html' else body, original)
                self.assertTrue(result_mime.startswith(mime))
                self.assertNotIn('allow-same-origin', headers['Content-Security-Policy'])
                if mime == 'text/html':
                    self.assertEqual(headers['Content-Security-Policy'], f"sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' https: {TARGET}; style-src 'unsafe-inline' https: {TARGET}; img-src data: blob: https: {TARGET}; font-src data: https: {TARGET}; media-src blob: https: {TARGET}; connect-src https: {TARGET}; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri {TARGET}; form-action 'none'; frame-ancestors {SOURCE}")
                self.assertEqual(headers['Access-Control-Allow-Origin'], '*')
                self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_real_chromium_bootstrap_order_and_nested_resources(self):
        files = fixtures()
        serve = runtime(files)
        responses = {}
        for name in [*files, '__stella_storage.js']:
            body, mime, headers = serve(name)
            responses[name] = dict(body=base64.b64encode(body).decode(), mime=mime, headers=headers)
        output = Path(os.environ['BOOTSTRAP_EVIDENCE'])
        output.mkdir(parents=True, exist_ok=True)
        payload = {'source': SOURCE, 'target': TARGET, 'cap': CAP, 'responses': responses,
                   'cases': {'comment-head.html': 'early', 'pre-head.html': 'early',
                             'doctype-no-head.html': 'early', 'doctype-legacy.html': 'early', 'module.html': 'module',
                             'nested/pages/index.html': 'nested'},
                   'runtime_sha256': hashlib.sha256((ROOT / 'app/services/web_project_runtime.py').read_bytes()).hexdigest()}
        spec = output / 'fixtures.json'
        spec.write_text(json.dumps(payload))
        result = subprocess.run([os.environ['BOOTSTRAP_NODE'], str(ROOT / 'frontend/tests/web-project-html-bootstrap.mjs'), str(spec), str(output)],
                                capture_output=True, text=True, timeout=90)
        (output / 'browser.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
