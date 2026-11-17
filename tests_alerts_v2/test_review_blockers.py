"""Independent-review regressions. Run in its own guarded PG process (--noconftest)."""
import pytest
from datetime import timedelta,datetime,timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_persistence import domain,db,intent,NOW,sample

def fixed(start=NOW-timedelta(seconds=20),end=NOW,threshold='150'):
    return dict(metric='network.volume',interface='eth0',direction='out',threshold=threshold,window=dict(kind='fixed',start=start.isoformat(),end=end.isoformat(),timezone='UTC'))

def point(a,b,n=100):
    return dict(interval_start=NOW+timedelta(seconds=a),ts=NOW+timedelta(seconds=b),elapsed_seconds=b-a,quality='valid',rx_delta=0,tx_delta=n)

def savepoints(domain,db,points):
    for p in points:db.add(domain.node.NodeMetric(node_id=1,iface='eth0',**p))
    db.commit()


@pytest.mark.parametrize('points',[
    [point(-20,-5),point(-10,0)],
    [point(-20,-10,0),point(-9.999999,0,0)],
    [point(-20,-10),point(-10,0)],
    [point(-30,-10),point(-10,10)],
    [point(-40,-30),point(-20,-10),point(-10,0),point(1,10)],
    [{**point(-20,-10),'quality':None},point(-10,0)],
    [point(-20,-10),{**point(-5,-5),'elapsed_seconds':.05}],
])
def test_sql_pure_full_result_parity(domain,db,points):
    from app.alert_metrics import Condition,evaluate
    savepoints(domain,db,points)
    c=fixed(threshold='9999')
    assert domain.svc.preview(db,1,c,NOW)==evaluate(Condition.model_validate(c),points,NOW)

@pytest.mark.parametrize('metric',['network.rate','cpu'])
def test_future_quarantine_reason_and_watermark(domain,db,metric):
    from app.alert_metrics import Condition,evaluate
    c=intent()['condition'] if metric.startswith('network') else dict(metric='cpu',threshold='50')
    points=[point(-10,0),point(3590,3600)]
    if metric=='cpu':
        points=[dict(ts=p['ts'],cpu_pct=70,mem_pct=80,disk_pct=10) for p in points]
        for p in points:db.add(domain.node.NodeSysMetric(node_id=1,**p))
        db.commit()
    else:savepoints(domain,db,points)
    pure=evaluate(Condition.model_validate(c),points,NOW)
    sql=domain.svc.preview(db,1,c,NOW)
    assert pure['quality']==sql['quality']=='valid'
    from decimal import Decimal
    assert Decimal(pure.pop('value'))==Decimal(sql.pop('value'))
    assert pure==sql  # persisted Float columns may format 80 as 8E+1 / 70.0
    assert pure['reason']=='future_clock_quarantined' and pure['watermark']==NOW.isoformat() and pure['bad'] is True

@pytest.mark.parametrize('method',['close','reset'])
def test_reuse_discards_rolledback_queue(domain,db,monkeypatch,method):
    seen=[];monkeypatch.setattr(domain.legacy,'_push_ws',seen.append)
    r=domain.legacy.create_rule(db,'node_offline','1',debounce=1,email=False);rid=r.id;db.commit()
    domain.legacy._evaluate(db,r,True,'abandoned',NOW)
    getattr(db,method)()
    assert not db.info.get('alert_dispatch')
    db.commit();assert seen==[]
    r=db.get(domain.alert.AlertRule,rid)
    domain.legacy._evaluate(db,r,True,'new',NOW+timedelta(seconds=1));db.commit()
    assert len(seen)==1 and db.query(domain.alert.Notification).count()==1

def test_start_failure_logs_without_failing_durable_rows(domain,db,monkeypatch,caplog):
    r=domain.legacy.create_rule(db,'node_offline','1',debounce=1,email=False);rid=r.id;db.commit()
    monkeypatch.setattr(domain.legacy,'_push_ws',lambda p:None)
    domain.legacy._evaluate(db,r,True,'durable',NOW)
    payload,_,tx=db.info['alert_dispatch'][0]
    db.info['alert_dispatch']=[(payload,dict(address='never@example.invalid'),tx)]
    def denied(*a,**k):raise RuntimeError('synthetic failure')
    monkeypatch.setattr(domain.legacy.threading.Thread,'start',denied)
    with caplog.at_level('WARNING'):db.commit()
    assert 'alert_dispatch_failed' in caplog.text and 'RuntimeError' in caplog.text
    assert 'never@example.invalid' not in caplog.text
    with Session(db.get_bind()) as fresh:
        assert fresh.get(domain.alert.AlertState,rid).state=='firing'
        assert fresh.query(domain.alert.Notification).count()==1
    assert not db.info.get('alert_dispatch')

@pytest.mark.parametrize('missing',['interface','node'])
def test_disable_preserves_history_but_cannot_edit_invalid_target(domain,db,missing):
    r=domain.svc.save(db,intent(),now=NOW-timedelta(seconds=10));rid=r.id;db.commit()
    domain.legacy._evaluate(db,r,True,'bad',NOW);domain.legacy._evaluate(db,r,True,'bad',NOW+timedelta(seconds=1));db.commit()
    n=db.get(domain.node.Node,1)
    if missing=='interface':n.interfaces={}
    else:n.status='removed'
    db.commit()
    original=r.condition.copy();event_count=db.query(domain.alert.AlertEvent).count()
    # Disabling is not permission to smuggle in a new invalid condition.
    changed=intent(enabled=False);changed['condition']['threshold']='90'
    with pytest.raises(ValueError):domain.svc.save(db,changed,rid,1,now=NOW)
    db.rollback()
    domain.svc.save(db,intent(enabled=False),rid,1,now=NOW);db.commit()
    assert db.get(domain.alert.AlertRule,rid).condition==original
    assert db.get(domain.alert.AlertRule,rid).enabled is False
    assert db.query(domain.alert.AlertEvent).count()==event_count==1
    with pytest.raises(ValueError):domain.svc.save(db,intent(),rid,2,now=NOW)

def test_microgap_does_not_resolve_firing_incident(domain,db):
    c=fixed(end=NOW+timedelta(seconds=10),threshold='1')
    d=intent();d['condition']=c
    r=domain.svc.save(db,d,now=NOW-timedelta(seconds=30));rid=r.id;db.commit()
    state=db.get(domain.alert.AlertState,rid);state.state='firing';db.commit()
    savepoints(domain,db,[point(-20,-10,0),point(-9.9995,0,0)])
    domain.svc.evaluate_node(db,1,NOW);db.commit()
    assert db.get(domain.alert.AlertState,rid).state=='firing'
    assert db.query(domain.alert.AlertEvent).filter_by(rule_id=rid,event='resolved').count()==0


def test_absolute_endpoints_zone_is_display_metadata(domain):
    from app.alert_metrics import Condition
    c=fixed();c['window']['timezone']='Asia/Shanghai'
    p=Condition.model_validate(c)
    assert p.window.end.astimezone(timezone.utc)==NOW
    assert p.window.start.astimezone(timezone.utc)==NOW-timedelta(seconds=20)
    # DST repeated and skipped local clock times use their explicit offsets.
    for a,b,seconds in [('2026-11-01T01:30:00-04:00','2026-11-01T01:30:00-05:00',3600),('2026-03-08T01:30:00-05:00','2026-03-08T03:30:00-04:00',3600)]:
        c['window'].update(start=a,end=b,timezone='America/New_York')
        p=Condition.model_validate(c)
        assert (p.window.end.astimezone(timezone.utc)-p.window.start.astimezone(timezone.utc)).total_seconds()==seconds
    c['window'].update(start='2026-10-16T00:00:00',end=NOW.isoformat())
    with pytest.raises(ValueError):Condition.model_validate(c)

"""Controlled real-PG interleavings: observer releases holder only on lock wait."""
import json,time,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import timedelta
import pytest
from sqlalchemy import text,event
from sqlalchemy.orm import Session

@pytest.mark.parametrize('kind,operation',[('metric','delete'),('metric','update'),('legacy','delete'),('legacy','update')])
def test_rule_then_state_interleaving(domain,db,kind,operation,tmp_path):
    r=domain.svc.save(db,intent(),now=NOW-timedelta(seconds=10)) if kind=='metric' else domain.legacy.create_rule(db,'node_offline','1',debounce=1,email=False)
    rid=r.id;db.commit();sample(domain,db)
    schema=db.execute(text('select current_schema()')).scalar_one();db.commit();engine=db.get_bind().engine
    held=threading.Event();release=threading.Event();pids={};trace=[]
    def before(c,cursor,sql,params,ctx,many):
        role=c.info.get('lock_role')
        if role and (('FOR UPDATE' in sql) or sql.startswith(('DELETE','UPDATE'))):trace.append(dict(role=role,sql=sql))
    def after(c,cursor,sql,params,ctx,many):
        if c.info.get('lock_role')=='evaluate' and 'FROM alert_rules' in sql and 'FOR UPDATE' in sql and not held.is_set():
            held.set();assert release.wait(10)
    event.listen(engine,'before_cursor_execute',before);event.listen(engine,'after_cursor_execute',after)
    def worker(role):
        try:
            with engine.connect() as c:
                assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_probe','alerts_probe','alerts-owned')
                c.execute(text('SET search_path TO '+schema));c.execute(text("SET statement_timeout='8s'"))
                pids[role]=c.execute(text('select pg_backend_pid()')).scalar_one();c.commit();c.info['lock_role']=role
                try:
                    with Session(c) as s:
                        if role=='evaluate':
                            if kind=='metric':domain.svc.evaluate_node(s,1,NOW)
                            else:domain.legacy._evaluate(s,s.get(domain.alert.AlertRule,rid),True,'down',NOW)
                        else:
                            if operation=='delete':domain.legacy.delete_rule(s,rid)
                            elif kind=='metric':domain.svc.save(s,intent(enabled=False),rid,1,now=NOW)
                            else:domain.legacy.update_rule(s,rid,{'enabled':False})
                        s.commit()
                finally:c.info.pop('lock_role',None)
            return dict(role=role,status='committed')
        except Exception as e:return dict(role=role,status='error',error=type(e).__name__,pgcode=getattr(getattr(e,'orig',None),'pgcode',None))
    observation=None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f=pool.submit(worker,'evaluate')
            try:
                assert held.wait(5),'evaluator did not acquire rule before state'
                g=pool.submit(worker,'crud')
                with engine.connect() as observer:
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline:
                        if 'crud' in pids:
                            row=observer.execute(text('select wait_event_type,pg_blocking_pids(pid),query from pg_stat_activity where pid=:pid'),dict(pid=pids['crud'])).first();observer.commit()
                            if row and row[0]=='Lock' and pids['evaluate'] in row[1]:
                                observation=dict(wait=row[0],blockers=row[1],query=row[2]);break
                        time.sleep(.01)
                assert observation is not None,'no real PG wait observed'
            finally:release.set()
            results=[f.result(timeout=15),g.result(timeout=15)]
    finally:
        release.set();event.remove(engine,'before_cursor_execute',before);event.remove(engine,'after_cursor_execute',after)
    (tmp_path/f'locks-{kind}-{operation}.json').write_text(json.dumps(dict(observation=observation,results=results,trace=trace),indent=2))
    assert all(x['status']=='committed' for x in results),results
    assert 'alert_rules' in observation['query']
    assert 'FOR UPDATE' in observation['query']
    crud=[x['sql'] for x in trace if x['role']=='crud']
    assert next(i for i,x in enumerate(crud) if 'alert_rules' in x and 'FOR UPDATE' in x) < next((i for i,x in enumerate(crud) if 'alert_states' in x),len(crud))
    db.expire_all()
    assert db.query(domain.alert.AlertRule).filter_by(id=rid).count()==(0 if operation=='delete' else 1)
