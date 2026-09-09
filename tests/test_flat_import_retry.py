from uuid import uuid4
import pytest
from tests.test_notes_zip import workspace_id


def test_flat_retry_returns_original_without_overwrite(client, workspace_id):
    path = '/imports/' + uuid4().hex + '/a.md'
    payload = {'workspace_id': workspace_id, 'title': 'a', 'file_path': path, 'content': 'original'}
    first = client.post('/documents/', json=payload, headers={'X-Import-Key': path})
    assert first.status_code == 201
    doc = first.json()
    saved = client.put('/documents/' + doc['id'], json={'updated_at': doc['updated_at'], 'content': 'user edit'})
    assert saved.status_code == 200
    retry = client.post('/documents/', json=payload, headers={'X-Import-Key': path})
    assert retry.status_code == 201
    assert retry.json()['id'] == doc['id']
    assert retry.json()['content'] == 'user edit'
    ordinary = client.post('/documents/', json=payload)
    assert ordinary.status_code == 201
    assert ordinary.json()['id'] != doc['id']


@pytest.mark.parametrize('key,path', [('/imports/a/x.md', '/imports/b/x.md'), ('/other/x.md', '/other/x.md'), ('/imports/' + 'a' * 1024, '/imports/' + 'a' * 1024)])
def test_invalid_flat_import_key(client, workspace_id, key, path):
    response = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'a', 'file_path': path}, headers={'X-Import-Key': key})
    assert response.status_code == 400
