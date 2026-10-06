"""Final-review reproductions using actual main/auth/grants and HTTP upstream."""
import json,time
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from tests_isolated.test_integration_security_hotfix import integration_env, upstream
from tests_isolated.test_owner_admin_security import DAILY, ADMIN
from app.models.config import AppConfig
from app.models.user import AuthSession
from app.services import integrations as store, admin_security


def adapter(factory, mid, name):
    with factory() as db:
        row=db.get(AppConfig,store.KEY);value=json.loads(row.value)
        value['modules'][mid]['adapter']=name;row.value=json.dumps(value);db.commit()


@pytest.mark.parametrize('state',['locked','expired','other_sid'])
def test_openlist_isolated_writes_check_current_sid_elevation(integration_env,state):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    adapter(f,mid,'openlist')
    if state=='locked':c.post('/auth/admin/lock')
    elif state=='expired':
        with f() as db:
            row=db.get(AppConfig,admin_security.STATE_KEY);v=json.loads(row.value)
            v['grants'][sid]['expires_at']='2000-01-01T00:00:00+00:00';row.value=json.dumps(v);db.commit()
    else:
        other=TestClient(app,base_url='https://stella.xiya.live')
        assert other.post('/auth/login',json={'username':'owner','password':DAILY}).status_code==200
        boot=other.post('/external-modules/'+mid+'/launch').json()
        r=other.post(boot['url'],data=boot['fields'],headers={'Origin':'https://stella.xiya.live'},follow_redirects=False)
        cookie=r.headers['set-cookie'].split(';')[0];other.close()
    assert c.post(origin+'/api/fs/list',headers={'Cookie':cookie},json={}).status_code==200
    seen.clear()
    for method,path in [('post','api/fs/remove'),('post','api/admin/setting/save'),('put','api/fs/put'),('delete','api/admin/storage/delete'),('get','api/admin/setting/list')]:
        r=getattr(c,method)(origin+'/'+path,headers={'Cookie':cookie})
        assert r.status_code==403,r.text
        assert r.json()['detail']['code']=='admin_elevation_required'
    assert seen==[]


def test_openlist_isolated_elevated_write_and_lock_reject_without_upstream(integration_env):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env;adapter(f,mid,'openlist')
    assert c.post(origin+'/api/fs/remove',headers={'Cookie':cookie}).status_code==200
    assert seen==[('POST','api/fs/remove')];seen.clear()
    assert c.post('/auth/admin/lock').status_code==200
    assert c.post(origin+'/api/fs/remove',headers={'Cookie':cookie}).status_code==403
    assert seen==[]


def test_openlist_isolated_ws_requires_elevation(integration_env):
    from starlette.websockets import WebSocketDisconnect
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env;adapter(f,mid,'openlist')
    assert c.post('/auth/admin/lock').status_code==200
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(origin.replace('https:','wss:')+'/socket',headers={'Cookie':cookie,'Origin':origin}):pass


@pytest.mark.parametrize('change',['lock','identity'])
def test_openlist_existing_ws_loses_access_on_lock_or_reconfiguration(integration_env,change):
    from starlette.websockets import WebSocketDisconnect
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env;adapter(f,mid,'openlist')
    with c.websocket_connect(origin.replace('https:','wss:')+'/socket',headers={'Cookie':cookie,'Origin':origin}) as ws:
        ws.send_text('synthetic probe');assert ws.receive_text()=='synthetic probe'
        if change=='lock':assert c.post('/auth/admin/lock').status_code==200
        else:assert c.patch('/external-modules/'+mid,json={'initial_path':'/new'}).status_code==200
        with pytest.raises(WebSocketDisconnect) as closed:ws.receive_text()
        assert closed.value.code==1008


@pytest.mark.parametrize('change',[{'adapter':'immich','browser_url':'https://immich.xiya.live'},{'initial_path':'/changed'},{'target_id':'target2'},{'enabled':False}])
def test_identity_patch_recomputes_origin_and_revokes_prior_authorization(integration_env,change):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    with f() as db:
        row=db.get(AppConfig,store.KEY);state=json.loads(row.value)
        state['targets']['target2']=dict(state['targets']['target'],id='target2')
        state['tickets']['synthetic-ticket']={'id':mid,'sid':sid,'origin':origin,'expires':time.time()+30}
        row.value=json.dumps(state);db.commit()
    r=c.patch('/external-modules/'+mid,json=change);assert r.status_code==200,r.text
    expected='https://immich.xiya.live' if change.get('adapter')=='immich' else origin
    assert r.json()['origin']==expected
    with f() as db:
        state=store.state(db)
        assert not any(x['id']==mid for x in state['tickets'].values())
        assert not any(x['id']==mid for x in state['grants'].values())
    response=c.get(expected+'/echo',headers={'Cookie':cookie})
    assert response.status_code in (401,404)
    assert seen==[]


@pytest.mark.parametrize('url',['https://IMMICH.xiya.live','HTTPS://immich.xiya.live','HTTPS://IMMICH.XIYA.LIVE/'])
def test_immich_case_equivalence_canonical_host_and_unique_origin(integration_env,url):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    response=c.patch('/external-modules/'+mid,json={'adapter':'immich','browser_url':url})
    assert response.status_code==200,response.text
    assert response.json()['browser_url']==url
    assert response.json()['origin']=='https://immich.xiya.live'
    launch=c.post('/external-modules/'+mid+'/launch').json()
    assert launch['url'].startswith('https://immich.xiya.live/')
    boot=c.post(launch['url'],data=launch['fields'],headers={'Origin':'https://stella.xiya.live'},follow_redirects=False)
    assert boot.status_code==303,boot.text
    new_cookie=boot.headers['set-cookie'].split(';')[0]
    assert c.get('https://immich.xiya.live/echo',headers={'Cookie':new_cookie}).status_code==200
    body={'name':'duplicate','icon':'globe','mode':'isolated_proxy','adapter':'immich','browser_url':'https://immich.xiya.live','target_id':'target','initial_path':'/','enabled':True}
    assert c.post('/external-modules',json=body).status_code==409
    with f() as db:
        row=db.get(AppConfig,store.KEY);value=json.loads(row.value)
        value['modules'][mid]['origin']='HTTPS://IMMICH.XIYA.LIVE'
        value['modules']['b'*32]=dict(value['modules'][mid],id='b'*32,adapter='generic',origin='https://app-'+('b'*32)+'.xiya.live')
        row.value=json.dumps(value);db.commit()
    assert c.post('/external-modules',json=body).status_code==409
    assert c.patch('/external-modules/'+('b'*32),json={'adapter':'immich','browser_url':'https://immich.xiya.live'}).status_code==409
    assert c.patch('/external-modules/'+mid,json={'browser_url':url}).json()['origin']=='https://immich.xiya.live'


def test_immich_domain_change_reset_and_duplicate_rejection(integration_env):
    c,f,app,uid,sid,mid,origin,cookie,seen=integration_env
    assert c.patch('/external-modules/'+mid,json={'adapter':'immich','browser_url':'https://immich.xiya.live'}).json()['origin']=='https://immich.xiya.live'
    assert c.patch('/external-modules/'+mid,json={'browser_url':'https://immich.yunxi.life'}).json()['origin']=='https://immich.yunxi.life'
    with f() as db:
        row=db.get(AppConfig,store.KEY);v=json.loads(row.value)
        v['modules']['b'*32]=dict(v['modules'][mid],id='b'*32,adapter='generic',origin='https://app-'+('b'*32)+'.xiya.live')
        row.value=json.dumps(v);db.commit()
    assert c.patch('/external-modules/'+('b'*32),json={'adapter':'immich','browser_url':'https://immich.yunxi.life'}).status_code==409
    assert c.patch('/external-modules/'+mid,json={'adapter':'generic'}).json()['origin']==origin
