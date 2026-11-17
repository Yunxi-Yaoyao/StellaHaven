"""Real PostgreSQL/HTTP candidate tests. Run only via owned Notes PG launcher.

Not run by the detached-source subagent: parent browser E2E owns PG resources.
The fixture seeds synthetic auth/get_db; runtime auth is stubbed only in the
explicit resource-resolution assertion, not claimed as full capability proof.
"""
import io
import json
import zipfile
from uuid import UUID, uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes


def create(db, notes):
    from app.services import web_projects
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('index.html', '<!doctype html><script src="app.js"></script>')
        z.writestr('app.js', 'const text = "**not markdown**";\n')
        z.writestr('README.md', '# 原始 Markdown\n<script>raw()</script>\n')
        z.writestr('cat.png', b'\x89PNG\r\n\x1a\nfixture')
    root = web_projects.create(db, notes.uid, notes.wid, None, uuid4(), stream.getvalue(), 'detach.zip', 'index.html')['id']
    return root, web_projects.manifest(db, notes.uid, root)


@pytest.mark.parametrize('path', ['index.html', 'app.js', 'README.md'])
def test_detached_source_http_edit_move_delete_restore_private(notes, monkeypatch, path):
    from app.models.document import Document
    from app.models.config import AppConfig
    from app.schemas.document import DocumentUpdate
    from app.services import web_projects, detached_sources, web_project_runtime
    from app.routers.detached_sources import router
    notes.client.app.include_router(router)
    headers = {'Authorization': 'Bearer ' + notes.token}
    with Session(notes.engine) as db:
        root, info = create(db, notes)
        item = next(f for f in info['files'] if f['path'] == path)
        ident = UUID(item['id']);doc = db.get(Document, ident);original = doc.content
        notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, parent_id=None))
    # New session proves metadata is persisted, not an in-memory classification.
    with Session(notes.engine) as db:
        assert detached_sources.read(db, notes.uid, ident)['content'] == original
        metadata = json.loads(db.get(AppConfig, 'web-project-source:' + str(ident)).value)
        assert metadata['owner_id'] == str(notes.uid) and metadata['kind'] == 'text'
        assert str(ident) not in {f['id'] for f in web_projects.manifest(db, notes.uid, root)['files']}
        monkeypatch.setattr(web_project_runtime, 'authorize', lambda *a: ({'owner': str(notes.uid), 'root': str(root), 'source': 'https://fixture.invalid'}, {}))
        with pytest.raises(HTTPException) as denied:
            web_project_runtime.resource(db, 'synthetic-old-grant', 'https://runtime.invalid', path)
        assert denied.value.status_code == 404
        with pytest.raises(HTTPException): detached_sources.read(db, uuid4(), ident)
        if path == 'index.html': assert web_projects.manifest(db, notes.uid, root)['entry_file_id'] is None
    url = f'/detached-sources/{ident}'
    source = notes.client.get(url, headers=headers)
    assert source.status_code == 200 and source.json()['content'] == original
    raw = '<script>const x = "**raw**";</script>\r\n# unchanged source semantics'
    saved = notes.client.put(url, headers=headers, json={'updated_at': source.json()['updated_at'], 'content': raw})
    assert saved.status_code == 200, saved.text
    assert notes.client.get(url, headers=headers).json()['content'] == raw
    stale = notes.client.put(url, headers=headers, json={'updated_at': source.json()['updated_at'], 'content': 'stale'})
    assert stale.status_code == 409
    with Session(notes.engine) as db:
        doc = db.get(Document, ident)
        for fields in ({'content': 'ordinary conversion'}, {'visibility': 'public'}, {'is_folder': True}):
            with pytest.raises(HTTPException): notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, **fields))
            db.expire_all();doc = db.get(Document, ident)
            assert doc.content == raw and doc.visibility == 'private'
        notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, parent_id=notes.did, title='no-extension'))
        assert detached_sources.read(db, notes.uid, ident)['kind'] == 'detached-source'
        notes.svc.delete_document(db, ident)
        with pytest.raises(HTTPException): detached_sources.read(db, notes.uid, ident)
        notes.svc.restore_document(db, ident)
        assert detached_sources.read(db, notes.uid, ident)['content'] == raw
        notes.svc.update_document(db, ident, DocumentUpdate(updated_at=db.get(Document, ident).updated_at, parent_id=None))
        notes.svc.permanently_delete_document(db, root)
        assert detached_sources.read(db, notes.uid, ident)['content'] == raw
    catalog = notes.client.get(f'/detached-sources?workspace_id={notes.wid}', headers=headers)
    assert catalog.status_code == 200
    assert next(x for x in catalog.json() if x['id'] == str(ident))['title'] == 'no-extension'
    with Session(notes.engine) as db:
        notes.svc.permanently_delete_document(db, ident)
        assert db.get(AppConfig, 'web-project-source:' + str(ident)) is None


def test_rejected_boundary_and_combined_update_are_atomic(notes):
    from app.models.document import Document
    from app.models.config import AppConfig
    from app.schemas.document import DocumentUpdate
    from app.services import web_projects
    with Session(notes.engine) as db:
        root, info = create(db, notes);other, _ = create(db, notes)
        text = UUID(next(f['id'] for f in info['files'] if f['path'] == 'app.js'))
        binary = UUID(next(f['id'] for f in info['files'] if f['path'] == 'cat.png'))
        before = db.get(AppConfig, 'web-project:' + str(root)).value
        for ident, fields in [(text, {'parent_id': other}), (binary, {'parent_id': None}),
                               (text, {'parent_id': None, 'content': 'converted'}),
                               (text, {'parent_id': None, 'visibility': 'public'})]:
            doc = db.get(Document, ident);old_parent, old_content = doc.parent_id, doc.content
            with pytest.raises(HTTPException): notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, **fields))
            db.expire_all();doc = db.get(Document, ident)
            assert (doc.parent_id, doc.content) == (old_parent, old_content)
            assert db.get(AppConfig, 'web-project-source:' + str(ident)) is None
            assert db.get(AppConfig, 'web-project:' + str(root)).value == before
        doc = db.get(Document, text)
        notes.svc.update_document(db, text, DocumentUpdate(updated_at=doc.updated_at, parent_id=None))
        for target in (root, other):
            doc = db.get(Document, text)
            with pytest.raises(HTTPException): notes.svc.update_document(db, text, DocumentUpdate(updated_at=doc.updated_at, parent_id=target))
            db.expire_all();assert db.get(Document, text).parent_id is None


@pytest.mark.parametrize('action', ['trash-promote', 'purge-promote', 'restore-orphan'])
def test_implicit_reparenting_preserves_source_identity(notes, action):
    from app.models.document import Document
    from app.services import web_projects, detached_sources
    with Session(notes.engine) as db:
        root = web_projects.create(db, notes.uid, notes.wid, None, uuid4(), b'<h1>raw</h1>', 'single.html', 'single.html')['id']
        ident = UUID(web_projects.manifest(db, notes.uid, root)['files'][0]['id'])
        if action == 'trash-promote': notes.svc.delete_document(db, root, cascade=False)
        elif action == 'purge-promote': notes.svc.permanently_delete_document(db, root, cascade=False)
        else:
            notes.svc.delete_document(db, root, cascade=True)
            notes.svc.restore_document(db, ident)
        assert db.get(Document, ident).parent_id is None
        assert detached_sources.read(db, notes.uid, ident)['content'] == '<h1>raw</h1>'


def test_source_limits_are_zero_write(notes):
    from app.models.document import Document
    from app.schemas.document import DocumentUpdate
    from app.services import detached_sources
    with Session(notes.engine) as db:
        _, info = create(db, notes);ident = UUID(info['files'][0]['id'])
        doc = db.get(Document, ident);notes.svc.update_document(db, ident, DocumentUpdate(updated_at=doc.updated_at, parent_id=None))
        original = detached_sources.read(db, notes.uid, ident)
        for content, status in [('界' * (2 * 1024 * 1024), 413), ('\ud800', 422), ('nul\x00', 422)]:
            with pytest.raises(HTTPException) as denied: detached_sources.save(db, notes.uid, ident, db.get(Document, ident).updated_at, content)
            assert denied.value.status_code == status
            assert detached_sources.read(db, notes.uid, ident) == original
