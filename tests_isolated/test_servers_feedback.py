"""Scoped integration tests on a dedicated fixture or the exact CI test DB.
Never connect using the application's database URL; missing prerequisites fail.
"""
from uuid import uuid4

import pytest
from sqlalchemy import text
from tests_isolated.servers_fixture import fixture_engine
from tests_ha.testdb_guard import IDENTITY_SQL, verify_identity
from sqlalchemy.orm import Session
from app.models.node import Node
from app.models.monitor import Monitor
from app.models.task import MtrTask, IperfTask, AgentCommand, ComponentTask, NetTask
from app.services import task as svc
from app.repositories import task as repo


@pytest.fixture
def database():
    from app.models.config import AppConfig
    from app.models.alert import AlertRule
    engine = fixture_engine()
    schema = 'servers_fixture_' + uuid4().hex
    url, address, revalidate = engine._stella_test_identity
    scoped = None
    created = False
    try:
        with engine.begin() as conn:
            revalidate()
            verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
            conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
            created = True
        scoped = fixture_engine(schema)
        tables = [Node.__table__, Monitor.__table__, MtrTask.__table__, IperfTask.__table__, AgentCommand.__table__, ComponentTask.__table__, NetTask.__table__, AppConfig.__table__, AlertRule.__table__]
        # Real reached config/alert dependencies, not service mocks.
        with scoped.begin() as conn:
            verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
            Node.metadata.create_all(conn, tables=tables)
            assert conn.execute(text('SELECT current_schema()')).scalar_one() == schema
        with Session(scoped) as db:
            db.add_all([Node(id=i, name=f'fixture-{i}', platform='linux', host='fixture.invalid', token=f'fixture-token-{i}', status='online') for i in (1, 2)])
            db.flush()
            db.add(Monitor(id=1, name='fixture', node_id=1, type='ping', target='fixture.invalid'))
            db.commit()
        yield scoped
    finally:
        if scoped is not None:
            scoped.dispose()
        if created:
            with engine.begin() as conn:
                revalidate()
                verify_identity(conn.execute(text(IDENTITY_SQL)).one(), url, address)
                conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
                assert conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:s'), {'s': schema}).first() is None
        engine.dispose()


def test_manual_filter_precedes_limit_and_keeps_monitor_manual(database):
    with Session(database) as db:
        db.add_all([MtrTask(node_id=1, monitor_id=1, target='manual.invalid', protocol='icmp', trigger='manual', status='done'), MtrTask(node_id=1, target='tool.invalid', trigger='manual', status='done')])
        db.flush()
        db.add_all([MtrTask(node_id=1, monitor_id=1, target='auto.invalid', trigger='periodic', status='done') for _ in range(105)])
        db.commit()
        rows = repo.list_mtr(db, limit=2, trigger='manual')
        assert [r.target for r in rows] == ['tool.invalid', 'manual.invalid']
        assert rows[1].monitor_id == 1
        assert len(repo.list_mtr(db, limit=110)) == 107


def test_manual_admission_does_not_trim_other_sources_or_active(database):
    with Session(database) as db:
        db.add_all([MtrTask(node_id=1, monitor_id=1, target='auto.invalid', trigger='periodic', status='done') for _ in range(105)])
        db.commit()
        repo.create_mtr(db, 1, 'manual.invalid', 'icmp')
        assert db.query(MtrTask).filter(MtrTask.trigger == 'periodic').count() == 105


def test_real_agent_completion_persists_and_manual_history_reads_same_id(database):
    from app.routers.task import agent_task_router
    from app.database import get_db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(agent_task_router)
    def fixture_db():
        with Session(database) as db:
            yield db
    app.dependency_overrides[get_db] = fixture_db
    with Session(database) as db:
        task = repo.create_mtr(db, 1, 'manual.invalid', 'icmp', monitor_id=1)
        task_id = task.id
        svc.poll_tasks(db, 'fixture-token-1')
    result = {'hubs': [{'host': '192.0.2.1', 'loss': 0, 'avg': 3.2}]}
    with TestClient(app) as client:
        response = client.post(f'/agent/mtr-tasks/{task_id}/result', params={'token': 'fixture-token-1', 'status': 'done'}, json=result)
        assert response.status_code == 200, response.text
        # A late live snapshot and a second result cannot overwrite the terminal result.
        assert client.post(f'/agent/mtr-tasks/{task_id}/live', params={'token': 'fixture-token-1'}, json={'hops': []}).status_code == 409
        assert client.post(f'/agent/mtr-tasks/{task_id}/result', params={'token': 'fixture-token-1', 'status': 'failed'}, json={'error': 'late'}).status_code == 409
    with Session(database) as db:
        row = repo.list_mtr(db, trigger='manual')[0]
        assert (row.id, row.status, row.result_json, row.monitor_id) == (task_id, 'done', result, 1)


def test_multi_node_job_atomic_busy_reject_and_independent_results(database):
    with Session(database) as db:
        rows = repo.create_mtr_job(db, [1, 2], 'multi.invalid', 'icmp', {'count': 3})
        assert len(rows) == 2 and rows[0].job_id == rows[1].job_id and rows[0].job_id
        ids = [row.id for row in rows]
        with pytest.raises(ValueError, match='进行中'):
            repo.create_mtr(db, 1, 'must-not-queue.invalid', 'icmp')
        assert db.query(MtrTask).count() == 2
        assert [t['id'] for t in svc.poll_tasks(db, 'fixture-token-1')['mtr_tasks']] == [ids[0]]
        assert [t['id'] for t in svc.poll_tasks(db, 'fixture-token-2')['mtr_tasks']] == [ids[1]]
        repo.finish_mtr(db, ids[0], 'done', {'hubs': []})
        with pytest.raises(ValueError, match='进行中'):
            repo.create_mtr_job(db, [1], 'must-not-queue.invalid', 'icmp')
        repo.finish_mtr(db, ids[1], 'failed', {'error': 'fixture'})
        assert len(repo.create_mtr_job(db, [1], 'next.invalid', 'icmp')) == 1


def test_concurrent_manual_admission_is_one_job_not_a_queue(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    def submit():
        with Session(database) as db:
            barrier.wait()
            try:
                return ('accepted', repo.create_mtr_job(db, [1, 2], 'race.invalid', 'icmp')[0].job_id)
            except ValueError:
                return ('busy', None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(r[0] for r in replies) == ['accepted', 'busy']
    with Session(database) as db:
        assert db.query(MtrTask).count() == 2


def test_mtr_job_migration_keeps_existing_history(database):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/83b5f190a621_mtr_job_identity.py'
    spec = importlib.util.spec_from_file_location('fixture_mtr_revision', path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with Session(database) as db:
        db.add(MtrTask(node_id=1,target='legacy.invalid',trigger='manual',status='done',result_json={'hubs':[]}))
        db.commit()
    with database.begin() as conn:
        conn.exec_driver_sql('DROP INDEX ix_mtr_tasks_job_id')
        conn.exec_driver_sql('ALTER TABLE mtr_tasks DROP COLUMN job_id')
        with Operations.context(MigrationContext.configure(conn)):
            revision.upgrade()
        assert conn.execute(text('select target,job_id,result_json from mtr_tasks')).one() == ('legacy.invalid',None,{'hubs':[]})


def test_explicit_monitor_group_preserves_child_identity_and_history(database):
    from app.services import monitor_groups as groups
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/94c6a201b732_explicit_monitor_groups.py'
    spec = importlib.util.spec_from_file_location('fixture_group_revision', path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with database.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            # The fixture uses today's Monitor model. Reconstruct only the two
            # historical flag columns before replaying their real migration.
            conn.exec_driver_sql('ALTER TABLE monitors DROP COLUMN visible')
            conn.exec_driver_sql('ALTER TABLE monitors DROP COLUMN enabled')
            revision.upgrade()
            for filename in ('cd20261020_monitor_group_identity.py',
                             'ce20261021_monitor_management.py'):
                followup_path = path.parent / filename
                followup_spec = importlib.util.spec_from_file_location('fixture_' + filename[:-3], followup_path)
                assert followup_spec is not None and followup_spec.loader is not None
                followup = importlib.util.module_from_spec(followup_spec)
                followup_spec.loader.exec_module(followup)
                followup.upgrade()
    with Session(database) as db:
        db.add(Monitor(id=2,name='second',node_id=2,type='tcp',target='fixture.invalid:443'))
        db.add(MtrTask(node_id=1,monitor_id=1,target='history.invalid',trigger='manual',status='done',result_json={'hubs':[]}))
        db.commit()
        group = groups.save_group(db, None, name='Fixed parent', child_ids=[1,2], failure_policy='any', rotation_seconds=0)
        group_id = group['id']
        assert group['child_ids'] == [1,2]
        with pytest.raises(ValueError):
            groups.save_group(db,None,name='No implicit reparent',child_ids=[1,2],failure_policy='any',rotation_seconds=0)
        groups.remove_group(db,group_id)
        assert db.query(Monitor).count() == 2
        assert db.query(MtrTask).one().monitor_id == 1


# Binary availability: unknown/empty is conservative down, never fresh up.
# Keep historical parameter IDs even where the approved expectation changed.
@pytest.mark.parametrize('policy,states,expected',[
    pytest.param('any',['up','down'],'down',id='any-states0-down'),
    pytest.param('any',['up','unknown'],'down',id='any-states1-unknown'),
    pytest.param('all',['up','down'],'up',id='all-states2-up'),
    pytest.param('all',['down','unknown'],'down',id='all-states3-unknown'),
    pytest.param('all',['down','down'],'down',id='all-states4-down'),
    pytest.param('any',[],'down',id='any-states5-unknown'),
])
def test_group_aggregation_does_not_invent_availability(policy,states,expected):
    from app.services.monitor_groups import aggregate_status
    assert aggregate_status(states,policy) == expected
