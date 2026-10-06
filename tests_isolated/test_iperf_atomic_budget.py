"""Repository orchestration unit proof; separate PG barrier test required."""
from unittest.mock import Mock
import pytest
from app.repositories import task

class DB:
    def __init__(self, active=0, fail=False):
        self.events = []
        self.active = active
        self.fail = fail
    def execute(self, statement, params=None):
        self.events.append(('sql', str(statement), params))
    def query(self, model):
        self.events.append(('query', model.__name__))
        return self
    def filter(self, *args): return self
    def count(self):
        self.events.append(('count', self.active))
        return self.active
    def add(self, obj):
        self.events.append(('add', obj))
        if self.fail: raise RuntimeError('insert failed')
    def commit(self): self.events.append(('commit',))
    def flush(self): self.events.append(('flush',))
    def rollback(self): self.events.append(('rollback',))
    def refresh(self, obj): pass


def test_global_advisory_lock_precedes_count_and_insert(monkeypatch):
    db = DB()
    monkeypatch.setattr(task, 'trim_old', lambda *a: None)
    task.create_iperf(db, None, 1, 'speedtest', 'forward', 10, 1)
    assert db.events[0][0] == 'sql'
    assert 'pg_advisory_xact_lock' in db.events[0][1]
    actions = [e[0] for e in db.events]
    assert actions.index('count') < actions.index('add') < actions.index('commit')
    assert actions.count('commit') == 1


def test_active_task_rejected_and_lock_released(monkeypatch):
    db = DB(active=1)
    monkeypatch.setattr(task, 'trim_old', lambda *a: None)
    with pytest.raises(ValueError, match='已有打流任务'):
        task.create_iperf(db, None, 1, 'speedtest', 'forward', 10, 1)
    assert db.events[-1] == ('rollback',)
    assert not any(e[0] == 'add' for e in db.events)


def test_insert_failure_rolls_back_transaction(monkeypatch):
    db = DB(fail=True)
    monkeypatch.setattr(task, 'trim_old', lambda *a: None)
    with pytest.raises(RuntimeError):
        task.create_iperf(db, None, 1, 'speedtest', 'forward', 10, 1)
    assert db.events[-1] == ('rollback',)
