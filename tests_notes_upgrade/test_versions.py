from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.models.document_version import DocumentVersion
from app.schemas.document import DocumentUpdate
from app.services.document import update_document
from app.routers import document_version


def test_save_snapshots_baseline_and_checkpoints_not_each_edit(db, make_doc):
    d = make_doc(updated_at=datetime.now())
    update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, content='after'))
    rows = db.query(DocumentVersion).order_by(DocumentVersion.version_no).all()
    assert [r.content for r in rows] == ['before', 'after']
    update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, content='after!'))
    assert db.query(DocumentVersion).count() == 2
    latest = rows[-1]; latest.created_at = datetime.now() - timedelta(minutes=6); db.commit()
    update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, content='after!!'))
    assert db.query(DocumentVersion).count() == 3


def test_conflict_has_no_snapshot_side_effect(db, make_doc):
    d = make_doc(updated_at=datetime.now())
    try:
        update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at - timedelta(seconds=1), content='conflict'))
    except ValueError:
        pass
    assert db.query(DocumentVersion).count() == 0
    assert d.content == 'before'


def test_restore_does_not_repeat_attachment_cleanup(db, make_doc, monkeypatch):
    from app.routers import attachment
    calls = []
    monkeypatch.setattr(attachment, 'cleanup_unreferenced', lambda *a: calls.append(a))
    d = make_doc()
    update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, content='restored'), force_version=True)
    assert calls == []


def test_diff_restore_permissions_and_optimistic_token(db, make_doc):
    d = make_doc(updated_at=datetime.now())
    update_document(db, d.id, DocumentUpdate(updated_at=d.updated_at, content='after'))
    v = db.query(DocumentVersion).order_by(DocumentVersion.version_no).first()
    assert v is not None
    app = FastAPI(); app.include_router(document_version.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    r = client.get(f'/document-versions/{v.id}/diff')
    assert r.status_code == 200, r.text
    assert '-before' in r.json()['diff'] and '+after' in r.json()['diff']
    r = client.post(f'/document-versions/{v.id}/restore', json={'updated_at': d.updated_at.isoformat()})
    assert r.status_code == 403
    from app.routers.auth import admin_user, current_user
    app.dependency_overrides[admin_user] = current_user
    stale = (d.updated_at - timedelta(seconds=1)).isoformat()
    assert client.post(f'/document-versions/{v.id}/restore', json={'updated_at': stale}).status_code == 409
    r = client.post(f'/document-versions/{v.id}/restore', json={'updated_at': d.updated_at.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()['content'] == 'before'
    assert db.query(DocumentVersion).count() == 3
    assert client.get(f'/document-versions/{v.id}/diff', params={'against': '00000000-0000-0000-0000-000000000000'}).status_code == 404
