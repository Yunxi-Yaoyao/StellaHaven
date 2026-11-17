"""Original case ID retained; approved owner-delete/elevated-restore contract."""
from uuid import uuid4
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.database import get_db
from app.models import Document
from app.routers import document
from app.routers.auth import current_user


def test_destructive_notes_routes_require_elevation(db, workspace, make_doc):
    d = make_doc()
    doc_id, ws_id = d.id, workspace.id
    app = FastAPI(); app.include_router(document.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    # Only these operations retain elevation under the approved contract.
    for path in ['/documents/clear-all?workspace_id=' + str(ws_id),
                 '/documents/' + str(doc_id) + '/restore']:
        assert client.post(path).status_code == 403, path
    assert client.put('/documents/' + str(doc_id), json={'updated_at': d.updated_at.isoformat(), 'title': 'ordinary edit'}).status_code == 200
    denied_paths = [('delete', '/documents/' + str(doc_id)),
                    ('delete', '/documents/' + str(doc_id) + '/permanent'),
                    ('post', '/documents/trash/empty?workspace_id=' + str(ws_id))]
    # Authentication and ownership are not relaxed with the elevation removal.
    def anonymous():
        raise HTTPException(401, 'authentication required')
    app.dependency_overrides[current_user] = anonymous
    for method, path in denied_paths:
        assert getattr(client, method)(path).status_code == 401, path
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uuid4(), is_admin=True)
    for method, path in denied_paths:
        assert getattr(client, method)(path).status_code == 404, path
    db.expire_all()
    assert db.get(Document, doc_id).deleted_at is None
    app.dependency_overrides.pop(current_user)
    assert client.delete('/documents/' + str(doc_id)).status_code == 204
    db.expire_all()
    assert db.get(Document, doc_id).deleted_at is not None
    # Repetition remains idempotent; no elevation bypass permits restoration.
    assert client.delete('/documents/' + str(doc_id)).status_code == 204
    assert client.post('/documents/' + str(doc_id) + '/restore').status_code == 403
    assert client.post('/documents/trash/empty?workspace_id=' + str(ws_id)).json() == {'purged': 1}
    db.expire_all()
    assert db.get(Document, doc_id) is None
    assert client.post('/documents/trash/empty?workspace_id=' + str(ws_id)).json() == {'purged': 0}
