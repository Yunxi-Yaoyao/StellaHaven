"""Review regressions; nonce-owned PostgreSQL only, no production state."""
import io
import json
import zipfile
from uuid import uuid4
import pytest
from tests_isolated.test_native_nav_pg import lane, pytestmark


def boundary_data():
    from app.schemas.native_nav import NavData
    from app.services.native_nav_package import canonical
    data=NavData().model_dump(mode='json')
    data['groups']=[{'id':str(uuid4()),'title':str(g),'items':[{'id':str(uuid4()),'title':'bounded','url':'https://example.test','description':'x'*820} for _ in range(500)]} for g in range(4)]
    data=NavData.model_validate(data).model_dump(mode='json')
    add=(2*1024**2-len(canonical(data).encode())-100)//2000
    for g in data['groups']:
        for c in g['items']: c['description']+='x'*add
    assert len(canonical(data).encode())==2_096_960
    assert len(json.dumps(data,ensure_ascii=False).encode())==2_129_069
    return data


def fresh(factory,nav,uid):
    with factory() as db:
        r=db.get(nav.NavState,uid)
        return (None if r is None else (r.data,r.revision,r.mutation_id,r.mutation_hash),[(str(a.id),a.content) for a in db.query(nav.NavAsset)])


def settings_zip(lane,tmp_path,monkeypatch,data):
    from sqlalchemy import text
    from app.database import Base
    import app.models
    from app.services.ha_state import metadata
    from app.services.backup_projection import export_settings
    from app.services.backup_archive import create_archive
    monkeypatch.setenv('STELLA_BLOB_STORAGE','postgres');monkeypatch.setenv('STELLA_SHARED_STATE','postgres')
    client,factory,uid,other,nav,app=lane
    engine=factory.kw['bind']
    with engine.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        Base.metadata.create_all(conn);metadata.create_all(conn)
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn,tmp_path) as payload:
            create_archive(tmp_path/'seed.zip',scope='settings',entries=payload.entries,warnings=payload.warnings)
    with zipfile.ZipFile(tmp_path/'seed.zip') as z:
        entries={n:io.BytesIO(z.read(n)) for n in z.namelist() if n!='manifest.json'}
    dto=json.loads(entries['settings.json'].getvalue())
    # This valid replacement intentionally has no assets: remove the old domain
    # resource entries too, so rejection cannot be an orphan-manifest false RED.
    entries={k:v for k,v in entries.items() if not k.startswith('resources/native-nav/')}
    dto['native_nav']=[{'owner_id':str(uid),'data':data,'assets':[]}]
    entries['settings.json']=io.BytesIO(json.dumps(dto).encode())
    path=tmp_path/'review.zip';create_archive(path,scope='settings',entries=entries)
    return path


def test_review_oversize_import_and_settings_restore_are_atomic(lane,tmp_path,monkeypatch):
    from app.services.native_nav_package import package,sha
    from app.services.backup_projection import restore_settings
    from app.services.backup_archive import InvalidArchive
    client,factory,uid,other,nav,app=lane
    seed=client.get('/nav-data').json()
    assert client.put('/nav-data',json={**seed,'mutation_id':str(uuid4())}).status_code==200
    from qa.native_nav_synthetic import PNG
    from types import SimpleNamespace
    assert client.post('/nav-assets',files={'file':('retained.png',PNG,'image/png')}).status_code==200
    data=boundary_data()
    for g in data['groups']:
        for c in g['items']: c['description']+='xx'
    before=fresh(factory,nav,uid)
    candidate=SimpleNamespace(id=uuid4(),name='not-imported.png',mime='image/png',size=len(PNG),content=PNG,category='icon')
    source=json.dumps(package(data,[candidate]))
    assert client.post('/nav-package-preview',json={'source':source}).status_code==413
    assert client.post('/nav-package-import',json={'source':source,'digest':sha(source.encode()),'confirmed':True,'revision':1,'mutation_id':str(uuid4())}).status_code==413
    assert client.put('/nav-data',json={'data':data,'revision':1,'mutation_id':str(uuid4())}).status_code==413
    assert fresh(factory,nav,uid)==before
    archive=settings_zip(lane,tmp_path,monkeypatch,data)
    before=fresh(factory,nav,uid)
    with pytest.raises(InvalidArchive): restore_settings(factory.kw['bind'],archive)
    assert fresh(factory,nav,uid)==before


def test_review_admitted_boundary_restore_is_ordinary_saveable(lane,tmp_path,monkeypatch):
    from app.services.backup_projection import restore_settings
    client,factory,uid,other,nav,app=lane
    data=boundary_data()
    archive=settings_zip(lane,tmp_path,monkeypatch,data)
    restore_settings(factory.kw['bind'],archive)
    read=client.get('/nav-data').json()
    assert read['data']==data
    result=client.put('/nav-data',json={**read,'mutation_id':str(uuid4())})
    assert result.status_code==200,result.text[:300]
    assert client.get('/nav-data').json()==result.json()
    assert fresh(factory,nav,uid)[0][0]==data
