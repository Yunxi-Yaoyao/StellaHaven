"""Real-PG boundary proofs; only run via run_notes_boundary_pg.py.

The launcher owns the container; each case owns a random schema. All DDL is
guarded on the same connection. Production config/main imports remain blocked
by the reused standalone fixture; only the database dependency is redirected.
"""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries import (
    tagged, preview, execute,
    test_untag_failure_rolls_back_before_retry,
    test_tag_precheck_then_purge_is_controlled,
    test_unlinked_tag_is_not_deleted,
    test_add_failure_after_insert_rolls_back_and_success_commits_once,
    test_preview_complete_trash_descendants_readonly,
    test_preview_openapi_owner_and_origin_contract,
    test_scope_drift_is_zero_write,
    test_empty_replay_after_lost_ack_never_deletes_new_arrivals,
    test_scope_token_is_bound_and_expires,
    test_matching_scope_success_and_non_cascade_promotion,
    test_preview_missing_foreign_and_invalid_inputs_never_disclose,
    test_empty_preview_cannot_authorize_later_trash,
    test_preview_database_budget_failure_is_controlled_incomplete,
)


@pytest.fixture
def notes(env):
    path = os.environ.get('NOTES_BOUNDARY_PG_MANIFEST')
    if not path:
        pytest.skip('Requires self-provisioning disposable PG launcher')
    assert not any(key.startswith('PG') for key in os.environ), 'Ambient libpq overrides forbidden'
    path = Path(path).resolve()
    assert path.is_relative_to('/root/.hermes/cache/scratch') and path.stat().st_mode & 0o077 == 0
    cfg = json.loads(path.read_text())
    nonce = cfg['nonce']
    assert len(nonce) == 32 and all(c in '0123456789abcdef' for c in nonce)
    assert cfg['host'] == '127.0.0.1' and cfg['database'] == 'notes_boundary_'+nonce and cfg['role'] == 'notes_role_'+nonce
    meta = json.loads(subprocess.run(['docker', 'inspect', cfg['cid']], check=True, text=True, capture_output=True).stdout)[0]
    assert meta['Id'] == cfg['cid'] and meta['Config']['Labels']['stella.notes-boundary'] == nonce
    assert meta['NetworkSettings']['Ports']['5432/tcp'] == [{'HostIp': '127.0.0.1', 'HostPort': str(cfg['port'])}]
    url = URL.create('postgresql+psycopg2', username=cfg['role'], password=cfg['password'],
                     host=cfg['host'], port=cfg['port'], database=cfg['database'])
    assert not url.query and (url.host, url.port, url.database, url.username) == ('127.0.0.1', cfg['port'], cfg['database'], cfg['role'])
    schema = 'notes_case_' + uuid4().hex
    engine = create_engine(url, pool_size=6, max_overflow=0, connect_args={'options': f'-c search_path={schema} -c statement_timeout=12000 -c lock_timeout=10000'})
    @event.listens_for(engine, 'checkout')
    def identity(connection, record, proxy):
        assert connection.get_transaction_status() == 0
        with connection.cursor() as cursor:
            cursor.execute('select current_database(), current_user')
            assert cursor.fetchone() == (cfg['database'], cfg['role'])
        connection.rollback()
    def guard(connection):
        assert connection.exec_driver_sql('select current_database(), current_user').one() == (cfg['database'], cfg['role'])
    from app.models import Tag, DocTag, DocumentLink, DocumentVersion, Attachment
    from app.models.blob import BlobObject, BlobChunk
    from app.database import get_db
    classes = [env.models.User, env.models.AuthSession, env.models.AppConfig, env.models.Workspace, env.models.Document,
               Tag, DocTag, DocumentLink, DocumentVersion, Attachment, BlobObject, BlobChunk]
    try:
        with engine.begin() as connection:
            guard(connection)
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            env.models.Base.metadata.create_all(connection, tables=[cls.__table__ for cls in classes])
        # Copy only synthetic standalone seed rows, never a production database.
        with env.engine.connect() as source, engine.begin() as dest:
            guard(dest)
            for cls in classes[:5]:
                values = [dict(row) for row in source.execute(select(cls.__table__)).mappings()]
                if values:
                    dest.execute(cls.__table__.insert(), values)
        def isolated_db():
            with Session(engine) as db:
                yield db
        env.client.app.dependency_overrides[get_db] = isolated_db
        env.engine = engine
        yield env
    finally:
        with engine.begin() as connection:
            guard(connection)
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            assert connection.execute(text('select count(*) from pg_namespace where nspname=:name'), {'name': schema}).scalar() == 0
        engine.dispose()
        print('PG_SCHEMA_CLEAN', schema)


def wait_for_lock(engine, waiter, blocker):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            row = conn.execute(text('select wait_event_type, query, pg_blocking_pids(pid) from pg_stat_activity where pid=:pid'), {'pid': waiter}).first()
        if row and row[0] == 'Lock' and blocker in row[2]:
            assert 'pg_advisory_xact_lock' in row[1]
            print('PG_LOCK_PROOF', json.dumps({'waiter': waiter, 'blocker': blocker, 'event': row[0], 'query': row[1], 'blocking_pids': row[2]}))
            return
        time.sleep(.02)
    raise AssertionError('No real PostgreSQL graph-lock wait observed')


@pytest.mark.parametrize('holder_action,waiter_action', [('purge', 'add'), ('remove', 'add_other'), ('add', 'purge'), ('remove', 'purge')])
def test_graph_doc_tag_lock_order_and_post_wait_recheck(notes, monkeypatch, holder_action, waiter_action):
    from app.services import doc_tag, document
    from app.schemas.doc_tag import DocTagCreate
    from app.models import Tag, DocTag
    tid = tagged(notes, linked=holder_action != 'add')
    other = uuid4()
    with Session(notes.engine) as db:
        db.add(notes.models.Document(id=other, workspace_id=notes.wid, title='other', file_path='/other', content_hash='h')); db.commit()
    held, release, started = threading.Event(), threading.Event(), threading.Event()
    pids = {}
    original_commit = Session.commit
    def gated_commit(db):
        if db.info.get('holder'):
            held.set()
            assert release.wait(8), 'gate timed out'
        return original_commit(db)
    monkeypatch.setattr(Session, 'commit', gated_commit)
    def run(action, holder=False):
        with Session(notes.engine) as db:
            db.info['holder'] = holder
            pids['holder' if holder else 'waiter'] = db.execute(text('select pg_backend_pid()')).scalar()
            if not holder:
                # Stale route precheck populates the identity map before lock wait.
                assert db.get(notes.models.Document, notes.did) is not None
                assert db.get(Tag, tid) is not None
                started.set()
            try:
                if action in ('add', 'add_other'):
                    pair = doc_tag.add_tag(db, DocTagCreate(doc_id=other if action == 'add_other' else notes.did, tag_id=tid), user_id=notes.uid)
                    return str(pair.tag_id)
                if action == 'remove':
                    doc_tag.remove_tag(db, notes.did, tid, user_id=notes.uid)
                else:
                    document.permanently_delete_document(db, notes.did, user_id=notes.uid)
                return 'ok'
            except HTTPException as exc:
                assert not db.in_transaction(), 'controlled error must rollback'
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, holder_action, True)
        try:
            assert held.wait(5)
            second = pool.submit(run, waiter_action)
            assert started.wait(5)
            wait_for_lock(notes.engine, pids['waiter'], pids['holder'])
        finally:
            release.set()
        assert first.result(timeout=5) in ('ok', str(tid))
        outcome = second.result(timeout=5)
        assert outcome == (404 if waiter_action in ('add', 'add_other') else 'ok')
    with Session(notes.engine) as db:
        assert db.get(Tag, tid) is None
        assert db.query(DocTag).count() == 0
        assert db.get(notes.models.Document, other) is not None
        if 'purge' in (holder_action, waiter_action):
            assert db.get(notes.models.Document, notes.did) is None


def test_scope_recomputed_after_real_lock_wait(notes):
    from app.services import document
    from app.services.notes_lifecycle import lock_workspace
    from app.schemas.document import DocumentCreate
    plan = preview(notes)
    child = uuid4()
    started = threading.Event()
    pid = {}
    def confirmed_delete():
        with Session(notes.engine) as db:
            pid['waiter'] = db.execute(text('select pg_backend_pid()')).scalar()
            started.set()
            try:
                document.permanently_delete_document(db, notes.did, scope_token=plan['scope_token'], user_id=notes.uid)
            except HTTPException as exc:
                assert exc.status_code == 409 and exc.detail['code'] == 'delete_scope_changed'
                assert not db.in_transaction()
                return 'changed'
            return 'unsafe success'
    with ThreadPoolExecutor(max_workers=1) as pool, Session(notes.engine) as holder:
        lock_workspace(holder, notes.wid)
        blocker = holder.execute(text('select pg_backend_pid()')).scalar()
        holder.add(notes.models.Document(id=child, workspace_id=notes.wid, parent_id=notes.did,
            title='concurrent child', file_path='/concurrent', content_hash='h')); holder.flush()
        future = pool.submit(confirmed_delete)
        try:
            assert started.wait(5)
            wait_for_lock(notes.engine, pid['waiter'], blocker)
        finally:
            holder.commit()
        assert future.result(timeout=5) == 'changed'
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did) is not None
        assert db.get(notes.models.Document, child).parent_id == notes.did


def test_preview_real_lock_budget_rolls_back_and_pool_settings_restore(notes):
    from app.services.notes_lifecycle import lock_graph
    with Session(notes.engine) as holder:
        lock_graph(holder)
        start = time.monotonic()
        r = notes.client.post('/documents/delete-preview', json={
            'workspace_id': str(notes.wid), 'doc_id': str(notes.did), 'mode': 'permanent'})
        elapsed = time.monotonic() - start
        assert r.status_code == 409, r.text
        assert r.json()['detail']['code'] == 'document_tree_check_incomplete'
        assert 1 <= elapsed < 5
        holder.rollback()
    # Every pooled connection must retain fixture defaults, not preview budgets.
    connections = [notes.engine.connect() for _ in range(6)]
    try:
        for conn in connections:
            assert conn.exec_driver_sql('SHOW lock_timeout').scalar() == '10s'
            assert conn.exec_driver_sql('SHOW statement_timeout').scalar() == '12s'
    finally:
        for conn in connections:
            conn.close()
    assert preview(notes)['target_ids'] == [str(notes.did)]


@pytest.mark.parametrize('state', ['deleted', 'foreign_workspace', 'foreign_tag'])
def test_tag_rechecks_active_and_owner_after_wait(notes, state):
    from datetime import datetime
    from app.services.notes_lifecycle import lock_graph
    from app.services.doc_tag import add_tag
    from app.schemas.doc_tag import DocTagCreate
    from app.models import Tag, DocTag
    tid = tagged(notes, linked=False)
    foreign = uuid4()
    with Session(notes.engine) as db:
        db.add(notes.models.User(id=foreign, username='foreign', display_name='foreign')); db.commit()
    ready = threading.Event()
    pids = {}
    def waiter():
        with Session(notes.engine, expire_on_commit=False) as db:
            stale = db.get(notes.models.Document, notes.did)
            assert stale.deleted_at is None
            assert db.get(Tag, tid).user_id == notes.uid
            pids['waiter'] = db.execute(text('select pg_backend_pid()')).scalar()
            ready.set()
            with pytest.raises(HTTPException) as error:
                add_tag(db, DocTagCreate(doc_id=notes.did, tag_id=tid), user_id=notes.uid)
            assert error.value.status_code == 404
            assert not db.in_transaction()
    with ThreadPoolExecutor(max_workers=1) as pool, Session(notes.engine) as holder:
        lock_graph(holder)
        blocker = holder.execute(text('select pg_backend_pid()')).scalar()
        if state == 'deleted':
            holder.get(notes.models.Document, notes.did).deleted_at = datetime.now()
        elif state == 'foreign_workspace':
            holder.get(notes.models.Workspace, notes.wid).user_id = foreign
        else:
            holder.get(Tag, tid).user_id = foreign
        holder.flush()
        future = pool.submit(waiter)
        try:
            assert ready.wait(5)
            wait_for_lock(notes.engine, pids['waiter'], blocker)
        finally:
            holder.commit()
        future.result(timeout=5)
    with Session(notes.engine) as db:
        assert db.query(DocTag).count() == 0
        assert db.get(Tag, tid) is not None


def test_eight_concurrent_tag_add_retries_have_one_relationship(notes):
    from app.services.doc_tag import add_tag
    from app.schemas.doc_tag import DocTagCreate
    from app.models import DocTag
    tid = tagged(notes, linked=False)
    gate = threading.Barrier(8)
    def run():
        gate.wait(timeout=5)
        with Session(notes.engine) as db:
            row = add_tag(db, DocTagCreate(doc_id=notes.did, tag_id=tid), user_id=notes.uid)
            assert not db.in_transaction()
            return row.doc_id, row.tag_id
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: run(), range(8)))
    assert results == [(notes.did, tid)] * 8
    with Session(notes.engine) as db:
        assert db.query(DocTag).count() == 1
