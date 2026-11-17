"""In-place renewal: real HTTP/auth and owned disposable PostgreSQL only."""
import json
import time
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes, wait_for_lock
from test_web_project_review_pg import project


def renew(notes, project, *, token=None, origin='https://stella.test', **changes):
    root, grant = project
    return notes.client.post('https://stella.test/web-projects/'+str(root)+'/renew',
        headers={'Origin': origin, 'Cookie': 'stella_at='+(token or notes.token)},
        json={'capability': grant['capability'], 'epoch': grant['state']['epoch'], **changes})


def expire(notes, project, seconds=1):
    from app.models.config import AppConfig
    from app.services import web_project_runtime as runtime
    with Session(notes.engine) as db:
        row = db.get(AppConfig, runtime.key(project[1]['capability']))
        value = json.loads(row.value)
        value['expires'] = time.time()-seconds
        row.value = json.dumps(value)
        db.commit()
        return value


def test_renewal_expired_cap_preserves_url_state_and_dynamic_http_resource(notes, project, monkeypatch):
    from starlette.testclient import TestClient
    from app.services import web_projects as projects, web_project_runtime as runtime
    from app.models.config import AppConfig
    import app.database as database
    monkeypatch.setattr(database, 'sessionLocal', lambda: Session(notes.engine), raising=False)
    from app.routers.web_project_host import WebProjectHostMiddleware
    root, grant = project
    url = grant['url']
    with Session(notes.engine) as db:
        baseline = projects.write_state(db, notes.uid, root, 0, 0, str(uuid4()), {'answer':'kept'})
        before = {row.key:row.value for row in db.query(AppConfig).all()}
    old = expire(notes, project)
    with TestClient(WebProjectHostMiddleware(notes.client.app, lambda: Session(notes.engine))) as client:
        assert client.get(url).status_code == 403
        response = renew(notes, project)
        assert response.status_code == 200, response.text
        assert response.json() == {'capability':grant['capability'], 'epoch':0, 'expires_in':900, 'renew_after':840}
        assert client.get(url).status_code == 200
        assert client.get(url.rsplit('/',1)[0]+'/__stella_storage.js').status_code == 200
    with Session(notes.engine) as db:
        assert projects.read_state(db, notes.uid, root) == baseline
        after = {row.key:row.value for row in db.query(AppConfig).all()}
        new = json.loads(after.pop(runtime.key(grant['capability'])))
        before.pop(runtime.key(grant['capability']))
        # HTTP auth may refresh session metadata, never project config/data.
        assert after == before
        assert new.pop('expires') > time.time()
        old.pop('expires')
        assert new == old


@pytest.mark.parametrize('boundary', ['relaunch', 'removed', 'revoke', 'reset', 'sid', 'owner', 'root', 'origin', 'epoch', 'grace', 'session-expired', 'inactive'])
def test_renewal_denies_invalid_identity_and_never_resurrects(notes, project, boundary):
    from app.models.config import AppConfig
    from app.models.user import AuthSession, User
    from app.security import make_access_token
    from app.services import web_projects as projects, web_project_runtime as runtime
    root, grant = project
    options = {}
    target = project
    with Session(notes.engine) as db:
        if boundary == 'relaunch': runtime.launch(db, notes.uid, root, notes.sid, 'https://stella.test')
        elif boundary == 'removed': db.delete(db.get(AppConfig, runtime.key(grant['capability']))); db.commit()
        elif boundary == 'revoke': db.get(AuthSession, notes.sid).revoked = True; db.commit()
        elif boundary == 'inactive': db.get(User, notes.uid).is_active = False; db.commit()
        elif boundary == 'session-expired':
            from datetime import timedelta
            db.get(AuthSession, notes.sid).last_seen = notes.now-timedelta(days=365); db.commit()
        elif boundary == 'reset': projects.reset_state(db, notes.uid, root)
        elif boundary == 'sid':
            sid = uuid4()
            db.add(AuthSession(id=sid,user_id=notes.uid,refresh_hash=str(sid),created_at=notes.now,last_seen=notes.now)); db.commit()
            options['token'] = make_access_token(str(notes.uid),str(sid))
        elif boundary == 'owner': options['token'] = make_access_token(str(uuid4()),str(notes.sid))
        elif boundary == 'root':
            other = projects.create(db,notes.uid,notes.wid,None,uuid4(),b'<p>other</p>','index.html','index.html')['id']
            target = other, grant
        elif boundary == 'origin': options['origin'] = 'https://foreign.test'
        elif boundary == 'epoch': options['epoch'] = 1
    if boundary == 'grace': expire(notes, project, seconds=301)
    with Session(notes.engine) as db:
        before = {row.key:row.value for row in db.query(AppConfig).all()}
    response = renew(notes, target, **options)
    assert response.status_code in (401,403,409), response.text
    with Session(notes.engine) as db:
        assert {row.key:row.value for row in db.query(AppConfig).all()} == before


def test_renewal_grace_retention_cleanup_and_same_sid_relaunch(notes, project):
    from app.models.config import AppConfig
    from app.services import web_projects as projects, web_project_runtime as runtime
    expire(notes, project)
    with Session(notes.engine) as db:
        other = projects.create(db,notes.uid,notes.wid,None,uuid4(),b'<p>other</p>','index.html','index.html')['id']
        runtime.launch(db, notes.uid, other, notes.sid, 'https://stella.test')
        assert db.get(AppConfig, runtime.key(project[1]['capability'])) is not None
    assert renew(notes, project).status_code == 200
    expire(notes, project, seconds=301)
    with Session(notes.engine) as db:
        runtime.launch(db, notes.uid, other, notes.sid, 'https://stella.test')
        assert db.get(AppConfig, runtime.key(project[1]['capability'])) is None
    assert renew(notes, project).status_code == 403


@pytest.mark.parametrize('body', [{'capability':'!'*43,'epoch':0}, {'capability':'a'*43,'epoch':True}, {'capability':'a'*43,'epoch':0,'data':{}}, {'capability':'a'*43,'epoch':9007199254740992}])
def test_renewal_strict_bounded_schema(notes, project, body):
    response = renew(notes, project, **body)
    assert response.status_code == 422, response.text


def test_renewal_body_bounded_before_json_decode_and_duplicate_origin_denied(notes, project):
    url = 'https://stella.test/web-projects/'+str(project[0])+'/renew'
    headers = {'Origin':'https://stella.test','Cookie':'stella_at='+notes.token,'Content-Type':'application/json'}
    response = notes.client.post(url, headers=headers, content=(b'x'*600 for _ in range(2)))
    assert response.status_code == 413, response.text
    response = notes.client.post(url, headers=[*headers.items(),('Origin','https://stella.test')], json={'capability':project[1]['capability'],'epoch':0})
    assert response.status_code == 403, response.text


@pytest.mark.parametrize('change', ['revoke', 'grace', 'relaunch', 'reset'])
def test_renewal_rechecks_after_actual_pg_workspace_wait(notes, project, monkeypatch, change):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import text
    from app.models.config import AppConfig
    from app.models.user import AuthSession
    from app.services import web_projects as projects, web_project_runtime as runtime
    from app.services.notes_lifecycle import lock_workspace
    original = projects.lock_workspace
    waiting = threading.Event()
    pids = {}
    def observed(db, wid, *args, **kwargs):
        pids['waiter'] = db.execute(text('select pg_backend_pid()')).scalar_one()
        waiting.set()
        return original(db, wid, *args, **kwargs)
    monkeypatch.setattr(projects, 'lock_workspace', observed)
    with Session(notes.engine) as blocker:
        lock_workspace(blocker, notes.wid)
        pids['blocker'] = blocker.execute(text('select pg_backend_pid()')).scalar_one()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(renew, notes, project)
            try:
                assert waiting.wait(5)
                wait_for_lock(notes.engine, pids['waiter'], pids['blocker'])
                if change == 'reset': projects.reset_state(blocker,notes.uid,project[0])
                else:
                    with Session(notes.engine) as other:
                        if change == 'revoke': other.get(AuthSession,notes.sid).revoked=True; other.commit()
                        elif change == 'grace':
                            row=other.get(AppConfig,runtime.key(project[1]['capability']))
                            value=json.loads(row.value);value['expires']=time.time()-301;row.value=json.dumps(value);other.commit()
                        else: runtime.launch(other,notes.uid,project[0],notes.sid,'https://stella.test')
            finally: blocker.rollback()
            response=future.result(timeout=8)
        assert response.status_code == (409 if change=='reset' else 403),response.text
    with Session(notes.engine) as db:
        state=projects.read_state(db,notes.uid,project[0])
        assert state['data']=={} and state['revision']==(1 if change=='reset' else 0)


@pytest.mark.parametrize('field,value', [('sid',str(uuid4())), ('owner',str(uuid4())), ('root',str(uuid4())), ('source','https://foreign.test'), ('target','https://foreign.test'), ('epoch',7), ('expires',0)])
def test_renewal_revalidates_grant_after_actual_row_lock_wait(notes, project, monkeypatch, field, value):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import text
    from app.models.config import AppConfig
    from app.services import web_project_runtime as runtime
    # The mutation remains uncommitted while renewal reaches SELECT FOR UPDATE.
    # Inspect PG's lock graph, not a helper-only fake wait.
    with Session(notes.engine) as blocker:
        row=blocker.query(AppConfig).filter_by(key=runtime.key(project[1]['capability'])).with_for_update().one()
        blocking=blocker.execute(text('select pg_backend_pid()')).scalar_one()
        changed=json.loads(row.value);changed[field]=value;row.value=json.dumps(changed);blocker.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(renew,notes,project)
            deadline=time.monotonic()+6;proof=None
            try:
                while time.monotonic()<deadline:
                    with notes.engine.connect() as conn:
                        proof=conn.execute(text("select pid,query,pg_blocking_pids(pid) from pg_stat_activity where :pid=ANY(pg_blocking_pids(pid)) and query like '%FOR UPDATE%'"),{'pid':blocking}).first()
                    if proof:break
                    time.sleep(.02)
                assert proof is not None,'Renewal never waited on real grant row lock'
                print('PG_RENEW_ROW_LOCK_PROOF',json.dumps({'waiter':proof[0],'query':proof[1],'blocking_pids':proof[2],'field':field}))
            finally:blocker.commit()
            response=future.result(timeout=8)
        assert response.status_code in (403,409),response.text
    with Session(notes.engine) as db:
        assert json.loads(db.get(AppConfig,runtime.key(project[1]['capability'])).value)==changed
