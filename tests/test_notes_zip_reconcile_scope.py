"""Reconciliation scope and actual PostgreSQL reference-writer interleavings."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.test_notes_zip import archive, post_zip, workspace_id
from tests.test_notes_zip_reconcile import file_storage, fault_commit, rows


@pytest.mark.parametrize('veto', ['owner', 'receipt-other-scope', 'live-metadata', 'draft', 'version', 'trash', 'ambiguous'])
def test_zip_fresh_reconcile_veto(client, workspace_id, db_session, file_storage, monkeypatch, veto):
    from app.services import notes_zip
    from app.models.workspace import Workspace
    from app.models.user import User
    from app.models.document import Document
    from app.models.document_version import DocumentVersion
    from app.models.attachment import Attachment
    from app.models.config import AppConfig
    from datetime import datetime
    doc = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'kept', 'file_path': 'kept.md', 'content': 'keep'}).json()
    reconcile = notes_zip._reconcile_failed_files
    ids = []
    def interleave(bind, owner, receipt, scope, created, storage):
        ids.extend(created)
        with Session(bind) as fresh:
            if veto == 'owner':
                other = User(username='other_' + uuid4().hex, display_name='Other')
                fresh.add(other); fresh.flush()
                fresh.get(Workspace, UUID(workspace_id)).user_id = other.id
            elif veto == 'receipt-other-scope':
                fresh.add(AppConfig(key=receipt, value=json.dumps({'scope': [str(uuid4()), None, 'different', 'utf8'], 'result': {}})))
            elif veto == 'live-metadata':
                fresh.add(Attachment(id=created[0], doc_id=UUID(doc['id']), filename='retained', mime='text/plain', size=5))
            else:
                ref = '/attachments/' + str(created[0])
                current = fresh.get(Document, UUID(doc['id']))
                if veto == 'draft': current.draft_content = ref
                elif veto == 'version': fresh.add(DocumentVersion(doc_id=current.id, content=ref, diff='', version_no=1))
                elif veto == 'trash': current.content = ref; current.deleted_at = datetime.now()
                else: current.content = '/attachments/unknown-identifier'
            fresh.commit()
        reconcile(bind, owner, receipt, scope, created, storage)
    monkeypatch.setattr(notes_zip, '_reconcile_failed_files', interleave)
    original = fault_commit(db_session, monkeypatch)
    with pytest.raises(OSError, match='import-commit-outcome'):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    monkeypatch.setattr(db_session, 'commit', original)
    assert len(ids) == 1
    assert (file_storage / str(ids[0])).read_bytes() == b'image'
    assert (file_storage / 'existing').read_bytes() == b'keep'
    with Session(db_session.get_bind()) as fresh:
        assert fresh.query(AppConfig).filter(AppConfig.key.startswith('notes-file-gc:')).count() == 0


def test_zip_failure_does_not_drain_other_import_intents(client, workspace_id, db_session, file_storage, monkeypatch):
    from app.models.config import AppConfig
    other_id = uuid4()
    other = file_storage / str(other_id)
    other.write_bytes(b'other-import')
    intent = {'attachment_id': str(other_id), 'state': 'pending', 'attempts': 0, 'source': 'notes-zip'}
    db_session.add(AppConfig(key='notes-file-gc:' + str(other_id), value=json.dumps(intent)))
    db_session.commit()
    original = fault_commit(db_session, monkeypatch)
    with pytest.raises(OSError, match='import-commit-outcome'):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    monkeypatch.setattr(db_session, 'commit', original)
    assert {p.name for p in file_storage.iterdir()} == {'existing', str(other_id)}
    assert other.read_bytes() == b'other-import'
    with Session(db_session.get_bind()) as fresh:
        assert json.loads(fresh.get(AppConfig, 'notes-file-gc:' + str(other_id)).value) == intent


def test_zip_rollback_failure_retains_original_error_and_files(client, workspace_id, db_session, file_storage, monkeypatch, caplog):
    original = fault_commit(db_session, monkeypatch)
    rollback = db_session.rollback
    monkeypatch.setattr(db_session, 'rollback', lambda: (_ for _ in ()).throw(RuntimeError('rollback-unavailable')))
    try:
        with pytest.raises(OSError, match='import-commit-outcome'):
            post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    finally:
        monkeypatch.setattr(db_session, 'rollback', rollback)
        monkeypatch.setattr(db_session, 'commit', original)
        rollback()
    assert len(list(file_storage.iterdir())) == 2
    assert 'notes_zip_rollback_uncertain' in caplog.text


def test_zip_reconcile_waits_for_real_http_reference_writer(client, workspace_id, db_session, file_storage, monkeypatch):
    """A pre-existing writer commits its reference before the fresh scan.

    Actual authenticated PUT + pg_blocking_pids, not a compiled-lock assertion.
    The candidate came from a failed import, with reconciliation deliberately
    delayed to allow the competing writer to enter first.
    """
    from app.services import notes_zip
    from app.models.config import AppConfig
    doc = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'reference', 'file_path': 'ref.md', 'content': 'before'}).json()
    reconcile = notes_zip._reconcile_failed_files
    captured = []
    monkeypatch.setattr(notes_zip, '_reconcile_failed_files', lambda *args: captured.append(args))
    original = fault_commit(db_session, monkeypatch)
    with pytest.raises(OSError, match='import-commit-outcome'):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    monkeypatch.setattr(db_session, 'commit', original)
    bind, owner, receipt, scope, ids, storage = captured[0]
    # Warm route/client before concurrent work; read current optimistic token.
    token = client.get('/documents/' + doc['id']).json()['updated_at']
    entered, release = Event(), Event()
    pids = []
    def hold_commit():
        pids.append(db_session.execute(text('SELECT pg_backend_pid()')).scalar())
        entered.set()
        assert release.wait(5), 'writer was not released'
        original()
    monkeypatch.setattr(db_session, 'commit', hold_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(client.put, '/documents/' + doc['id'], json={
            'updated_at': token, 'content': '/attachments/' + str(ids[0])})
        assert entered.wait(5)
        cleaner = pool.submit(reconcile, *captured[0])
        waiting = []
        try:
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                with Session(bind) as observer:
                    waiting = observer.execute(text("SELECT pid, wait_event_type, query FROM pg_stat_activity WHERE :holder = ANY(pg_blocking_pids(pid))"), {'holder': pids[0]}).all()
                if waiting: break
                time.sleep(.01)
            assert waiting and all(r.wait_event_type == 'Lock' and 'pg_advisory_xact_lock' in r.query for r in waiting), waiting
        finally:
            release.set()
        response = writer.result(timeout=5)
        assert response.status_code == 200, response.text
        cleaner.result(timeout=5)
    monkeypatch.setattr(db_session, 'commit', original)
    assert (storage / str(ids[0])).read_bytes() == b'image'
    with Session(bind) as fresh:
        assert fresh.get(AppConfig, 'notes-file-gc:' + str(ids[0])) is None
    assert '/attachments/' + str(ids[0]) in client.get('/documents/' + doc['id']).json()['content']


def test_zip_gc_holds_graph_lock_through_unlink(client, workspace_id, db_session, file_storage, monkeypatch):
    from pathlib import Path
    from app.services import notes_zip, attachment_lifecycle
    from app.models.config import AppConfig
    doc = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'writer', 'file_path': 'writer.md', 'content': 'before'}).json()
    reconcile = notes_zip._reconcile_failed_files
    captured = []
    monkeypatch.setattr(notes_zip, '_reconcile_failed_files', lambda *a: captured.append(a))
    original = fault_commit(db_session, monkeypatch)
    with pytest.raises(OSError, match='import-commit-outcome'):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    monkeypatch.setattr(db_session, 'commit', original)
    args = captured[0]
    bind, ident = args[0], args[4][0]
    token = client.get('/documents/' + doc['id']).json()['updated_at']
    entered, release = Event(), Event()
    pids = []
    scan = attachment_lifecycle.referenced_candidates
    def hold_after_scan(db, candidates, **kwargs):
        result = scan(db, candidates, **kwargs)
        if db.get(AppConfig, 'notes-file-gc:' + str(ident)) is not None:
            pids.append(db.execute(text('SELECT pg_backend_pid()')).scalar())
            entered.set()
            assert release.wait(5), 'GC was not released'
        return result
    monkeypatch.setattr(attachment_lifecycle, 'referenced_candidates', hold_after_scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleaner = pool.submit(reconcile, *args)
        assert entered.wait(5)
        writer = pool.submit(client.put, '/documents/' + doc['id'], json={
            'updated_at': token, 'content': '/attachments/' + str(ident)})
        waiting = []
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with Session(bind) as observer:
                    waiting = observer.execute(text("SELECT pid, wait_event_type, query FROM pg_stat_activity WHERE :holder = ANY(pg_blocking_pids(pid))"), {'holder': pids[0]}).all()
                if waiting: break
                time.sleep(.01)
            assert waiting and all(r.wait_event_type == 'Lock' and 'pg_advisory_xact_lock' in r.query for r in waiting), waiting
            assert (file_storage / str(ident)).exists()
            assert not writer.done()
        finally:
            release.set()
        cleaner.result(timeout=5)
        response = writer.result(timeout=5)
        assert response.status_code == 200, response.text
    # Raw references to nonexistent IDs remain allowed, but cannot race the
    # protected scan/unlink interval. No metadata was ever committed for this ID.
    assert not (file_storage / str(ident)).exists()
    with Session(bind) as fresh:
        assert fresh.get(AppConfig, 'notes-file-gc:' + str(ident)) is None
