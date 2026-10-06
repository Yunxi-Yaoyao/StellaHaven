"""Safe migration unit contract: never block populated production with CREATE INDEX."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

@pytest.fixture
def migration():
    path=Path(__file__).parents[1]/'alembic/versions/c0d1e2f3a4b5_monitor_query_index.py'
    assert path.exists(), 'index migration not delivered'
    spec=importlib.util.spec_from_file_location('perf_migration',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('populated', [False,True])
def test_migration_adopts_only_valid_existing_index(migration,populated):
    db=Mock(); db.execute.return_value.mappings.return_value.first.return_value={
      'indisvalid':True,'indisready':True,'indisunique':False,'method':'btree','columns':['node_id','ts'],'indpred':None,'indexprs':None}
    op=Mock(); op.get_bind.return_value=db; migration.op=op
    migration.upgrade()
    op.create_index.assert_not_called()


def test_populated_table_without_index_requires_concurrent_preparation(migration):
    db=Mock(); db.execute.return_value.mappings.return_value.first.return_value=None
    db.execute.return_value.scalar.return_value=True
    op=Mock(); op.get_bind.return_value=db; migration.op=op
    with pytest.raises(RuntimeError,match='CONCURRENTLY'): migration.upgrade()
    op.create_index.assert_not_called()


def test_empty_database_creates_index_transactionally(migration):
    db=Mock(); db.execute.return_value.mappings.return_value.first.return_value=None
    db.execute.return_value.scalar.return_value=False
    op=Mock(); op.get_bind.return_value=db; migration.op=op
    migration.upgrade()
    op.create_index.assert_called_once_with('ix_node_metrics_node_ts','node_metrics',['node_id','ts'])
