"""Merged A/B/website/Agent/monitor seams: actual auth, SQLite, ASGI.
No app.main, PG, external network, mail, installer or live account. Run with
v6_test_runner.py --noconftest from an owned scratch cwd.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from test_owner_admin_security import auth_env, DAILY, owner
from tests_website_settings.test_website_settings import upstream


@compiles(JSONB, 'sqlite')
def sqlite_jsonb(element, compiler, **kwargs):
    return 'JSON'


@pytest.fixture
def combined(auth_env, monkeypatch):
    from app.models.node import Node
    from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
    from app.routers.monitor import monitor_router, node_router, agent_router
    from app.routers.website_settings import router as website_router
    from app.routers.integrations import router as integrations_router
    from app.services import entry_registry, agent_channels
    c, db, app = auth_env
    c.base_url = 'https://main.test'
    for table in (Node.__table__, Monitor.__table__, MonitorGroup.__table__, MonitorGroupMember.__table__):
        table.create(db.get_bind())
    for router in (monitor_router, node_router, agent_router, website_router, integrations_router):
        app.include_router(router)
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public':'https://main.test', 'private':'https://other.test'}})
    monkeypatch.setattr(agent_channels, 'center_id', lambda: 'a'*64)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://main.test,https://other.test')
    monkeypatch.delenv('STELLA_AGENT_ROLLOUT_VERSION', raising=False)
    return c, db, app


def test_real_owner_profile_and_normal_management_no_unlock(combined, upstream):
    from app.models.user import AuthSession
    from app.models.config import AppConfig
    from app.models.node import Node
    from app.models.monitor import Monitor, MonitorGroup
    c, db, app = combined
    uid = owner(c)
    sid = str(db.query(AuthSession).one().id)
    assert c.patch('/auth/me', json={'username':'merged-owner','display_name':'合并账号'}).status_code == 200
    assert c.get('/auth/me').json()['id'] == uid
    assert str(db.query(AuthSession).one().id) == sid
    for path, payload in [('/auth/admin/setup',{'user_password':DAILY,'new_password':'retired-only'}),('/auth/admin/unlock',{'password':'retired-only'}),('/auth/admin/lock',{})]:
        assert c.post(path,json=payload).status_code == 410
    n = Node(name='owned',host='192.0.2.7',platform='linux',token='combined-agent-token',status='online',last_seen_at=datetime.now(timezone.utc))
    db.add(n);db.commit()
    root, _, seen = upstream
    site = c.post('/website-settings',json={'address':root+'/first?q=a%2Fb#one','address_mode':'ip','alternate_address':root+'/other?q=c%2Fd#two','connection':{'transport':'auto'},'name':'合并网站','idempotency_key':'combined-site-create'})
    assert site.status_code == 201, site.text
    item=site.json()
    assert c.get('/external-modules/'+item['id']).json()['alternate_address'] == root+'/other?q=c%2Fd#two'
    assert seen and {p for p,_ in seen} == {'/first?q=a%2Fb','/other?q=c%2Fd'}
    group=c.post('/monitors/groups',json={'name':'合并监控','items':[{'name':'正常输入','type':'tcp','target':'nas:80','node_id':n.id}],'request_key':'10000000-1234-4234-8234-123456789abc'})
    assert group.status_code == 201,group.text
    assert c.get('/monitors/groups').json()[0]['id'] == group.json()['id']
    channel=c.put('/nodes/report-channels',json={'revision':0,'node_ids':[n.id],'mode':'auto','entry_id':None})
    assert channel.status_code == 200,channel.text
    assert c.get('/nodes/report-channels').json()['nodes'][0]['mode'] == 'auto'
    assert c.get('https://main.test/agent/config',headers={'Authorization':'Bearer '+n.token}).json()['report_channel']['mode'] == 'auto'
    keys=[row.key for row in db.query(AppConfig)]
    assert not any('elevation' in key or 'admin_password' in key for key in keys)
    assert db.query(Monitor).filter(Monitor.id.in_(group.json()['child_ids'])).count() == 1
    assert db.query(MonitorGroup).filter(MonitorGroup.id==group.json()['id']).count() == 1


def test_anonymous_cross_lane_requests_are_401_and_write_nothing(combined):
    from app.models.monitor import Monitor, MonitorGroup
    from app.models.config import AppConfig
    c, db, app = combined
    probes=[('GET','/auth/me',None),('PATCH','/auth/me',{'display_name':'no'}),('POST','/website-settings',{'address':'https://example.test','name':'no'}),('GET','/external-modules',None),('PUT','/nodes/report-channels',{'revision':0,'node_ids':[1],'mode':'auto'}),('POST','/monitors/groups',{'name':'no','items':[{'name':'no','node_id':1,'type':'tcp','target':'nas:80'}],'request_key':'10000000-1234-4234-8234-123456789abc'})]
    for method,path,body in probes:
        response=c.request(method,path,**({'json':body} if body is not None else {}))
        assert response.status_code == 401,(method,path,response.text)
    assert db.query(Monitor).count() == db.query(MonitorGroup).count() == db.query(AppConfig).count() == 0


def test_agent_actual_source_and_parked_announcement_never_fake_manifest(combined,monkeypatch):
    c, _, _ = combined
    source=Path(__file__).resolve().parents[1]/'agent/stella_agent.py'
    body=source.read_bytes()
    script=c.get('/agent/script');assert script.status_code == 200 and script.content == body
    actual=c.get('/agent/version').json()
    assert actual['sha256'] == hashlib.sha256(body).hexdigest() and actual['size'] == len(body)
    monkeypatch.setenv('STELLA_AGENT_ROLLOUT_VERSION','0.6.17')
    parked=c.get('/agent/version').json()
    assert parked == {'version':'0.6.17'} and parked['version'] != actual['version']


def test_monitor_new_reason_repair_via_normal_owner_and_agent_config(combined):
    from app.models.node import Node
    from app.models.monitor import Monitor
    c, db, app=combined;owner(c)
    n=Node(name='owned',host='192.0.2.7',platform='linux',token='combined-validity-token',status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['tcp'],'targets':['nas']}})
    db.add(n);db.flush()
    m=Monitor(name='1',node_id=n.id,type='tcp',target='1:1',interval=60,timeout=5)
    db.add(m);db.commit();mid=m.id
    first=c.get('/monitors/').json();assert first[0]['status_reason']=='invalid_target'
    cfg=c.get('https://main.test/agent/config',headers={'Authorization':'Bearer '+n.token})
    assert cfg.status_code==200,cfg.text
    assert mid not in [v['id'] for v in cfg.json()['monitors']]
    before_ids={m.id for m in db.query(Monitor)}
    rejected=c.patch('/monitors/'+str(mid),json={'target':'1:1'});assert rejected.status_code==400
    repaired=c.patch('/monitors/'+str(mid),json={'target':'nas:80'})
    assert repaired.status_code==200 and repaired.json()['status_reason']=='pending'
    cfg=c.get('https://main.test/agent/config',headers={'Authorization':'Bearer '+n.token}).json()
    assert mid in [v['id'] for v in cfg['monitors']]
    assert {m.id for m in db.query(Monitor)}==before_ids
    assert db.get(Monitor,mid).target=='nas:80'
