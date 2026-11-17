"""Owned PG / actual HTTP, rule, agent-target and report persistence paths.

Auth role decisions stubbed; no app lifespan, external mail, real probes or agents.
"""
import os
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.models import Base
from app.models.node import Node
from app.models.alert import AlertRule, AlertState, AlertEvent
from app.services import alerts, server_map as m
from test_manual import snapshot, intent, load_agent

@pytest.fixture
def db(monkeypatch):
    url=os.environ['WG13_TEST_URL'];u=make_url(url)
    assert (u.host,u.username,u.database)==('127.0.0.1','stella_wg13','wg13_test') and u.port!=5432
    engine=create_engine(url)
    with engine.begin() as c:
        assert c.execute(text("select current_setting('stella.test_isolation')")).scalar_one()=='wg13-owned'
        Base.metadata.create_all(c)
    monkeypatch.setattr(alerts,'_push_ws',lambda *a:None)
    monkeypatch.setattr(alerts,'_send_alert_email',lambda *a:pytest.fail('no mail'))
    with Session(engine) as db:
        yield db
        db.rollback()
    with engine.begin() as c:
        assert c.execute(text("select current_setting('stella.test_isolation')")).scalar_one()=='wg13-owned'
        Base.metadata.drop_all(c)
    engine.dispose()

def setup(db):
    now=datetime.now(timezone.utc)
    n=Node(id=1,name='synthetic wg source',host='fixture.invalid',platform='linux',status='online',last_seen_at=now,token='wg13-fixture-token')
    db.add(n);db.flush()
    s=snapshot();s['observed_at']=now.isoformat();m.save_snapshot(db,1,s);db.commit()
    return s

def client_for(db,monkeypatch):
    from app.routers import alerts as routes, monitor, auth
    from app.database import get_db
    state={'admin':True}
    def admin():
        if not state['admin']:raise HTTPException(403,'fixture role denied')
        return object()
    app=FastAPI();app.include_router(routes.router);app.include_router(monitor.agent_router)
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[auth.current_user]=lambda:object()
    app.dependency_overrides[auth.admin_user]=admin
    return TestClient(app),state

def test_http_manual_create_readback_agent_execution_report_fire_unknown_recover_archive(db,monkeypatch):
    s=setup(db);client,state=client_for(db,monkeypatch)
    body=dict(kind='wg_link',target='',wg_manual=intent(),label='fixture direction',email=False,debounce=1)
    state['admin']=False
    assert client.post('/alerts/rules',json=body).status_code==403
    state['admin']=True
    response=client.post('/alerts/rules',json=body)
    assert response.status_code==201,response.text
    rule_id=response.json()['id'];r=db.get(AlertRule,rule_id)
    assert r.target.startswith('manual:') and r.condition['wg_manual']['peer_key_id']=='b'*64
    listed=client.get('/alerts/rules').json()[0]
    assert listed['wg_manual']['target']=='10.0.0.9' and listed['wg_observation']['health']=='unknown'
    assert client.get('/agent/map-targets',headers={'Authorization':'Bearer wrong'}).status_code==401
    reply=client.get('/agent/map-targets',headers={'Authorization':'Bearer wg13-fixture-token'})
    assert reply.status_code==200,reply.text
    targets=reply.json()['targets'];assert len(targets)==1 and targets[0]['manual'] is True
    # Actual agent function -> actual typed report -> service persistence/evaluator.
    a=load_agent();monkeypatch.setattr(a.shutil,'which',lambda name:'/usr/bin/'+name)
    monkeypatch.setattr(a.platform,'system',lambda:'Linux')
    received=[0]
    def run(cmd,**kwargs):
        if cmd[0].endswith('/ip'):return '[{"dev":"wg0","prefsrc":"10.0.0.1"}]'
        return f'5 packets transmitted, {received[0]} received, 100% packet loss'
    monkeypatch.setattr(a,'_map_command',run)
    from app.schemas.monitor import AgentReport
    from app.services.node import handle_report
    def report():
        current=snapshot();current['observed_at']=datetime.now(timezone.utc).isoformat()
        a._probe_map_targets(current['wireguard'],targets)
        handle_report(db,'wg13-fixture-token',AgentReport(map_snapshot=current))
    report();assert db.get(AlertState,rule_id).state=='firing'
    assert db.query(AlertEvent).filter_by(rule_id=rule_id,event='fired').count()==1
    # Disappearance does not recover. Identity replacement does not rebind.
    changed=snapshot();changed['observed_at']=datetime.now(timezone.utc).isoformat();changed['wireguard']['interfaces']=[]
    handle_report(db,'wg13-fixture-token',AgentReport(map_snapshot=changed))
    assert db.get(AlertState,rule_id).state=='firing'
    assert client.get('/agent/map-targets',headers={'Authorization':'Bearer wg13-fixture-token'}).json()['targets']==[]
    assert client.get('/alerts/rules').json()[0]['wg_observation']['health']=='unknown'
    received[0]=5;report();assert db.get(AlertState,rule_id).state=='ok'
    assert db.query(AlertEvent).filter_by(rule_id=rule_id,event='resolved').count()==1
    assert client.delete(f'/alerts/rules/{rule_id}').status_code==200
    assert db.get(AlertRule,rule_id).archived is True
    assert client.get('/agent/map-targets',headers={'Authorization':'Bearer wg13-fixture-token'}).json()['targets']==[]

def test_manual_debounce_counts_new_probe_samples_not_other_nodes_reports(db,monkeypatch):
    setup(db);client,_=client_for(db,monkeypatch)
    r_id=client.post('/alerts/rules',json=dict(kind='wg_link',target='',wg_manual=intent(),email=False,debounce=2)).json()['id']
    now=datetime.now(timezone.utc)
    s=snapshot();s['observed_at']=now.isoformat()
    s['wireguard']['interfaces'][0]['peers'][0]['manual_probes']=[dict(checked_at=now.isoformat(),status='failed',sent=5,received=0,loss_pct=100.0,rtt_ms=None,target='10.0.0.9',reason='icmp_no_response')]
    m.save_snapshot(db,1,s)
    alerts.evaluate_wg_rules(db,now=now);db.commit()
    assert db.get(AlertState,r_id).consecutive==1
    alerts.evaluate_wg_rules(db,now=now+timedelta(seconds=1));db.commit()
    assert db.get(AlertState,r_id).state=='ok' and db.get(AlertState,r_id).consecutive==1
    assert db.query(AlertEvent).count()==0

def test_manual_capacity_token_scope_rotation_and_disabled_or_archived_handout(db,monkeypatch):
    setup(db);client,_=client_for(db,monkeypatch)
    now=datetime.now(timezone.utc)
    other=Node(id=2,name='synthetic remote',host='other.invalid',platform='linux',status='online',last_seen_at=now,token='wg13-other-token')
    db.add(other);db.flush()
    remote=snapshot();remote['observed_at']=now.isoformat()
    iface=remote['wireguard']['interfaces'][0];iface['public_key_id']='b'*64;iface['addresses']=['10.0.0.2/24'];iface['peers'][0]['public_key_id']='a'*64
    m.save_snapshot(db,2,remote);db.commit()
    ids=[]
    for i in range(8):
        response=client.post('/alerts/rules',json=dict(kind='wg_link',target='',wg_manual=intent(target=f'10.0.0.{9+i}'),email=False))
        assert response.status_code==201,response.text
        ids.append(response.json()['id'])
    assert client.post('/alerts/rules',json=dict(kind='wg_link',target='',wg_manual=intent(target='10.0.0.30'),email=False)).status_code==400
    all_targets=set()
    for seconds in (0,60):
        targets=m.get_probe_targets(db,'wg13-fixture-token',now=now+timedelta(seconds=seconds))
        assert len(targets)==8
        all_targets.update((t['target'],t.get('manual',False)) for t in targets)
    assert len(all_targets)==9 and ('10.0.0.2',False) in all_targets
    targets=m.get_probe_targets(db,'wg13-other-token',now=now)
    assert all(not t.get('manual') for t in targets)
    assert client.patch(f'/alerts/rules/{ids[0]}',json={'enabled':False}).status_code==200
    assert all(t['target']!='10.0.0.9' for t in m.get_probe_targets(db,'wg13-fixture-token',now=now))
    assert client.delete(f'/alerts/rules/{ids[0]}').status_code==200
    assert client.post('/alerts/rules',json=dict(kind='wg_link',target='',wg_manual=intent(target='10.0.0.30'),email=False)).status_code==201

def test_http_manual_input_is_strict_and_cannot_be_smuggled_as_discovered_target(db,monkeypatch):
    setup(db);client,_=client_for(db,monkeypatch)
    for bad in (intent(command='id'),intent(interface='wg0;id'),intent(target='169.254.169.254')):
        assert client.post('/alerts/rules',json=dict(kind='wg_link',target='',wg_manual=bad,email=False)).status_code==422
    assert client.post('/alerts/rules',json=dict(kind='wg_link',target='manual:forged',email=False)).status_code==400
    assert client.post('/alerts/rules',json=dict(kind='node_offline',target='1',wg_manual=intent(),email=False)).status_code==400
    assert db.query(AlertRule).count()==0
