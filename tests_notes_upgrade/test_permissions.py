from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.routers import document


def test_destructive_notes_routes_require_elevation(db, workspace, make_doc):
    d = make_doc()
    app = FastAPI(); app.include_router(document.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    for method, path in [('post', '/documents/clear-all?workspace_id=' + str(workspace.id)),
                         ('post', '/documents/trash/empty?workspace_id=' + str(workspace.id)),
                         ('delete', '/documents/' + str(d.id)),
                         ('post', '/documents/' + str(d.id) + '/restore')]:
        assert getattr(client, method)(path).status_code == 403, path
    assert client.put('/documents/' + str(d.id), json={'updated_at': d.updated_at.isoformat(), 'title': 'ordinary edit'}).status_code == 200
