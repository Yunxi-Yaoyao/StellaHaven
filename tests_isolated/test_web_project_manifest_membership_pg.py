"""Manifest membership precedes path validation; owned disposable PG only."""
import io
import json
import zipfile
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes


def create_project(db, notes):
    from app.services import web_projects as projects
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('index.html', '<p>fixture</p>')
        bundle.writestr('assets/app.js', 'window.fixture = true;')
    return projects.create(db, notes.uid, notes.wid, None, uuid4(),
                           archive.getvalue(), 'fixture.zip', 'index.html')['id']


def snapshot(db, model):
    return {str(row.id if hasattr(row, 'id') else row.key):
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in db.query(model).all()}


@pytest.mark.parametrize('outside', [
    'invalid-sibling', 'invalid-ancestor', 'deep-sibling', 'deep-ancestor',
    'cycle', 'invalid-cycle', 'other-project', 'nested-project',
])
def test_manifest_and_launch_ignore_unrelated_paths(notes, monkeypatch, outside):
    from app.models.config import AppConfig
    from app.models.document import Document
    from app.services import web_projects as projects, web_project_runtime as runtime
    from app.routers.web_projects import router
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id': 'stella', 'public': 'https://stella.test'},
        {'service_id': 'web-project-runtime', 'public': 'https://pages.test'},
    ]))
    notes.client.app.include_router(router)
    with Session(notes.engine) as db:
        root = create_project(db, notes)
        expected = projects.manifest(db, notes.uid, root)
        if outside.startswith('invalid-') and outside != 'invalid-cycle':
            node = projects.new_doc(db, notes.wid, None, 'ordinary/folder', folder=True)
            if outside == 'invalid-ancestor':
                db.get(Document, root).parent_id = node.id
        elif outside.startswith('deep-'):
            parent = None
            for _ in range(35):
                parent = projects.new_doc(db, notes.wid, parent, 'ordinary', folder=True).id
            if outside == 'deep-ancestor':
                db.get(Document, root).parent_id = parent
        elif outside in {'cycle', 'invalid-cycle'}:
            first = projects.new_doc(db, notes.wid, None, 'cycle', folder=True)
            second = projects.new_doc(db, notes.wid, first.id,
                                      'invalid/name' if outside == 'invalid-cycle' else 'cycle', folder=True)
            first.parent_id = second.id
        else:
            other = create_project(db, notes)
            other_root = db.get(Document, other)
            other_root.title = 'other/project'
            if outside == 'nested-project':
                other_root.parent_id = root
            parent = other
            for _ in range(35):
                parent = projects.new_doc(db, notes.wid, parent, 'other', folder=True).id
            projects.new_doc(db, notes.wid, parent, 'invalid/name', folder=True)
        db.commit()
        documents, configs = snapshot(db, Document), snapshot(db, AppConfig)
        assert projects.manifest(db, notes.uid, root) == expected
        assert snapshot(db, Document) == documents
        assert snapshot(db, AppConfig) == configs
    url = 'https://stella.test/web-projects/' + str(root)
    response = notes.client.get(url)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    response = notes.client.post(url + '/launch', headers={'Origin': 'https://stella.test'})
    assert response.status_code == 200, response.text
    with Session(notes.engine) as db:
        assert snapshot(db, Document) == documents
        grant = response.json()
        body, mime, _ = runtime.resource(db, grant['capability'], 'https://pages.test', 'assets/app.js')
        assert body == b'window.fixture = true;' and mime == 'text/javascript; charset=utf-8'
        assert projects.manifest(db, notes.uid, root) == expected


@pytest.mark.parametrize('kind', ['file', 'directory'])
@pytest.mark.parametrize('name', ['', '.', '..', 'a/b', 'a\\b', 'nul\x00name'])
def test_member_path_names_still_fail_closed(notes, kind, name):
    from app.models.document import Document
    from app.services import web_projects as projects
    with Session(notes.engine) as db:
        root = create_project(db, notes)
        baseline = projects.manifest(db, notes.uid, root)
        item = (baseline['files'][0] if kind == 'file' else baseline['directories'][0])
        db.get(Document, UUID(item['id'])).title = name
        # PostgreSQL cannot persist NUL; check that guard without flushing it.
        with db.no_autoflush, pytest.raises(HTTPException) as error:
            projects.manifest(db, notes.uid, root)
        assert error.value.status_code == 409
        assert error.value.detail == '网页文件名不符合路径规则'
        db.rollback()
        assert projects.manifest(db, notes.uid, root) == baseline


@pytest.mark.parametrize('depth', [32, 33])
def test_member_relative_depth_limit_is_preserved(notes, depth):
    from app.models.document import Document
    from app.services import web_projects as projects
    with Session(notes.engine) as db:
        root = create_project(db, notes)
        info = projects.manifest(db, notes.uid, root)
        source = UUID(next(f['id'] for f in info['files'] if f['path'] == 'assets/app.js'))
        parent = root
        for _ in range(depth - 1):
            parent = projects.new_doc(db, notes.wid, parent, 'level', folder=True).id
        db.get(Document, source).parent_id = parent
        db.commit()
        if depth == 33:
            with pytest.raises(HTTPException) as error:
                projects.manifest(db, notes.uid, root)
            assert error.value.status_code == 409
            assert error.value.detail == '网页文件层级过深'
        else:
            path = '/'.join(['level'] * (depth - 1) + ['app.js'])
            assert projects.read_file(db, notes.uid, root, path)[0] == b'window.fixture = true;'


@pytest.mark.parametrize('boundary', [
    'deleted-file', 'deleted-directory', 'cycle', 'moved-out', 'missing-file',
    'cross-workspace-file', 'cross-workspace-directory', 'other-project',
])
def test_stale_file_metadata_never_bypasses_membership(notes, boundary):
    from app.models.config import AppConfig
    from app.models.document import Document
    from app.models.workspace import Workspace
    from app.services import web_projects as projects
    from app.routers.web_projects import router
    notes.client.app.include_router(router)
    with Session(notes.engine) as db:
        root = create_project(db, notes)
        info = projects.manifest(db, notes.uid, root)
        source = UUID(next(f['id'] for f in info['files'] if f['path'] == 'assets/app.js'))
        file = db.get(Document, source)
        directory = db.get(Document, file.parent_id)
        if boundary == 'deleted-file':
            file.deleted_at = notes.now
        elif boundary == 'deleted-directory':
            directory.deleted_at = notes.now
        elif boundary == 'cycle':
            directory.parent_id = file.id
        elif boundary == 'moved-out':
            file.parent_id = notes.did
        elif boundary == 'missing-file':
            db.delete(file)
        elif boundary.startswith('cross-workspace-'):
            other_workspace = Workspace(id=uuid4(), user_id=notes.uid, name='other')
            db.add(other_workspace)
            db.flush()
            (file if boundary.endswith('-file') else directory).workspace_id = other_workspace.id
        else:
            other = create_project(db, notes)
            db.get(Document, other).parent_id = root
            directory.parent_id = other
        db.commit()
        documents, configs = snapshot(db, Document), snapshot(db, AppConfig)
        actual = projects.manifest(db, notes.uid, root)
        assert {f['path'] for f in actual['files']} == {'index.html'}
        assert str(source) not in {f['id'] for f in actual['files']}
        expected_dirs = {'assets'} if boundary in {
            'deleted-file', 'moved-out', 'missing-file', 'cross-workspace-file',
        } else set()
        assert {d['path'] for d in actual['directories']} == expected_dirs
        with pytest.raises(HTTPException) as error:
            projects.read_file(db, notes.uid, root, 'assets/app.js')
        assert error.value.status_code == 404
        assert snapshot(db, Document) == documents
        assert snapshot(db, AppConfig) == configs
    response = notes.client.get('/web-projects/' + str(root) + '/files/' + str(source))
    assert response.status_code == 404, response.text
