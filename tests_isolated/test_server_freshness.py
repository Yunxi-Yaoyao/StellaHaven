import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from app.services import task
from unittest.mock import Mock, patch

class FreshnessTests(unittest.TestCase):
    def test_boundary_and_monitor_source_offline_preserve_last_result(self):
        from app.services.server_status import node_status, monitor_status
        now = datetime.now(timezone.utc)
        n = SimpleNamespace(status='online', last_seen_at=now-timedelta(seconds=120))
        m = SimpleNamespace(status='up', last_check_at=now, interval=30)
        self.assertEqual(node_status(n, now), 'online')
        self.assertEqual(node_status(n, now+timedelta(microseconds=1)), 'offline')
        self.assertEqual(monitor_status(m, n, now+timedelta(seconds=1)), 'unknown')
        self.assertEqual(m.status, 'up')
        self.assertEqual(n.status, 'online')
    def test_scan_rejects_stale_stored_online_without_list_read(self):
        node = SimpleNamespace(status='online', last_seen_at=datetime.now(timezone.utc)-timedelta(seconds=121))
        with patch.object(task.node_repo, 'get_by_id', return_value=node):
            with self.assertRaisesRegex(ValueError, '不在线'):
                task.create_docker_scan(Mock(), 1)

if __name__ == '__main__': unittest.main()
