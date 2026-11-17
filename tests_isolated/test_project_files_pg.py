"""Parent must run via isolated Notes PG runner; not executed by files subagent."""
import io
import zipfile
from uuid import UUID, uuid4
import pytest
from sqlalchemy.orm import Session
from fastapi import HTTPException
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes


def archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('index.html', '<h1>原页面</h1>')
        z.writestr('pages/second.html', '<script src="../js/app.js"></script>')
        z.writestr('js/app.js', 'const raw = "**not markdown**";\r\n')
        z.writestr('images/cat.png', b'\x89PNG\r\n\x1a\nfixture')
    return stream.getvalue()


def create(db, notes):
    from app.services import web_projects as service
    return service.create(db, notes.uid, notes.wid, None, uuid4(), archive(), 'files.zip', 'index.html')['id']


def test_manifest_directories_size_and_transactional_move_rejection(notes):
    from app.services import web_projects as service
    from app.models.document import Document
    from app.schemas.document import DocumentUpdate
    with Session(notes.engine) as db:
        a, b = create(db, notes), create(db, notes)
        initial = service.manifest(db, notes.uid, a)
        assert {d['path'] for d in initial['directories']} == {'pages', 'js', 'images'}
        assert all(d['kind'] == 'directory' for d in initial['directories'])
        assert not set(d['id'] for d in initial['directories']) & set(f['id'] for f in initial['files'])
        image = next(f for f in initial['files'] if f['path'] == 'images/cat.png')
        assert image['mime'] == 'image/png' and image['size'] == len(b'\x89PNG\r\n\x1a\nfixture')
        source = next(f for f in initial['files'] if f['path'] == 'js/app.js')
        ident = UUID(source['id'])
        original = db.get(Document, ident).content
        # Text export to ordinary parents/root is now a positive W02 contract;
        # test_detached_source_pg.py covers its durable identity and rollback.
        for target in (b,):
            doc = db.get(Document, ident)
            old_parent = doc.parent_id
            with pytest.raises(HTTPException) as error:
                notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, parent_id=target, content='must roll back'))
            assert error.value.status_code == 409
            db.expire_all()
            doc = db.get(Document, ident)
            assert doc.parent_id == old_parent and doc.content == original
            assert service.manifest(db, notes.uid, a) == initial
            assert source['id'] not in {f['id'] for f in service.manifest(db, notes.uid, b)['files']}
        # Same-project and entire-project moves keep member identity and exact bytes.
        doc = db.get(Document, ident)
        notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, parent_id=a))
        assert service.read_file(db, notes.uid, a, 'app.js')[0].decode() == original
        root = db.get(Document, a)
        notes.svc.update_document(db, a, DocumentUpdate(updated_at=root.updated_at, parent_id=notes.did, title='renamed root'))
        assert service.read_file(db, notes.uid, a, 'app.js')[0].decode() == original


def test_entry_endpoint_checks_owner_cas_html_and_preserves_runtime_state(notes):
    from app.services import web_projects as service
    from app.routers.project_files import router
    from app.routers.web_projects import router as projects_router
    notes.client.app.include_router(router)
    notes.client.app.include_router(projects_router)
    with Session(notes.engine) as db:
        root = create(db, notes)
        info = service.manifest(db, notes.uid, root)
        second = next(f['id'] for f in info['files'] if f['path'] == 'pages/second.html')
        image = next(f['id'] for f in info['files'] if f['kind'] == 'binary')
        service.write_state(db, notes.uid, root, 0, 0, str(uuid4()), {'score': '42'})
        with pytest.raises(HTTPException): service.set_entry(db, uuid4(), root, UUID(second), info['entry_file_id'])
    headers = {'Authorization': 'Bearer ' + notes.token}
    url = f'/web-project-files/{root}/entry'
    rejected = notes.client.patch(url, json={'file_id': image, 'expected_entry_file_id': info['entry_file_id']}, headers=headers)
    assert rejected.status_code == 409
    changed = notes.client.patch(url, json={'file_id': second, 'expected_entry_file_id': info['entry_file_id']}, headers=headers)
    assert changed.status_code == 200, changed.text
    readback = notes.client.get(f'/web-projects/{root}', headers=headers)
    assert readback.status_code == 200
    assert readback.json()['entry'] == 'pages/second.html'
    assert readback.json()['entry_file_id'] == second
    stale = notes.client.patch(url, json={'file_id': info['entry_file_id'], 'expected_entry_file_id': info['entry_file_id']}, headers=headers)
    assert stale.status_code == 409
    with Session(notes.engine) as db:
        assert service.read_state(db, notes.uid, root) == {'revision': 1, 'epoch': 0, 'data': {'score': '42'}}


def test_image_copy_receipt_remains_stable_and_original_survives(notes):
    from app.services import web_projects as service
    from app.models.attachment import Attachment
    with Session(notes.engine) as db:
        root = create(db, notes)
        initial = service.manifest(db, notes.uid, root)
        request = uuid4()
        first = service.copy_asset(db, notes.uid, root, 'images/cat.png', notes.did, request)
        replay = service.copy_asset(db, notes.uid, root, 'images/cat.png', notes.did, request)
        assert replay == first
        assert service.manifest(db, notes.uid, root) == initial
        assert db.get(Attachment, first['id']).doc_id == notes.did
        notes.svc.permanently_delete_document(db, root)
        assert db.get(Attachment, first['id']).doc_id == notes.did


def test_project_filename_rename_http_cas_path_owner_and_blob_guards(notes):
    """The UI uses this existing title CAS, not a parallel rename API."""
    from app.services import web_projects as service
    from app.routers.web_projects import router
    from app.models import Document, User, AuthSession, Workspace
    from app.security import make_access_token
    notes.client.app.include_router(router)
    with Session(notes.engine) as db:
        root = create(db, notes)
        initial = service.manifest(db, notes.uid, root)
        source = next(f for f in initial['files'] if f['path'] == 'js/app.js')
        original = service.read_file(db, notes.uid, root, 'js/app.js')[0]
        doc = db.get(Document, UUID(source['id']))
        logical_path = doc.file_path
    url = '/documents/' + source['id']
    stamp = notes.client.get(url).json()['updated_at']
    moved = notes.client.put(url, json={'updated_at': stamp, 'parent_id': str(root)})
    assert moved.status_code == 200, moved.text
    stamp = moved.json()['updated_at']
    baseline = notes.client.get('/web-projects/'+str(root)).json()
    for name in ('../escape.js', 'nested/app.js', 'nested\\app.js', '.', '..', '', '__stella_storage.js', 'index.html'):
        rejected = notes.client.put(url, json={'updated_at': stamp, 'title': name})
        assert rejected.status_code == 409, (name, rejected.text)
        assert notes.client.get('/web-projects/'+str(root)).json() == baseline
        assert notes.client.get(url).json()['updated_at'] == stamp
    renamed = notes.client.put(url, json={'updated_at': stamp, 'title': 'renamed.js'})
    assert renamed.status_code == 200, renamed.text
    stale = notes.client.put(url, json={'updated_at': stamp, 'title': 'lost.js'})
    assert stale.status_code == 409
    with Session(notes.engine) as db:
        assert service.read_file(db, notes.uid, root, 'renamed.js')[0] == original
        assert db.get(Document, UUID(source['id'])).file_path == logical_path
        uid, sid = uuid4(), uuid4()
        db.add(User(id=uid, username='rename-foreign', display_name='rename-foreign'))
        db.flush()
        db.add(AuthSession(id=sid, user_id=uid, refresh_hash='fixture-other', created_at=notes.now, last_seen=notes.now))
        foreign_workspace, foreign_id = uuid4(), uuid4()
        db.add(Workspace(id=foreign_workspace, user_id=uid, name='foreign-workspace'))
        db.flush()
        db.add(Document(id=foreign_id, workspace_id=foreign_workspace, title='foreign.js', file_path='/foreign.js', content='private', content_hash='fixture'))
        db.commit()
    foreign_url = '/documents/'+str(foreign_id)
    assert notes.client.get(foreign_url).status_code == 404
    assert notes.client.put(foreign_url, json={'updated_at': renamed.json()['updated_at'], 'title': 'stolen.js'}).status_code == 404
    notes.client.cookies.set('stella_at', make_access_token(str(uid), str(sid)))
    try:
        # Current single-owner auth rejects another valid session before routing.
        assert notes.client.get(url).status_code == 403
        assert notes.client.put(url, json={'updated_at': renamed.json()['updated_at'], 'title': 'foreign.js'}).status_code == 403
        assert notes.client.get('/web-projects/'+str(root)).status_code == 403
    finally:
        notes.client.cookies.set('stella_at', notes.token)
    assert notes.client.get(url).json()['title'] == 'renamed.js'
    with Session(notes.engine) as db:
        assert service.read_file(db, notes.uid, root, 'renamed.js')[0] == original
