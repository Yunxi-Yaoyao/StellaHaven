import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_release import ROOT, IMAGE, load


class TemplateTests(unittest.TestCase):
    def test_render_manual_profile_and_compose_config_without_start(self):
        self.assertTrue((ROOT / 'render.py').exists(), 'renderer missing')
        render = load('render')
        with tempfile.TemporaryDirectory() as tmp:
            render.render(Path(tmp), node='nyarch', node_ip='10.66.0.2',
                          app_image=IMAGE, pg_image=IMAGE,
                          etcd_hosts=['https://etcd1.invalid:2379', 'https://etcd2.invalid:2379', 'https://etcd3.invalid:2379'])
            config = json.loads((Path(tmp) / 'patroni.json').read_text())
            self.assertTrue(config['tags']['nofailover'])
            self.assertEqual(config['watchdog']['mode'], 'off')
            self.assertNotIn('pause', config)
            self.assertEqual(config['scope'], 'stella-local-ha-v1')
            self.assertNotIn('password', json.dumps(config))
            result = subprocess.run(['docker', 'compose', '--env-file', str(Path(tmp) / 'compose.env'),
                                     '-f', str(ROOT / 'compose.yaml'), 'config', '--format', 'json'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            services = json.loads(result.stdout)['services']
            self.assertEqual(services['app']['image'], IMAGE)
            self.assertEqual(services['app']['network_mode'], 'host')
            self.assertNotIn('depends_on', services['app'])
            self.assertNotIn('build', services['app'])
            self.assertIn('--port', services['app']['command'])
            self.assertIn('24131', services['app']['command'])
            self.assertTrue(any(v.get('read_only') and v['target'] == '/app/data' for v in services['app']['volumes']))
            self.assertTrue(all(v['bind']['create_host_path'] is False for v in services['pg']['volumes']))

    def test_render_refuses_automatic_profile_and_overwrite(self):
        render = load('render')
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = dict(node='nas', node_ip='10.66.0.3', app_image=IMAGE, pg_image=IMAGE,
                          etcd_hosts=['https://e1.invalid:2379', 'https://e2.invalid:2379', 'https://e3.invalid:2379'])
            with self.assertRaises(ValueError):
                render.render(Path(tmp), profile='automatic', **kwargs)
            render.render(Path(tmp), **kwargs)
            with self.assertRaises(FileExistsError):
                render.render(Path(tmp), **kwargs)
