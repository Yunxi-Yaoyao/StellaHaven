"""R4/W03: real disposable PG, real services and authenticated attachment HTTP.
Run only through run_notes_boundary_pg.py; no main/config/.env imports.
"""
import io
import json
import zipfile
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes

PAYLOAD = b'project-resource-bytes'


def project(notes):
    from app.services import web_projects
    from app.models import AppConfig
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('index.html', '<img src="image.png">')
        archive.writestr('image.png', PAYLOAD)
    with Session(notes.engine) as db:
        root = web_projects.create(db, notes.uid, notes.wid, None, uuid4(), data.getvalue(), 'project.zip', 'index.html')['id']
        meta = json.loads(db.get(AppConfig, 'web-project:'+str(root)).value)
        file_id, record = next((key, value) for key, value in meta['files'].items() if 'attachment_id' in value)
        return root, UUID(file_id), UUID(record['attachment_id'])


def add_reference(notes, aid, position):
    from app.models import Document, DocumentVersion
    content = f'![shared](/attachments/{aid})'
    with Session(notes.engine) as db:
        doc = db.get(Document, notes.did)
        doc.content = content if position in ('body', 'trash') else ''
        doc.draft_content = content if position == 'draft' else None
        if position == 'trash':
            doc.deleted_at = datetime.now()
        if position == 'history':
            db.add(DocumentVersion(doc_id=doc.id, content=content, diff='', version_no=1))
        db.commit()


def serve_setup(notes, monkeypatch, tmp_path):
    from app.routers import attachment
    monkeypatch.setenv('STELLA_BLOB_CACHE', str(tmp_path / 'blob-cache'))
    notes.client.app.include_router(attachment.router)


@pytest.mark.parametrize('position', ['body', 'draft', 'history', 'trash'])
def test_project_delete_releases_reference_retains_original_url(notes, monkeypatch, tmp_path, position):
    from app.models import Attachment, Document
    from app.services import document, blob_store
    serve_setup(notes, monkeypatch, tmp_path)
    root, file_id, aid = project(notes)
    add_reference(notes, aid, position)
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, root, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Document, root) is None
        assert db.get(Document, file_id) is None
        att = db.get(Attachment, aid)
        assert att is not None and att.doc_id is None and att.owner_id == notes.uid
        assert b''.join(blob_store.read_range(db, 'attachments/'+str(aid), 0, att.size)) == PAYLOAD
    response = notes.client.get('/attachments/'+str(aid))
    assert response.status_code == 200, response.text
    assert response.content == PAYLOAD
    assert response.headers['cache-control'] == 'no-store'
    assert notes.client.head('/attachments/'+str(aid)).status_code == 200
    # Purging the last referencing note releases body/draft/history/trash together.
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, notes.did, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is None
        assert blob_store.metadata(db, 'attachments/'+str(aid)) is None
    assert notes.client.get('/attachments/'+str(aid)).status_code == 404


@pytest.mark.parametrize('position', ['body', 'draft', 'history', 'trash'])
def test_http_project_delete_with_external_references(notes, monkeypatch, tmp_path, position):
    from app.models import Attachment, Document
    from test_notes_review_boundaries import preview
    serve_setup(notes, monkeypatch, tmp_path)
    root, file_id, aid = project(notes)
    add_reference(notes, aid, position)
    plan = preview(notes, doc_id=root)
    response = notes.client.delete(f'/documents/{root}/permanent', params={'cascade': 'true', 'scope_token': plan['scope_token']})
    assert response.status_code == 204, response.text
    assert notes.client.get('/attachments/'+str(aid)).content == PAYLOAD
    with Session(notes.engine) as db:
        assert db.get(Document, root) is None and db.get(Document, file_id) is None
        assert db.get(Attachment, aid).doc_id is None
    plan = preview(notes)
    response = notes.client.delete(f'/documents/{notes.did}/permanent', params={'scope_token': plan['scope_token']})
    assert response.status_code == 204, response.text
    assert notes.client.get('/attachments/'+str(aid)).status_code == 404


@pytest.mark.parametrize('foreign', [False, True])
def test_template_copy_of_detached_project_attachment_is_owner_scoped(notes, foreign):
    from fastapi import HTTPException
    from app.models import Attachment, Document, Workspace, User
    from app.services import document, notes_templates, blob_store
    from app.services.notes_lifecycle import lock_document
    root, _, aid = project(notes)
    add_reference(notes, aid, 'body')
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, root, user_id=notes.uid)
        if foreign:
            other = User(username='foreign-template', display_name='foreign')
            db.add(other); db.flush()
            db.get(Attachment, aid).owner_id = other.id
            db.commit()
    with Session(notes.engine) as db:
        source = lock_document(db, notes.did)
        if foreign:
            with pytest.raises(HTTPException) as error:
                notes_templates.independent_copy(db, source, None, 'copy')
            assert error.value.status_code == 409
            db.rollback()
            return
        result = notes_templates.independent_copy(db, source, None, 'copy')
        copied_id = result.id
        db.commit()
    with Session(notes.engine) as db:
        att = db.query(Attachment).filter_by(doc_id=copied_id).one()
        copy_aid = att.id
        assert att.id != aid and att.owner_id is None
        assert '/attachments/'+str(copy_aid) in db.get(Document, copied_id).content
        document.permanently_delete_document(db, notes.did, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is None
        assert db.get(Attachment, copy_aid) is not None
        assert b''.join(blob_store.read_range(db, 'attachments/'+str(copy_aid), 0, len(PAYLOAD))) == PAYLOAD


def test_last_detached_draft_reference_overwrite_collects(notes):
    from app.models import Attachment
    from app.services import document, blob_store
    root, _, aid = project(notes)
    add_reference(notes, aid, 'draft')
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, root, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is not None
        assert document.save_draft(db, notes.did, 'no image', 'same device')
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is None
        assert blob_store.metadata(db, 'attachments/'+str(aid)) is None


def migration():
    from pathlib import Path
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/62a4d9c0e871_project_attachment_owner.py'
    assert path.is_file(), 'Explicit owner-scoped attachment migration required'
    spec = importlib.util.spec_from_file_location('attachment_owner_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_migration(notes, module, action):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with notes.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(module, action)()


def test_attachment_migration_backfills_only_project_and_refuses_lossy_downgrade(notes):
    from app.models import Attachment
    from app.services import document, web_projects, blob_store
    from sqlalchemy import inspect
    module = migration()
    root, _, aid = project(notes)
    with Session(notes.engine) as db:
        ordinary = web_projects.copy_asset(db, notes.uid, root, 'image.png', notes.did, uuid4())['id']
    apply_migration(notes, module, 'downgrade')
    assert 'owner_id' not in {c['name'] for c in inspect(notes.engine).get_columns('attachments')}
    apply_migration(notes, module, 'upgrade')
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid).owner_id == notes.uid
        assert db.get(Attachment, ordinary).owner_id is None
    add_reference(notes, aid, 'body')
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, root, user_id=notes.uid)
    with pytest.raises(RuntimeError, match='detached'):
        apply_migration(notes, module, 'downgrade')
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid).owner_id == notes.uid
        assert b''.join(blob_store.read_range(db, 'attachments/'+str(aid), 0, len(PAYLOAD))) == PAYLOAD
        document.permanently_delete_document(db, notes.did, user_id=notes.uid)
    apply_migration(notes, module, 'downgrade')
    apply_migration(notes, module, 'upgrade')


def test_project_trash_restore_keeps_files_state_and_copy_independent(notes):
    from app.models import Attachment, AppConfig, Document
    from app.services import document, web_projects, blob_store
    root, file_id, aid = project(notes)
    with Session(notes.engine) as db:
        web_projects.write_state(db, notes.uid, root, 0, 0, uuid4(), {'answer': 'B'})
        copied = web_projects.copy_asset(db, notes.uid, root, 'image.png', notes.did, uuid4())['id']
        document.delete_document(db, root, cascade=True, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Document, file_id).deleted_at is not None
        assert db.get(Attachment, aid).doc_id == file_id
        assert db.get(AppConfig, 'web-project:'+str(root)) is not None
        document.restore_document(db, root, cascade=True)
    with Session(notes.engine) as db:
        assert web_projects.read_file(db, notes.uid, root, 'image.png')[0] == PAYLOAD
        assert web_projects.read_state(db, notes.uid, root)['data'] == {'answer': 'B'}
        document.permanently_delete_document(db, root, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is None
        assert db.get(Attachment, copied).doc_id == notes.did
        assert db.get(Attachment, copied).owner_id is None
        assert b''.join(blob_store.read_range(db, 'attachments/'+str(copied), 0, len(PAYLOAD))) == PAYLOAD


@pytest.mark.parametrize('position', ['body', 'draft', 'history', 'trash'])
def test_ordinary_attachment_preflight_is_unchanged(notes, position):
    from fastapi import HTTPException
    from app.models import Attachment, Document
    from app.services import document, web_projects, blob_store
    with Session(notes.engine) as db:
        source = web_projects.new_doc(db, notes.wid, None, 'ordinary')
        sid = source.id
        aid = web_projects.attach(db, source, 'ordinary.png', PAYLOAD, 'image/png').id
        db.commit()
    add_reference(notes, aid, position)
    with Session(notes.engine) as db:
        with pytest.raises(HTTPException) as error:
            document.permanently_delete_document(db, sid, user_id=notes.uid)
        assert error.value.status_code == 409 and error.value.detail['code'] == 'attachment_in_use'
    with Session(notes.engine) as db:
        assert db.get(Document, sid) is not None
        assert db.get(Attachment, aid).doc_id == sid
        assert db.get(Attachment, aid).owner_id is None
        assert blob_store.metadata(db, 'attachments/'+str(aid)) is not None


def test_detach_unknown_scan_defers_gc_and_retry_is_owner_scoped(notes, monkeypatch, tmp_path):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.models import Attachment, Document, User
    from app.services import attachment_lifecycle, document
    from app.routers import attachment
    serve_setup(notes, monkeypatch, tmp_path)
    root, _, aid = project(notes)
    foreign = uuid4()
    with Session(notes.engine) as db:
        db.add(User(id=foreign, username='foreign-resource-owner', display_name='foreign'))
        db.get(Document, notes.did).content = '/attachments/unknown-object-reference'
        db.get(Document, notes.did).draft_content = None
        db.commit()
        document.permanently_delete_document(db, root, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid).doc_id is None
        with pytest.raises(HTTPException) as error:
            attachment.serve(aid, Request({'type': 'http', 'method': 'GET', 'headers': []}), db, db.get(User, foreign))
        assert error.value.status_code == 404
    assert notes.client.get('/attachments/'+str(aid)).content == PAYLOAD
    with Session(notes.engine) as db:
        result = attachment_lifecycle.collect_detached(db, notes.uid)
        assert result['incomplete'] and result['removed'] == 0
        db.get(Document, notes.did).content = ''
        db.commit()
    with Session(notes.engine) as db:
        assert attachment_lifecycle.collect_detached(db, foreign)['scanned'] == 0
        db.commit()
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is not None
        assert attachment_lifecycle.collect_detached(db, notes.uid)['removed'] == 2
        db.commit()
    assert notes.client.get('/attachments/'+str(aid)).status_code == 404
    notes.client.cookies.clear()
    assert notes.client.get('/attachments/'+str(aid)).status_code == 401


def test_detach_transaction_rollback_keeps_project_and_original_bytes(notes, monkeypatch):
    from app.models import Attachment, Document, AppConfig
    from app.services import document, blob_store, attachment_lifecycle
    root, file_id, aid = project(notes)
    add_reference(notes, aid, 'body')
    original = attachment_lifecycle.collect_detached
    def fail_after_deletion(db, owner_id, **kwargs):
        assert db.get(Document, root) is None
        assert db.get(Attachment, aid).doc_id is None
        raise RuntimeError('fault after document delete and detach')
    monkeypatch.setattr(attachment_lifecycle, 'collect_detached', fail_after_deletion)
    with Session(notes.engine) as db:
        with pytest.raises(RuntimeError, match='fault after'):
            document.permanently_delete_document(db, root, user_id=notes.uid)
    with Session(notes.engine) as db:
        assert db.get(Document, root) is not None
        assert db.get(Attachment, aid).doc_id == file_id
        assert db.get(AppConfig, 'web-project:'+str(root)) is not None
        assert b''.join(blob_store.read_range(db, 'attachments/'+str(aid), 0, len(PAYLOAD))) == PAYLOAD
    monkeypatch.setattr(attachment_lifecycle, 'collect_detached', original)
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, root, user_id=notes.uid)


def test_project_attachment_owner_drift_fails_closed(notes):
    from fastapi import HTTPException
    from app.models import Attachment, User, Document
    from app.services import document
    root, file_id, aid = project(notes)
    with Session(notes.engine) as db:
        foreign = User(username='drift-owner', display_name='drift')
        db.add(foreign); db.flush()
        db.get(Attachment, aid).owner_id = foreign.id
        db.commit()
        with pytest.raises(HTTPException) as error:
            document.permanently_delete_document(db, root, user_id=notes.uid)
        assert error.value.detail['code'] == 'attachment_owner_mismatch'
    with Session(notes.engine) as db:
        assert db.get(Document, root) is not None
        assert db.get(Attachment, aid).doc_id == file_id


def test_detached_last_body_save_collects_without_pruning_real_history(notes):
    from app.models import Attachment, DocumentVersion, Document
    from app.schemas.document import DocumentUpdate
    from app.services import document
    root, _, aid = project(notes)
    add_reference(notes, aid, 'body')
    with Session(notes.engine) as db:
        # A real prior checkpoint prevents a new initial snapshot of the body.
        db.add(DocumentVersion(doc_id=notes.did, content='', diff='', version_no=1, created_at=datetime.now()))
        db.commit()
        document.permanently_delete_document(db, root, user_id=notes.uid)
    with Session(notes.engine) as db:
        doc = db.get(Document, notes.did)
        document.update_document(db, notes.did, DocumentUpdate(content='', updated_at=doc.updated_at))
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is None
        assert db.query(DocumentVersion).filter_by(doc_id=notes.did).count() == 1


def test_body_save_of_attached_project_does_not_collect_implicit_resource(notes):
    from app.models import Attachment, Document, DocumentVersion
    from app.services import document, web_projects
    from app.schemas.document import DocumentUpdate
    root, file_id, aid = project(notes)
    with Session(notes.engine) as db:
        db.add(DocumentVersion(doc_id=file_id, content='', diff='', version_no=1, created_at=datetime.now()))
        db.commit()
        doc = db.get(Document, file_id)
        document.update_document(db, file_id, DocumentUpdate(content='', updated_at=doc.updated_at))
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid).doc_id == file_id
        assert web_projects.read_file(db, notes.uid, root, 'image.png')[0] == PAYLOAD


def test_detached_foreign_http_and_gc_do_not_cross_owner(notes, monkeypatch, tmp_path):
    from app.models import Attachment, User, Workspace, Document
    from app.services import blob_store, attachment_lifecycle
    serve_setup(notes, monkeypatch, tmp_path)
    other, aid, wid = uuid4(), uuid4(), uuid4()
    with Session(notes.engine) as db:
        db.add(User(id=other, username='foreign-detached', display_name='foreign'))
        db.flush()
        db.add(Workspace(id=wid, user_id=other, name='foreign'))
        db.add(Attachment(id=aid, doc_id=None, owner_id=other, filename='foreign.png', mime='image/png', size=len(PAYLOAD)))
        blob_store.put(db, 'attachments/'+str(aid), io.BytesIO(PAYLOAD), 'image/png', len(PAYLOAD))
        db.commit()
    response = notes.client.get('/attachments/'+str(aid))
    assert response.status_code == 404 and response.headers['cache-control'] == 'no-store'
    assert notes.client.head('/attachments/'+str(aid)).status_code == 404
    with Session(notes.engine) as db:
        assert attachment_lifecycle.collect_detached(db, notes.uid, candidates={aid})['scanned'] == 0
        # A foreign text reference must protect bytes, not grant access/ownership.
        db.get(Document, notes.did).content = '/attachments/'+str(aid)
        db.commit()
    with Session(notes.engine) as db:
        assert attachment_lifecycle.collect_detached(db, other)['removed'] == 0
        assert db.get(Attachment, aid).owner_id == other
        db.commit()
    assert notes.client.get('/attachments/'+str(aid)).status_code == 404


def test_detached_gc_waits_for_reference_writer_and_rechecks(notes):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import text
    from app.models import Attachment, Document
    from app.services import document, attachment_lifecycle
    from app.services.notes_lifecycle import lock_document
    from test_notes_review_boundaries_pg import wait_for_lock
    root, _, aid = project(notes)
    add_reference(notes, aid, 'body')
    with Session(notes.engine) as db:
        document.permanently_delete_document(db, root, user_id=notes.uid)
        db.get(Document, notes.did).content = ''
        db.commit()
    started = threading.Event()
    pid = {}
    def collect():
        with Session(notes.engine) as db:
            pid['waiter'] = db.execute(text('select pg_backend_pid()')).scalar()
            started.set()
            result = attachment_lifecycle.collect_detached(db, notes.uid)
            db.commit()
            return result
    with Session(notes.engine) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        doc = lock_document(holder, notes.did)
        blocker = holder.execute(text('select pg_backend_pid()')).scalar()
        doc.draft_content = '/attachments/'+str(aid)
        holder.flush()
        future = pool.submit(collect)
        try:
            assert started.wait(5)
            wait_for_lock(notes.engine, pid['waiter'], blocker)
        finally:
            holder.commit()
        assert future.result(timeout=5)['removed'] == 0
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid).doc_id is None
        document.save_draft(db, notes.did, '', 'writer')
    with Session(notes.engine) as db:
        assert db.get(Attachment, aid) is None


def test_attachment_migration_full_alembic_env_chain(notes, monkeypatch):
    """Run the unchanged env.py and complete chain on the fixture-owned schema."""
    import sys
    import types
    from pathlib import Path
    import sqlalchemy
    from sqlalchemy import text, inspect
    from alembic.config import Config
    from alembic import command
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
    assert ScriptDirectory.from_config(cfg).get_heads() == ['62a4d9c0e871']
    # The exact owned engine retains its same-connection identity guards and
    # random-schema search_path. Do not import app.config or resolve any .env.
    config = types.ModuleType('app.config')
    config.settings = types.SimpleNamespace(database_url='owned-engine-only')
    monkeypatch.setitem(sys.modules, 'app.config', config)
    monkeypatch.setattr(sqlalchemy, 'engine_from_config', lambda *a, **kw: notes.engine)
    with notes.engine.begin() as conn:
        schema = conn.execute(text('select current_schema()')).scalar()
        assert schema.startswith('notes_case_')
        notes.models.Base.metadata.drop_all(conn)
    command.upgrade(cfg, 'head')
    with notes.engine.connect() as conn:
        assert conn.execute(text('select version_num from alembic_version')).scalar() == '62a4d9c0e871'
        assert {c['name']: c['nullable'] for c in inspect(conn).get_columns('attachments')}['doc_id']
    command.downgrade(cfg, '47c1d9e2ab60')
    with notes.engine.connect() as conn:
        assert not {c['name']: c['nullable'] for c in inspect(conn).get_columns('attachments')}['doc_id']
    command.upgrade(cfg, 'head')
    with notes.engine.connect() as conn:
        assert conn.execute(text('select version_num from alembic_version')).scalar() == '62a4d9c0e871'
