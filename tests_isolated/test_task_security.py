"""No database connection; real FastAPI routes and policy, isolated from tests/conftest.py."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.routers.task import agent_task_router
from app.services import task as svc

class TaskSecurityTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(agent_task_router)
        self.db = Mock()
        self.task = SimpleNamespace(id=1, node_id=10, client_node_id=10, server_node_id=20, mode='iperf3', status='running', server_started=True)
        self.db.get.return_value = self.task
        self.db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = self.task
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.token = patch.object(svc.node_repo, 'get_by_token', return_value=SimpleNamespace(id=10, status='online'))
        self.token_mock = self.token.start()
        self.addCleanup(self.token.stop)
    def post(self, path, **params):
        return self.client.post('/agent/' + path, params={'token':'test', **params}, json={})
    def test_all_result_routes_reject_unknown_token(self):
        self.token_mock.return_value = None
        for path in ['iperf-tasks/1/result','iperf-tasks/1/progress','component-installs/1/result','net-tasks/1/result','mtr-tasks/1/result','mtr-tasks/1/live','commands/1/result']:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, status='done', ts='2026-01-01').status_code, 401)
    def test_other_node_cannot_write(self):
        self.token_mock.return_value.id = 99
        for path in ['iperf-tasks/1/result','iperf-tasks/1/progress','component-installs/1/result','net-tasks/1/result','mtr-tasks/1/result','mtr-tasks/1/live','commands/1/result']:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, status='done', ts='2026-01-01').status_code, 403)
    def test_invalid_status_and_terminal_task_rejected(self):
        self.assertEqual(self.post('commands/1/result', status='running').status_code, 422)
        self.task.status = 'cancelled'
        self.assertEqual(self.post('commands/1/result', status='done').status_code, 409)
    def test_role_cannot_be_spoofed(self):
        self.assertEqual(self.post('iperf-tasks/1/progress', role='server', ts='now').status_code, 403)
    def test_owner_can_finish(self):
        with patch.object(svc, 'finish_command') as finish:
            self.assertEqual(self.post('commands/1/result', status='done').status_code, 200)
            finish.assert_called_once()
    def test_removed_token_and_missing_task(self):
        self.token_mock.return_value.status = 'removed'
        self.assertEqual(self.post('commands/1/result', status='done').status_code, 401)
        self.token_mock.return_value.status = 'online'
        self.db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
        self.assertEqual(self.post('commands/1/result', status='done').status_code, 404)
    def test_server_auxiliary_and_speedtest_roles(self):
        self.token_mock.return_value.id = 20
        with patch.object(svc, 'append_iperf_progress') as append:
            self.assertEqual(self.post('iperf-tasks/1/progress', role='server', ts='now').status_code, 200)
            append.assert_called_once()
        self.task.mode = 'speedtest'
        self.assertEqual(self.post('iperf-tasks/1/progress', role='server', ts='now').status_code, 403)
    def test_status_read_requires_membership(self):
        self.token_mock.return_value.id = 99
        response = self.client.get('/agent/iperf-tasks/1/status', params={'token':'test'})
        self.assertEqual(response.status_code, 403)

if __name__ == '__main__': unittest.main()
