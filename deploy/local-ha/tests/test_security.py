"""Offline security regressions: no SSH, Docker daemon, or DB access."""
import contextlib
import io
import runpy
import sys
import unittest
from unittest.mock import patch
from test_release import ROOT


class ErrorRedactionTests(unittest.TestCase):
    def test_live_cli_never_echoes_private_inventory_errors(self):
        output = io.StringIO()
        argv = ['validate_live.py', '--inventory', '/private/inventory',
                '--ssh-config', '/private/ssh', '--image', 'unused']
        with patch.object(sys, 'argv', argv), patch('pathlib.Path.read_text',
                side_effect=ValueError('PRIVATE_SENTINEL')), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc:
                runpy.run_path(str(ROOT / 'validate_live.py'), run_name='__main__')
        self.assertEqual(exc.exception.code, 2)
        self.assertNotIn('PRIVATE_SENTINEL', output.getvalue())
        self.assertIn('blocked', output.getvalue())

    def test_entrypoint_never_echoes_secret_parse_errors(self):
        output = io.StringIO()
        env = {'LOCAL_HA_PROFILE': 'manual', 'LOCAL_HA_ENABLE_APP': 'operator-approved',
               'STELLA_HA_MODE': 'primary-only'}
        with patch.object(sys, 'argv', ['entrypoint.py', 'app']), patch.dict('os.environ', env, clear=True), patch('readiness.check_resources',
                side_effect=ValueError('PRIVATE_SENTINEL')), contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as exc:
                runpy.run_path(str(ROOT / 'entrypoint.py'), run_name='__main__')
        self.assertEqual(exc.exception.code, 2)
        self.assertNotIn('PRIVATE_SENTINEL', output.getvalue())
