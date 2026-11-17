import json
import hashlib
import base64
from uuid import uuid4
from tests_isolated.test_native_nav_pg import lane,pytestmark
from qa.native_nav_synthetic import transfer,PNG


def test_full_package_legacy_owner_bytes_roundtrip_and_atomic_conflict(lane):
    client,factory,uid,other,nav,app=lane
    source=json.dumps(transfer(),ensure_ascii=False)
    before=client.get('/nav-data').json()
    result=client.post('/nav-package-preview',json={'source':source})
    assert result.status_code==200,result.text
    p=result.json();assert p['counts']=={'groups':1,'items':1,'assets':1,'bytes':len(PNG)}
    assert any('openMethod=3' in w and '独立' in w for w in p['warnings'])
    assert p['data']['preferences']['newWindowOpen'] is False
    assert p['data']['preferences']['layout']=='info'  # actual old enum: info=0, icon=1
    assert p['data']['preferences']['widthUnit']=='%'
    assert p['data']['preferences']['defaultEngine']==p['data']['preferences']['engines'][1]['id']
    assert client.get('/nav-data').json()==before and client.get('/nav-assets').json()==[]
    payload={'source':source,'revision':p['revision'],'digest':p['digest'],'mutation_id':str(uuid4()),'confirmed':False}
    assert client.post('/nav-package-import',json=payload).status_code==422
    changed={**before,'mutation_id':str(uuid4())};changed['data']['preferences']['title']='并发写'
    assert client.put('/nav-data',json=changed).status_code==200
    payload['confirmed']=True
    assert client.post('/nav-package-import',json=payload).status_code==409
    assert client.get('/nav-assets').json()==[]
    p=client.post('/nav-package-preview',json={'source':source}).json();payload['revision']=p['revision']
    saved=client.post('/nav-package-import',json=payload)
    assert saved.status_code==200,saved.text
    assert client.post('/nav-package-import',json=payload).json()==saved.json()
    assert client.get('/nav-data').json()==saved.json()
    asset=client.get('/nav-assets').json()[0]
    assert client.get(asset['url']).content==PNG
    assert saved.json()['data']['groups'][0]['items'][0]['openMethod']==2
    exported=client.get('/nav-package').json()
    assert base64.b64decode(exported['assets'][0]['base64'])==PNG
    assert exported['assets'][0]['sha256']==hashlib.sha256(PNG).hexdigest()
    assert 'never-execute' not in json.dumps(exported)
    r=client.post('/nav-package-preview',json={'source':json.dumps(exported)})
    assert r.status_code==200,r.text
    assert r.json()['counts']==p['counts']
    with factory() as db:
        assert db.get(nav.NavState,other) is None
        assert {a.owner_id for a in db.query(nav.NavAsset)}=={uid}
    exported['counts']['bytes']+=1
    assert client.post('/nav-package-preview',json={'source':json.dumps(exported)}).status_code==422


def test_package_invalid_bytes_or_missing_reference_never_write(lane):
    client,*_=lane
    for mutate in [lambda x:x['assets'][0].update(sha256='0'*64),lambda x:x.update(assets=[]),lambda x:x['assets'][0].update(mime='image/svg+xml')]:
        raw=transfer();mutate(raw)
        assert client.post('/nav-package-preview',json={'source':json.dumps(raw)}).status_code in {415,422}
    assert client.get('/nav-data').json()['revision']==0
    assert client.get('/nav-assets').json()==[]


def test_actual_settings_zip_nav_domain_roundtrip_and_rollback(lane,tmp_path,monkeypatch):
    import io,zipfile,pytest
    from sqlalchemy import text
    from app.database import Base
    import app.models
    from app.services.ha_state import metadata
    from app.services.backup_projection import export_settings,restore_settings
    from app.services.backup_archive import create_archive,InvalidArchive
    from app.models.config import AppConfig
    from app.models.user import AuthSession
    monkeypatch.setenv('STELLA_BLOB_STORAGE','postgres');monkeypatch.setenv('STELLA_SHARED_STATE','postgres')
    client,factory,uid,other,nav,app=lane
    engine=factory.kw['bind']
    with engine.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        Base.metadata.create_all(conn);metadata.create_all(conn)
    source=json.dumps(transfer());p=client.post('/nav-package-preview',json={'source':source}).json()
    r=client.post('/nav-package-import',json={'source':source,'digest':p['digest'],'confirmed':True,'revision':0,'mutation_id':str(uuid4())})
    assert r.status_code==200,r.text
    before=client.get('/nav-data').json()
    with factory() as db:
        db.add(AppConfig(key='native-nav-test-private',value='PRIVATE-CONTENT-SENTINEL'));db.commit()
        sessions=[str(s.id) for s in db.query(AuthSession)]
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn,tmp_path) as payload:
            create_archive(tmp_path/'nav-settings.zip',scope='settings',entries=payload.entries,warnings=payload.warnings)
    with zipfile.ZipFile(tmp_path/'nav-settings.zip') as z:
        dto=json.loads(z.read('settings.json'))
        assert len(dto['native_nav'])==1
        assert z.read(dto['native_nav'][0]['assets'][0]['entry'])==PNG
        assert b'PRIVATE-CONTENT-SENTINEL' not in z.read('settings.json')
    changed=client.get('/nav-data').json();changed['data']['preferences']['title']='改后'
    assert client.put('/nav-data',json={**changed,'mutation_id':str(uuid4())}).status_code==200
    restore_settings(engine,tmp_path/'nav-settings.zip')
    after=client.get('/nav-data').json()
    assert after['data']==before['data'] and after['revision']>changed['revision']
    assert client.get(after['data']['preferences']['backgroundUrl']).content==PNG
    with factory() as db:
        assert [str(s.id) for s in db.query(AuthSession)]==sessions
        assert db.get(AppConfig,'native-nav-test-private').value=='PRIVATE-CONTENT-SENTINEL'
    with zipfile.ZipFile(tmp_path/'nav-settings.zip') as z:
        entries={n:io.BytesIO(z.read(n)) for n in z.namelist() if n!='manifest.json'}
    dto['native_nav'][0]['owner_id']=str(other)
    entries['settings.json']=io.BytesIO(json.dumps(dto).encode())
    create_archive(tmp_path/'bad-nav.zip',scope='settings',entries=entries)
    with pytest.raises(InvalidArchive): restore_settings(engine,tmp_path/'bad-nav.zip')
    assert client.get('/nav-data').json()==after
