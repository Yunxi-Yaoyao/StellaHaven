"""Offline contract tests. Synthetic public bytes; no app imports or DB."""
import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'public_assets.py'
MODULE = '125398b55f1847c7a9ebb70cc651baee'
ORIGIN = f'https://app-{MODULE}.example.test'
PREFIX = '/drive/openlist/assets/'
NAME = 'components--D9HLKs-.js'
BODY = b'export const example = "synthetic public asset";\n' * 400


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load_tool():
    spec = importlib.util.spec_from_file_location('public_assets', TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file(), 'missing offline public fingerprint asset builder')
        self.tool = load_tool()
        self.temp = tempfile.TemporaryDirectory(prefix='experience-static-', dir=os.environ['TMPDIR'])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.spec = dict(schema='stella-public-assets-source-v1', module_id=MODULE,
                         origin=ORIGIN, asset_prefix=PREFIX, public=True,
                         files={NAME: dict(sha256=sha(BODY), size=len(BODY))})
        (self.source / NAME).write_bytes(BODY)

    def build(self, spec=None, name='bundle'):
        spec = copy.deepcopy(self.spec if spec is None else spec)
        source_spec = self.root / (name + '-source.json')
        source_spec.write_bytes(encoded(spec))
        return self.tool.build(source_spec, sha(source_spec.read_bytes()), self.source, self.root / name)


class AssetsTest(FixtureCase):
    def test_build_pins_only_explicit_public_bytes_and_deterministic_gzip(self):
        # Unlisted local files must never be copied or treated as public.
        (self.source / 'private.txt').write_text('not an asset')
        manifest = self.build()
        bundle = self.root / 'bundle'
        self.assertEqual((bundle / 'public' / NAME).read_bytes(), BODY)
        compressed = (bundle / 'public' / (NAME + '.gz')).read_bytes()
        self.assertEqual(gzip.decompress(compressed), BODY)
        self.assertLess(len(compressed), len(BODY))
        self.assertEqual(manifest['source'], self.spec)
        self.assertEqual(manifest['gzip'][NAME], dict(sha256=sha(compressed), size=len(compressed)))
        self.assertEqual({p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()},
                         {'manifest.json', 'public/' + NAME, 'public/' + NAME + '.gz'})
        same = self.build(name='again')
        self.assertEqual(same, manifest)
        verified = self.tool.verify(bundle, manifest['version'], MODULE, ORIGIN)
        self.assertEqual(verified, manifest)

    def test_unapproved_or_ambiguous_scope_is_rejected_before_writes(self):
        changes = [
            {'public': False}, {'public': 1}, {'token': 'never accepted'},
            {'schema': 'other'}, {'module_id': MODULE + '-oops'},
            {'origin': 'https://app-' + '0' * 32 + '.example.test'},
            {'origin': ORIGIN + '/'}, {'origin': ORIGIN + '?key=x'},
            {'origin': ORIGIN.replace('https://', 'https://user:password@')},
            {'origin': ORIGIN.replace('https:', 'http:')},
            {'origin': ORIGIN + ':443'}, {'origin': ORIGIN.upper()},
            {'asset_prefix': '/'}, {'asset_prefix': '/api/assets/'},
            {'asset_prefix': '/private/assets/'}, {'asset_prefix': '/d/assets/'},
            {'asset_prefix': '/attachments/static/'}, {'asset_prefix': '/assets/../assets/'},
            {'asset_prefix': '//assets/'}, {'asset_prefix': '/assets/%2e/'},
            {'files': {}}, {'files': {NAME: dict(sha256='a' * 63, size=len(BODY))}},
            {'files': {NAME: dict(sha256=sha(BODY), size=True)}},
            {'files': {NAME: dict(sha256=sha(BODY), size=9 * 1024 * 1024)}},
        ]
        for i, change in enumerate(changes):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.build(self.spec | change, name='bad' + str(i))
                self.assertFalse((self.root / ('bad' + str(i))).exists())

    def test_only_fingerprint_basenames_are_eligible(self):
        self.assertTrue(callable(getattr(self.tool, 'validate_source', None)), 'source scope validator missing')
        for i, name in enumerate(['index.html', 'index-abcdefgh.html', 'plain.js',
                                  'debug-abcdefgh.js.map', 'secret-abcdefgh.js',
                                  'access_token-abcdefgh.js', 'index-abcdefgh.json',
                                  '../components--D9HLKs-.js', '/components--D9HLKs-.js',
                                  'sub/index-abcdefgh.js', 'index-abcdefgh.js?x',
                                  'index-abcdefgh.js;bad', 'index-%61bcdefg.js']):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.tool.validate_source(self.spec | {'files': {name: dict(sha256=sha(BODY), size=len(BODY))}})

    def test_html_and_obvious_embedded_credentials_never_enter_bundle(self):
        bodies = [b' <!DOCTYPE html><html>private login</html>', b'\xef\xbb\xbf<html>private</html>',
                  b'-----BEGIN PRIVATE KEY-----\nexample',
                  b'export const access_token = "secretcredentialvalue123456";',
                  b'{"password":"longplaintextpassword123"}',
                  b'\x00\x01not javascript']
        for i, body in enumerate(bodies):
            (self.source / NAME).write_bytes(body)
            spec = self.spec | {'files': {NAME: dict(sha256=sha(body), size=len(body))}}
            with self.subTest(i=i), self.assertRaises(ValueError):
                self.build(spec, 'content' + str(i))

    def test_source_hash_duplicate_json_keys_and_symlink_chains_rejected(self):
        p = self.root / 'input.json'
        p.write_bytes(encoded(self.spec))
        with self.assertRaises(ValueError):
            self.tool.build(p, '0' * 64, self.source, self.root / 'out')
        p.write_bytes(encoded(self.spec).replace(b'"public": true', b'"public": false, "public": true'))
        with self.assertRaises(ValueError):
            self.tool.build(p, sha(p.read_bytes()), self.source, self.root / 'out')
        linked = self.root / 'linked'
        linked.symlink_to(self.source, target_is_directory=True)
        p.write_bytes(encoded(self.spec))
        with self.assertRaises(ValueError):
            self.tool.build(p, sha(p.read_bytes()), linked, self.root / 'out')
        (self.source / NAME).unlink()
        outside = self.root / 'outside.js'
        outside.write_bytes(BODY)
        (self.source / NAME).symlink_to(outside)
        with self.assertRaises(ValueError):
            self.build()

    def test_renamed_html_fragments_are_not_javascript_or_css(self):
        for i, body in enumerate([b'<title>private</title>', b'<!-- private page -->\n<div>private</div>',
                                  b'<?xml version="1.0"?><html>private</html>']):
            (self.source / NAME).write_bytes(body)
            spec = self.spec | {'files': {NAME: dict(sha256=sha(body), size=len(body))}}
            with self.subTest(i=i), self.assertRaises(ValueError):
                self.build(spec, 'fragment' + str(i))

    def test_bad_file_modes_hardlinks_and_output_symlinks_are_rejected(self):
        (self.source / NAME).chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'owner/mode'):
            self.build()
        (self.source / NAME).chmod(0o644)
        os.link(self.source / NAME, self.root / 'hardlink')
        with self.assertRaises(ValueError):
            self.build()
        (self.root / 'hardlink').unlink()
        (self.root / 'bundle').symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.build()

    def test_bounded_gzip_decoder_rejects_truncation_trailing_data_and_bomb(self):
        manifest = self.build()
        bundle = self.root / 'bundle'
        for body in [gzip.compress(BODY, mtime=0)[:-1], gzip.compress(BODY, mtime=0) + b'trailing',
                     gzip.compress(BODY + b'bomb' * 100000, mtime=0)]:
            (bundle / 'public' / (NAME + '.gz')).write_bytes(body)
            manifest['gzip'][NAME] = dict(sha256=sha(body), size=len(body))
            manifest.pop('version', None)
            manifest['version'] = sha(encoded(manifest))
            (bundle / 'manifest.json').write_bytes(encoded(manifest))
            with self.assertRaisesRegex(ValueError, 'gzip content mismatch'):
                self.tool.verify(bundle, manifest['version'], MODULE, ORIGIN)

    def test_verifies_gzip_from_different_python_zlib_versions_without_unbounded_decode(self):
        manifest = self.build()
        bundle = self.root / 'bundle'
        # gzip OS header / compressor choices differ across Python/zlib releases.
        zipped = bytearray(gzip.compress(BODY, compresslevel=9, mtime=0))
        zipped[9] = 3
        zipped = bytes(zipped)
        (bundle / 'public' / (NAME + '.gz')).write_bytes(zipped)
        manifest['gzip'][NAME] = dict(sha256=sha(zipped), size=len(zipped))
        del manifest['version']
        manifest['version'] = sha(encoded(manifest))
        (bundle / 'manifest.json').write_bytes(encoded(manifest))
        self.assertEqual(self.tool.verify(bundle, manifest['version'], MODULE, ORIGIN), manifest)

    def test_cli_build_and_verify_are_real_offline_commands(self):
        import subprocess
        import sys
        source_spec = self.root / 'source.json'
        source_spec.write_bytes(encoded(self.spec))
        run = subprocess.run([sys.executable, str(TOOL), 'build', '--spec', str(source_spec),
                              '--spec-sha256', sha(source_spec.read_bytes()), '--source', str(self.source),
                              '--out', str(self.root / 'cli')], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('"version"', run.stdout, 'CLI must actually build, not exit without action')
        manifest = json.loads(run.stdout)
        run = subprocess.run([sys.executable, str(TOOL), 'verify', '--bundle', str(self.root / 'cli'),
                              '--version', manifest['version'], '--module-id', MODULE, '--origin', ORIGIN],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), manifest)

    def test_verification_rejects_extra_files_corruption_and_scope_swap(self):
        manifest = self.build()
        bundle = self.root / 'bundle'
        for module, origin in [('0' * 32, ORIGIN), (MODULE, ORIGIN + '.wrong')]:
            with self.subTest(module=module, origin=origin), self.assertRaises(ValueError):
                self.tool.verify(bundle, manifest['version'], module, origin)
        with self.assertRaises(ValueError):
            self.tool.verify(bundle, '0' * 64, MODULE, ORIGIN)
        (bundle / 'public' / 'credentials.txt').write_text('must reject even unserved files')
        with self.assertRaises(ValueError):
            self.tool.verify(bundle, manifest['version'], MODULE, ORIGIN)
        (bundle / 'public' / 'credentials.txt').unlink()
        (bundle / 'public' / (NAME + '.gz')).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            self.tool.verify(bundle, manifest['version'], MODULE, ORIGIN)


if __name__ == '__main__':
    unittest.main()
