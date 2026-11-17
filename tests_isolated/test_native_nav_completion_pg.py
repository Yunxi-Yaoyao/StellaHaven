"""New completion paths only; do not repeat closed R1/R2/R3 review."""
import json
import os
import pytest
from pathlib import Path
from uuid import uuid4
from tests_isolated.test_native_nav_pg import lane,pytestmark


def test_legacy_empty_search_config_is_valid_first_use(lane):
    from qa.native_nav_synthetic import transfer
    client,*_=lane
    raw=transfer();raw['userConfig']['searchEngine']={}
    response=client.post('/nav-package-preview',json={'source':json.dumps(raw)})
    assert response.status_code==200  # no response body: private source must never leak
    assert response.json()['data']['preferences']['engines']==[]


def test_navigation_ws_authorizes_revision_changes_and_revocation(lane,monkeypatch):
    import pytest
    from starlette.websockets import WebSocketDisconnect
    from app.services import request_security
    from app.models.user import AuthSession
    client,factory,uid,other,nav,app=lane
    if hasattr(nav,'events_router'):app.include_router(nav.events_router)
    monkeypatch.setattr(request_security,'trusted_origins',lambda:{'https://nav-qa.test'})
    # Valid session alone never authorizes an untrusted/missing Origin or query.
    for path,headers in [('/ws/native-nav/changes',{'Origin':'https://evil.test'}),('/ws/native-nav/changes',{}),('/ws/native-nav/changes?owner=other',{'Origin':'https://nav-qa.test'})]:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path,headers=headers):pass
    with client.websocket_connect('/ws/native-nav/changes',headers={'Origin':'https://nav-qa.test'}) as ws:
        assert ws.receive_json()=={'type':'nav_revision','revision':0}
        body=client.get('/nav-data').json();body['data']['preferences']['title']='another-tab'
        assert client.put('/nav-data',json={**body,'mutation_id':str(uuid4())}).status_code==200
        assert ws.receive_json()=={'type':'nav_revision','revision':1}
        with factory() as db:
            for row in db.query(AuthSession).filter(AuthSession.user_id==uid):row.revoked=True
            db.commit()
        with pytest.raises(WebSocketDisconnect):ws.receive_json()
    for headers in ({'Origin':'https://evil.test'},{'Origin':'https://nav-qa.test'}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/native-nav/changes',headers=headers):pass


def test_package_explicit_module_rebinding_is_atomic_and_receipt_bound(lane,monkeypatch):
    from qa.native_nav_synthetic import transfer
    from app.services import integrations
    client,*_=lane
    monkeypatch.setattr(integrations,'state',lambda db:{'modules':{'docs':{'name':'Docs'}}})
    source=json.dumps(transfer());preview=client.post('/nav-package-preview',json={'source':source}).json()
    card=preview['data']['groups'][0]['items'][0]['id']
    body={'source':source,'digest':preview['digest'],'revision':0,'confirmed':True,'mutation_id':str(uuid4()),'module_bindings':{card:'docs'}}
    saved=client.post('/nav-package-import',json=body)
    assert saved.status_code==200
    assert saved.json()['data']['groups'][0]['items'][0]['module_id']=='docs'
    assert client.post('/nav-package-import',json=body).json()==saved.json()
    body['module_bindings'][card]=None
    assert client.post('/nav-package-import',json=body).status_code==409
    current=client.get('/nav-data').json();assets=client.get('/nav-assets').json()
    for mapping in ({card:'missing'},{str(uuid4()):'docs'}):
        request={**body,'mutation_id':str(uuid4()),'revision':current['revision'],'module_bindings':mapping}
        assert client.post('/nav-package-import',json=request).status_code==422
        assert client.get('/nav-data').json()==current and client.get('/nav-assets').json()==assets


def test_actual_readonly_source_rehearsal_roundtrip(lane,tmp_path):
    source_path=os.getenv('NAV_LEGACY_TRANSFER')
    if not source_path:pytest.skip('explicit private read-only legacy transfer required')
    from tools.native_nav_legacy_export import sha
    from app.services.native_nav_package import parse
    client,factory,uid,other,nav,app=lane
    source=Path(source_path).read_text()
    before=client.get('/nav-data').json()
    result=client.post('/nav-package-preview',json={'source':source})
    assert result.status_code==200
    preview=result.json()
    assert client.get('/nav-data').json()==before and client.get('/nav-assets').json()==[]
    body={'source':source,'digest':preview['digest'],'revision':preview['revision'],'confirmed':True,'mutation_id':str(uuid4())}
    result=client.post('/nav-package-import',json=body)
    assert result.status_code==200
    actual=client.get('/nav-data').json()
    expected,assets,counts,warnings=parse(source,uid)
    assert actual['data']==expected
    for asset in assets:
        assert client.get('/nav-assets/'+str(asset['id'])).content==asset['content']
    exported=client.get('/nav-package').json()
    assert exported['counts']==counts
    # Same-owner complete reimport retains every field and asset byte.
    native_source=json.dumps(exported)
    p=client.post('/nav-package-preview',json={'source':native_source}).json()
    r=client.post('/nav-package-import',json={'source':native_source,'digest':p['digest'],'revision':p['revision'],'confirmed':True,'mutation_id':str(uuid4())})
    assert r.status_code==200 and r.json()['data']==actual['data']
    with factory() as db:assert db.get(nav.NavState,other) is None
    (Path(os.environ['NAV_REHEARSAL_RECEIPT'])).write_text(json.dumps({'source_sha256':sha(source.encode()),'counts':counts,'preview_readonly':True,'actual_pg_fields_equal':True,'all_asset_bytes_equal':True,'complete_package_roundtrip':True,'production_writes':False},indent=2))
