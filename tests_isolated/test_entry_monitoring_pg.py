"""Opt-in real Linux ICMP + bearer /agent/report into ONLY disposable PG 25461.

POSTGRES_* must explicitly select the owned fixture. No production/app startup.
"""
import os, socket, threading, time, ssl, secrets, importlib.util, json
from pathlib import Path
from collections import deque
import pytest

pytestmark=pytest.mark.skipif(os.getenv('STELLA_ENTRY_MONITORING_PG')!='1',reason='owned PG opt-in')
ROOT=Path(__file__).parents[1]


def test_actual_agent_report_icmp_pg_roundtrip(monkeypatch):
    assert (os.getenv('POSTGRES_HOST'),os.getenv('POSTGRES_PORT'),os.getenv('POSTGRES_DB'),os.getenv('POSTGRES_USER'))==('127.0.0.1','25461','entry_monitoring','entry_monitoring')
    import uvicorn, httpx
    from fastapi import FastAPI
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from app.database import engine
    from app.models.node import Node
    from app.models.monitor import Monitor, MonitorCheck
    from app.routers.monitor import agent_router, node_router
    from app.routers.auth import current_user
    from app.services import entry_registry
    from app.schemas.monitor import NodeRead
    target=os.environ['OWNED_ICMP_IP']
    # Only a local assigned address is admitted; never scan a subnet.
    import subprocess
    local=json.loads(subprocess.check_output(['ip','-j','address','show','dev','wlan0']))
    assert target in {a['local'] for i in local for a in i['addr_info']}
    spec=importlib.util.spec_from_file_location('real_entry_agent',ROOT/'agent/stella_agent.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    agent=mod.Agent.__new__(mod.Agent)
    cap=agent._monitoring_capability()
    assert 'ping' in cap['types']
    cap['targets']=[target]
    token=secrets.token_urlsafe(32)
    with Session(engine) as db:
        n=Node(name='entry-monitoring-owned-real',host=target,platform='linux',token=token)
        other=Node(name='entry-monitoring-owned-other',host=target,platform='linux',token=secrets.token_urlsafe(32))
        db.add_all([n,other]);db.commit();identity=n.id;other_id=other.id
    app=FastAPI();app.include_router(agent_router);app.include_router(node_router)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':origin,'private':f'https://{target}'}})
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.01)
    assert server.started
    agent.url=origin;agent.token=token;agent._ssl_context=ssl.create_default_context();agent.queue=deque();agent.monitors={};agent.monitors_version=0
    agent._check_components=lambda:{'monitoring':cap}
    agent._os_info=lambda:{};agent._storage_info=lambda:[]
    raw=[]
    real_run=mod.subprocess.run
    def observed_run(argv,**kw):
        result=real_run(argv,**kw)
        if argv[0]=='ping':raw.append({'argv':argv,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        return result
    monkeypatch.setattr(mod.subprocess,'run',observed_run)
    try:
        assert httpx.post(origin+'/agent/report',json={'metrics':[]}).status_code==401
        assert httpx.get(origin+f'/nodes/{identity}').status_code==401
        agent._post('/agent/report',json_body={'metrics':[],'components':{'monitoring':cap},'agent_version':mod.AGENT_VERSION})
        first=agent._last_report_transaction.copy()
        agent.refresh_config();assert len(agent._entry_manifest['entries'])==2
        agent.run_entry_probes()
        assert agent._entry_samples[0]['status']=='outside_scope'  # loopback is not silently admitted
        actual=agent._entry_samples[1]
        assert actual['status']=='complete' and actual['results'][0]['ip']==target
        assert actual['results'][0]['status']=='up'
        agent.report([],[]);agent.report([],[])
        assert not agent.queue
        app.dependency_overrides[current_user]=lambda:object()  # fixture read identity, NOT production login acceptance
        public=httpx.get(origin+f'/nodes/{identity}').json()
        assert public['control_channel']['report']['entry_id']=='public'
        assert public['control_channel']['report']['duration_ms']>0
        assert public['control_channel']['icmp'][1]['results'][0]['latency_ms']>0
        assert public['components']['monitoring']['types']==cap['types']
        assert 'token' not in public
        # Bad scope and wrong entry rejected by the actual report HTTP handler.
        bad={'control_channel':{'icmp':[{**actual,'version':'0'*24}]}}
        assert httpx.post(origin+'/agent/report',headers={'Authorization':'Bearer '+token},json=bad).status_code==422
        with Session(engine) as db:
            stored=db.get(Node,identity).control_channel
            assert stored==public['control_channel']
            assert db.get(Node,other_id).control_channel is None
            monitors=db.scalars(select(Monitor).where(Monitor.node_id==identity)).all()
            assert len(monitors)==1
            checks=db.scalars(select(MonitorCheck).where(MonitorCheck.monitor_id==monitors[0].id)).all()
            assert len(checks)==1 and checks[0].loss_pct==0
            snapshot=NodeRead.model_validate(db.get(Node,identity)).model_dump(mode='json',exclude={'token'})
        assert 'private' not in [stored['report']['entry_id']]  # no invented other-entry report timing
        evidence={'scope':'owned loopback HTTP + local assigned wlan0 numeric ICMP; not split-horizon/Windows/production acceptance','first_transaction':first,'channel':stored,'node_projection':snapshot,'raw_ping':raw,'monitor_count':len(monitors),'check_count':len(checks),'http_statuses':{'no_token':401,'no_owner_session':401,'bad_manifest':422},'db':'127.0.0.1:25461/entry_monitoring'}
        if os.getenv('ENTRY_EVIDENCE'):
            Path(os.environ['ENTRY_EVIDENCE']).write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    finally:
        server.should_exit=True;thread.join(timeout=5);sock.close()
        assert not thread.is_alive()


def test_pg_concurrent_latest_sample_cas_is_monotonic_and_source_scoped(monkeypatch):
    from datetime import datetime,timezone,timedelta
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    from app.database import engine
    from app.models.node import Node
    from app.services import entry_registry,entry_monitoring
    from app.schemas.control_channel import ControlChannel
    assert engine.url.port==25461 and engine.url.database=='entry_monitoring'
    monkeypatch.setattr(entry_registry,'records',lambda:{'stella':{'public':'https://main.example'}})
    with Session(engine) as db:
        a=Node(name='owned-concurrent-source',host='192.168.0.103',platform='linux')
        b=Node(name='owned-other-source',host='192.168.0.103',platform='linux');db.add_all([a,b]);db.commit();identity=a.id;other=b.id
    barrier=threading.Barrier(2);now=datetime.now(timezone.utc)
    def write(age,duration):
        with Session(engine,autoflush=False) as db:
            n=db.get(Node,identity)
            value=ControlChannel.model_validate({'report':dict(entry_id='public',origin='https://main.example',duration_ms=duration,status='ok',http_status=200,sampled_at=(now-timedelta(seconds=age)).isoformat())})
            barrier.wait(timeout=3);entry_monitoring.save_channel(db,n,value);db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(write,2,100),pool.submit(write,1,200)]
        for f in futures:f.result(timeout=5)
    with Session(engine) as db:
        assert db.get(Node,identity).control_channel['report']['duration_ms']==200
        assert db.get(Node,other).control_channel is None


def test_settings_archive_never_replays_automatic_entry_monitors_as_manual(monkeypatch):
    from sqlalchemy.orm import Session
    from app.database import engine
    from app.models.monitor import Monitor
    from app.services import backup_projection,entry_monitoring
    assert engine.url.port==25461 and engine.url.database=='entry_monitoring'
    monkeypatch.setattr(backup_projection,'require_settings_mode',lambda:None)
    with Session(engine) as db:
        from app.models.node import Node
        n=db.query(Node).first()
        manual=Monitor(name='owned-backup-manual',node_id=n.id,type='tcp',target='192.168.0.103:12345',interval=60,timeout=1,status='unknown');db.add(manual);db.commit();identity=manual.id
        automatic=entry_monitoring.managed_ids(db)
    assert automatic
    with engine.connect() as conn:
        with backup_projection.export_settings(conn,os.environ['TMPDIR']) as payload:
            data=json.load(payload.entries['settings.json'])
    exported={row['id'] for row in data['tables']['monitors']}
    assert identity in exported and not (exported & automatic)
    assert all('control_channel' not in row for row in data['tables']['nodes'])
    assert not any(row['key'].startswith('entry_monitoring.') for row in data['config'])
