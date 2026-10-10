"""Execute the real repository heartbeat offline; never import app.database."""
import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def heartbeat_function():
    tree = ast.parse((ROOT / 'app/repositories/node.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'heartbeat')
    namespace = {'Session': object, 'Node': object, 'datetime': datetime, 'timezone': timezone,
                 'get_by_id': lambda db, node_id: db.node,
                 'NodeStatusEvent': lambda **kwargs: SimpleNamespace(**kwargs)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / 'app/repositories/node.py'), 'exec'), namespace)
    return namespace['heartbeat']


class Session:
    def __init__(self):
        self.node = SimpleNamespace(status='online', installed=True, arch=None,
                                    uninstall_status=None, monitored_ifaces=None,
                                    sys_info={'hardware': {'sampled_at': 'previous'}})
        self.commits = 0
    def commit(self):
        self.commits += 1
    def refresh(self, node):
        assert node is self.node
    def add(self, value):
        pass


class HardwareRepositoryTests(unittest.TestCase):
    def test_heartbeat_persists_hardware_alongside_legacy_metadata(self):
        db = Session()
        hardware = {'sampled_at': datetime.now(timezone.utc).isoformat(),
                    'cpu': {'temperature_c': None}, 'gpus': [], 'sensors': [],
                    'availability': {'gpu': 'unavailable', 'cpu_temperature': 'unavailable'}}
        result = heartbeat_function()(db, 1, os_info={'kernel': 'test-kernel', 'hardware': hardware})
        self.assertEqual(result.sys_info.get('hardware'), hardware)
        self.assertEqual(result.sys_info['kernel'], 'test-kernel')
        self.assertEqual(db.commits, 1)


    def test_old_agent_clears_hardware_instead_of_preserving_stale_measurements(self):
        db = Session()
        result = heartbeat_function()(db, 1, os_info={'cpu_model': 'old CPU', 'load1': 1.5})
        self.assertIsNone(result.sys_info['hardware'])
        self.assertEqual(result.sys_info['cpu_model'], 'old CPU')
        self.assertEqual(result.sys_info['load1'], 1.5)

    def test_report_without_os_info_does_not_replace_saved_metadata(self):
        db = Session()
        previous = db.node.sys_info
        result = heartbeat_function()(db, 1)
        self.assertIs(result.sys_info, previous)

    def test_hardware_roundtrips_through_a_real_isolated_sqlite_json_column(self):
        # Exercise commit/readback without loading app.database or using PostgreSQL.
        from sqlalchemy import JSON, String, Integer, create_engine, select
        from sqlalchemy.orm import DeclarativeBase, mapped_column, Session as SqlSession
        class Base(DeclarativeBase):
            pass
        class SqlNode(Base):
            __tablename__ = 'hardware_node'
            id = mapped_column(Integer, primary_key=True)
            sys_info = mapped_column(JSON)
            status = mapped_column(String)
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with SqlSession(engine) as db:
                node = SqlNode(id=1, status='online', sys_info={})
                node.installed, node.arch, node.uninstall_status = True, None, None
                db.add(node)
                db.commit()
                function = heartbeat_function()
                function.__globals__['get_by_id'] = lambda session, node_id: session.get(SqlNode, node_id)
                hardware = {'sampled_at': '2026-10-10T00:00:00+00:00', 'cpu': {'temperature_c': None},
                            'gpus': [{'id': 'GPU-a', 'temperature_c': 62.0}], 'sensors': [],
                            'availability': {'cpu_temperature': 'unavailable', 'gpu': 'available'}}
                function(db, 1, os_info={'kernel': 'test', 'hardware': hardware})
            with SqlSession(engine) as readback:
                saved = readback.scalar(select(SqlNode)).sys_info
                self.assertEqual(saved['hardware'], hardware)
                self.assertEqual(saved['kernel'], 'test')
        finally:
            engine.dispose()


    def test_old_agent_cpu_cores_is_not_reinterpreted_as_physical_cores(self):
        db = Session()
        result = heartbeat_function()(db, 1, os_info={'cpu_cores': 12})
        self.assertEqual(result.sys_info['cpu_cores'], 12)
        self.assertIsNone(result.sys_info['cpu_logical_cores'])
        self.assertIsNone(result.sys_info['storage_status'])

    def test_gpu_query_failure_and_presence_roundtrip_without_inventory_rows(self):
        db = Session()
        hardware = {'gpus': [], 'availability': {'gpu': 'collection_failed',
                    'gpu_query': 'query_failed', 'gpu_presence': 'none'}}
        result = heartbeat_function()(db, 1, os_info={'hardware': hardware})
        self.assertEqual(result.sys_info['hardware'], hardware)

    def test_storage_failure_and_cpu_threads_roundtrip_without_erasing_storage(self):
        from sqlalchemy import JSON, String, Integer, create_engine, select
        from sqlalchemy.orm import DeclarativeBase, mapped_column, Session as SqlSession
        class Base(DeclarativeBase):
            pass
        class SqlNode(Base):
            __tablename__ = 'refresh_node'
            id = mapped_column(Integer, primary_key=True)
            sys_info = mapped_column(JSON)
            storage = mapped_column(JSON)
            status = mapped_column(String)
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        sample = [{'device': 'disk0', 'sampled_at': 'old-source', 'used': 0}]
        failure = {'state': 'query_failed', 'sampled_at': '2026-10-10T00:00:00+00:00',
                   'attempted_at': '2026-10-10T00:01:00+00:00'}
        try:
            with SqlSession(engine) as db:
                node = SqlNode(id=1, status='online', sys_info={}, storage=sample)
                node.installed, node.arch, node.uninstall_status = True, None, None
                db.add(node)
                db.commit()
                function = heartbeat_function()
                function.__globals__['get_by_id'] = lambda session, node_id: session.get(SqlNode, node_id)
                function(db, 1, storage=None, os_info={'cpu_cores': 6, 'cpu_logical_cores': 12,
                                                     'storage_status': failure})
            with SqlSession(engine) as readback:
                saved = readback.scalar(select(SqlNode))
                self.assertEqual(saved.sys_info.get('storage_status'), failure)
                self.assertEqual(saved.sys_info['cpu_cores'], 6)
                self.assertEqual(saved.sys_info.get('cpu_logical_cores'), 12)
                self.assertEqual(saved.storage, sample)
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
