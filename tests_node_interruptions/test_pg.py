"""Real PostgreSQL acceptance. Only a random-port, identity-marked owned DB."""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.alert import AlertRule, AlertState, AlertEvent, Notification
from app.models.user import User
from app.services import alerts


@pytest.fixture
def engine(monkeypatch):
    raw = os.environ.get('STELLA_INTERRUPTION_TEST_DSN')
    assert raw, 'explicit isolated PG required'
    url = make_url(raw)
    expected_port = int(os.environ['STELLA_INTERRUPTION_TEST_PORT'])
    assert url.host == '127.0.0.1' and url.port == expected_port
    assert expected_port not in (5432, 25436, 24532)
    assert url.username == url.database == 'alerts_v5_owned' and not url.query
    root = create_engine(url, connect_args={'connect_timeout': 2})
    schema = 'interruptions_' + uuid.uuid4().hex
    def guard(conn):
        assert conn.execute(text("select current_database(), current_user, current_setting('stella.test_isolation'), pg_is_in_recovery()" )).one() == ('alerts_v5_owned', 'alerts_v5_owned', 'alerts-v5-owned', False)
    with root.begin() as conn:
        guard(conn)
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    owned = create_engine(url, connect_args={'connect_timeout': 2, 'options': f'-c search_path={schema}'})
    from test_deadlines import TABLES
    with owned.begin() as conn:
        guard(conn)
        for cls in TABLES:
            cls.__table__.create(conn)
    monkeypatch.setattr(alerts, '_push_ws', lambda payload: None)
    monkeypatch.setattr(alerts, '_send_alert_email', lambda payload: pytest.fail('unexpected mail'))
    try:
        yield owned
    finally:
        owned.dispose()
        with root.begin() as conn:
            guard(conn)
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            assert conn.execute(text('select 1 from pg_namespace where nspname=:s'), {'s': schema}).first() is None
        root.dispose()


def seed(engine, count=1):
    with Session(engine) as db:
        ids = []
        for index in range(count):
            node = Node(name=f'owned-{index}', host='invalid.test', platform='linux', token=f'owned-{index}',
                        status='online', installed=True,
                        last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=300))
            db.add(node); db.flush()
            alerts.create_node_interruption_rule(db, node)
            ids.append(node.id)
        db.commit()
        return ids


def test_independent_concurrent_workers_all_nodes_offline_and_lifecycle(engine):
    from app.services.node_deadlines import NodeDeadlineWatcher
    seed(engine, 3)
    a = NodeDeadlineWatcher(engine, interval=0.02)
    b = NodeDeadlineWatcher(engine, interval=0.02)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda w: w.tick(), (a, b)))
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 3
        assert {s.state for s in db.query(AlertState)} == {'firing'}
    a.start(); b.start()
    time.sleep(0.08)
    a.stop(); b.stop()
    assert not a.timer.is_alive() and not b.timer.is_alive()
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 3


def test_concurrent_same_node_evaluations_commit_one_event(engine):
    [node_id] = seed(engine)
    def evaluate(_):
        with Session(engine) as db:
            alerts.evaluate_node_rules(db, node_id=node_id)
            db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(evaluate, range(8)))
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 1


@pytest.mark.parametrize('exceptional_exit', [False, True])
def test_main_lifespan_starts_and_stops_real_deadline_worker(engine, monkeypatch, exceptional_exit):
    # Execute the exact production lifespan AST without importing the whole app
    # (main mounts asset dirs and unrelated integrations). Only backup is stubbed.
    import ast
    import asyncio
    from contextlib import asynccontextmanager
    from pathlib import Path
    from types import SimpleNamespace
    from app.services.node_deadlines import NodeDeadlineWatcher
    from app.services import backup_center
    import app.database
    seed(engine)
    real_worker = NodeDeadlineWatcher(engine, interval=0.01)
    monkeypatch.setattr(NodeDeadlineWatcher, 'from_url', lambda url: real_worker)
    monkeypatch.setattr(app.database, 'engine', engine)
    class Backup:
        def __init__(self, *args, **kw): pass
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr(backup_center, 'BackupCenter', Backup)
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'main.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'backup_lifespan')
    scope = {'asynccontextmanager': asynccontextmanager, 'Path': Path, '__file__': str(root / 'main.py')}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(root / 'main.py'), 'exec'), scope)
    app = SimpleNamespace(state=SimpleNamespace())
    async def exercise():
        async with scope['backup_lifespan'](app):
            assert app.state.node_deadlines is real_worker
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with Session(engine) as db:
                    if db.query(AlertEvent).count() == 1:
                        break
                await asyncio.sleep(0.01)
            else:
                pytest.fail('independent lifecycle worker did not fire')
            if exceptional_exit:
                raise RuntimeError('owned exit failure')
    if exceptional_exit:
        with pytest.raises(RuntimeError, match='owned exit failure'): asyncio.run(exercise())
    else:
        asyncio.run(exercise())
    assert real_worker.timer is not None and not real_worker.timer.is_alive()


def test_read_only_database_is_a_background_write_fence(engine):
    from app.services.node_deadlines import NodeDeadlineWatcher
    seed(engine)
    with engine.connect() as c:
        schema = c.scalar(text('SELECT current_schema()'))
    readonly = create_engine(engine.url, connect_args={'options': f'-c search_path={schema} -c default_transaction_read_only=on'})
    try:
        assert NodeDeadlineWatcher(readonly).tick() == 0
        with Session(engine) as db:
            assert db.query(AlertEvent).count() == 0
    finally:
        readonly.dispose()


def test_bounded_keyset_batches_eventually_cover_all_nodes(engine):
    from app.services.node_deadlines import NodeDeadlineWatcher
    seed(engine, 5)
    worker = NodeDeadlineWatcher(engine, batch_size=2)
    assert worker.tick() == 2
    assert worker.tick() == 2
    assert worker.tick() == 1
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == 5


def test_background_ha_admission_fails_closed_before_db_writes(engine, monkeypatch):
    import httpx
    from app.services.node_deadlines import NodeDeadlineWatcher
    seed(engine)
    calls = []
    class Client:
        def __init__(self, **kw):
            assert kw == {'trust_env': False, 'timeout': 1.0}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url):
            calls.append(url)
            return httpx.Response(503)
    monkeypatch.setenv('STELLA_HA_MODE', 'primary-only')
    monkeypatch.setenv('STELLA_PATRONI_URL', 'http://127.0.0.1:1')
    monkeypatch.setattr(httpx, 'Client', Client)
    assert NodeDeadlineWatcher(engine).tick() == 0
    assert calls == ['http://127.0.0.1:1/primary']
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == 0


def wait_for_lock(engine, pid):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with engine.connect() as c:
            waiting = c.scalar(text("select wait_event_type = 'Lock' from pg_stat_activity where pid=:pid"), {'pid': pid})
        if waiting:
            return
        time.sleep(0.01)
    pytest.fail('owned competing transaction did not reach its Node lock')


def test_waiting_evaluator_refreshes_old_snapshot_after_heartbeat_commit(engine):
    import threading
    [node_id] = seed(engine)
    entered = threading.Event(); info = {}
    with Session(engine) as heartbeat:
        node = heartbeat.query(Node).filter_by(id=node_id).with_for_update().one()
        def delayed():
            with Session(engine) as db:
                old = db.get(Node, node_id)
                assert old.last_seen_at < datetime.now(timezone.utc) - timedelta(seconds=200)
                info['pid'] = db.scalar(text('select pg_backend_pid()'))
                entered.set()
                alerts.evaluate_node_rules(db, node_id=node_id)
                db.commit()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(delayed)
            assert entered.wait(2)
            wait_for_lock(engine, info['pid'])
            node.last_seen_at = datetime.now(timezone.utc); heartbeat.commit()
            future.result(timeout=3)
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == 0


def test_report_waiting_for_firing_tick_recovers_once_without_deadlock(engine):
    import threading
    from app.services.node import handle_report
    from app.schemas.monitor import AgentReport
    [node_id] = seed(engine)
    entered = threading.Event(); info = {}
    with Session(engine) as tick:
        alerts.evaluate_node_rules(tick, node_id=node_id)
        def report():
            with Session(engine) as db:
                info['pid'] = db.scalar(text('select pg_backend_pid()'))
                entered.set()
                handle_report(db, 'owned-0', AgentReport())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(report)
            assert entered.wait(2)
            wait_for_lock(engine, info['pid'])
            tick.commit()
            future.result(timeout=3)
    with Session(engine) as db:
        transitions = db.query(AlertEvent).order_by(AlertEvent.id).all()
        assert [e.event for e in transitions] == ['fired', 'resolved']
        assert transitions[1].ts > transitions[0].ts
        assert db.query(Notification).count() == 2
        assert db.query(AlertState).one().state == 'ok'


def test_same_node_creation_concurrency_respects_existing_rule(engine):
    [node_id] = seed(engine)
    with Session(engine) as db:
        rule = db.query(AlertRule).one(); rule.email = True; rule.enabled = False; db.commit()
    def hook(_):
        with Session(engine) as db:
            node = db.get(Node, node_id)
            rule = alerts.create_node_interruption_rule(db, node)
            result = rule.id
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(hook, range(8)))) == 1
    with Session(engine) as db:
        rule = db.query(AlertRule).one()
        assert rule.email is True and rule.enabled is False


def test_report_second_transaction_relocks_node_before_metric_rules(engine, monkeypatch):
    from sqlalchemy import event
    from app.repositories import node as repo
    from app.schemas.monitor import AgentReport
    from app.services.node import handle_report
    from app.services import alert_metrics
    [node_id] = seed(engine)
    with Session(engine) as db:
        alert_metrics.save(db, {'node_id': node_id, 'condition': {'metric': 'cpu', 'threshold': '50'}})
        db.commit()
    queries = []
    original = repo.heartbeat
    def heartbeat(*args, **kwargs):
        result = original(*args, **kwargs)
        queries.clear()  # examine the distinct report-sample transaction
        return result
    monkeypatch.setattr(repo, 'heartbeat', heartbeat)
    def before(conn, cursor, sql, params, context, many):
        if 'FOR UPDATE' in sql: queries.append(sql)
    event.listen(engine, 'before_cursor_execute', before)
    try:
        with Session(engine) as db:
            handle_report(db, 'owned-0', AgentReport(sys_metrics=[{'ts': datetime.now(timezone.utc), 'cpu_pct': 90}]))
    finally:
        event.remove(engine, 'before_cursor_execute', before)
    node_lock = next(i for i, sql in enumerate(queries) if 'FROM nodes' in sql)
    rule_lock = next(i for i, sql in enumerate(queries) if 'FROM alert_rules' in sql)
    assert node_lock < rule_lock


def test_creation_unique_race_keeps_user_rule_and_outer_transaction(engine):
    from sqlalchemy import event
    with Session(engine) as db:
        node = Node(name='owned', host='invalid.test', platform='linux')
        db.add(node); db.commit(); node_id = node.id
    injected = []
    def before(conn, cursor, sql, params, context, many):
        if sql.startswith('INSERT INTO alert_rules') and not injected:
            injected.append(True)
            with Session(engine) as manual:
                alerts.create_rule(manual, 'node_offline', str(node_id), email=True, label='manual winner')
                manual.commit()
    event.listen(engine, 'before_cursor_execute', before)
    try:
        with Session(engine) as db:
            node = db.get(Node, node_id)
            rule = alerts.create_node_interruption_rule(db, node)
            node.name = 'outer transaction survives'
            db.commit()
            assert rule.label == 'manual winner' and rule.email is True
    finally:
        event.remove(engine, 'before_cursor_execute', before)
    with Session(engine) as db:
        assert db.query(AlertRule).count() == db.query(AlertState).count() == 1
        assert db.get(Node, node_id).name == 'outer transaction survives'


def _process_tick(url, schema, ready, go):
    from app.services.node_deadlines import NodeDeadlineWatcher
    own = create_engine(url, connect_args={'connect_timeout': 2, 'options': f'-c search_path={schema}'})
    try:
        with own.connect() as conn:
            assert conn.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one() == ('alerts_v5_owned', 'alerts_v5_owned', 'alerts-v5-owned')
        ready.put(os.getpid())
        assert go.wait(3)
        NodeDeadlineWatcher(own).tick()
    finally:
        own.dispose()


def test_independent_process_workers_do_not_duplicate_incidents(engine):
    import multiprocessing
    seed(engine, 3)
    with engine.connect() as conn:
        schema = conn.scalar(text('SELECT current_schema()'))
    context = multiprocessing.get_context('fork')
    ready = context.Queue(); go = context.Event()
    workers = [context.Process(target=_process_tick, args=(engine.url, schema, ready, go)) for _ in range(2)]
    try:
        for worker in workers: worker.start()
        assert len({ready.get(timeout=3), ready.get(timeout=3)}) == 2
        go.set()
        for worker in workers:
            worker.join(5)
            assert worker.exitcode == 0
    finally:
        go.set()
        for worker in workers:
            if worker.is_alive(): worker.terminate(); worker.join(2)
        ready.close(); ready.join_thread()
    with Session(engine) as db:
        assert db.query(AlertEvent).count() == db.query(Notification).count() == 3


def test_real_http_create_report_auth_old_sample_and_incident_readback(engine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.routers.auth import current_user, admin_user
    from app.routers.monitor import node_router, agent_router
    from app.routers.alerts import router
    from app.services.node_deadlines import NodeDeadlineWatcher
    app = FastAPI()
    for routes in (node_router, agent_router, router): app.include_router(routes)
    # User/admin sessions are a harness boundary; agent auth is REAL.
    app.dependency_overrides[current_user] = lambda: object()
    app.dependency_overrides[admin_user] = lambda: object()
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            response = client.post('/nodes/', json={'name': 'http-owned', 'platform': 'linux', 'host': 'invalid.test'})
            assert response.status_code == 201, response.text
            assert 'token' not in response.json()
            node_id = response.json()['id']
            node = db.get(Node, node_id); token = node.token
            assert node.last_seen_at is None
            rule = client.get('/alerts/rules').json()[0]
            assert rule['email'] is False and rule['enabled'] is True
            assert client.post('/agent/report', json={}).status_code == 401
            assert client.post('/agent/report', headers={'Authorization': 'Bearer wrong-owned-token'}, json={}).status_code == 401
            assert client.post('/agent/report', headers={'Authorization': f'Bearer {token}'}, json={}).status_code == 200
            assert db.query(AlertEvent).count() == 0
            node.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=300); db.commit()
            NodeDeadlineWatcher(engine).tick()
            db.expire_all()
            assert client.post('/agent/report', headers={'Authorization': 'Bearer wrong-owned-token'}, json={}).status_code == 401
            assert db.query(AlertState).one().state == 'firing'
            old_sample = {'sys_metrics': [{'ts': '2000-01-01T00:00:00Z', 'cpu_pct': 0}]}
            assert client.post('/agent/report', headers={'Authorization': f'Bearer {token}'}, json=old_sample).status_code == 200
            db.expire_all()
            node = db.get(Node, node_id)
            assert node.last_seen_at > datetime.now(timezone.utc) - timedelta(seconds=5)
            assert db.query(AlertState).one().state == 'ok'
            transitions = db.query(AlertEvent).order_by(AlertEvent.id).all()
            assert [e.event for e in transitions] == ['fired', 'resolved']
            history = client.get('/alerts/incidents').json()['items']
            assert len(history) == 1 and history[0]['status'] == 'resolved'
            assert history[0]['duration_seconds'] >= 180
            notes = client.get('/notifications').json()
            assert len(notes) == 2
