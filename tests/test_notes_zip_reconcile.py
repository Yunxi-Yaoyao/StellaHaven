"""Real guarded PostgreSQL; fault only the requested boundary, not auth/locks."""
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from tests.test_notes_zip import archive, post_zip, workspace_id


@pytest.fixture
def file_storage(monkeypatch, tmp_path):
    from app.routers import attachment
    monkeypatch.setenv('STELLA_BLOB_STORAGE', 'file')
    monkeypatch.setattr(attachment, 'STORAGE', tmp_path)
    keep = tmp_path / 'existing'
    keep.write_bytes(b'keep')
    return tmp_path


def rows(db):
    from app.models.document import Document
    from app.models.attachment import Attachment
    from app.models.blob import BlobObject, BlobChunk
    with Session(db.get_bind()) as fresh:
        return tuple(fresh.query(cls).count() for cls in (Document, Attachment, BlobObject, BlobChunk))


def fault_commit(db, monkeypatch, durable=False):
    original = db.commit
    def fail():
        if durable:
            original()
        raise OSError('import-commit-outcome')
    monkeypatch.setattr(db, 'commit', fail)
    return original


@pytest.mark.parametrize('mode', ['file', 'postgres'])
@pytest.mark.parametrize('durable', [False, True], ids=['before-commit', 'after-commit'])
def test_zip_commit_boundary_bytes_and_same_key_retry(client, workspace_id, db_session, file_storage, monkeypatch, mode, durable):
    from app.models.attachment import Attachment
    from app.models.config import AppConfig
    from app.services import blob_store
    monkeypatch.setenv('STELLA_BLOB_STORAGE', mode)
    before = rows(db_session)
    key = str(uuid4())
    data = archive([('x.md', '![](pic.png)'), ('pic.png', b'original-bytes')])
    original = fault_commit(db_session, monkeypatch, durable)
    with pytest.raises(OSError, match='import-commit-outcome'):
        post_zip(client, workspace_id, data, import_id=key)
    monkeypatch.setattr(db_session, 'commit', original)
    if not durable:
        assert rows(db_session) == before
        assert sorted(p.name for p in file_storage.iterdir()) == ['existing']
    else:
        with Session(db_session.get_bind()) as fresh:
            att = fresh.query(Attachment).one()
            assert att.filename == 'pic.png'
            if mode == 'file':
                assert (file_storage / str(att.id)).read_bytes() == b'original-bytes'
            else:
                assert b''.join(blob_store.read_range(fresh, 'attachments/' + str(att.id), 0, att.size)) == b'original-bytes'
            assert fresh.query(AppConfig).filter(AppConfig.key.startswith('notes-file-gc:')).count() == 0
    retry = post_zip(client, workspace_id, data, import_id=key)
    assert retry.status_code == 200, retry.text
    assert retry.json()['reused'] is durable
    assert len(retry.json()['documents']) == 1
    attachments = client.get('/attachments/', params={'workspace_id': workspace_id}).json()
    assert len(attachments) == 1
    assert client.get(attachments[0]['url']).content == b'original-bytes'
    assert (file_storage / 'existing').read_bytes() == b'keep'


def test_zip_cleanup_failure_has_durable_intent_and_retry(client, workspace_id, db_session, file_storage, monkeypatch):
    from app.models.config import AppConfig
    from app.services.attachment_lifecycle import drain_file_gc
    before = rows(db_session)
    owner_id = client.get('/auth/me').json()['id']
    key = str(uuid4())
    data = archive([('x.md', '![](pic.png)'), ('pic.png', b'image')])
    original = fault_commit(db_session, monkeypatch)
    unlink = Path.unlink
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', lambda self, *a, **kw: (_ for _ in ()).throw(OSError('unlink-fault')) if self.parent == file_storage and not self.name.startswith('.') else unlink(self, *a, **kw))
        with pytest.raises(OSError, match='import-commit-outcome'):
            post_zip(client, workspace_id, data, import_id=key)
    monkeypatch.setattr(db_session, 'commit', original)
    assert rows(db_session) == before
    with Session(db_session.get_bind()) as fresh:
        intent = fresh.query(AppConfig).filter(AppConfig.key.startswith('notes-file-gc:')).one()
        value = json.loads(intent.value)
        assert value['source'] == 'notes-zip'
        assert value['owner_id'] == owner_id
        assert value['receipt_key'] == hashlib.sha256(f'notes-zip:{owner_id}:{key}'.encode()).hexdigest()
        assert value['scope'] == [workspace_id, None, hashlib.sha256(data).hexdigest(), 'auto']
        assert value['attempts'] == 1 and value['state'] == 'retry'
        orphan = file_storage / value['attachment_id']
        assert orphan.read_bytes() == b'image'
        drain_file_gc(fresh, storage=file_storage)
        drain_file_gc(fresh, storage=file_storage)
    assert sorted(p.name for p in file_storage.iterdir()) == ['existing']
    with Session(db_session.get_bind()) as fresh:
        assert fresh.query(AppConfig).filter(AppConfig.key.startswith('notes-file-gc:')).count() == 0


@pytest.mark.parametrize('durable', [False, True])
def test_zip_fresh_read_failure_preserves_bytes_and_original_error(client, workspace_id, db_session, file_storage, monkeypatch, caplog, durable):
    bind = db_session.get_bind()
    from app.services import notes_zip
    reconcile = notes_zip._reconcile_failed_files
    calls = []
    def record(*args):
        calls.append(args)
        return reconcile(*args)
    monkeypatch.setattr(notes_zip, '_reconcile_failed_files', record)
    original = db_session.commit
    armed = False
    def fail_commit():
        nonlocal armed
        if durable:
            original()
        armed = True
        raise OSError('import-commit-outcome')
    def deny_read(conn, cursor, statement, parameters, context, executemany):
        if armed and statement.lstrip().upper().startswith('SELECT'):
            raise RuntimeError('reconcile-read-unavailable')
    event.listen(bind, 'before_cursor_execute', deny_read)
    monkeypatch.setattr(db_session, 'commit', fail_commit)
    try:
        with pytest.raises(OSError, match='import-commit-outcome'):
            post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    finally:
        event.remove(bind, 'before_cursor_execute', deny_read)
        monkeypatch.setattr(db_session, 'commit', original)
    objects = [p for p in file_storage.iterdir() if p.name != 'existing']
    assert len(objects) == 1 and objects[0].read_bytes() == b'image'
    assert 'notes_zip_file_reconcile_required' in caplog.text
    assert 'notes_zip_file_reconcile_deferred' in caplog.text
    assert len(calls) == 1
    # Explicit reconciliation retry, using this import's retained provenance only.
    reconcile(*calls[0])
    reconcile(*calls[0])
    assert objects[0].exists() is durable
    assert (file_storage / 'existing').read_bytes() == b'keep'


@pytest.mark.parametrize('durable', [False, True])
def test_zip_gc_intent_commit_uncertainty_is_retryable(client, workspace_id, db_session, file_storage, monkeypatch, durable):
    from app.services import notes_zip
    from app.services.attachment_lifecycle import drain_file_gc
    from app.models.config import AppConfig
    reconcile = notes_zip._reconcile_failed_files
    captured = []
    def record(*args):
        captured.append(args)
        return reconcile(*args)
    monkeypatch.setattr(notes_zip, '_reconcile_failed_files', record)
    original = fault_commit(db_session, monkeypatch)
    real_commit = Session.commit
    def uncertain(self):
        if durable:
            real_commit(self)
        raise RuntimeError('intent-commit-outcome')
    with monkeypatch.context() as patch:
        patch.setattr(Session, 'commit', uncertain)
        with pytest.raises(OSError, match='import-commit-outcome'):
            post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    monkeypatch.setattr(db_session, 'commit', original)
    assert len(captured) == 1
    ident = captured[0][4][0]
    path = file_storage / str(ident)
    assert path.read_bytes() == b'image'
    with Session(db_session.get_bind()) as fresh:
        assert (fresh.get(AppConfig, 'notes-file-gc:' + str(ident)) is not None) is durable
    if not durable:
        reconcile(*captured[0])
    else:
        with Session(db_session.get_bind()) as fresh:
            drain_file_gc(fresh, storage=file_storage, object_ids=[ident])
    assert not path.exists()
    assert (file_storage / 'existing').read_bytes() == b'keep'


def test_zip_gc_drain_has_transaction_local_budgets(client, workspace_id, db_session, file_storage, monkeypatch):
    from app.services import attachment_lifecycle
    original_drain = attachment_lifecycle.drain_file_gc
    seen = []
    def inspect_budget(db, **kwargs):
        seen.append(tuple(db.execute(text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")).one()))
        return original_drain(db, **kwargs)
    monkeypatch.setattr(attachment_lifecycle, 'drain_file_gc', inspect_budget)
    original = fault_commit(db_session, monkeypatch)
    with pytest.raises(OSError, match='import-commit-outcome'):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    monkeypatch.setattr(db_session, 'commit', original)
    assert seen == [('2s', '5s')]
    with Session(db_session.get_bind()) as fresh:
        assert tuple(fresh.execute(text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")).one()) == ('0', '0')


def test_zip_precommit_metadata_failure_reclaims_only_published_files(client, workspace_id, db_session, file_storage, monkeypatch):
    from app.models.attachment import Attachment
    before = rows(db_session)
    original = db_session.add
    def fail_add(instance, *args, **kwargs):
        if isinstance(instance, Attachment):
            raise OSError('metadata-add-failure')
        return original(instance, *args, **kwargs)
    monkeypatch.setattr(db_session, 'add', fail_add)
    with pytest.raises(OSError, match='metadata-add-failure'):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    assert rows(db_session) == before
    assert sorted(p.name for p in file_storage.iterdir()) == ['existing']


def test_zip_existing_uuid_collision_never_becomes_gc_candidate(client, workspace_id, db_session, file_storage, monkeypatch):
    from app.services import notes_zip
    doc_id, att_id = uuid4(), uuid4()
    existing = file_storage / str(att_id)
    existing.write_bytes(b'previous-generation')
    ids = iter([doc_id, att_id])
    monkeypatch.setattr(notes_zip, 'uuid4', lambda: next(ids))
    before = rows(db_session)
    with pytest.raises(FileExistsError):
        post_zip(client, workspace_id, archive([('x.md', '![](pic.png)'), ('pic.png', b'image')]))
    assert rows(db_session) == before
    assert existing.read_bytes() == b'previous-generation'
    assert (file_storage / 'existing').read_bytes() == b'keep'


def test_zip_gc_retry_preserves_new_reference(client, workspace_id, db_session, file_storage):
    from app.models.config import AppConfig
    from app.services.attachment_lifecycle import drain_file_gc
    ident = uuid4()
    path = file_storage / str(ident)
    path.write_bytes(b'pending-reconcile')
    # An orphan approved earlier can gain a legacy/raw reference before retry.
    db_session.add(AppConfig(key='notes-file-gc:' + str(ident), value=json.dumps({
        'attachment_id': str(ident), 'attempts': 0, 'state': 'pending', 'source': 'notes-zip'})))
    db_session.commit()
    doc = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'late reference',
        'file_path': 'late.md', 'content': '/attachments/' + str(ident)})
    assert doc.status_code == 201, doc.text
    with Session(db_session.get_bind()) as fresh:
        drain_file_gc(fresh, storage=file_storage)
    assert path.read_bytes() == b'pending-reconcile'
    with Session(db_session.get_bind()) as fresh:
        assert fresh.get(AppConfig, 'notes-file-gc:' + str(ident)) is not None
