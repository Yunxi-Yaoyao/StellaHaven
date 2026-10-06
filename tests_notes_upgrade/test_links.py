from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.models import DocumentLink, Workspace
from app.routers import document_link


def client_for(db):
    app = FastAPI(); app.include_router(document_link.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_graph_is_workspace_scoped_and_requires_scope(db, workspace, make_doc):
    a = make_doc(); b = make_doc()
    other = Workspace(id=uuid4(), name='other', user_id=uuid4()); db.add(other); db.commit()
    c = make_doc(); c.workspace_id = other.id; db.commit()
    db.add_all([DocumentLink(source_id=a.id, target_id=b.id, link_type='wiki'), DocumentLink(source_id=a.id, target_id=c.id, link_type='wiki')]); db.commit()
    client = client_for(db)
    r = client.get('/document-links/', params={'workspace_id': str(workspace.id)})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert client.get('/document-links/').status_code == 422
    assert client.get('/document-links/', params={'workspace_id': str(other.id)}).status_code == 404


def test_link_cannot_reference_other_workspace(db, workspace, make_doc):
    a = make_doc(); b = make_doc()
    other = Workspace(id=uuid4(), name='other', user_id=workspace.user_id); db.add(other); db.commit()
    b.workspace_id = other.id; db.commit()
    r = client_for(db).post('/document-links/', json={'source_id': str(a.id), 'target_id': str(b.id), 'link_type': 'ref'})
    assert r.status_code == 404
    assert db.query(DocumentLink).count() == 0
