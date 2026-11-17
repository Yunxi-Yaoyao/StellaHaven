"""Standalone synthetic SQLite/FK proofs; never loads app settings or conftest.
Run: python3 -I tests_isolated/test_notes_lifecycle.py [Case.test]
Not PostgreSQL concurrency or production acceptance.
"""
import os
import sys
import types
import unittest
import importlib
import tempfile
from pathlib import Path
from uuid import uuid4
from datetime import datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path('/root/.hermes/cache/scratch')
SCRATCH.mkdir(parents=True, exist_ok=True)
HOME = tempfile.TemporaryDirectory(prefix='notes-lifecycle-', dir=SCRATCH)
for key in list(os.environ):
    if key.startswith(('STELLA_', 'PG', 'HERMES_', 'MCP_', 'UV_')) or key in ('DATABASE_URL', 'VIRTUAL_ENV', 'NODE_ENV'):
        os.environ.pop(key, None)
os.environ.update(HOME=HOME.name, TMPDIR=HOME.name, STELLA_BLOB_STORAGE='postgres', STELLA_SECRET_KEY='synthetic-lifecycle-key-never-production-0000')
sys.path.insert(0, '/root/.hermes/cache/scratch/lifecycle-pytest-deps')
sys.path.insert(0, str(ROOT))
# Prevent package initializers importing unrelated application routers/settings.
for name in ('app.services', 'app.routers'):
    mod = types.ModuleType(name)
    mod.__path__ = [str(ROOT / name.replace('.', '/'))]
    sys.modules[name] = mod
from sqlalchemy import create_engine, event, JSON
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
@compiles(JSONB, 'sqlite')
def sqlite_json(element, compiler, **kw):
    return 'JSON'
module = types.ModuleType('app.database')
module.Base = declarative_base()
def get_db():
    raise AssertionError('Production dependency may not run')
module.get_db = get_db
sys.modules['app.database'] = module
class ConfigBlocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('app.config', 'dotenv'):
            raise AssertionError('Private configuration import forbidden')
sys.meta_path.insert(0, ConfigBlocker())
from app.models import Document, Workspace, User, AppConfig, Attachment, DocumentVersion, DocumentLink
from app.models.blob import BlobObject, BlobChunk
from app.services import document as service
from app.schemas.document import DocumentUpdate, DocumentCreate
from fastapi import HTTPException

class Isolated(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        @event.listens_for(self.engine, 'connect')
        def fk(conn, record):
            conn.execute('PRAGMA foreign_keys=ON')
        names = ['users', 'auth_sessions', 'workspaces', 'documents', 'tags', 'doc_tags', 'document_links', 'document_versions', 'attachments', 'app_config', 'blob_objects', 'blob_chunks']
        module.Base.metadata.create_all(self.engine, tables=[module.Base.metadata.tables[n] for n in names])
        self.db = Session(self.engine)
        self.user = User(id=uuid4(), username='synthetic', display_name='synthetic')
        self.db.add(self.user); self.db.flush()
        self.ws = Workspace(id=uuid4(), user_id=self.user.id, name='synthetic')
        self.db.add(self.ws); self.db.commit()
    def tearDown(self):
        self.db.close(); self.engine.dispose()
    def doc(self, **kw):
        values = dict(id=uuid4(), title='synthetic', file_path='/synthetic', workspace_id=self.ws.id, updated_at=datetime.now(), content='', content_hash=service._hash_content(''))
        values.update(kw)
        obj = Document(**values)
        self.db.add(obj); self.db.commit()
        return obj

class Preferences(Isolated):
    def test_defaults_read_only_and_revision_cas(self):
        self.assertIsNotNone(importlib.util.find_spec('app.services.notes_preferences'), 'owner preferences service missing')
        from app.services.notes_preferences import get_preferences, patch_preferences
        from app.schemas.notes_preferences import NotesPreferencesPatch
        owner = self.user.id
        # ACCEPTANCE N06: closed ten-field contract, independent of service DEFAULT.
        default = dict(revision=0, delete_action='trash', ask_before_delete=True,
                       font_size=16, line_height=1.8, read_width=800,
                       code_line_numbers=False, code_wrap=True,
                       directory_sort='updated', hidden_folders=[])
        self.assertEqual(get_preferences(self.db, owner), default)
        self.assertEqual(self.db.query(AppConfig).count(), 0)
        data = NotesPreferencesPatch(expected_revision=0, delete_action='permanent', ask_before_delete=False)
        expected = {**default, 'revision': 1, 'delete_action': 'permanent', 'ask_before_delete': False}
        self.assertEqual(patch_preferences(self.db, owner, data), expected)
        self.db.expire_all()
        self.assertEqual(get_preferences(self.db, owner), expected)
        self.assertEqual(patch_preferences(self.db, owner, data), expected)
        with self.assertRaises(HTTPException) as caught:
            patch_preferences(self.db, owner, NotesPreferencesPatch(expected_revision=0, delete_action='trash'))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(get_preferences(self.db, uuid4()), default)
        self.assertEqual(self.db.query(AppConfig).count(), 1)

class DeleteRetry(Isolated):
    def test_repeated_delete_never_purges_or_resets_timestamp(self):
        doc = self.doc()
        self.assertEqual(service.delete_document(self.db, doc.id), 'trashed')
        stamp = doc.deleted_at
        with patch.object(service, '_physical_delete') as purge:
            self.assertEqual(service.delete_document(self.db, doc.id), 'trashed')
            purge.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(Document, doc.id).deleted_at, stamp)

class SaveIntegrity(Isolated):
    def test_explicit_null_body_rejected_and_hash_is_server_authoritative(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DocumentUpdate(updated_at=datetime.now(), content=None)
        doc = self.doc(content='actual', content_hash=service._hash_content('actual'))
        service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, content_hash='forged'))
        self.assertEqual(doc.content_hash, service._hash_content('actual'))
        service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, content=''))
        self.assertEqual(doc.content, '')
        self.assertEqual(doc.content_hash, service._hash_content(''))

    def test_precise_draft_receipt_consumes_only_matching_slot(self):
        self.assertIn('consumed_draft', DocumentUpdate.model_fields)
        stamp = datetime.now()
        doc = self.doc(draft_content='draft', draft_updated_at=stamp, draft_device='phone')
        receipt = dict(consumed_draft={'draft_updated_at': stamp, 'content_hash': service._hash_content('draft')})
        service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, content='draft', **receipt), force_version=True)
        self.assertIsNone(doc.draft_content)
        doc.draft_content = 'newer'; doc.draft_updated_at = datetime.now(); self.db.commit()
        service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, content='accepted body', **receipt), force_version=True)
        self.db.expire_all()
        self.assertEqual(doc.content, 'accepted body')
        self.assertEqual(doc.draft_content, 'newer')
        service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, content='without receipt'), force_version=True)
        self.assertEqual(doc.draft_content, 'newer')

    def test_create_link_failure_leaves_no_document(self):
        with patch.object(service, 'sync_wikilinks', side_effect=RuntimeError('injected-create-link')):
            with self.assertRaisesRegex(RuntimeError, 'injected-create-link'):
                service.create_document(self.db, DocumentCreate(title='new', file_path='/new', workspace_id=self.ws.id, content='new'))
        self.db.rollback()
        self.assertEqual(self.db.query(Document).count(), 0)

    def test_metadata_preserves_draft(self):
        doc = self.doc(draft_content='other device', draft_updated_at=datetime.now(), draft_device='synthetic')
        service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, title='renamed'))
        self.db.expire_all()
        self.assertEqual(self.db.get(Document, doc.id).draft_content, 'other device')

    def test_link_failure_rolls_back_body_versions_and_draft(self):
        doc = self.doc(content='before', draft_content='draft', draft_updated_at=datetime.now())
        token, doc_id = doc.updated_at, doc.id
        with patch.object(service, 'sync_wikilinks', side_effect=RuntimeError('injected-link')):
            with self.assertRaisesRegex(RuntimeError, 'injected-link'):
                service.update_document(self.db, doc_id, DocumentUpdate(updated_at=token, content='after'))
        self.db.rollback(); self.db.expire_all()
        doc = self.db.get(Document, doc_id)
        self.assertEqual(doc.content, 'before')
        self.assertEqual(doc.updated_at, token)
        self.assertEqual(doc.draft_content, 'draft')
        self.assertEqual(self.db.query(DocumentVersion).count(), 0)

def cleanup_for_test(db, doc, content, *, previous_content):
    if importlib.util.find_spec('app.services.attachment_lifecycle'):
        from app.services.attachment_lifecycle import cleanup_unreferenced
        return cleanup_unreferenced(db, doc, content, previous_content=previous_content)
    # Baseline helper import: auth is not exercised by this service-only proof.
    auth = types.ModuleType('app.routers.auth')
    auth.current_user = auth.require_ws_owner = auth.require_doc_owner = get_db
    with patch.dict(sys.modules, {'app.routers.auth': auth}):
        from app.routers.attachment import cleanup_unreferenced
        return cleanup_unreferenced(db, doc, content)

class References(Isolated):
    def attachment(self, doc):
        att = Attachment(id=uuid4(), doc_id=doc.id, filename='synthetic.png', mime='image/png', size=1)
        self.db.add(att); self.db.commit()
        return att

    def test_pending_upload_survives_unrelated_save(self):
        cleanup_unreferenced = cleanup_for_test
        doc = self.doc(content='plain')
        att = self.attachment(doc)
        self.assertEqual(cleanup_unreferenced(self.db, doc, 'plain', previous_content='plain'), 0)
        self.db.commit()
        self.assertIsNotNone(self.db.get(Attachment, att.id))

    def test_all_existing_reference_kinds_protect_removed_candidate(self):
        cleanup_unreferenced = cleanup_for_test
        owner = self.doc()
        att = self.attachment(owner)
        ref = '/attachments/' + str(att.id)
        # Different legacy user/workspace: preserve references without leaking their titles.
        other_user = User(id=uuid4(), username='legacy', display_name='legacy')
        self.db.add(other_user); self.db.flush()
        other_ws = Workspace(id=uuid4(), name='legacy', user_id=other_user.id)
        self.db.add(other_ws); self.db.commit()
        external = self.doc(workspace_id=other_ws.id)
        for kind in ('body', 'trash', 'draft', 'version101'):
            with self.subTest(kind=kind):
                external.content = ref.upper() if kind in ('body', 'trash') else ''
                external.deleted_at = datetime.now() if kind == 'trash' else None
                external.draft_content = ref if kind == 'draft' else None
                if kind == 'version101':
                    for n in range(101):
                        self.db.add(DocumentVersion(id=uuid4(), doc_id=external.id, content=ref if n == 100 else '', version_no=n+1, diff=''))
                self.db.commit()
                self.assertEqual(cleanup_unreferenced(self.db, owner, '', previous_content=ref), 0)
                self.db.commit()
                self.assertIsNotNone(self.db.get(Attachment, att.id))
        external.content = ''; external.draft_content = None
        self.db.query(DocumentVersion).delete(); self.db.commit()
        self.assertEqual(cleanup_unreferenced(self.db, owner, '', previous_content=ref), 1)
        self.db.commit()
        self.assertIsNone(self.db.get(Attachment, att.id))

class PermanentDelete(Isolated):
    attachment = References.attachment
    def test_permanent_subtree_is_leaf_first_and_atomic(self):
        self.assertTrue(hasattr(service, 'permanently_delete_document'), 'explicit permanent deletion missing')
        parent = self.doc()
        child = self.doc(parent_id=parent.id)
        grandchild = self.doc(parent_id=child.id)
        ids = [parent.id, child.id, grandchild.id]
        service.permanently_delete_document(self.db, parent.id, cascade=True)
        self.db.expire_all()
        self.assertTrue(all(self.db.get(Document, item) is None for item in ids))
        service.permanently_delete_document(self.db, ids[0], cascade=True)

    def test_permanent_non_cascade_promotes_all_surviving_children(self):
        self.assertTrue(hasattr(service, 'permanently_delete_document'))
        parent = self.doc()
        child = self.doc(parent_id=parent.id)
        trashed = self.doc(parent_id=parent.id, deleted_at=datetime.now())
        doc_id = parent.id
        service.permanently_delete_document(self.db, doc_id, cascade=False)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Document, doc_id))
        self.assertIsNone(child.parent_id)
        self.assertIsNone(trashed.parent_id)

    def test_external_reference_blocks_whole_trash_batch(self):
        first = self.doc(deleted_at=datetime.now())
        second = self.doc(deleted_at=datetime.now())
        att = self.attachment(second)
        external = self.doc(content='/attachments/' + str(att.id))
        ids = [first.id, second.id]
        # Baseline imports router; auth is irrelevant to this service proof.
        auth = types.ModuleType('app.routers.auth')
        auth.current_user = auth.require_ws_owner = auth.require_doc_owner = get_db
        with patch.dict(sys.modules, {'app.routers.auth': auth}):
            with self.assertRaises(HTTPException) as caught:
                service.empty_trash(self.db, self.ws.id)
        self.assertEqual(caught.exception.status_code, 409)
        self.db.rollback(); self.db.expire_all()
        self.assertTrue(all(self.db.get(Document, item) is not None for item in ids))
        self.assertIsNotNone(self.db.get(Attachment, att.id))

class LockParticipation(Isolated):
    def test_writers_take_graph_before_tree_before_document(self):
        from app.services import notes_tools
        doc = self.doc()
        events = []
        with patch.object(notes_tools, 'lock_key', side_effect=lambda db, key: events.append(key)):
            service.update_document(self.db, doc.id, DocumentUpdate(updated_at=doc.updated_at, title='next'))
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[:2], ['notes-reference-graph:v1', 'document-tree:' + str(self.ws.id)])

    def test_draft_version_restore_clear_join_reference_gate(self):
        from app.services import notes_tools, document_version
        from app.schemas.document_version import DocumentVersionCreate
        doc = self.doc()
        trashed = self.doc(deleted_at=datetime.now())
        operations = [
            lambda: service.save_draft(self.db, doc.id, 'draft', 'test'),
            lambda: document_version.create_version(self.db, DocumentVersionCreate(doc_id=doc.id, content='version', diff='', version_no=1)),
            lambda: service.restore_document(self.db, trashed.id),
            lambda: service.clear_workspace_docs(self.db, self.ws.id),
        ]
        for n, operation in enumerate(operations):
            with self.subTest(operation=n):
                events = []
                with patch.object(notes_tools, 'lock_key', side_effect=lambda db, key: events.append(key)):
                    operation()
                self.assertGreaterEqual(len(events), 2)
                self.assertEqual(events[0], 'notes-reference-graph:v1')

    def test_quick_record_failure_does_not_commit_empty_inbox(self):
        from app.services.notes_tools import quick_record
        with patch.object(service, 'sync_wikilinks', side_effect=RuntimeError('injected-quick-record')):
            with self.assertRaisesRegex(RuntimeError, 'injected-quick-record'):
                quick_record(self.db, self.ws.id, 'quick', 'body')
        self.db.rollback()
        self.assertEqual(self.db.query(Document).count(), 0)
        self.assertEqual(self.db.query(AppConfig).count(), 0)

    def test_deleted_note_cannot_recreate_node_binding(self):
        from app.services.notes_tools import set_note_node
        doc = self.doc(deleted_at=datetime.now())
        with self.assertRaises(HTTPException):
            set_note_node(self.db, doc.id, 123)
        self.assertEqual(self.db.query(AppConfig).count(), 0)

    def test_create_revalidates_deleted_parent(self):
        parent = self.doc(deleted_at=datetime.now())
        with self.assertRaises((ValueError, HTTPException)):
            service.create_document(self.db, DocumentCreate(title='child', file_path='/child', workspace_id=self.ws.id, parent_id=parent.id))
        self.db.rollback()
        self.assertEqual(self.db.query(Document).count(), 1)

    def test_soft_delete_preserves_already_trashed_child_timestamp(self):
        parent = self.doc()
        stamp = datetime(2020, 1, 1)
        child = self.doc(parent_id=parent.id, deleted_at=stamp)
        service.delete_document(self.db, parent.id)
        self.assertEqual(child.deleted_at, stamp)

    def test_workspace_force_rolls_back_entire_batch(self):
        from app.repositories.workspace import delete
        first = self.doc()
        second = self.doc()
        att = References.attachment(self, second)
        other_ws = Workspace(id=uuid4(), name='other', user_id=self.user.id)
        self.db.add(other_ws); self.db.commit()
        self.doc(workspace_id=other_ws.id, content='/attachments/' + str(att.id))
        ids = [first.id, second.id]
        with self.assertRaises(HTTPException):
            delete(self.db, self.ws.id, force=True)
        self.db.rollback(); self.db.expire_all()
        self.assertTrue(all(self.db.get(Document, item) is not None for item in ids))

class UploadIntegrity(Isolated):
    def upload(self, doc, *, before_read=None):
        import asyncio
        import io
        from fastapi import UploadFile
        from app.routers import attachment
        async def inline(fn):
            return fn()
        file = UploadFile(filename='synthetic.png', file=io.BytesIO(b'synthetic'))
        if before_read:
            original = file.read
            async def read(size):
                before_read()
                return await original(size)
            file.read = read
        with patch.object(attachment, 'run_in_threadpool', inline):
            return asyncio.run(attachment.upload(doc.id, file, self.db, self.user, None))

    def test_upload_rechecks_active_state_after_reading_body(self):
        doc = self.doc()
        with self.assertRaises(HTTPException) as caught:
            self.upload(doc, before_read=lambda: service.delete_document(self.db, doc.id))
        self.assertEqual(caught.exception.status_code, 404)
        self.db.rollback()
        self.assertEqual(self.db.query(Attachment).count(), 0)

    def test_failed_file_publish_never_commits_visible_metadata(self):
        from app.routers import attachment
        doc = self.doc()
        not_directory = Path(HOME.name) / 'not-directory'
        not_directory.write_bytes(b'x')
        with patch.dict(os.environ, STELLA_BLOB_STORAGE='file'), patch.object(attachment, 'STORAGE', not_directory):
            with self.assertRaises(OSError):
                self.upload(doc)
        self.db.rollback()
        self.assertEqual(self.db.query(Attachment).count(), 0)

class FileDeletion(Isolated):
    def test_file_cleanup_failure_is_durable_and_retryable_after_commit(self):
        from app.services import attachment_lifecycle as lifecycle
        self.assertTrue(hasattr(lifecycle, 'drain_file_gc'), 'post-commit file cleanup retry missing')
        doc = self.doc()
        att = References.attachment(self, doc)
        att_id, doc_id = att.id, doc.id
        storage = Path(HOME.name) / str(uuid4()); storage.mkdir()
        path = storage / str(att_id); path.write_bytes(b'synthetic')
        with patch.dict(os.environ, STELLA_BLOB_STORAGE='file'):
            lifecycle.delete_attachment(self.db, att)
            self.assertTrue(path.exists())
            self.db.commit()
            with patch.object(Path, 'unlink', side_effect=OSError('injected-unlink')):
                lifecycle.drain_file_gc(self.db, storage=storage)
            self.assertIsNone(self.db.get(Attachment, att_id))
            row = self.db.get(AppConfig, 'notes-file-gc:' + str(att_id))
            import json
            self.assertEqual(json.loads(row.value)['attempts'], 1)
            self.assertTrue(path.exists())
            lifecycle.drain_file_gc(self.db, storage=storage)
            lifecycle.drain_file_gc(self.db, storage=storage)
            self.assertFalse(path.exists())
            self.assertIsNone(self.db.get(AppConfig, 'notes-file-gc:' + str(att_id)))

class ZipCoordination(Isolated):
    def archive(self, with_attachment=False):
        import io, zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            archive.writestr('note.md', '![](image.png)' if with_attachment else 'plain')
            if with_attachment:
                archive.writestr('image.png', b'synthetic')
        return out.getvalue()

    def baseline_sql(self):
        execute = self.db.execute
        def wrapper(statement, *args, **kwargs):
            if 'pg_advisory_xact_lock' in str(statement):
                return None  # SQL syntax-only shim, never claims PG locking proof.
            return execute(statement, *args, **kwargs)
        return patch.object(self.db, 'execute', wrapper)

    def test_zip_revalidates_parent_inside_lifecycle_lock(self):
        from app.services.notes_zip import commit_archive
        parent = self.doc(deleted_at=datetime.now())
        with self.baseline_sql():
            with self.assertRaises(HTTPException):
                commit_archive(self.db, self.user, self.ws.id, parent.id, uuid4(), self.archive())
        self.db.rollback()
        self.assertEqual(self.db.query(Document).count(), 1)

    def test_zip_unknown_commit_never_unlinks_committed_file(self):
        from app.services.notes_zip import commit_archive
        from app.routers import attachment
        storage = Path(HOME.name) / str(uuid4()); storage.mkdir()
        real_commit = self.db.commit
        def uncertain():
            real_commit()
            raise OSError('unknown-commit-outcome')
        with self.baseline_sql(), patch.dict(os.environ, STELLA_BLOB_STORAGE='file'), patch.object(attachment, 'STORAGE', storage), patch.object(self.db, 'commit', uncertain):
            with self.assertRaisesRegex(OSError, 'unknown-commit-outcome'):
                commit_archive(self.db, self.user, self.ws.id, None, uuid4(), self.archive(True))
        att = self.db.query(Attachment).one()
        self.assertTrue((storage / str(att.id)).exists(), 'committed file was unlinked after uncertain commit')
        self.assertEqual((storage / str(att.id)).read_bytes(), b'synthetic')

class LinkIntegrity(Isolated):
    def test_manual_link_retry_is_idempotent_and_type_conflict_is_409(self):
        from app.repositories.document_link import create
        from app.schemas.document_link import DocumentLinkCreate
        first, second = self.doc(), self.doc()
        payload = DocumentLinkCreate(source_id=first.id, target_id=second.id, link_type='ref')
        create(self.db, payload)
        try:
            create(self.db, payload)
        except Exception as exc:
            self.fail('same-edge retry raised ' + type(exc).__name__)
        self.assertEqual(self.db.query(DocumentLink).count(), 1)
        with self.assertRaises(HTTPException) as caught:
            create(self.db, DocumentLinkCreate(source_id=first.id, target_id=second.id, link_type='wiki'))
        self.assertEqual(caught.exception.status_code, 409)

class FailureMatrix(Isolated):
    def test_save_failure_boundaries_restore_whole_state(self):
        import io
        from app.services import attachment_lifecycle, blob_store
        from app.repositories import document_link
        from app.schemas.document_link import DocumentLinkCreate
        doc = self.doc()
        target = self.doc(title='target')
        att = References.attachment(self, doc)
        att_id, doc_id = att.id, doc.id
        before = '/attachments/' + str(att_id)
        doc.content = before; doc.content_hash = service._hash_content(before)
        doc.draft_content = 'unconsumed'
        self.db.add(DocumentVersion(doc_id=doc_id, content='recent', diff='', version_no=1, created_at=datetime.now()))
        blob_store.put(self.db, 'attachments/' + str(att_id), io.BytesIO(b'synthetic'), 'image/png', 64)
        self.db.commit()
        for boundary in ('link', 'blob', 'commit'):
            with self.subTest(boundary=boundary):
                token = doc.updated_at
                def fault_after(fn):
                    def failing(*args, **kwargs):
                        fn(*args, **kwargs)
                        raise RuntimeError('injected-' + boundary)
                    return failing
                if boundary == 'link':
                    fault = patch.object(document_link, 'create', fault_after(document_link.create))
                elif boundary == 'blob':
                    fault = patch.object(blob_store, 'delete', fault_after(blob_store.delete))
                else:
                    fault = patch.object(self.db, 'commit', side_effect=RuntimeError('injected-commit'))
                with fault:
                    with self.assertRaisesRegex(RuntimeError, 'injected-'):
                        service.update_document(self.db, doc_id, DocumentUpdate(updated_at=token, content='[[target]]'))
                self.db.rollback(); self.db.expire_all()
                self.assertEqual(doc.content, before)
                self.assertEqual(doc.updated_at, token)
                self.assertEqual(doc.draft_content, 'unconsumed')
                self.assertEqual(self.db.query(DocumentVersion).count(), 1)
                self.assertEqual(self.db.query(DocumentLink).count(), 0)
                self.assertIsNotNone(self.db.get(Attachment, att_id))
                self.assertEqual(blob_store.metadata(self.db, 'attachments/' + str(att_id))['size'], 9)

    def test_second_document_delete_failure_rolls_back_first(self):
        first = self.doc(deleted_at=datetime.now())
        second = self.doc(deleted_at=datetime.now())
        ids = [first.id, second.id]
        count = 0
        def fail_second(conn, cursor, statement, params, context, executemany):
            nonlocal count
            if statement.startswith('DELETE FROM documents'):
                count += 1
                if count == 2:
                    raise RuntimeError('injected-second-delete')
        event.listen(self.engine, 'before_cursor_execute', fail_second)
        try:
            with self.assertRaisesRegex(RuntimeError, 'injected-second-delete'):
                service.empty_trash(self.db, self.ws.id)
        finally:
            event.remove(self.engine, 'before_cursor_execute', fail_second)
        self.db.rollback(); self.db.expire_all()
        self.assertTrue(all(self.db.get(Document, item) is not None for item in ids))

    def test_reference_budget_and_unknown_keep_objects(self):
        from app.services import attachment_lifecycle as lifecycle
        doc = self.doc()
        att = References.attachment(self, doc)
        external = self.doc(content='/attachments/not-a-uuid')
        ref = '/attachments/' + str(att.id)
        self.assertEqual(lifecycle.cleanup_unreferenced(self.db, doc, '', previous_content=ref), 0)
        external.content = ''; self.db.commit()
        self.doc(content='another scan row')
        with patch.object(lifecycle, 'MAX_REFERENCE_ROWS', 1):
            self.assertEqual(lifecycle.cleanup_unreferenced(self.db, doc, '', previous_content=ref), 0)
            with self.assertRaises(HTTPException) as caught:
                service.permanently_delete_document(self.db, doc.id)
            self.assertEqual(caught.exception.detail['code'], 'attachment_reference_check_incomplete')
        self.db.rollback()
        self.assertIsNotNone(self.db.get(Attachment, att.id))

class RouteContract(unittest.TestCase):
    def test_delete_intent_routes_use_owner_not_admin(self):
        import ast
        tree = ast.parse((ROOT / 'app/routers/document.py').read_text())
        funcs = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in ('delete_one', 'permanently_delete_one', 'empty_trash_endpoint'):
            with self.subTest(name=name):
                self.assertIn(name, funcs)
                node = funcs[name]
                index = next(i for i, arg in enumerate(node.args.args) if arg.arg == 'user')
                default = node.args.defaults[index - (len(node.args.args) - len(node.args.defaults))]
                self.assertEqual(ast.unparse(default), 'Depends(current_user)')
        restore = ast.unparse(funcs['restore_one'])
        self.assertIn('Depends(admin_user)', restore)

if __name__ == '__main__':
    unittest.main(verbosity=2)
