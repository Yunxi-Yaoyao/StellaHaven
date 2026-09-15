import json
import subprocess
import unittest
from unittest.mock import patch
from test_release import IMAGE, OLD, load, sample


class SSHTests(unittest.TestCase):
    def test_ssh_protocol_uses_json_stdin_and_fixed_remote_command(self):
        release = load('release')
        self.assertTrue(hasattr(release, 'SSHTransport'), 'SSH transport missing')
        replies = [subprocess.CompletedProcess([], 0, json.dumps(n), '') for n in sample()['nodes']]
        with patch('subprocess.run', side_effect=replies) as ssh:
            transport = release.SSHTransport({'nyarch': 'ha-test-nyarch', 'nas': 'ha-test-nas'})
            self.assertEqual(transport.snapshot(), sample())
            for call in ssh.call_args_list:
                self.assertEqual(call.args[0][0], 'ssh')
                self.assertNotIn('shell', call.kwargs)
                self.assertEqual(json.loads(call.kwargs['input'])['op'], 'probe')
                self.assertIn('StrictHostKeyChecking=yes', call.args[0])

    def test_node_update_cannot_target_primary_or_recreate_database(self):
        self.assertTrue(__import__('pathlib').Path(__file__).resolve().parents[1].joinpath('node.py').exists(), 'node guard missing')
        node = load('node')
        config = {'scope': 'stella-local-ha-v1', 'node': 'nas', 'app_updates_enabled': True}
        with patch.object(node, 'probe', return_value=sample()['nodes'][0]), patch.object(node, 'compose') as compose:
            with self.assertRaises(ValueError):
                node.update_app(config, IMAGE, OLD)
            compose.assert_not_called()

    def test_node_probe_reads_exact_project_and_container(self):
        node = load('node')
        config = {'scope': 'stella-local-ha-v1', 'node': 'nas', 'environment': 'nonproduction'}
        inspected = [{'Config': {'Image': OLD, 'Labels': {'com.docker.compose.project': 'stella-local-ha-nas'}}}]
        replies = [subprocess.CompletedProcess([], 0, json.dumps(inspected), ''),
                   subprocess.CompletedProcess([], 0, json.dumps(sample()['nodes'][1]), '')]
        with patch.object(node, 'compose', return_value='container-id'), patch('subprocess.run', side_effect=replies) as run:
            self.assertEqual(node.probe(config)['image'], OLD)
            self.assertEqual(run.call_args_list[0].args[0], ['docker', 'inspect', 'container-id'])
            self.assertEqual(run.call_args_list[1].args[0][:3], ['docker', 'exec', 'container-id'])
        with patch.object(node, 'compose') as compose:
            with self.assertRaises(ValueError):
                node.probe(dict(config, environment='production'))
            compose.assert_not_called()

    def test_switchover_request_is_explicitly_blocked_not_fake_fencing(self):
        release = load('release')
        self.assertTrue(hasattr(release, 'switchover_guard'), 'switchover guard missing')
        with self.assertRaises(release.Refused):
            release.switchover_guard(sample(), requested=True)
        self.assertEqual(release.switchover_guard(sample(), requested=False), 'not-requested')
