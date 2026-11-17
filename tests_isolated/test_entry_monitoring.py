"""Owned SQLite and candidate Agent only; no configured database or startup."""
import importlib.util
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from test_node_monitor_policy import db, node

@pytest.fixture
def agent():
    spec = importlib.util.spec_from_file_location('entry_agent', Path(__file__).parents[1]/'agent/stella_agent.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    obj = mod.Agent.__new__(mod.Agent)
    return mod, obj


def test_manifest_uses_deployed_pair_not_node_hosts(db, monkeypatch):
    from app.services import entry_monitoring as svc, entry_registry
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public':'https://main.example:8443', 'private':'https://other.example'}})
    n = node(db, host='192.168.160.9')
    value = svc.manifest(n)
    assert [(e['entry_id'], e['hostname']) for e in value['entries']] == [('public','main.example')]
    # Registry presence is not applied private consent; host remains irrelevant.
    assert value['interval'] == 60 and value['deadline_seconds'] == 12
    assert value['max_ips'] == 4
    assert '192.168.160.9' not in str(value)


def test_numeric_scope_rejects_special_and_unapproved_private(agent):
    mod, _ = agent
    for ip in ['127.0.0.1','169.254.169.254','::ffff:127.0.0.1','0.0.0.0','224.0.0.1','192.168.1.2','100.100.100.200']:
        assert not mod._entry_ip_allowed(ip, [], [])
    assert mod._entry_ip_allowed('192.168.1.2', ['192.168.1.2'], [])
    assert mod._entry_ip_allowed('fd00::2', [], ['fd00::/64'])
    assert not mod._entry_ip_allowed('169.254.169.254', [], ['0.0.0.0/0'])
    assert not mod._entry_ip_allowed('fd00:ec2::254', None, ['fd00::/8'])
    assert mod._entry_ip_allowed('8.8.8.8', None, [])
    assert not mod._entry_ip_allowed('8.8.8.8', [], [])


def test_control_channel_typed_validation_and_capability_projection():
    from app.schemas.monitor import AgentReport
    from app.schemas.public_node import Components
    from pydantic import ValidationError
    sample = dict(entry_id='public', origin='https://main.example', duration_ms=1.5,
                  status='ok', http_status=200, error=None, sampled_at=datetime.now(timezone.utc).isoformat())
    report = AgentReport.model_validate({'control_channel': {'report': sample}})
    assert report.control_channel.report.duration_ms == 1.5
    assert Components.model_validate({'monitoring':{'ready':True,'types':['ping']}}).model_dump()['monitoring']['types'] == ['ping']
    for patch in ({'duration_ms':-1},{'duration_ms':float('nan')},{'error':'https://secret?token=x'},{'http_status':900},{'sampled_at':'2026-10-20'}):
        with pytest.raises(ValidationError):
            AgentReport.model_validate({'control_channel': {'report': {**sample, **patch}}})
    assert AgentReport().control_channel is None


def test_report_previous_completed_transaction_is_measured_not_collection(agent, monkeypatch):
    from collections import deque
    mod, obj = agent
    obj.url='https://main.example'; obj.token='owned'; obj.queue=deque(); obj.monitors_version=1
    obj._check_components=lambda:{}; obj._os_info=lambda:{}; obj._storage_info=lambda:[]
    obj.refresh_config=Mock()
    seen=[]
    def post(path, json_body, **kw):
        seen.append(json_body.copy())
        obj._last_report_transaction={'entry_id':'public','origin':obj.url,'duration_ms':25,
            'status':'ok','http_status':200,'error':None,'sampled_at':datetime.now(timezone.utc).isoformat()}
        return {'monitors_version':1}
    obj._post=post
    obj.report([],[]); obj.report([],[])
    assert seen[0].get('control_channel') is None
    assert seen[1]['control_channel']['report']['duration_ms'] == 25
    assert len(seen) == 2


@pytest.mark.parametrize('fallback', [False, True])
def test_real_report_transport_records_completion_and_sanitized_failure(agent, monkeypatch, fallback):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    import threading, json, time, ssl, urllib.request
    mod,obj=agent
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == '/agent/report'
            assert self.headers['Authorization'] == 'Bearer owned'
            calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            time.sleep(.025)
            self.send_response(200 if len(calls) in (1,3) else 503); self.end_headers()
            self.wfile.write(b'not-json' if len(calls)==3 else b'{"ok":true}')
        def log_message(self,*a): pass
    server=ThreadingHTTPServer(('127.0.0.1',0), Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    obj.url=f'http://127.0.0.1:{server.server_port}'; obj.token='owned'; obj._ssl_context=ssl.create_default_context()
    if fallback:
        monkeypatch.setattr(mod,'httpx',None)
        monkeypatch.setattr(mod,'_agent_urlopen',urllib.request.urlopen)
    try:
        assert obj._post('/agent/report',json_body={'metrics':[]})['ok']
        sample=obj._last_report_transaction
        assert sample['status']=='ok' and sample['http_status']==200
        assert 20 <= sample['duration_ms'] < 5000
        with pytest.raises(Exception):obj._post('/agent/report',json_body={'metrics':[]})
        failure=obj._last_report_transaction
        assert failure['status']=='error' and failure['error']=='http' and failure['http_status']==503
        assert 'owned' not in str(failure) and '?' not in failure['origin']
        with pytest.raises(Exception):obj._post('/agent/report',json_body={'metrics':[]})
        assert obj._last_report_transaction['error']=='invalid_response'
        assert len(calls)==3
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_entry_cycle_pins_agent_dns_and_rejects_mixed_answers(agent, monkeypatch):
    mod,obj=agent
    obj._entry_manifest={'icmp_available':True,'entries':[dict(entry_id='public',origin='https://owned.example',hostname='owned.example',version='a'*24)], 'targets':['192.168.1.2'],'approved_ranges':[]}
    obj._entry_resolve=lambda host, timeout:['192.168.1.2']
    probes=[]
    obj._entry_ping=lambda ip,budget:probes.append(ip) or dict(ip=ip,family=4,status='up',latency_ms=1.25,loss_pct=0)
    obj.run_entry_probes()
    assert probes==['192.168.1.2'] and obj._entry_samples[0]['status']=='complete'
    assert obj._entry_samples[0]['results'][0]['ip']=='192.168.1.2'
    obj._next_entry_probe=0
    obj._entry_resolve=lambda host,timeout:['192.168.1.2','169.254.169.254']
    obj.run_entry_probes()
    assert probes==['192.168.1.2']
    assert obj._entry_samples[0]['status']=='outside_scope' and obj._entry_samples[0]['results']==[]
    obj._next_entry_probe=0
    obj._entry_resolve=lambda host,timeout:['192.168.1.'+str(i) for i in range(1,6)]
    obj.run_entry_probes()
    assert obj._entry_samples[0]['status']=='too_many_ips'


def test_entry_ping_windows_flags_are_fixture_only(agent, monkeypatch):
    mod,obj=agent
    monkeypatch.setattr(mod.platform,'system',lambda:'Windows')
    calls=[]
    def run(argv,**kw):
        calls.append((argv,kw)); return Mock(returncode=0,stdout='Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),\nMinimum = 2ms, Maximum = 2ms, Average = 2ms',stderr='')
    monkeypatch.setattr(mod.subprocess,'run',run)
    result=obj._entry_ping('192.168.1.2',1.5)
    assert calls[0][0]==['ping','-4','-n','1','-w','1000','192.168.1.2']
    assert result['latency_ms']==2 and result['loss_pct']==0
    monkeypatch.setattr(mod.shutil,'which',lambda _: 'ping')
    obj._monitoring_capability()
    assert calls[-1][0]==['ping','-n','1','-w','1000','127.0.0.1']


def test_incapable_agent_returns_unavailable_without_dns_or_ping(agent):
    _,obj=agent
    obj._entry_manifest={'entries':[dict(entry_id='public',hostname='main.example',version='a'*24)],'icmp_available':False}
    obj._entry_resolve=Mock(side_effect=AssertionError('must not resolve'))
    obj.run_entry_probes()
    assert obj._entry_samples[0]['status']=='unavailable'
    obj._entry_resolve.assert_not_called()


def test_channel_storage_preserves_newest_and_rejects_wrong_entry(db, monkeypatch):
    from app.services import entry_monitoring as svc, entry_registry
    from app.schemas.control_channel import ControlChannel
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example'}})
    n=node(db)
    from datetime import timedelta
    now=datetime.now(timezone.utc)
    value={'report':dict(entry_id='public',origin='https://main.example',duration_ms=15,status='ok',http_status=200,error=None,sampled_at=now.isoformat())}
    svc.save_channel(db,n,ControlChannel.model_validate(value)); db.commit()
    assert n.control_channel['report']['duration_ms']==15
    older={'report':{**value['report'],'duration_ms':999,'sampled_at':(now-timedelta(hours=1)).isoformat()}}
    svc.save_channel(db,n,ControlChannel.model_validate(older));db.commit()
    assert n.control_channel['report']['duration_ms']==15
    bad={'report':{**value['report'],'origin':'https://evil.example'}}
    with pytest.raises(ValueError):svc.save_channel(db,n,ControlChannel.model_validate(bad))


def test_icmp_results_create_distinct_monitor_history_never_dispatch_or_adopt_manual(db, monkeypatch):
    from app.services import entry_monitoring as svc, entry_registry, node_monitor_policy
    from app.schemas.control_channel import ControlChannel
    from app.models.monitor import Monitor, MonitorCheck
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example'}})
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', __import__('sqlalchemy').Integer())
    MonitorCheck.__table__.create(db.get_bind())
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3']}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n); db.commit()
    manual=Monitor(name='manual',node_id=n.id,type='ping',target='192.168.160.3',interval=60,timeout=2,status='unknown')
    db.add(manual);db.commit()
    e=svc.manifest(n, db=db)['entries'][0]
    sample=dict(entry_id=e['entry_id'],version=e['version'],hostname=e['hostname'],sampled_at=datetime.now(timezone.utc).isoformat(),status='complete',results=[dict(ip='192.168.160.3',family=4,status='up',latency_ms=2.4,loss_pct=0)])
    value=ControlChannel(icmp=[sample])
    svc.save_channel(db,n,value);db.commit()
    svc.save_channel(db,n,value);db.commit()
    monitors=db.query(Monitor).all()
    assert len(monitors)==2 and db.query(MonitorCheck).count()==1
    assert node_monitor_policy.dispatched(db,monitors)==[manual]
    assert n.control_channel['icmp'][0]['results'][0]['ip']=='192.168.160.3'
    auto=next(m for m in monitors if m.id!=manual.id)
    assert auto.last_latency_ms==2.4
    from app.services.monitor import list_monitors
    n.status='online';n.last_seen_at=datetime.now(timezone.utc);db.commit()
    assert next(m for m in list_monitors(db) if m.id==auto.id).status=='up'
    db.query(MonitorCheck).delete();db.delete(auto);db.commit()
    from datetime import timedelta
    sample['sampled_at']=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
    svc.save_channel(db,n,ControlChannel(icmp=[sample]));db.commit()
    assert db.query(Monitor).all()==[manual]  # deleted identity tombstone retained


def test_two_entry_samples_share_autoflush_false_session_without_losing_ledger(db,monkeypatch):
    from app.services import entry_monitoring as svc,entry_registry
    from app.schemas.control_channel import ControlChannel
    from app.models.monitor import Monitor,MonitorCheck
    from app.models.config import AppConfig
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example','private':'https://other.example'}})
    from test_entry_lifecycle_v11 import save_origins
    save_origins(db, monkeypatch, 'https://other.example')
    db.commit()
    monkeypatch.setattr(MonitorCheck.__table__.c.id, 'type', __import__('sqlalchemy').Integer())
    MonitorCheck.__table__.create(db.get_bind())
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3']}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n); db.commit()
    db.autoflush=False
    samples=[dict(entry_id=e['entry_id'],version=e['version'],hostname=e['hostname'],sampled_at=datetime.now(timezone.utc).isoformat(),status='complete',results=[dict(ip='192.168.160.3',family=4,status='up',latency_ms=1.2,loss_pct=0)]) for e in svc.manifest(n, db=db)['entries']]
    svc.save_channel(db,n,ControlChannel.model_validate({'icmp':samples}));db.commit()
    assert db.query(Monitor).count()==2 and db.query(MonitorCheck).count()==2
    assert len(__import__('json').loads(db.get(AppConfig,svc.LEDGER).value))==2


def test_entry_retirement_does_not_retire_a_different_node_reachability_measurement(db,monkeypatch):
    from app.services import entry_monitoring as svc,entry_registry,node_monitor_policy as legacy
    from app.schemas.control_channel import ControlChannel
    from app.models.monitor import Monitor
    from app.models.config import AppConfig
    import json
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example'}})
    source=node(db,status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping']}})
    target=node(db,host='192.168.160.4')
    legacy.update(db,dict(revision=0,enabled=True,source_node_id=source.id,host_node_id=None,interval=60))
    before=db.get(AppConfig,legacy.KEY).value
    owned=db.query(Monitor).one()
    manual=Monitor(name='manual',node_id=source.id,type='ping',target=target.host,interval=60,timeout=1,status='unknown');db.add(manual);db.commit()
    entry=svc.manifest(source)['entries'][0]
    value=ControlChannel.model_validate({'icmp':[dict(entry_id=entry['entry_id'],version=entry['version'],hostname=entry['hostname'],sampled_at=datetime.now(timezone.utc).isoformat(),status='unavailable',results=[])]})
    svc.save_channel(db,source,value);db.commit()
    assert legacy.dispatched(db,[owned,manual])==[owned,manual]
    assert db.get(AppConfig,legacy.KEY).value==before
    assert db.get(Monitor,owned.id) is not None
    assert svc.retired_sources(db)=={str(source.id)}
    node(db,host='192.168.160.5');legacy.reconcile(db)
    assert db.query(Monitor).count()==4
    assert legacy.read(db)['managed'][0]['paused'] is False
    assert svc.managed_ids(db).isdisjoint({m.id for m in legacy.dispatched(db,db.query(Monitor).all())})


def test_management_read_normalizes_malformed_slot_and_retains_storage(db):
    from app.schemas.monitor import NodeRead
    n=node(db,control_channel={'report':{'duration_ms':'not-a-number','token':'hidden'}})
    raw=n.control_channel.copy()
    assert NodeRead.model_validate(n).control_channel is None
    assert n.control_channel==raw


def test_new_management_summary_is_login_only_read_only(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import node_router
    from app.routers.auth import current_user
    from app.database import get_db
    from app.models.config import AppConfig
    app=FastAPI();app.include_router(node_router)
    app.dependency_overrides[get_db]=lambda:db
    with TestClient(app) as client:
        assert client.get('/nodes/entry-monitoring').status_code==401
        app.dependency_overrides[current_user]=lambda:object()
        r=client.get('/nodes/entry-monitoring')
        assert r.status_code==200 and len(r.json())<=2
        assert db.query(AppConfig).count()==0


def test_backend_scope_bounds_and_agent_boundary_parity(db,agent,monkeypatch):
    from app.services import entry_monitoring as svc,entry_registry
    from app.services.entry_targets import _entry_ip_allowed
    from app.schemas.control_channel import ControlChannel
    from pydantic import ValidationError
    mod,_=agent
    cases=['127.0.0.1','::ffff:127.0.0.1','169.254.169.254','::','ff02::1','100.100.100.200','168.63.129.16','192.168.160.3','fd00::5','8.8.8.8']
    for value in cases:
        for targets,ranges in [(None,[]),([],[]),(['192.168.160.3'],[]),(None,['fd00::/64'])]:
            assert _entry_ip_allowed(value,targets,ranges)==mod._entry_ip_allowed(value,targets,ranges)
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example'}})
    n=node(db,status='online',last_seen_at=datetime.now(timezone.utc),components={'monitoring':{'ready':True,'types':['ping'],'targets':['192.168.160.3']}})
    from app.services.entry_monitor_groups import reconcile
    reconcile(db, n); db.commit()
    e=svc.manifest(n, db=db)['entries'][0]
    sample=dict(entry_id='public',version=e['version'],hostname=e['hostname'],sampled_at=datetime.now(timezone.utc).isoformat(),status='complete',results=[dict(ip='169.254.169.254',family=4,status='up',latency_ms=1,loss_pct=0)])
    with pytest.raises(ValueError):svc.save_channel(db,n,ControlChannel.model_validate({'icmp':[sample]}))
    db.rollback();assert n.control_channel is None
    with pytest.raises(ValidationError):ControlChannel.model_validate({'icmp':[sample]*5})
    with pytest.raises(ValidationError):ControlChannel.model_validate({'icmp':[{**sample,'results':sample['results']*5}]})


def test_stuck_dns_worker_does_not_spawn_unbounded_threads(agent,monkeypatch):
    import threading,time
    mod,obj=agent
    started=threading.Event();release=threading.Event();calls=[]
    def resolve(*args):
        calls.append(args);started.set();release.wait(2);return []
    monkeypatch.setattr(mod.socket,'getaddrinfo',resolve)
    try:
        begin=time.monotonic()
        with pytest.raises(TimeoutError):obj._entry_resolve('owned.example',.03)
        assert started.is_set() and time.monotonic()-begin<.5
        for _ in range(8):
            with pytest.raises(TimeoutError):obj._entry_resolve('owned.example',.03)
        assert len(calls)==1
    finally:release.set()
