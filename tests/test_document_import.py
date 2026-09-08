"""Markdown import API regressions; use only conftest's isolated PostgreSQL DB."""
from hashlib import sha256
from uuid import uuid4

import pytest


@pytest.fixture
def workspace_id(client):
    r = client.post('/workspaces/', json={'user_id': str(uuid4()), 'name': 'Import tests'})
    assert r.status_code == 201
    return r.json()['id']


def make_doc(client, workspace_id, title, content='', **extra):
    return client.post('/documents/', json={
        'workspace_id': workspace_id, 'title': title, 'content': content,
        'file_path': f'/notes/{uuid4()}.md', 'status': 'published', **extra,
    })


def backlinks(client, doc):
    r = client.get(f"/documents/{doc['id']}/backlinks")
    assert r.status_code == 200
    return {d['id'] for d in r.json()}


def test_create_import_syncs_wikilinks(client, workspace_id):
    target = make_doc(client, workspace_id, 'Target').json()
    content = '正文 [[Target]] [[Target]] [[Missing]] [[Source]]'
    r = make_doc(client, workspace_id, 'Source', content)
    assert r.status_code == 201
    source = r.json()
    assert source['content'] == content
    assert source['content_hash'] == sha256(content.encode()).hexdigest()
    assert backlinks(client, target) == {source['id']}
    assert backlinks(client, source) == set()


def test_finalize_import_resolves_forward_links_without_saving(client, workspace_id):
    source = make_doc(client, workspace_id, 'A', '[[B]]').json()
    unrelated = make_doc(client, workspace_id, 'Unrelated', '[[B]]').json()
    target = make_doc(client, workspace_id, 'B', '[[A]]').json()
    assert backlinks(client, target) == set()
    for _ in range(2):
        r = client.post('/documents/import/finalize', json={
            'workspace_id': workspace_id, 'document_ids': [source['id'], target['id'], source['id']],
        })
        assert r.status_code == 200
        assert r.json() == {'synced': 2}
        assert backlinks(client, target) == {source['id']}
        assert backlinks(client, source) == {target['id']}
    for doc in (source, target, unrelated):
        saved = client.get(f"/documents/{doc['id']}").json()
        for key in ('content', 'content_hash', 'updated_at', 'status', 'parent_id'):
            assert saved[key] == doc[key]


@pytest.mark.parametrize('kind', ['foreign_doc', 'other_workspace', 'missing', 'deleted', 'foreign_workspace'])
def test_finalize_rejects_invalid_batch_before_sync(client, workspace_id, db_session, kind):
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.document import Document
    from datetime import datetime
    from uuid import UUID

    source = make_doc(client, workspace_id, 'A', '[[B]]').json()
    target = make_doc(client, workspace_id, 'B').json()
    other_ws = client.post('/workspaces/', json={'user_id': str(uuid4()), 'name': 'Other'}).json()['id']
    invalid = make_doc(client, other_ws, 'Invalid').json()['id']
    request_ws = workspace_id
    if kind in ('foreign_doc', 'foreign_workspace'):
        user = User(username=f'foreign_{uuid4().hex}', display_name='Foreign')
        db_session.add(user)
        db_session.flush()
        db_session.get(Workspace, UUID(other_ws)).user_id = user.id
        db_session.commit()
        if kind == 'foreign_workspace':
            request_ws = other_ws
    elif kind == 'missing':
        invalid = str(uuid4())
    elif kind == 'deleted':
        invalid = make_doc(client, workspace_id, 'Deleted').json()['id']
        db_session.get(Document, UUID(invalid)).deleted_at = datetime.now()
        db_session.commit()
    r = client.post('/documents/import/finalize', json={
        'workspace_id': request_ws, 'document_ids': [source['id'], invalid],
    })
    assert r.status_code == 404
    assert backlinks(client, target) == set()


@pytest.mark.parametrize('ids', [[], [str(uuid4())] * 201, ['not-a-uuid']])
def test_finalize_bounds_and_validates_ids(client, workspace_id, ids):
    r = client.post('/documents/import/finalize', json={
        'workspace_id': workspace_id, 'document_ids': ids,
    })
    assert r.status_code == 422


@pytest.mark.parametrize('kind', ['foreign', 'other_workspace', 'deleted', 'missing'])
def test_create_import_rejects_invalid_parent(client, workspace_id, db_session, kind):
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.document import Document
    from uuid import UUID
    from datetime import datetime

    ws = client.post('/workspaces/', json={'user_id': str(uuid4()), 'name': 'Parent WS'}).json()['id']
    parent_id = make_doc(client, ws, 'Parent').json()['id']
    if kind == 'foreign':
        user = User(username=f'foreign_{uuid4().hex}', display_name='Foreign')
        db_session.add(user)
        db_session.flush()
        db_session.get(Workspace, UUID(ws)).user_id = user.id
        db_session.commit()
    elif kind == 'deleted':
        parent_id = make_doc(client, workspace_id, 'Deleted parent').json()['id']
        db_session.get(Document, UUID(parent_id)).deleted_at = datetime.now()
        db_session.commit()
    elif kind == 'missing':
        parent_id = str(uuid4())
    before = db_session.query(Document).count()
    r = make_doc(client, workspace_id, 'Invalid child', parent_id=parent_id)
    assert r.status_code == 404
    assert db_session.query(Document).count() == before


def test_create_import_accepts_same_workspace_parent(client, workspace_id):
    parent = make_doc(client, workspace_id, 'Parent').json()
    r = make_doc(client, workspace_id, 'Child', parent_id=parent['id'])
    assert r.status_code == 201
    assert r.json()['parent_id'] == parent['id']
