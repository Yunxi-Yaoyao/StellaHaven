from uuid import UUID, uuid4

from tests.test_notes_zip import archive, post_zip, workspace_id


def test_import_put_preserves_exact_backlinks(client, workspace_id, db_session):
    from app.models.document_link import DocumentLink
    data = archive([('a.md', '[b](b.md)'), ('b.md', 'target')])
    result = post_zip(client, workspace_id, data)
    assert result.status_code == 200, result.text
    docs = {d['path']: d for d in result.json()['documents']}
    source = client.get('/documents/' + docs['a.md']['id']).json()
    target = UUID(docs['b.md']['id'])
    foreign_ws = client.post('/workspaces/', json={'name': 'other', 'user_id': str(uuid4())}).json()['id']
    foreign = client.post('/documents/', json={'workspace_id': foreign_ws, 'title': 'b', 'file_path': 'b.md'}).json()['id']
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.document import Document
    from datetime import datetime
    outsider = User(username='outsider_' + uuid4().hex, display_name='Outside')
    db_session.add(outsider); db_session.flush()
    db_session.get(Workspace, UUID(foreign_ws)).user_id = outsider.id
    deleted = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'deleted', 'file_path': 'deleted.md'}).json()['id']
    db_session.get(Document, UUID(deleted)).deleted_at = datetime.now()
    code = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'code', 'file_path': 'code.md'}).json()['id']
    db_session.commit()
    body = source['content'] + f'\n[foreign](/notes?doc={foreign})\n[deleted](/notes?doc={deleted})\n`[code](/notes?doc={code})`'
    response = client.put('/documents/' + source['id'], json={'updated_at': source['updated_at'], 'content': body})
    assert response.status_code == 200, response.text
    links = db_session.query(DocumentLink).filter(DocumentLink.source_id == UUID(source['id'])).all()
    assert {(l.target_id, l.link_type) for l in links} == {(target, 'ref')}
    response = client.put('/documents/' + source['id'], json={'updated_at': response.json()['updated_at'], 'content': 'removed'})
    assert response.status_code == 200
    assert not db_session.query(DocumentLink).filter(DocumentLink.source_id == UUID(source['id'])).all()
