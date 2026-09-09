"""ZIP integration tests, exclusively conftest's isolated PostgreSQL DB."""
import io
import zipfile
from uuid import uuid4

import pytest


@pytest.fixture
def workspace_id(client):
    response = client.post('/workspaces/', json={'user_id': str(uuid4()), 'name': 'ZIP tests'})
    assert response.status_code == 201
    return response.json()['id']


def archive(items):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for path, body in items:
            z.writestr(path, body)
    return stream.getvalue()


def post_zip(client, workspace_id, data, preview=False, **extra):
    fields = {'workspace_id': workspace_id, **extra}
    if not preview:
        fields.setdefault('import_id', str(uuid4()))
    return client.post('/documents/import/zip' + ('/preview' if preview else ''),
                       data=fields, files={'file': ('notes.zip', data, 'application/zip')})


def test_preview_readonly_tree_readme(client, workspace_id, db_session):
    from app.models.document import Document
    from app.models.attachment import Attachment
    data = archive([('Book/README.md', '目录正文'), ('Book/child.md', 'child'), ('Book/img.png', b'PNG')])
    before = (db_session.query(Document).count(), db_session.query(Attachment).count())
    r = post_zip(client, workspace_id, data, preview=True)
    assert r.status_code == 200, r.text
    assert r.json() == {'entries': [
        {'path': 'Book', 'title': 'Book', 'kind': 'directory', 'parent_path': None},
        {'path': 'Book/child.md', 'title': 'child', 'kind': 'document', 'parent_path': 'Book'},
        {'path': 'Book/img.png', 'title': 'img.png', 'kind': 'attachment', 'parent_path': 'Book'},
    ], 'warnings': [], 'counts': {'documents': 2, 'attachments': 1}}
    assert before == (db_session.query(Document).count(), db_session.query(Attachment).count())


def test_commit_tree_links_files_retry(client, workspace_id, db_session, tmp_path, monkeypatch):
    from app.routers import attachment
    from app.models.document import Document
    monkeypatch.setattr(attachment, 'STORAGE', tmp_path)
    existing = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'Book',
        'file_path': 'existing.md', 'content': 'preserved'}).json()
    body = ('[same](../Other/same.md) [[../Other/same|wiki]] ![pic](img.png)\n'
            '[ref][r]\n[r]: ../Other/same.md\n'
            '```md\n[x](../Other/same.md)\n```\n`[[../Other/same]]`')
    data = archive([('Book/README.md', body), ('Book/same.md', 'local'),
                    ('Other/same.md', 'remote'), ('Book/img.png', b'actual-image-bytes')])
    key = str(uuid4())
    r = post_zip(client, workspace_id, data, import_id=key)
    assert r.status_code == 200, r.text
    result = r.json()
    docs = {d['path']: d for d in result['documents']}
    assert set(docs) == {'Book', 'Book/same.md', 'Other', 'Other/same.md'}
    assert docs['Book']['title'] == 'Book (2)'
    assert docs['Book/same.md']['parent_id'] == docs['Book']['id']
    root = client.get('/documents/' + docs['Book']['id']).json()
    target = '/notes?doc=' + docs['Other/same.md']['id']
    assert root['content'].count(target) == 3
    assert '```md\n[x](../Other/same.md)\n```' in root['content']
    assert '`[[../Other/same]]`' in root['content']
    assert root['visibility'] == 'private' and root['status'] == 'published'
    attachments = client.get('/attachments/', params={'workspace_id': workspace_id}).json()
    assert len(attachments) == result['attachments'] == 1
    att = attachments[0]
    assert att['doc_id'] == root['id']
    assert att['filename'] == 'Book/img.png'
    assert client.get(att['url']).content == b'actual-image-bytes'
    assert att['url'] in root['content']
    before = db_session.query(Document).count()
    retry = post_zip(client, workspace_id, data, import_id=key)
    assert retry.json() == {**result, 'reused': True}
    assert db_session.query(Document).count() == before
    assert post_zip(client, workspace_id, archive([('x.md', 'x')]), import_id=key).status_code == 409
    assert client.get('/documents/' + existing['id']).json()['content'] == 'preserved'


@pytest.mark.parametrize('kind', ['traversal', 'absolute', 'backslash', 'duplicate', 'symlink',
                                  'encrypted', 'unsupported', 'bomb', 'collision', 'invalid', 'unicode_duplicate'])
def test_reject_invalid_archives(client, workspace_id, db_session, kind):
    from app.models.document import Document
    items = [('x.md', 'x')]
    if kind == 'traversal': items = [('../x.md', 'x')]
    if kind == 'absolute': items = [('/x.md', 'x')]
    if kind == 'backslash': items = [('a\\x.md', 'x')]
    if kind == 'duplicate': items = [('x.md', 'x'), ('x.md', 'y')]
    if kind == 'unicode_duplicate': items = [('é.md', 'x'), ('e\u0301.md', 'y')]
    if kind == 'collision': items = [('a', 'x'), ('a/x.md', 'y')]
    if kind == 'symlink':
        info = zipfile.ZipInfo('link.md'); info.create_system = 3
        info.external_attr = 0o120777 << 16
        items = [(info, '/etc/passwd')]
    data = archive(items)
    if kind in ('unsupported', 'bomb'):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_BZIP2 if kind == 'unsupported' else zipfile.ZIP_DEFLATED) as z:
            z.writestr('x.md', 'x' * 100000)
        data = stream.getvalue()
    if kind == 'invalid': data = b'not zip'
    if kind == 'encrypted':
        data = bytearray(data)
        index = data.index(b'PK\x01\x02')
        data[index + 8] |= 1
        data = bytes(data)
    before = db_session.query(Document).count()
    for preview in (True, False):
        response = post_zip(client, workspace_id, data, preview=preview)
        assert response.status_code in (400, 413), response.text
    assert db_session.query(Document).count() == before


@pytest.mark.parametrize('kind', ['foreign_workspace', 'foreign_parent', 'other_workspace', 'missing', 'deleted'])
def test_zip_permissions(client, workspace_id, db_session, kind):
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.document import Document
    from uuid import UUID
    from datetime import datetime
    ws = client.post('/workspaces/', json={'user_id': str(uuid4()), 'name': 'Other'}).json()['id']
    parent = client.post('/documents/', json={'workspace_id': ws, 'title': 'parent', 'file_path': 'p.md'}).json()['id']
    request_ws = workspace_id
    if kind.startswith('foreign'):
        foreign = User(username='foreign_' + uuid4().hex, display_name='Foreign')
        db_session.add(foreign); db_session.flush()
        db_session.get(Workspace, UUID(ws)).user_id = foreign.id
        db_session.commit()
        if kind == 'foreign_workspace': request_ws = ws
    if kind == 'missing': parent = str(uuid4())
    if kind == 'deleted':
        parent = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'deleted', 'file_path': 'd.md'}).json()['id']
        db_session.get(Document, UUID(parent)).deleted_at = datetime.now()
        db_session.commit()
    before = db_session.query(Document).count()
    for preview in (True, False):
        assert post_zip(client, request_ws, archive([('a.md', 'x')]), preview=preview, parent_id=parent).status_code == 404
    assert db_session.query(Document).count() == before


@pytest.mark.parametrize('encoding', ['auto', 'gb18030', 'utf8', 'bom'])
def test_zip_encoding_and_parent(client, workspace_id, encoding):
    parent = client.post('/documents/', json={'workspace_id': workspace_id, 'title': 'target', 'file_path': 'p.md'}).json()['id']
    text = '中文正文'
    data = archive([('中文.md', text.encode('gb18030' if encoding in ('auto', 'gb18030') else 'utf-8-sig'))])
    result = post_zip(client, workspace_id, data, parent_id=parent, encoding=encoding)
    assert result.status_code == 200, result.text
    doc = result.json()['documents'][0]
    assert doc['parent_id'] == parent
    assert client.get('/documents/' + doc['id']).json()['content'] == text


def test_failure_cleans_only_new_files(client, workspace_id, db_session, tmp_path, monkeypatch):
    from app.routers import attachment
    from app.models.document import Document
    monkeypatch.setattr(attachment, 'STORAGE', tmp_path)
    keep = tmp_path / 'existing'; keep.write_bytes(b'keep')
    before = db_session.query(Document).count()
    def fail(): raise OSError('injected commit failure')
    monkeypatch.setattr(db_session, 'commit', fail)
    with pytest.raises(OSError, match='injected commit failure'):
        post_zip(client, workspace_id, archive([('x.md', '![pic](pic.png)'), ('pic.png', b'image')]))
    assert db_session.query(Document).count() == before
    assert list(tmp_path.iterdir()) == [keep]
    assert keep.read_bytes() == b'keep'


def test_duplicate_readme_and_empty_zip_rejected(client, workspace_id):
    for data in (archive([('a/README.md', ''), ('a/readme.md', 'body')]), archive([])):
        assert post_zip(client, workspace_id, data, preview=True).status_code == 400
        assert post_zip(client, workspace_id, data).status_code == 400


@pytest.mark.parametrize('limit', ['MAX_COMPRESSED', 'MAX_TOTAL', 'MAX_FILE', 'MAX_ENTRIES'])
def test_zip_limits(client, workspace_id, monkeypatch, limit):
    from app.services import notes_zip
    monkeypatch.setattr(notes_zip, limit, 1)
    data = archive([('a.md', 'body'), ('b.md', 'body')])
    for preview in (True, False):
        assert post_zip(client, workspace_id, data, preview=preview).status_code == 413
