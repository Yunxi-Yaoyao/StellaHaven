"""Self-contained pytest fixture reuse; no tests/conftest, real owner auth."""
import json
from datetime import datetime
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session
from test_api_draft_contract import env


# ACCEPTANCE N06: independent, closed HTTP defaults, not the service's DEFAULT.
EXPECTED_PREFERENCES = {
    'revision': 0, 'delete_action': 'trash', 'ask_before_delete': True,
    'font_size': 16, 'line_height': 1.8, 'read_width': 800,
    'code_line_numbers': False, 'code_wrap': True,
    'directory_sort': 'updated', 'hidden_folders': [],
}


@pytest.fixture
def notes(env):
    from app.models import Attachment, DocumentVersion, DocumentLink, DocTag, Tag
    from app.models.blob import BlobObject, BlobChunk
    tables = [cls.__table__ for cls in [Tag, DocTag, DocumentLink, DocumentVersion, Attachment, BlobObject, BlobChunk]]
    with env.engine.begin() as connection:
        assert connection.dialect.name == 'sqlite'
        assert connection.exec_driver_sql('PRAGMA database_list').first()[2].endswith('draft.sqlite')
        env.models.Base.metadata.create_all(connection, tables=tables)
    from app.routers.notes_preferences import router
    env.client.app.include_router(router)
    with Session(env.engine) as db:
        doc = db.get(env.models.Document, env.did)
        doc.updated_at = datetime.now()
        db.commit()
    return env


def test_preferences_real_owner_no_management_grant_and_validation(notes):
    client = notes.client
    response = client.get('/notes-preferences')
    assert response.status_code == 200
    assert response.json() == EXPECTED_PREFERENCES
    with Session(notes.engine) as db:
        assert db.query(notes.models.AppConfig).filter(notes.models.AppConfig.key.startswith('notes-preferences:')).count() == 0
    for body in ({}, {'expected_revision': -1}, {'expected_revision': 0, 'owner_id': str(uuid4())},
                 {'expected_revision': 0, 'ask_before_delete': 'false'}, {'expected_revision': 0, 'delete_action': 'nope'},
                 {'expected_revision': 0, 'ask_before_delete': None},
                 *({'expected_revision': 0, key: value} for key, value in (
                     ('font_size', 29), ('font_size', '16'), ('line_height', 1),
                     ('read_width', 479), ('code_line_numbers', 'false'),
                     ('code_wrap', None), ('directory_sort', 'unknown'),
                     ('hidden_folders', ['not-a-uuid']), ('unreviewed_field', True)))):
        assert client.patch('/notes-preferences', json=body).status_code == 422
    body = {'expected_revision': 0, 'delete_action': 'permanent', 'ask_before_delete': False}
    expected = {**EXPECTED_PREFERENCES, 'revision': 1, 'delete_action': 'permanent', 'ask_before_delete': False}
    for _ in range(2):
        saved = client.patch('/notes-preferences', json=body)
        assert saved.status_code == 200
        assert saved.json() == expected  # Retry is an idempotent read, not a new revision.
    conflict = client.patch('/notes-preferences', json={'expected_revision': 0, 'delete_action': 'trash'})
    assert conflict.status_code == 409
    assert conflict.json() == {'detail': {'code': 'notes_preferences_conflict', 'current': expected}}
    assert client.get('/notes-preferences').json() == expected
    display = {'font_size': 20, 'line_height': 2, 'read_width': 960,
               'code_line_numbers': True, 'code_wrap': False,
               'directory_sort': 'title', 'hidden_folders': [str(notes.did)]}
    saved = client.patch('/notes-preferences', json={'expected_revision': 1, **display})
    expected = {**expected, **display, 'revision': 2}
    assert saved.status_code == 200
    assert saved.json() == expected
    assert client.get('/notes-preferences').json() == expected
    with Session(notes.engine) as db:
        row = db.get(notes.models.AppConfig, 'notes-preferences:' + str(notes.uid))
        assert json.loads(row.value) == expected
    stale = client.patch('/notes-preferences', json={'expected_revision': 1, 'font_size': 18})
    assert stale.status_code == 409
    assert stale.json() == {'detail': {'code': 'notes_preferences_conflict', 'current': expected}}
    client.cookies.clear()
    assert client.get('/notes-preferences').status_code == 401
    assert client.patch('/notes-preferences', json=body).status_code == 401


def test_owner_delete_retry_permanent_and_restore_permissions(notes):
    path = f'/documents/{notes.did}'
    for _ in range(2):
        response = notes.client.delete(path)
        assert response.status_code == 204, response.text
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did) is not None
    # Owner needs no retired management grant; restore is a durable write.
    restored = notes.client.post(path + '/restore')
    assert restored.status_code == 200, restored.text
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did).deleted_at is None
    assert notes.client.delete(path).status_code == 204
    for _ in range(2):
        response = notes.client.delete(path + '/permanent')
        assert response.status_code == 204, response.text
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did) is None
    assert notes.client.post('/documents/trash/empty', params={'workspace_id': str(notes.wid)}).json() == {'purged': 0}


def test_finalize_commits_derived_links_in_one_batch(notes):
    target_id = uuid4()
    with Session(notes.engine) as db:
        doc = db.get(notes.models.Document, notes.did)
        doc.content = '[[target]]'
        db.add(notes.models.Document(id=target_id, workspace_id=notes.wid, title='target', file_path='/target', content='', content_hash='empty'))
        db.commit()
    response = notes.client.post('/documents/import/finalize', json={'workspace_id': str(notes.wid), 'document_ids': [str(notes.did), str(target_id)]})
    assert response.status_code == 200, response.text
    with Session(notes.engine) as db:
        assert db.query(notes.models.DocumentLink).filter_by(source_id=notes.did, target_id=target_id).count() == 1


@pytest.mark.parametrize('identity,status', [('anonymous', 401), ('foreign', 403)])
def test_restore_keeps_real_identity_denials_and_durable_trash(notes, identity, status):
    from app.security import make_access_token
    from datetime import timezone
    path = f'/documents/{notes.did}'
    assert notes.client.delete(path).status_code == 204
    with Session(notes.engine) as db:
        before = db.get(notes.models.Document, notes.did).deleted_at
        assert before is not None
        if identity == 'foreign':
            uid, sid = uuid4(), uuid4()
            now = datetime.now(timezone.utc)
            db.add(notes.models.User(id=uid, username='foreign-session', display_name='Foreign', is_admin=True)); db.flush()
            db.add(notes.models.AuthSession(id=sid, user_id=uid, refresh_hash='foreign',
                                           remember=True, created_at=now, last_seen=now))
            db.commit()
    notes.client.cookies.clear()
    if identity == 'foreign':
        notes.client.cookies.set('stella_at', make_access_token(str(uid), str(sid)))
    assert notes.client.post(path + '/restore').status_code == status
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, notes.did).deleted_at == before


def test_delete_cannot_touch_foreign_user_document(notes):
    with Session(notes.engine) as db:
        uid, wid, did = uuid4(), uuid4(), uuid4()
        db.add(notes.models.User(id=uid, username='legacy', display_name='private title owner')); db.flush()
        db.add(notes.models.Workspace(id=wid, user_id=uid, name='legacy')); db.flush()
        db.add(notes.models.Document(id=did, workspace_id=wid, title='private title', file_path='/private', content='private', content_hash='private'))
        db.commit()
    assert notes.client.delete(f'/documents/{did}/permanent').status_code == 404
    assert notes.client.delete(f'/documents/{did}').status_code == 404
    assert notes.client.post(f'/documents/{did}/restore').status_code == 404
    assert notes.client.post('/documents/trash/empty', params={'workspace_id': str(wid)}).status_code == 404
    with Session(notes.engine) as db:
        assert db.get(notes.models.Document, did).content == 'private'
