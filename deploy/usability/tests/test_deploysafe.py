"""Isolated fixtures, no production mutations or business/auth requests."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deploysafe', Path(__file__).parents[1] / 'deploysafe.py')
assert spec is not None and spec.loader is not None
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
IMAGE = d.REGISTRY + '@sha256:' + '1' * 64
IID = 'sha256:' + '2' * 64
REV = '3' * 40
BASE = '''server {
    listen 80;
    server_name stella.xiya.live;
    access_log /var/log/nginx/stella-safe-access.log stella_upgrade_safe;
    error_log /dev/null crit;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name stella.xiya.live;
    access_log /var/log/nginx/stella-safe-access.log stella_upgrade_safe;
    error_log /dev/null crit;
    ssl_certificate /etc/ssl/xiya.live/fullchain.pem;
    ssl_certificate_key /etc/ssl/xiya.live/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:12031;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
'''


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='stella-edge-test-', dir=os.environ['TMPDIR'])
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, suffix='abcdefgh', content=None):
        dist = self.root / ('dist-' + suffix)
        (dist / 'static').mkdir(parents=True)
        (dist / 'index.html').write_text('<script src="/static/index-' + suffix + '.js"></script>')
        (dist / 'static' / ('index-' + suffix + '.js')).write_bytes(content or (b'export const x=1;\n' * 200))
        (dist / 'static' / ('index-' + suffix + '.css')).write_text('body{color:white;}\n' * 200)
        (dist / 'static' / 'debug.js.map').write_text('private source map')
        (dist / 'private.txt').write_text('do not publish')
        out = self.root / ('stage-' + suffix)
        m = d.make_stage(dist, IMAGE, IID, REV, out)
        return out, m

    def test_access_log_isolated_path(self):
        candidate = d.render(BASE, {}, str(self.root / 'safe.log'))
        self.assertNotIn('/var/log/nginx/', candidate)
        self.assertIn(str(self.root / 'safe.log'), candidate)

    def test_exact_public_manifest_and_source_private(self):
        stage, m = self.stage()
        self.assertEqual(m['public'], ['static/index-abcdefgh.css', 'static/index-abcdefgh.js'])
        self.assertIn('static/debug.js.map', m['files'])
        self.assertFalse((stage / 'public' / 'private.txt').exists())
        self.assertFalse((stage / 'public' / 'index.html').exists())
        self.assertEqual(d.verify_stage(stage), m)

    def test_tamper_hash_detected(self):
        stage, m = self.stage()
        (stage / 'public' / m['public'][0]).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            d.verify_stage(stage)

    def test_extra_private_file_detected(self):
        stage, _ = self.stage()
        (stage / 'public' / 'secret.txt').write_text('no')
        with self.assertRaisesRegex(ValueError, 'extra/missing'):
            d.verify_stage(stage)

    def test_symlink_rejected(self):
        stage, _ = self.stage()
        p = stage / 'public' / 'static' / 'index-abcdefgh.js'
        p.unlink()
        p.symlink_to(self.root / 'dist-abcdefgh' / 'static' / p.name)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            d.verify_stage(stage)

    def test_dist_symlink_rejected(self):
        dist = self.root / 'symlink-dist'
        dist.mkdir()
        (dist / 'index.html').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            d.make_stage(dist, IMAGE, IID, REV, self.root / 'out')

    def test_path_traversal_manifest_rejected(self):
        stage, m = self.stage()
        m['files']['../outside'] = {'sha256': '1' * 64, 'size': 1}
        with self.assertRaisesRegex(ValueError, 'traversal'):
            d.validate_manifest(m)

    def test_writable_parent_rejected(self):
        self.root.chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'owner/mode'):
            d.trusted(self.root / 'out', exists=False)
        self.root.chmod(0o700)

    def test_two_versions_retained(self):
        a, m1 = self.stage()
        b, m2 = self.stage('ijklmnop')
        root = self.root / 'serve'
        d.install_release(a, root)
        _, assets, versions = d.install_release(b, root)
        self.assertEqual(set(versions), {m1['version'], m2['version']})
        self.assertEqual(len(assets), 4)
        for entry in assets.values():
            self.assertEqual(d.sha(d.read(entry['path'])), entry['sha256'])
        self.assertEqual(d.install_release(b, root)[1], assets)

    def test_same_url_different_bytes_refused(self):
        a, _ = self.stage()
        d.install_release(a, self.root / 'serve')
        shutil.rmtree(self.root / 'dist-abcdefgh')
        shutil.rmtree(a)
        b, _ = self.stage(content=b'different build')
        with self.assertRaisesRegex(ValueError, 'different bytes'):
            d.install_release(b, self.root / 'serve')
        self.assertEqual(len(list((self.root / 'serve' / 'releases').iterdir())), 1)

    def test_release_subdirectories_are_fsynced(self):
        stage, m = self.stage()
        seen = []
        fsync = d.os.fsync
        def observe(fd):
            seen.append(os.readlink('/proc/self/fd/' + str(fd)))
            return fsync(fd)
        with patch.object(d.os, 'fsync', side_effect=observe):
            d.install_release(stage, self.root / 'serve')
        self.assertTrue(any(x.endswith('/public/static') for x in seen), seen)
        self.assertTrue(any(x.endswith('/public') for x in seen), seen)

    def test_retained_corruption_refused(self):
        a, _ = self.stage()
        _, assets, _ = d.install_release(a, self.root / 'serve')
        Path(next(iter(assets.values()))['path']).write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'corrupt'):
            d.install_release(a, self.root / 'serve')

    def test_only_exact_static_locations_and_proxy_preserved(self):
        stage, _ = self.stage()
        _, assets, _ = d.install_release(stage, self.root / 'serve')
        rendered = d.render(BASE, assets)
        self.assertEqual(rendered[rendered.index('    location / {'):], BASE[BASE.index('    location / {'):])
        self.assertIn('location ^~ /static/ { return 404; }', rendered)
        self.assertNotIn('location /assets', rendered)
        self.assertNotIn('location /auth', rendered)
        self.assertNotIn('location /ws', rendered)
        self.assertNotIn('source-index', rendered)
        self.assertEqual(d.render(rendered, assets), rendered)
        for bad in ('$args', '$request_uri', '$request"', '$http_authorization', '$http_cookie', '$http_referer'):
            self.assertNotIn(bad, d.LOG_FORMAT)
        for timing in ('request_time', 'upstream_connect_time', 'upstream_header_time', 'upstream_response_time'):
            self.assertIn(timing, d.LOG_FORMAT)

    def deployer(self, fail=None):
        path = self.root / 'stella.conf'
        path.write_text(BASE)
        path.chmod(0o644)
        calls = []
        failed = False
        def run(argv):
            nonlocal failed
            calls.append(argv)
            if fail == 'nginx' and argv == ['nginx', '-t'] and len(calls) > 2 and not failed:
                failed = True
                raise ValueError('nginx candidate invalid')
            if argv == ['nginx', '-T']:
                return d.read(path)
            return b'healthy'
        def health(m, assets):
            if fail == 'health':
                raise ValueError('health mismatch')
            self.assertTrue(assets)
        return d.Deployer(path, self.root / 'serve', self.root / 'state', run, health), calls, path

    def test_apply_backup_readback_and_manual_rollback(self):
        stage, m = self.stage()
        deployer, calls, path = self.deployer()
        tx = Path(deployer.apply(stage, d.sha(BASE.encode())))
        self.assertEqual(json.loads(d.read(tx / 'receipt.json'))['status'], 'verified')
        self.assertEqual(d.read(tx / 'previous.conf'), BASE.encode())
        self.assertEqual(tx.stat().st_mode & 0o777, 0o700)
        self.assertEqual((tx / 'complete-nginx-before.txt').stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        deployer.rollback(tx)
        self.assertEqual(d.read(path), BASE.encode())
        self.assertTrue((deployer.root / 'releases' / m['version']).exists())
        self.assertIn(['nginx', '-s', 'reload'], calls)

    def test_health_failure_automatic_exact_rollback(self):
        self.check_failure('health')

    def test_failed_rollback_probe_marks_needs_operator(self):
        stage, _ = self.stage()
        deployer, _, path = self.deployer('health')
        def bad_recovery():
            raise ValueError('rollback health unavailable')
        deployer.recovery_health = bad_recovery
        with self.assertRaisesRegex(ValueError, 'health mismatch'):
            deployer.apply(stage, d.sha(BASE.encode()))
        self.assertEqual(d.read(path), BASE.encode())
        receipt = next(deployer.state.glob('*/receipt.json'))
        self.assertEqual(json.loads(d.read(receipt))['status'], 'rollback-needs-operator')

    def test_nginx_failure_automatic_exact_rollback(self):
        self.check_failure('nginx')

    def check_failure(self, fail):
        stage, _ = self.stage()
        deployer, _, path = self.deployer(fail)
        with self.assertRaises(ValueError):
            deployer.apply(stage, d.sha(BASE.encode()))
        self.assertEqual(d.read(path), BASE.encode())
        receipt = next(deployer.state.glob('*/receipt.json'))
        self.assertEqual(json.loads(d.read(receipt))['status'], 'rolled-back')

    def test_changed_baseline_refused_before_write(self):
        stage, _ = self.stage()
        deployer, _, path = self.deployer()
        with self.assertRaisesRegex(ValueError, 'changed since approval'):
            deployer.apply(stage, '4' * 64)
        self.assertEqual(d.read(path), BASE.encode())

    def test_lock_symlink_rejected_before_write(self):
        stage, _ = self.stage()
        deployer, _, path = self.deployer()
        deployer.state.mkdir(mode=0o700)
        victim = self.root / 'unrelated'
        victim.write_text('untouched')
        victim.chmod(0o644)
        (deployer.state / 'lock').symlink_to(victim)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            deployer.apply(stage, d.sha(BASE.encode()))
        self.assertEqual(path.read_text(), BASE)
        self.assertEqual(victim.stat().st_mode & 0o777, 0o644)

    def test_concurrent_apply_locks_then_rechecks_baseline(self):
        import threading
        a, _ = self.stage()
        b, _ = self.stage('ijklmnop')
        deployer, _, path = self.deployer()
        entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def health(m, assets):
            entered.set()
            if not release.wait(3):
                raise ValueError('test release timeout')
        deployer.health = health
        def apply(stage, second=False):
            try:
                deployer.apply(stage, d.sha(BASE.encode()))
            except Exception as exc:
                errors.append(str(exc))
            finally:
                if second:
                    second_done.set()
        first = threading.Thread(target=apply, args=(a,))
        second = threading.Thread(target=apply, args=(b, True))
        first.start()
        self.assertTrue(entered.wait(2))
        second.start()
        try:
            self.assertFalse(second_done.wait(0.1))
        finally:
            release.set()
            first.join(4)
            second.join(4)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, ['vhost changed since approval'])
        self.assertIn('index-abcdefgh.js', path.read_text())
        self.assertNotIn('index-ijklmnop.js', path.read_text())

    def test_rollback_cannot_clobber_later_config(self):
        stage, _ = self.stage()
        deployer, _, path = self.deployer()
        tx = deployer.apply(stage, d.sha(BASE.encode()))
        path.write_text('later approved deploy')
        with self.assertRaisesRegex(ValueError, 'later deployment'):
            deployer.rollback(tx)
        self.assertEqual(path.read_text(), 'later approved deploy')

    def test_prepublication_retains_primary_stage_and_checks_old_html(self):
        prior, p = self.stage()
        target, m = self.stage('ijklmnop')
        deployer, _, path = self.deployer()
        observed = []
        def health(manifest, assets, primary_manifest=None):
            assert primary_manifest is not None
            self.assertEqual(manifest['version'], m['version'])
            self.assertEqual(primary_manifest['version'], p['version'])
            self.assertEqual(set(assets), set(p['public']) | set(m['public']))
            observed.append(primary_manifest['version'])
        deployer.health = health
        tx = deployer.apply(target, d.sha(BASE.encode()), primary_stage=prior)
        self.assertEqual(observed, [p['version']])
        receipt = json.loads(d.read(Path(tx) / 'receipt.json'))
        self.assertEqual(receipt['expected_primary_version'], p['version'])
        self.assertIn('index-abcdefgh.js', path.read_text())
        self.assertIn('index-ijklmnop.js', path.read_text())

    def test_production_health_waits_for_real_edge_header(self):
        stage, m = self.stage()
        _, assets, _ = d.install_release(stage, self.root / 'serve')
        attempts = {}
        def run(argv):
            url = argv[-1]
            if url.endswith('/live'):
                return b'{"ok":true}'
            if url.endswith('stella.xiya.live/'):
                return d.read(stage / 'source-index.html')
            name = url.split('stella.xiya.live/', 1)[1]
            attempts[name] = attempts.get(name, 0) + 1
            body = d.read(assets[name]['path'])
            # Same bytes returned by primary is NOT proof new nginx config loaded.
            if attempts[name] == 1:
                return b'HTTP/1.1 200 OK\r\nCache-Control: private\r\n\r\n' + body
            return ('HTTP/1.1 200 OK\r\nCache-Control: public, max-age=604800, immutable\r\nX-Stella-Static-SHA256: ' + assets[name]['sha256'] + '\r\n\r\n').encode() + body
        deployer = d.Deployer(run=run)
        deployer.production_health(m, assets)
        self.assertTrue(all(x >= 2 for x in attempts.values()))

    def test_extract_readonly_container_no_lifecycle(self):
        fixture, _ = self.stage()
        dist = self.root / 'dist-abcdefgh'
        calls = []
        def run(argv, timeout=90):
            calls.append(argv)
            if argv[:3] == ['docker', 'image', 'inspect']:
                return d.encoded([{'Id': IID, 'RepoDigests': [IMAGE], 'Config': {'Labels': {}}}])
            if argv[:2] == ['docker', 'inspect']:
                return d.encoded([{'Image': IID, 'HostConfig': {'ReadonlyRootfs': True}, 'Mounts': []}])
            if argv[:2] == ['docker', 'diff']:
                return b''
            if argv[:2] == ['docker', 'cp']:
                shutil.copytree(dist, argv[-1])
                return b''
            raise AssertionError('unexpected Docker lifecycle command')
        with patch.object(d, 'command', side_effect=run):
            m = d.extract(IMAGE, REV, self.root / 'readonly-stage', read_only_container='stella-app-shadow-nyarch')
        self.assertEqual(m['image_id'], IID)
        self.assertFalse(any(x[1] in ('create', 'rm', 'start', 'exec') for x in calls))

    def test_readonly_carrier_overlay_dist_change_rejected(self):
        image = {'Id': IID, 'RepoDigests': [IMAGE], 'Config': {'Labels': {}}}
        container = {'Image': IID, 'HostConfig': {'ReadonlyRootfs': True}, 'Mounts': []}
        with patch.object(d, 'command', side_effect=[d.encoded([image]), d.encoded([container]), b'C /app/frontend/dist/index.html\n']):
            with self.assertRaisesRegex(ValueError, 'overlay dist change'):
                d.extract(IMAGE, REV, self.root / 'bad-stage', read_only_container='fixture')

    def test_extract_refuses_tag_before_docker_call(self):
        with patch.object(d, 'command') as run:
            with self.assertRaisesRegex(ValueError, 'immutable'):
                d.extract(d.REGISTRY + ':latest', REV, self.root / 'out')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
