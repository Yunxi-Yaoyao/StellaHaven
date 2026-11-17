"""Notes classification is independent of manifest path/resource validation."""
import json
from uuid import UUID, uuid4
import pytest
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes
from test_web_project_manifest_membership_pg import create_project, snapshot

def test_identity_index_carries_authoritative_image_drag_paths_without_full_manifest(notes):
    import io, zipfile
    from app.services import web_projects as projects
    from app.routers.web_projects import router
    notes.client.app.include_router(router)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        archive.writestr('index.html', '<p>fixture</p>')
        archive.writestr('images/cat.png', b'fixture image')
    with Session(notes.engine) as db:
        root = projects.create(db, notes.uid, notes.wid, None, uuid4(), raw.getvalue(), 'image.zip', 'index.html')['id']
        info = projects.manifest(db, notes.uid, root)
        image = next(f for f in info['files'] if f['path'] == 'images/cat.png')
        # An unrelated bad member must not block the image identity hint either.
        from app.models.document import Document
        db.get(Document, UUID(next(f['id'] for f in info['files'] if f['path']=='index.html'))).title = 'bad/name'
        db.commit()
    response = notes.client.get(f'/web-projects/workspace/{notes.wid}/identities')
    assert response.status_code == 200
    assert response.json()[0]['assets'] == [{'root':str(root),'file':image['id'],'path':'images/cat.png','mime':'image/png'}]

def test_identity_index_keeps_nested_live_members_workspace_scoped_and_owner_only(notes):
    from app.models.document import Document
    from app.models.workspace import Workspace
    from app.models.user import User
    from app.services import web_projects as projects
    from app.routers.web_projects import router
    notes.client.app.include_router(router)
    with Session(notes.engine) as db:
        root = create_project(db, notes)
        nested = create_project(db, notes)
        db.get(Document, nested).parent_id = root
        nested_info = projects.manifest(db, notes.uid, nested)
        deleted = projects.new_doc(db, notes.wid, root, 'deleted').id
        db.get(Document, deleted).deleted_at = notes.now
        other_workspace = Workspace(id=uuid4(), user_id=notes.uid, name='other')
        foreign_owner = User(id=uuid4(), username='foreign', display_name='Foreign fixture')
        db.add_all([other_workspace, foreign_owner]);db.flush()
        foreign = Workspace(id=uuid4(), user_id=foreign_owner.id, name='foreign')
        db.add(foreign);db.flush()
        outside = projects.new_doc(db, other_workspace.id, None, 'outside').id
        db.commit()
        other_id,foreign_id=other_workspace.id,foreign.id
    response = notes.client.get(f'/web-projects/workspace/{notes.wid}/identities')
    assert response.status_code == 200
    identities = {p['id']: set(p['members']) for p in response.json()}
    assert identities[str(nested)] == {str(nested)} | {f['id'] for f in nested_info['files']} | {d['id'] for d in nested_info['directories']}
    assert identities[str(root)].isdisjoint(identities[str(nested)])
    assert str(deleted) not in set.union(*identities.values())
    assert str(outside) not in set.union(*identities.values())
    assert notes.client.get(f'/web-projects/workspace/{other_id}/identities').json() == []
    assert notes.client.get(f'/web-projects/workspace/{foreign_id}/identities').status_code == 404

@pytest.mark.parametrize('damage', ['path', 'metadata'])
def test_identity_index_survives_broken_project_and_remains_readonly(notes, damage):
    from app.routers.web_projects import router
    from app.models.document import Document
    from app.models.config import AppConfig
    from app.services import web_projects as projects
    notes.client.app.include_router(router)
    with Session(notes.engine) as db:
        root = create_project(db, notes)
        manifest = projects.manifest(db, notes.uid, root)
        member = UUID(manifest['files'][0]['id'])
        if damage == 'path':
            db.get(Document, member).title = 'bad/name'
        else:
            db.get(AppConfig, projects.PREFIX + str(root)).value = '{broken'
        # Even an unregistered child is protected by authoritative ancestry.
        child = projects.new_doc(db, notes.wid, root, 'extensionless').id
        db.commit()
        before = snapshot(db, Document), snapshot(db, AppConfig)
    response = notes.client.get(f'/web-projects/workspace/{notes.wid}/identities')
    assert response.status_code == 200, response.text
    assert response.json() == [{'id': str(root), 'workspace_id': str(notes.wid),
        'members': sorted([str(root), str(child)] + [f['id'] for f in manifest['files']] + [d['id'] for d in manifest['directories']])}]
    assert str(notes.did) not in response.json()[0]['members']
    broken = notes.client.get(f'/web-projects/{root}')
    assert broken.status_code == 409
    assert broken.json()['detail'] == ('网页文件名不符合路径规则' if damage == 'path' else '网页项目元数据损坏，请检查此项目')
    with Session(notes.engine) as db:
        assert (snapshot(db, Document), snapshot(db, AppConfig)) == before
    assert notes.client.get(f'/documents/{notes.did}').status_code == 200
    assert notes.client.get(f'/web-projects/workspace/{uuid4()}/identities').status_code == 404
    notes.client.cookies.clear()
    assert notes.client.get(f'/web-projects/workspace/{notes.wid}/identities').status_code == 401
