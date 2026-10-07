"""Offline staging/retention contract; synthetic fixtures only."""
import unittest

import test_public_assets as f


class StageTest(f.FixtureCase):

    def stage(self, bundles, name='stage', previous=None, **changes):
        self.assertTrue(callable(getattr(self.tool, 'stage', None)), 'offline stage generator missing')
        plan = dict(schema='stella-public-assets-plan-v1', module_id=f.MODULE, origin=f.ORIGIN,
                    target_root=str(self.root / 'edge' / f.MODULE),
                    bundles=[dict(path=str(self.root / p), version=m['version']) for p, m in bundles],
                    previous=previous)
        plan.update(changes)
        path = self.root / (name + '-plan.json')
        path.write_bytes(f.encoded(plan))
        receipt = self.tool.stage(path, f.sha(path.read_bytes()), self.root / name)
        return receipt

    def test_stage_is_exact_scope_and_retains_previous_versions_without_overwrite(self):
        m1 = self.build()
        r1 = self.stage([('bundle', m1)])
        name2 = 'next-12345678.js'
        (self.source / name2).write_bytes(f.BODY + b'//new')
        self.spec['files'] = {name2: dict(sha256=f.sha(f.BODY + b'//new'), size=len(f.BODY + b'//new'))}
        m2 = self.build(name='bundle2')
        r2 = self.stage([('bundle2', m2)], name='stage2',
                        previous=dict(path=str(self.root / 'stage'), version=r1['version']))
        self.assertEqual(r2['versions'], sorted([m1['version'], m2['version']]))
        self.assertEqual(r2['previous_stage_version'], r1['version'])
        self.assertEqual(r2['unknown_policy'], 'unchanged-authenticated-upstream')
        self.assertEqual(r2['missing_policy'], '404-no-cache')
        text = (self.root / 'stage2' / 'locations.conf').read_text()
        for name in [f.NAME, name2]:
            self.assertIn('location = ' + f.PREFIX + name + ' {', text)
        self.assertNotIn('location /', text)
        self.assertIn('gzip_static on;', text)
        self.assertIn('public, max-age=31536000, immutable', text)
        self.assertEqual(self.tool.verify_stage(self.root / 'stage2', r2['version'], f.MODULE, f.ORIGIN), r2)
        self.assertFalse((self.root / 'edge').exists(), 'staging must not install to target_root')

    def test_stage_rejects_same_url_changed_bytes_and_wrong_previous_identity(self):
        old = self.build()
        receipt = self.stage([('bundle', old)])
        before = (self.root / 'stage' / 'locations.conf').read_bytes()
        body = f.BODY + b'// changed without new filename'
        (self.source / f.NAME).write_bytes(body)
        self.spec['files'][f.NAME] = dict(sha256=f.sha(body), size=len(body))
        new = self.build(name='bundle2')
        with self.assertRaisesRegex(ValueError, 'same URL'):
            self.stage([('bundle2', new)], 'conflict', dict(path=str(self.root / 'stage'), version=receipt['version']))
        self.assertFalse((self.root / 'conflict').exists())
        self.assertEqual((self.root / 'stage' / 'locations.conf').read_bytes(), before)
        with self.assertRaises(ValueError):
            self.stage([('bundle', old)], 'wrongorigin', origin=f.ORIGIN + '.wrong')
        with self.assertRaises(ValueError):
            self.stage([('bundle', old)], 'wrongroot', target_root='/var/www/assets;bad')
        with self.assertRaises(ValueError):
            self.stage([('bundle', old)], 'wrongprevious', dict(path=str(self.root / 'stage'), version='0' * 64))

    def test_stage_detects_snippet_and_gzip_content_tamper_even_if_self_hash_recomputed(self):
        manifest = self.build()
        receipt = self.stage([('bundle', manifest)])
        stage = self.root / 'stage'
        (stage / 'locations.conf').write_text('location / { return 200; }')
        with self.assertRaises(ValueError):
            self.tool.verify_stage(stage, receipt['version'], f.MODULE, f.ORIGIN)
        # A manifest hash is integrity, not permission to replace compressed bytes.
        bundle = self.root / 'bundle'
        evil = f.gzip.compress(b'private data', mtime=0)
        (bundle / 'public' / (f.NAME + '.gz')).write_bytes(evil)
        manifest['gzip'][f.NAME] = dict(sha256=f.sha(evil), size=len(evil))
        del manifest['version']
        manifest['version'] = f.sha(f.encoded(manifest))
        (bundle / 'manifest.json').write_bytes(f.encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'gzip content mismatch'):
            self.tool.verify(bundle, manifest['version'], f.MODULE, f.ORIGIN)


if __name__ == '__main__':
    unittest.main()
