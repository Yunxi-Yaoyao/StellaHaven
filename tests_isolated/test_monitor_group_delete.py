"""Explicit whole-group deletion; real router, owned DB, no live state."""
from datetime import datetime, timezone
import os
import json
import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import Session
from test_node_monitor_policy import db as sqlite_db, node
from test_entry_monitor_groups import tables
from test_monitor_basics_v7 import client_for
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember, MonitorCheck
from app.models.task import MtrTask
from app.repositories.config import get_monitors_version


@pytest.fixture
def db(sqlite_db):
    url = os.environ.get('STELLA_GROUP_DELETE_PG')
    if not url:
        yield sqlite_db
        return
    from sqlalchemy.engine import make_url
    from app.models.config import AppConfig
    from app.models.node import Node
    from app.models.alert import AlertRule, AlertState
    from uuid import uuid4
    parsed = make_url(url)
    owned_port = int(os.environ['STELLA_GROUP_DELETE_PG_OWNED_PORT'])
    assert parsed.host == '127.0.0.1' and parsed.port == owned_port and owned_port not in (25436,24532,5432) and parsed.database == 'monitor_delete'
    schema = 'owned_delete_' + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    for table in (Node.__table__, Monitor.__table__, MonitorGroup.__table__, MonitorGroupMember.__table__, AppConfig.__table__, AlertRule.__table__, AlertState.__table__):
        table.create(scoped)
    try:
        with Session(scoped, autoflush=False) as session:
            yield session
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()


def seed(db, count=2):
    MtrTask.__table__.create(db.get_bind(), checkfirst=True)
    n = node(db)
    g = MonitorGroup(name='明确删除组'); other = MonitorGroup(name='保留组')
    db.add_all([g, other]); db.flush()
    children = [Monitor(name=f'成员 {i}', node_id=n.id, type='ping', target='owned.example') for i in range(count+1)]
    db.add_all(children); db.flush()
    for i, m in enumerate(children):
        db.add(MonitorGroupMember(group_id=g.id if i<count else other.id, monitor_id=m.id, position=i))
        db.add(MonitorCheck(id=100+i, monitor_id=m.id, ts=datetime.now(timezone.utc), success=True))
    task = MtrTask(node_id=n.id, monitor_id=children[0].id, target='owned.example', protocol='icmp', status='done')
    db.add(task); db.commit()
    return g.id, [m.id for m in children[:count]], other.id, children[-1].id, task.id


def test_atomic_group_delete_preserves_unrelated_and_mtr(db):
    gid, ids, other, solo, tid = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    c = client_for(db); version = get_monitors_version(db)
    r = c.post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids': ids, 'expected_stable_uuid': confirmed_uuid})
    assert r.status_code == 204, r.text
    db.expire_all()
    assert db.get(MonitorGroup, gid) is None
    assert all(db.get(Monitor, mid) is None for mid in ids)
    assert db.query(MonitorCheck).filter(MonitorCheck.monitor_id.in_(ids)).count() == 0
    assert db.query(MonitorGroupMember).filter_by(group_id=gid).count() == 0
    assert db.get(MonitorGroup, other) is not None and db.get(Monitor, solo) is not None
    assert db.query(MonitorCheck).filter_by(monitor_id=solo).count() == 1
    assert db.get(MtrTask, tid).monitor_id is None
    assert get_monitors_version(db) == version+1
    state = c.get(f'/monitors/groups/{gid}/deletion-state', params=[('expected_stable_uuid', confirmed_uuid)]+[('expected_child_ids', mid) for mid in ids])
    assert state.status_code == 200, state.text
    assert state.json() == {'stable_uuid': None, 'identity_matches': False, 'group_exists': False, 'name': None, 'children': [], 'protected': False, 'remaining_child_ids': []}


@pytest.mark.parametrize('count', [0, 1])
def test_empty_and_last_member_group_really_deleted(db, count):
    gid, ids, *_ = seed(db, count)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    c = client_for(db)
    preview = c.get(f'/monitors/groups/{gid}/deletion-state').json()
    assert preview['group_exists'] and not preview['protected']
    assert preview['stable_uuid'] == confirmed_uuid and preview['identity_matches'] is None
    matched = c.get(f'/monitors/groups/{gid}/deletion-state', params={'expected_stable_uuid': confirmed_uuid}).json()
    assert matched['identity_matches'] is True and matched['stable_uuid'] == confirmed_uuid
    assert [m['id'] for m in preview['children']] == ids
    assert c.post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids': ids, 'expected_stable_uuid': confirmed_uuid}).status_code == 204
    db.expire_all()
    assert db.get(MonitorGroup, gid) is None


@pytest.mark.parametrize('scope', ['missing', 'extra', 'same_count_replaced'])
def test_confirmation_must_match_exact_members_with_no_writes(db, scope):
    gid, ids, _, solo, _ = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    c = client_for(db)
    expected = ids[:1] if scope=='missing' else ids+[solo] if scope=='extra' else [ids[0], solo]
    statements = []
    def record(conn, cursor, stmt, *args): statements.append(stmt.lstrip().upper())
    event.listen(db.get_bind(), 'before_cursor_execute', record)
    try:
        response = c.post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids': expected, 'expected_stable_uuid': confirmed_uuid})
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record)
    assert response.status_code == 409, response.text
    assert not any(s.startswith(('UPDATE', 'DELETE', 'INSERT')) for s in statements)
    assert db.get(MonitorGroup, gid) is not None
    assert db.query(MonitorCheck).count() == 3


@pytest.mark.parametrize('body', [{}, {'expected_child_ids':[True]}, {'expected_child_ids':['1']}, {'expected_child_ids':[1,1]}, {'expected_child_ids':[-1]}, {'expected_child_ids':list(range(1,14))}, {'expected_child_ids':[], 'dissolve':True}])
def test_invalid_scope_rejected_before_mutation(db, body):
    gid, ids, *_ = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    assert client_for(db).post(f'/monitors/groups/{gid}/delete', json=body | {'expected_stable_uuid': confirmed_uuid}).status_code == 422
    assert db.get(MonitorGroup, gid) is not None


@pytest.mark.parametrize('protected', ['system_group', 'entry_icmp', 'archived_entry_icmp'])
def test_protected_group_or_member_rejects_delete(db, protected):
    from app.models.config import AppConfig
    from app.services.entry_monitor_groups import KEY
    from app.services.entry_monitoring import LEDGER
    gid, ids, *_ = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    group = db.get(MonitorGroup, gid)
    if protected == 'system_group':
        row = AppConfig(key=KEY, value=json.dumps({'public':dict(group_id=gid, group_uuid=group.stable_uuid, purpose='node_to_center', lifecycle=2)}))
    else:
        row = AppConfig(key=LEDGER, value=json.dumps({'owned':dict(monitor_id=ids[0], purpose='management_entry_icmp', archived=protected.startswith('archived'))}))
    db.add(row); db.commit()
    c = client_for(db)
    assert c.get(f'/monitors/groups/{gid}/deletion-state').json()['protected'] is True
    assert c.post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids':ids, 'expected_stable_uuid': confirmed_uuid}).status_code == 400
    assert db.get(MonitorGroup, gid) is not None
    assert db.query(MonitorCheck).count() == 3


def test_version_failure_rolls_back_every_delete_dependency(db, monkeypatch):
    gid, ids, _, _, tid = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    version = get_monitors_version(db)
    def fail(session):
        session.flush()  # inject after SQL deletes, not only ORM admission
        raise RuntimeError('injected commit failure')
    monkeypatch.setattr('app.repositories.config.bump_monitors_version', fail)
    with pytest.raises(RuntimeError, match='injected'):
        client_for(db).post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids':ids, 'expected_stable_uuid': confirmed_uuid})
    db.expire_all()
    assert db.get(MonitorGroup, gid) is not None
    assert all(db.get(Monitor, mid) is not None for mid in ids)
    assert db.query(MonitorGroupMember).filter_by(group_id=gid).count() == 2
    assert db.query(MonitorCheck).count() == 3
    assert db.get(MtrTask, tid).monitor_id == ids[0]
    assert get_monitors_version(db) == version


def test_dissolve_contract_remains_non_destructive(db):
    gid, ids, _, _, tid = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    assert client_for(db).delete(f'/monitors/groups/{gid}').status_code == 204
    db.expire_all()
    assert db.get(MonitorGroup, gid) is None
    assert all(db.get(Monitor, mid) is not None for mid in ids)
    assert db.query(MonitorCheck).count() == 3
    assert db.get(MtrTask, tid).monitor_id == ids[0]


def test_readback_does_not_mistake_dissolve_for_delete_and_is_read_only(db):
    gid, ids, *_ = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    c = client_for(db)
    c.delete(f'/monitors/groups/{gid}')
    statements = []
    def record(conn, cursor, stmt, *args): statements.append(stmt.lstrip().upper())
    event.listen(db.get_bind(), 'before_cursor_execute', record)
    try:
        state = c.get(f'/monitors/groups/{gid}/deletion-state', params=[('expected_stable_uuid', confirmed_uuid)]+[('expected_child_ids', mid) for mid in ids]).json()
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record)
    assert not state['group_exists'] and state['remaining_child_ids'] == ids
    assert not any(s.startswith(('UPDATE', 'DELETE', 'INSERT')) for s in statements)


def test_management_can_list_empty_group_without_changing_overview_default(db):
    gid, _, *_ = seed(db, 0)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    c = client_for(db)
    assert gid not in [g['id'] for g in c.get('/monitors/groups').json()]
    assert gid in [g['id'] for g in c.get('/monitors/groups?include_empty=true').json()]


def test_delete_and_preview_require_authentication(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import monitor_router
    from app.database import get_db
    app = FastAPI(); app.include_router(monitor_router)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    assert c.post('/monitors/groups/1/delete', json={'expected_child_ids':[]}).status_code == 401
    assert c.get('/monitors/groups/1/deletion-state').status_code == 401


@pytest.mark.skipif(not os.environ.get('STELLA_GROUP_DELETE_PG'), reason='owned PG required')
def test_pg_http_delete_waits_for_membership_writer_then_rejects_changed_scope(db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.services.entry_monitor_groups import lock
    gid, ids, _, solo, _ = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    n_id = db.get(Monitor, solo).node_id
    db.rollback()
    attempted = Event()
    def observed(conn, cursor, stmt, *args):
        if 'pg_advisory_xact_lock(1937006960)' in stmt:
            attempted.set()
    with Session(db.get_bind(), autoflush=False) as writer:
        lock(writer)
        extra = Monitor(name='确认后新增', node_id=n_id, type='ping', target='new.example')
        writer.add(extra); writer.flush()
        extra_id = extra.id
        writer.add(MonitorGroupMember(group_id=gid, monitor_id=extra.id, position=2)); writer.flush()
        def deleting():
            with Session(db.get_bind(), autoflush=False) as target:
                return client_for(target).post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids':ids, 'expected_stable_uuid': confirmed_uuid})
        event.listen(db.get_bind(), 'before_cursor_execute', observed)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(deleting)
                assert attempted.wait(5), 'HTTP request never reached lifecycle lock'
                assert not future.done()
                writer.commit()
                response = future.result(timeout=8)
        finally:
            event.remove(db.get_bind(), 'before_cursor_execute', observed)
    assert response.status_code == 409, response.text
    db.expire_all()
    assert db.get(MonitorGroup, gid) is not None
    assert db.get(Monitor, extra_id) is not None
    assert db.query(MonitorGroupMember).filter_by(group_id=gid).count() == 3
    assert db.query(MonitorCheck).count() == 3


@pytest.mark.skipif(not os.environ.get('STELLA_GROUP_DELETE_PG'), reason='owned PG required')
def test_pg_two_http_sessions_delete_once_not_partial(db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    gid, ids, _, _, tid = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    db.rollback(); gate = Barrier(2)
    def deleting(_):
        with Session(db.get_bind(), autoflush=False) as target:
            gate.wait(timeout=5)
            return client_for(target).post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids':ids, 'expected_stable_uuid': confirmed_uuid}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(deleting, range(2)))
    assert sorted(statuses) == [204, 409]
    db.expire_all()
    assert db.get(MonitorGroup, gid) is None
    assert all(db.get(Monitor, mid) is None for mid in ids)
    assert db.get(MtrTask, tid).monitor_id is None


@pytest.mark.skipif(not os.environ.get('STELLA_GROUP_DELETE_PG'), reason='owned PG required')
def test_pg_stale_session_cannot_miss_new_system_ownership(db):
    from app.models.config import AppConfig
    from app.services.entry_monitor_groups import KEY
    gid, ids, *_ = seed(db)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    initial = db.get(AppConfig, KEY)
    if initial is None:
        initial = AppConfig(key=KEY, value='{}'); db.add(initial); db.commit()
    held = db.get(AppConfig, KEY)
    with Session(db.get_bind()) as other:
        row = other.get(AppConfig, KEY)
        row.value = json.dumps({'owner':dict(group_id=gid, group_uuid=other.get(MonitorGroup,gid).stable_uuid, purpose='node_to_center', lifecycle=2)})
        other.commit()
    assert held.value == '{}'
    response = client_for(db).post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids':ids, 'expected_stable_uuid': confirmed_uuid})
    assert response.status_code == 400, response.text
    db.expire_all()
    assert db.get(MonitorGroup, gid) is not None
    assert all(db.get(Monitor, mid) is not None for mid in ids)


@pytest.mark.parametrize('count', [0, 2])
def test_identity_replacement_rejected_zero_writes(db, count):
    from uuid import uuid4
    from sqlalchemy import inspect
    gid, ids, *_ = seed(db, count)
    confirmed_uuid = db.get(MonitorGroup, gid).stable_uuid
    c = client_for(db)
    preview = c.get(f'/monitors/groups/{gid}/deletion-state').json()
    assert preview['stable_uuid'] == confirmed_uuid
    assert preview['identity_matches'] is None
    db.query(MonitorGroupMember).filter_by(group_id=gid).delete(synchronize_session=False)
    db.query(MonitorGroup).filter_by(id=gid).delete(synchronize_session=False)
    db.flush()
    db.add(MonitorGroup(id=gid, stable_uuid=str(uuid4()), name='different identity'))
    db.flush()
    db.add_all([MonitorGroupMember(group_id=gid, monitor_id=mid, position=i) for i, mid in enumerate(ids)])
    db.commit(); db.expire_all()
    def snapshot():
        schema = db.get_bind().get_execution_options().get('schema_translate_map', {}).get(None)
        return {name: [tuple(map(str, row)) for row in db.execute(text(f'SELECT * FROM '+(f'"{schema}".' if schema else '')+f'"{name}" ORDER BY 1'))]
                for name in inspect(db.get_bind()).get_table_names(schema=schema)}
    before = snapshot(); version = get_monitors_version(db)
    statements = []
    def record(conn, cursor, stmt, *args): statements.append(stmt.lstrip().upper())
    event.listen(db.get_bind(), 'before_cursor_execute', record)
    try:
        response = c.post(f'/monitors/groups/{gid}/delete', json={'expected_child_ids': ids, 'expected_stable_uuid': confirmed_uuid})
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record)
    assert response.status_code == 409, response.text
    db.expire_all()
    assert snapshot() == before
    state = c.get(f'/monitors/groups/{gid}/deletion-state', params=[('expected_stable_uuid', confirmed_uuid)]+[('expected_child_ids', mid) for mid in ids]).json()
    assert state['group_exists'] and state['identity_matches'] is False
    assert state['stable_uuid'] != confirmed_uuid and state['remaining_child_ids'] == ids
    assert get_monitors_version(db) == version
    assert not any(s.startswith(('UPDATE', 'DELETE', 'INSERT')) for s in statements)
    assert snapshot() == before  # GET-only readback must also leave every table intact.
    if os.environ.get('STELLA_IDENTITY_CASE_OUT'):
        import hashlib
        from pathlib import Path
        digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        target = Path(os.environ['STELLA_IDENTITY_CASE_OUT']); target.mkdir(parents=True, exist_ok=True)
        (target/f'identity-{count}.json').write_text(json.dumps(dict(status=response.status_code,confirmed_uuid=confirmed_uuid,current_uuid=state['stable_uuid'],expected_child_ids=ids,tables=sorted(before),before_hash=digest(before),after_hash=digest(snapshot()),version_before=version,version_after=get_monitors_version(db),statements=statements,readback=state), indent=2))



@pytest.mark.parametrize('value', ['missing', None, '', 'not-a-uuid', 123, True, [], {}, '11111111111141118111111111111111'])
def test_uuid_required_strict_before_writes(db, value):
    gid, ids, *_ = seed(db)
    body = {'expected_child_ids': ids}
    if value != 'missing': body['expected_stable_uuid'] = value
    statements = []
    def record(conn, cursor, stmt, *args): statements.append(stmt.lstrip().upper())
    event.listen(db.get_bind(), 'before_cursor_execute', record)
    try:
        assert client_for(db).post(f'/monitors/groups/{gid}/delete', json=body).status_code == 422
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record)
    assert not any(s.startswith(('UPDATE', 'DELETE', 'INSERT')) for s in statements)
    assert db.get(MonitorGroup, gid) is not None


@pytest.mark.parametrize('remaining_count', [0, 1, 2])
def test_identity_readback_new_group_never_reports_original_present_or_children_deleted(db, remaining_count):
    from uuid import uuid4
    gid, ids, *_ = seed(db)
    confirmed = db.get(MonitorGroup, gid).stable_uuid
    db.query(MonitorGroupMember).filter_by(group_id=gid).delete(synchronize_session=False)
    db.query(MonitorGroup).filter_by(id=gid).delete(synchronize_session=False)
    for mid in ids[remaining_count:]:
        db.query(MtrTask).filter_by(monitor_id=mid).update({'monitor_id':None}, synchronize_session=False)
        db.query(MonitorCheck).filter_by(monitor_id=mid).delete(synchronize_session=False)
        db.query(Monitor).filter_by(id=mid).delete(synchronize_session=False)
    db.add(MonitorGroup(id=gid, name='new group', stable_uuid=str(uuid4())))
    db.commit(); db.expire_all()
    state = client_for(db).get(f'/monitors/groups/{gid}/deletion-state', params=[('expected_stable_uuid', confirmed)]+[('expected_child_ids',mid) for mid in ids]).json()
    assert state['group_exists'] is True and state['identity_matches'] is False
    assert state['remaining_child_ids'] == ids[:remaining_count]
    assert state['stable_uuid'] != confirmed


@pytest.mark.skipif(not os.environ.get('STELLA_GROUP_DELETE_BROWSER'), reason='explicit owned-PG browser required')
def test_real_browser_identity_contract_over_owned_http_pg(db, tmp_path):
    import socket, threading, subprocess, time
    from pathlib import Path
    from uuid import uuid4
    from fastapi import FastAPI
    from app.routers.monitor import monitor_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    from app.models.config import AppConfig
    import uvicorn
    assert os.environ.get('STELLA_GROUP_DELETE_PG'), 'never run browser against SQLite/resident DB'
    seed(db)
    bind = db.get_bind(); db.rollback()
    app = FastAPI(); app.include_router(monitor_router)
    def session():
        with Session(bind, autoflush=False) as own:
            yield own
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[current_user] = lambda: object()
    app.dependency_overrides[admin_user] = lambda: object()
    state = {}
    @app.post('/_fixture/reset')
    def reset(mode: str):
        with Session(bind) as own:
            for model in (MtrTask, MonitorCheck, MonitorGroupMember, Monitor, MonitorGroup, AppConfig):
                own.execute(model.__table__.delete())
            from app.models.node import Node
            nid = own.query(Node.id).first()[0]
            g = MonitorGroup(id=1, name='真实PG确认组', stable_uuid=str(uuid4()))
            own.add(g); own.flush()
            ids = [] if mode == 'empty-replaced' else [7, 8]
            for pos, mid in enumerate(ids):
                own.add(Monitor(id=mid,name=f'确认成员{mid}',node_id=nid,type='ping',target='owned.example'))
                own.flush(); own.add(MonitorGroupMember(group_id=1, monitor_id=mid,position=pos))
                own.add(MonitorCheck(id=100+mid,monitor_id=mid,ts=datetime.now(timezone.utc),success=True))
            own.commit()
            state.clear(); state.update(mode=mode,uuid=g.stable_uuid,ids=ids,version=get_monitors_version(own),node_id=nid)
            return state.copy()
    @app.post('/_fixture/replace')
    def replace():
        with Session(bind) as own:
            own.query(MonitorGroupMember).filter_by(group_id=1).delete(synchronize_session=False)
            own.query(MonitorGroup).filter_by(id=1).delete(synchronize_session=False)
            own.flush()
            replacement = str(uuid4()); state['replacement_uuid'] = replacement
            own.add(MonitorGroup(id=1,name='数字ID复用的新组',stable_uuid=replacement));own.flush()
            # Explicitly restore a confirmed numeric child after atomic commit:
            # even this conservative ambiguity must not produce whole-batch success.
            if state['mode'] == 'lost-ack-partial':
                own.add(Monitor(id=7,name='显式恢复确认ID',node_id=state['node_id'],type='ping',target='owned.example'));own.flush()
            for pos, mid in enumerate(state['ids']):
                if own.get(Monitor,mid):own.add(MonitorGroupMember(group_id=1,monitor_id=mid,position=pos))
            own.commit()
            return {'replacement_uuid':replacement}
    @app.get('/_fixture/state')
    def inspect_state():
        with Session(bind) as own:
            group = own.get(MonitorGroup,1)
            return dict(group_uuid=group.stable_uuid if group else None,replacement_uuid=state.get('replacement_uuid'),ids=[mid for mid in state['ids'] if own.get(Monitor,mid)],version=get_monitors_version(own))
    sock = socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', lifespan='off'))
    thread = threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        assert server.started
        env = {k:v for k,v in os.environ.items() if k not in ('NODE_ENV','PYTHONPATH')}
        env.update(STELLA_IDENTITY_HTTP=f'http://127.0.0.1:{sock.getsockname()[1]}', STELLA_IDENTITY_OUT=os.environ['STELLA_IDENTITY_OUT'],PLAYWRIGHT_BROWSERS_PATH='/root/.cache/ms-playwright')
        root = Path(__file__).resolve().parents[1]
        process = subprocess.run(['/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node',str(root/'frontend/src/modules/servers/monitorGroupIdentity.browser.mjs')],cwd=root/'frontend',env=env,capture_output=True,text=True,timeout=150)
        (Path(os.environ['STELLA_IDENTITY_OUT'])/'execution.log').write_text(process.stdout+process.stderr)
        assert process.returncode == 0, process.stdout+process.stderr
        receipt=json.loads((Path(os.environ['STELLA_IDENTITY_OUT'])/'real-browser.json').read_text())
        assert receipt['passed'] and len(receipt['checks']) == 5
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
        assert not thread.is_alive()
