"""Regression assertions for F8/F9; real ORM/HTTP on isolated SQLite.

Original independent RED harness is retained outside the tree unchanged.
F8 checks rollback BEFORE a legitimate successful retry. F9 allows the
controlled HTTPException instead of incorrectly turning it into a 500.
"""
from datetime import datetime
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_lifecycle_http import notes


def tagged(notes, *, linked=True):
    from app.models import Tag, DocTag
    tid = uuid4()
    with Session(notes.engine) as db:
        db.add(Tag(id=tid, user_id=notes.uid, name=str(tid))); db.flush()
        if linked:
            db.add(DocTag(doc_id=notes.did, tag_id=tid))
        db.commit()
    from app.routers.doc_tag import router
    notes.client.app.include_router(router)
    return tid


def test_untag_failure_rolls_back_before_retry(notes):
    tid = tagged(notes)
    from app.models import Tag, DocTag
    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith('DELETE FROM tags'):
            raise RuntimeError('injected orphan cleanup failure')
    event.listen(notes.engine, 'before_cursor_execute', fail)
    try:
        with TestClient(notes.client.app, raise_server_exceptions=False) as client:
            client.cookies.set('stella_at', notes.token)
            response = client.delete('/doc-tags/', params={'doc_id': str(notes.did), 'tag_id': str(tid)})
        assert response.status_code == 500
    finally:
        event.remove(notes.engine, 'before_cursor_execute', fail)
    with Session(notes.engine) as db:
        assert db.get(DocTag, (notes.did, tid)) is not None, 'failure must roll back relationship removal'
        assert db.get(Tag, tid) is not None
    assert notes.client.delete('/doc-tags/', params={'doc_id': str(notes.did), 'tag_id': str(tid)}).status_code == 204
    with Session(notes.engine) as db:
        assert db.get(DocTag, (notes.did, tid)) is None
        assert db.get(Tag, tid) is None
    # Preserve explicit missing-tag semantics, not an unrelated orphan sweep.
    assert notes.client.delete('/doc-tags/', params={'doc_id': str(notes.did), 'tag_id': str(tid)}).status_code == 404


def test_tag_precheck_then_purge_is_controlled(notes, monkeypatch):
    tid = tagged(notes)
    from app.routers import doc_tag
    from app.services.document import permanently_delete_document
    original = doc_tag.add_tag
    def interleave(db, data, **kwargs):
        db.rollback()
        with Session(notes.engine) as deletion:
            permanently_delete_document(deletion, notes.did)
        return original(db, data, **kwargs)
    monkeypatch.setattr(doc_tag, 'add_tag', interleave)
    with TestClient(notes.client.app, raise_server_exceptions=False) as client:
        client.cookies.set('stella_at', notes.token)
        response = client.post('/doc-tags/', json={'doc_id': str(notes.did), 'tag_id': str(tid)})
    assert response.status_code in (404, 409), response.text


def test_add_failure_after_insert_rolls_back_and_success_commits_once(notes):
    tid = tagged(notes, linked=False)
    from app.models import DocTag, Tag
    def fail(conn, cursor, sql, params, ctx, many):
        if sql.startswith('INSERT INTO doc_tags'):
            raise RuntimeError('synthetic post-insert fault')
    event.listen(notes.engine, 'after_cursor_execute', fail)
    try:
        with TestClient(notes.client.app, raise_server_exceptions=False) as client:
            client.cookies.set('stella_at', notes.token)
            r = client.post('/doc-tags/', json={'doc_id': str(notes.did), 'tag_id': str(tid)})
        assert r.status_code == 500
    finally:
        event.remove(notes.engine, 'after_cursor_execute', fail)
    with Session(notes.engine) as db:
        assert db.get(DocTag, (notes.did, tid)) is None
        assert db.get(Tag, tid) is not None
    from app.services.doc_tag import add_tag, remove_tag
    from app.schemas.doc_tag import DocTagCreate
    with Session(notes.engine) as db:
        commits = []
        event.listen(db, 'after_commit', lambda *a: commits.append(True))
        add_tag(db, DocTagCreate(doc_id=notes.did, tag_id=tid), user_id=notes.uid)
        assert len(commits) == 1 and not db.in_transaction()
        remove_tag(db, notes.did, tid, user_id=notes.uid)
        assert len(commits) == 2 and not db.in_transaction()


def test_unlinked_tag_is_not_deleted(notes):
    tid = tagged(notes, linked=False)
    for _ in range(2):
        assert notes.client.delete('/doc-tags/', params={'doc_id': str(notes.did), 'tag_id': str(tid)}).status_code == 204
    from app.models import Tag
    with Session(notes.engine) as db:
        assert db.get(Tag, tid) is not None


def preview(notes, mode='permanent', cascade=True, doc_id='default'):
    body = {'workspace_id': str(notes.wid), 'mode': mode, 'cascade': cascade}
    if mode != 'empty-trash':
        body['doc_id'] = str(notes.did if doc_id == 'default' else doc_id)
    response = notes.client.post('/documents/delete-preview', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_openapi_owner_and_origin_contract(notes, monkeypatch):
    from fastapi import FastAPI
    from app.openapi_contract import install_openapi_contract, validate_contract
    from app.services.request_security import MainSiteSecurityMiddleware
    app = FastAPI()
    app.include_router(notes.routes.router)
    install_openapi_contract(app)
    schema = validate_contract(app)
    operation = schema['paths']['/documents/delete-preview']['post']
    assert operation['x-stella-auth-type'] == 'cookie-access'
    assert operation['x-stella-elevation'] == 'none'
    for path, method in [('/documents/{doc_id}', 'delete'), ('/documents/{doc_id}/permanent', 'delete'), ('/documents/trash/empty', 'post')]:
        assert any(p['name'] == 'scope_token' and p['in'] == 'query' for p in schema['paths'][path][method]['parameters'])
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'http://testserver')
    body = {'workspace_id': str(notes.wid), 'doc_id': str(notes.did), 'mode': 'permanent'}
    with TestClient(MainSiteSecurityMiddleware(notes.client.app)) as client:
        client.cookies.set('stella_at', notes.token)
        assert client.post('/documents/delete-preview', json=body, headers={'Origin': 'https://foreign.invalid'}).status_code == 403
        assert client.post('/documents/delete-preview', json=body, headers={'Origin': 'http://testserver'}).status_code == 200
        client.cookies.clear()
        assert client.post('/documents/delete-preview', json=body).status_code == 401


def test_preview_complete_trash_descendants_readonly(notes, monkeypatch):
    child = uuid4()
    with Session(notes.engine) as db:
        db.add(notes.models.Document(id=child, workspace_id=notes.wid, parent_id=notes.did,
            title='cold trash', file_path='/child', content_hash='h', deleted_at=datetime.now()))
        db.commit()
    writes = []
    def record(conn, cursor, sql, params, ctx, many):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(notes.engine, 'before_cursor_execute', record)
    notified = []
    monkeypatch.setattr(notes.routes, 'notify_list', lambda *a: notified.append(a))
    try:
        data = preview(notes)
        assert set(data['target_ids']) == {str(notes.did), str(child)}
        assert data['descendant_count'] == 1
        single = preview(notes, cascade=False)
        assert single['target_ids'] == [str(notes.did)] and single['descendant_count'] == 1
        assert data['scope_token'] != single['scope_token']
        assert not writes and not notified
    finally:
        event.remove(notes.engine, 'before_cursor_execute', record)


def execute(notes, plan, **overrides):
    params = {'scope_token': plan['scope_token']}
    if plan['mode'] == 'empty-trash':
        params.update(workspace_id=str(notes.wid), **overrides)
        return notes.client.post('/documents/trash/empty', params=params)
    params.update(cascade=str(plan['cascade']).lower(), **overrides)
    suffix = '/permanent' if plan['mode'] == 'permanent' else ''
    return notes.client.delete(f'/documents/{notes.did}{suffix}', params=params)


def add_child(notes, *, deleted=False):
    child = uuid4()
    with Session(notes.engine) as db:
        db.add(notes.models.Document(id=child, workspace_id=notes.wid, parent_id=notes.did,
            title='new child', file_path=str(child), content_hash='h',
            deleted_at=datetime.now() if deleted else None))
        db.commit()
    return child


@pytest.mark.parametrize('mode', ['trash', 'permanent', 'empty-trash'])
def test_scope_drift_is_zero_write(notes, mode):
    if mode == 'empty-trash':
        with Session(notes.engine) as db:
            db.get(notes.models.Document, notes.did).deleted_at = datetime.now(); db.commit()
    plan = preview(notes, mode)
    child = add_child(notes, deleted=mode == 'empty-trash')
    result = execute(notes, plan)
    assert result.status_code == 409, result.text
    assert result.json()['detail']['code'] == 'delete_scope_changed'
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did) is not None
        assert db.get(notes.models.Document, child).parent_id == notes.did
        if mode == 'trash':
            assert db.get(notes.models.Document, notes.did).deleted_at is None


def test_empty_replay_after_lost_ack_never_deletes_new_arrivals(notes, monkeypatch):
    with Session(notes.engine) as db:
        db.get(notes.models.Document, notes.did).deleted_at = datetime.now(); db.commit()
    plan = preview(notes, 'empty-trash')
    original = Session.commit
    def lost_ack(db):
        original(db)
        raise OSError('commit acknowledgement lost')
    with TestClient(notes.client.app, raise_server_exceptions=False) as client:
        client.cookies.set('stella_at', notes.token)
        with monkeypatch.context() as patch:
            patch.setattr(Session, 'commit', lost_ack)
            response = client.post('/documents/trash/empty', params={
                'workspace_id': str(notes.wid), 'scope_token': plan['scope_token']})
    assert response.status_code == 500
    other = uuid4()
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did) is None
        db.add(notes.models.Document(id=other, workspace_id=notes.wid, title='new trash',
            file_path='/new', content_hash='h', deleted_at=datetime.now())); db.commit()
    response = execute(notes, plan)
    assert response.status_code == 409, response.text
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, other) is not None


@pytest.mark.parametrize('change', ['malformed', 'unicode', 'expired', 'cascade', 'mode', 'empty'])
def test_scope_token_is_bound_and_expires(notes, monkeypatch, change):
    from app.services import notes_delete_scope
    plan = preview(notes)
    if change == 'malformed':
        plan['scope_token'] = 'not-a-token'
    elif change == 'unicode':
        plan['scope_token'] = plan['scope_token'][:-1] + '界'
    elif change == 'expired':
        now = notes_delete_scope.time.time()
        monkeypatch.setattr(notes_delete_scope.time, 'time', lambda: now + 601)
    elif change == 'cascade':
        plan['cascade'] = False
    elif change == 'mode':
        plan['mode'] = 'trash'
    else:
        plan['scope_token'] = ''
    response = execute(notes, plan)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'delete_scope_changed'
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did).deleted_at is None


@pytest.mark.parametrize('mode', ['trash', 'permanent', 'empty-trash'])
def test_matching_scope_success_and_non_cascade_promotion(notes, mode):
    child = add_child(notes, deleted=mode == 'empty-trash')
    if mode == 'empty-trash':
        with Session(notes.engine) as db:
            db.get(notes.models.Document, notes.did).deleted_at = datetime.now(); db.commit()
    plan = preview(notes, mode, cascade=mode == 'empty-trash')
    # An awaited save/draft barrier may update body but not deletion topology.
    with Session(notes.engine) as db:
        row = db.get(notes.models.Document, notes.did)
        row.content = 'awaited save'; row.draft_content = 'new draft'; db.commit()
    result = execute(notes, plan)
    assert result.status_code == (200 if mode == 'empty-trash' else 204), result.text
    with Session(notes.engine) as db:
        root, desc = db.get(notes.models.Document, notes.did), db.get(notes.models.Document, child)
        if mode == 'empty-trash':
            assert root is None and desc is None
        else:
            assert desc.parent_id is None
            assert root is None if mode == 'permanent' else root.deleted_at is not None


def test_preview_missing_foreign_and_invalid_inputs_never_disclose(notes, monkeypatch):
    from app.services import notes_lifecycle
    with Session(notes.engine) as db:
        uid, wid, did = uuid4(), uuid4(), uuid4()
        db.add(notes.models.User(id=uid, username='foreign', display_name='foreign')); db.flush()
        db.add(notes.models.Workspace(id=wid, user_id=uid, name='secret workspace')); db.flush()
        db.add(notes.models.Document(id=did, workspace_id=wid, title='secret title', file_path='/secret', content_hash='h')); db.commit()
    for workspace_id, doc_id in [(wid, did), (notes.wid, did), (notes.wid, uuid4()), (uuid4(), notes.did)]:
        r = notes.client.post('/documents/delete-preview', json={'workspace_id': str(workspace_id), 'doc_id': str(doc_id), 'mode': 'permanent'})
        assert r.status_code == 404 and 'secret' not in r.text
    for body in [{'mode': 'trash'}, {'mode': 'empty-trash', 'doc_id': str(notes.did)},
                 {'mode': 'empty-trash', 'cascade': False}, {'mode': 'trash', 'doc_id': str(notes.did), 'cascade': 'false'}]:
        r = notes.client.post('/documents/delete-preview', json={'workspace_id': str(notes.wid), **body})
        assert r.status_code == 422
    monkeypatch.setattr(notes_lifecycle, 'MAX_TREE_DOCUMENTS', 0)
    r = notes.client.post('/documents/delete-preview', json={'workspace_id': str(notes.wid), 'doc_id': str(notes.did), 'mode': 'permanent'})
    assert r.status_code == 409 and r.json()['detail']['code'] == 'document_tree_check_incomplete'


def test_empty_preview_cannot_authorize_later_trash(notes):
    plan = preview(notes, 'empty-trash')
    assert plan['target_ids'] == [] and plan['descendant_count'] == 0
    with Session(notes.engine) as db:
        db.get(notes.models.Document, notes.did).deleted_at = datetime.now(); db.commit()
    assert execute(notes, plan).status_code == 409
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did) is not None


@pytest.mark.parametrize('sqlstate', ['55P03', '57014', '08006'])
def test_preview_database_budget_failure_is_controlled_incomplete(notes, monkeypatch, sqlstate):
    from sqlalchemy.exc import OperationalError
    from app.services import notes_delete_scope
    class BudgetError(Exception):
        pgcode = sqlstate
    def fail(*args):
        raise OperationalError('synthetic preview query', {}, BudgetError('private diagnostic'))
    monkeypatch.setattr(notes_delete_scope, 'owned_tree', fail)
    with TestClient(notes.client.app, raise_server_exceptions=False) as client:
        client.cookies.set('stella_at', notes.token)
        r = client.post('/documents/delete-preview', json={
            'workspace_id': str(notes.wid), 'doc_id': str(notes.did), 'mode': 'permanent'})
    assert r.status_code == 409, r.text
    assert r.json()['detail']['code'] == 'document_tree_check_incomplete'
    assert 'private' not in r.text
