"""Real dedicated PG; isolated imports, no production configuration or network."""
import importlib,os,sys,types,uuid
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column,Session
ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,10,16,tzinfo=timezone.utc)

@pytest.fixture(scope='module')
def domain():
    class Base(DeclarativeBase): pass
    modules={}
    for path in ['app','app.models','app.services','app.repositories']:
        m=types.ModuleType(path);m.__path__=[str(ROOT/path.replace('.','/'))];modules[path]=m
    modules['app.models'].__dict__.update(Base=Base,Mapped=Mapped,mapped_column=mapped_column,UUID=uuid.UUID,uuid4=uuid.uuid4)
    # Production config/database imports are a hard failure.
    modules['app.config']=None; modules['app.database']=None
    before=set(sys.modules)
    with patch.dict(sys.modules,modules):
        node=importlib.import_module('app.models.node')
        alert=importlib.import_module('app.models.alert')
        importlib.import_module('app.models.user')
        importlib.import_module('app.models.config')
        legacy=importlib.import_module('app.services.alerts')
        svc=None
        if (ROOT/'app/services/alert_metrics.py').exists(): svc=importlib.import_module('app.services.alert_metrics')
        yield types.SimpleNamespace(Base=Base,node=node,alert=alert,svc=svc,legacy=legacy)
        for key in set(sys.modules)-before:
            if key.startswith('app.'):sys.modules.pop(key,None)

@pytest.fixture
def db(domain):
    dsn=os.environ.get('ALERTS_TEST_DSN')
    assert dsn, 'explicit owned PG required'
    u=make_url(dsn)
    assert (u.host,u.port,u.username,u.database)==('127.0.0.1',int(os.environ['ALERTS_TEST_PORT']),'alerts_probe','alerts_probe') and not u.query
    engine=create_engine(u)
    schema='alerts_'+uuid.uuid4().hex
    with engine.connect() as c:
        assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_probe','alerts_probe','alerts-owned')
        c.execute(text(f'CREATE SCHEMA {schema}'));c.commit()
        c.execute(text(f'SET search_path TO {schema}'));c.commit()
        domain.Base.metadata.create_all(c);c.commit()
        try:
            with Session(c) as session:
                node=domain.node.Node(name='Synthetic',platform='linux',host='invalid.test',interfaces={'eth0':{'physical':True}},status='online',last_seen_at=NOW)
                session.add(node);session.commit()
                yield session
        finally:
            c.rollback()
            assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_probe','alerts_probe','alerts-owned')
            c.execute(text(f'DROP SCHEMA {schema} CASCADE'));c.commit()
            assert c.execute(text('select 1 from pg_namespace where nspname=:s'),{'s':schema}).first() is None
    engine.dispose()

def intent(**kw):
    return dict(node_id=1,label='出站',condition={'metric':'network.rate','interface':'eth0','direction':'out','threshold':'80'},debounce=2,email=False,**kw)

def sample(d,db,t=NOW,tx=100):
    p=d.node.NodeMetric(node_id=1,iface='eth0',ts=t,rx_delta=0,tx_delta=tx,interval_start=t-timedelta(seconds=10),elapsed_seconds=10,quality='valid')
    db.add(p);db.commit();return p

def test_rule_multi_revision_legacy_compatibility(domain,db):
    assert domain.svc is not None, 'persisted metric rules are missing'
    a=domain.svc.save(db,intent());db.commit()
    b=intent();b['condition']['direction']='in'
    domain.svc.save(db,b);db.commit()
    domain.legacy.create_rule(db,'node_offline','1',email=False);db.commit()
    assert len(domain.legacy.list_rules(db))==1
    assert len(domain.svc.list_rules(db))==2
    with pytest.raises(ValueError):domain.svc.save(db,intent())
    db.rollback()
    with pytest.raises(ValueError,match='revision'):domain.svc.save(db,intent(),a.id,99)
    with pytest.raises(ValueError):domain.legacy.update_rule(db,a.id,{'enabled':False})

def test_readonly_preview_and_watermark_unknown(domain,db,monkeypatch):
    assert domain.svc is not None, 'persisted metric rules are missing'
    dispatched=[]
    monkeypatch.setattr(domain.legacy,'_push_ws',lambda p:dispatched.append(p))
    r=domain.svc.save(db,intent(),now=NOW-timedelta(seconds=10));db.commit();sample(domain,db)
    counts=lambda:[db.query(m).count() for m in (domain.alert.AlertState,domain.alert.AlertEvent,domain.alert.Notification)]
    before=counts();p=domain.svc.preview(db,1,intent()['condition'],NOW)
    assert p['bad'] is True and counts()==before and dispatched==[]
    domain.svc.evaluate_node(db,1,NOW);db.commit()
    domain.svc.evaluate_node(db,1,NOW);db.commit()
    s=db.get(domain.alert.AlertState,r.id)
    assert s.consecutive==1 and s.state=='ok'
    sample(domain,db,NOW+timedelta(seconds=10))
    domain.svc.evaluate_node(db,1,NOW+timedelta(seconds=10))
    assert dispatched==[]
    db.commit(); assert len(dispatched)==1
    assert db.get(domain.alert.AlertState,r.id).state=='firing'
    domain.svc.evaluate_node(db,1,NOW+timedelta(minutes=5));db.commit()
    assert db.get(domain.alert.AlertState,r.id).state=='firing'
    assert db.query(domain.alert.AlertEvent).count()==1

def test_rollback_does_not_dispatch(domain,db,monkeypatch):
    seen=[];monkeypatch.setattr(domain.legacy,'_push_ws',seen.append)
    r=domain.legacy.create_rule(db,'node_offline','1',debounce=1,email=False);db.commit()
    domain.legacy._evaluate(db,r,True,'down',NOW)
    assert seen==[]
    db.rollback();assert seen==[]
    assert db.query(domain.alert.Notification).count()==0
    domain.legacy._evaluate(db,r,True,'down',NOW+timedelta(seconds=1));db.commit()
    assert len(seen)==1

def test_fixed_sql_matches_strict_bounds_and_excludes_other_iface(domain,db):
    assert domain.svc is not None, 'persisted metric rules are missing'
    sample(domain,db,NOW-timedelta(seconds=10),900)
    sample(domain,db,NOW,200)
    c={'metric':'network.volume','interface':'eth0','direction':'out','threshold':'1000','window':{'kind':'fixed','start':(NOW-timedelta(seconds=20)).isoformat(),'end':NOW.isoformat(),'timezone':'UTC'}}
    p=domain.svc.preview(db,1,c,NOW)
    assert p['value']=='1100' and p['bad'] is True
    db.query(domain.node.NodeMetric).filter(domain.node.NodeMetric.ts==NOW-timedelta(seconds=10)).delete();db.commit()
    p=domain.svc.preview(db,1,c,NOW)
    assert p['value'] is None and p['upper'] is None and p['lower']=='200' and p['bad'] is None


def test_legacy_duplicate_and_unknown_never_recovers(domain,db,monkeypatch):
    monkeypatch.setattr(domain.legacy,'_push_ws',lambda p:None)
    r=domain.legacy.create_rule(db,'node_offline','1',debounce=2,email=False);db.commit()
    domain.legacy._evaluate(db,r,True,'down',NOW);db.commit()
    domain.legacy._evaluate(db,r,True,'down',NOW);db.commit()
    assert db.get(domain.alert.AlertState,r.id).consecutive==1
    domain.legacy._evaluate(db,r,True,'down',NOW+timedelta(seconds=5));db.commit()
    domain.legacy._evaluate(db,r,None,'',NOW+timedelta(seconds=10));db.commit()
    assert db.get(domain.alert.AlertState,r.id).state=='firing'


def test_savepoint_does_not_dispatch_before_outer_commit(domain,db,monkeypatch):
    seen=[];monkeypatch.setattr(domain.legacy,'_push_ws',seen.append)
    r=domain.legacy.create_rule(db,'node_offline','1',debounce=1,email=False);db.commit()
    domain.legacy._evaluate(db,r,True,'down',NOW)
    with db.begin_nested(): pass
    assert seen==[]
    db.commit();assert len(seen)==1


def test_http_preview_validation_permissions_and_revision(domain,db):
    from fastapi import FastAPI,HTTPException,Header
    from fastapi.testclient import TestClient
    def current(authorization: str = Header('')):
        if authorization not in ('reader','admin'):raise HTTPException(401)
    def admin(authorization: str = Header('')):
        if authorization!='admin':raise HTTPException(403)
    def get_db():yield db
    database=types.ModuleType('app.database');database.get_db=get_db
    auth=types.ModuleType('app.routers.auth');auth.current_user=current;auth.admin_user=admin
    routers=types.ModuleType('app.routers');routers.__path__=[str(ROOT/'app/routers')]
    with patch.dict(sys.modules,{'app.database':database,'app.routers.auth':auth,'app.routers':routers}):
        router=importlib.import_module('app.routers.alerts')
        app=FastAPI();app.include_router(router.router)
        with TestClient(app) as client:
            p={'node_id':1,'condition':intent()['condition']}
            assert client.post('/alerts/v2/preview',json=p).status_code==401
            r=client.post('/alerts/v2/preview',json=p,headers={'authorization':'reader'})
            assert r.status_code==200,r.text
            assert r.json()['value'] is None
            assert client.post('/alerts/v2/rules',json=intent(),headers={'authorization':'reader'}).status_code==403
            response=client.post('/alerts/v2/rules',json=intent(),headers={'authorization':'admin'})
            assert response.status_code==201,response.text
            saved=response.json()
            patch_data={**intent(),'revision':saved['revision']}
            assert client.put(f"/alerts/v2/rules/{saved['id']}",json=patch_data,headers={'authorization':'admin'}).status_code==200
            assert client.put(f"/alerts/v2/rules/{saved['id']}",json=patch_data,headers={'authorization':'admin'}).status_code==409
            assert client.get('/alerts/rules',headers={'authorization':'reader'}).json()==[]
            assert db.query(domain.alert.AlertEvent).count()==0
        sys.modules.pop('app.routers.alerts',None)


def test_nested_notification_rollback_cannot_escape(domain,db,monkeypatch):
    seen=[];monkeypatch.setattr(domain.legacy,'_push_ws',seen.append)
    r=domain.legacy.create_rule(db,'node_offline','1',debounce=1,email=False);db.commit()
    nested=db.begin_nested()
    domain.legacy._evaluate(db,r,True,'down',NOW)
    nested.rollback();db.commit()
    assert seen==[] and db.query(domain.alert.Notification).count()==0


def test_concurrent_workers_count_one_sample(domain,db,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    seen=[];monkeypatch.setattr(domain.legacy,'_push_ws',seen.append)
    data=intent();data['debounce']=1
    r=domain.svc.save(db,data,now=NOW-timedelta(seconds=10));rid=r.id;db.commit();sample(domain,db)
    schema=db.execute(text('select current_schema()')).scalar_one();db.commit()
    engine=db.get_bind().engine;barrier=Barrier(2)
    def worker():
        with engine.connect() as c:
            assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_probe','alerts_probe','alerts-owned')
            c.execute(text(f'SET search_path TO {schema}'));c.commit()
            with Session(c) as s:
                barrier.wait(timeout=5);domain.svc.evaluate_node(s,1,NOW);s.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker) for _ in range(2)]
        for f in futures:f.result(timeout=10)
    db.expire_all()
    assert db.get(domain.alert.AlertState,rid).consecutive==1
    assert db.query(domain.alert.AlertEvent).count()==1 and len(seen)==1


def test_actual_additive_migrations_preserve_legacy(domain,db):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import importlib.util
    r=domain.legacy.create_rule(db,'node_offline','1',email=False);rid=r.id;db.commit()
    for index in ('uq_alert_rule_legacy','uq_alert_rule_fingerprint'):db.execute(text(f'DROP INDEX {index}'))
    for table,cols in [('alert_rules',['schema_version','revision','condition','fingerprint']),('alert_states',['watermark','evaluated_at','preview']),('node_metrics',['interval_start','elapsed_seconds','quality'])]:
        for col in cols:db.execute(text(f'ALTER TABLE {table} DROP COLUMN {col}'))
    db.execute(text('ALTER TABLE alert_rules ADD CONSTRAINT uq_alert_rule UNIQUE(kind,target)'));db.commit()
    c=db.connection()
    assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_probe','alerts_probe','alerts-owned')
    ctx=MigrationContext.configure(c)
    with Operations.context(ctx):
        for filename in ('d0a1b2c3d4e5_alert_intervals.py','d1a2b3c4d5e6_alert_metric_rules.py'):
            spec=importlib.util.spec_from_file_location('_migration',ROOT/'alembic/versions'/filename)
            m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.upgrade()
    db.commit();db.expire_all()
    old=db.get(domain.alert.AlertRule,rid)
    assert old.schema_version==1 and old.revision==1 and old.target=='1'
    assert db.get(domain.alert.AlertState,rid).state=='ok'
    domain.svc.save(db,intent());db.commit()
    assert db.query(domain.alert.AlertRule).count()==2


def test_scope_cache_and_event_budget(domain,db,monkeypatch):
    a=intent();b=intent();b['condition']['threshold']='90'
    domain.svc.save(db,a,now=NOW-timedelta(seconds=10));domain.svc.save(db,b,now=NOW-timedelta(seconds=10));db.commit();sample(domain,db)
    original=domain.svc.preview;calls=[]
    def preview(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(domain.svc,'preview',preview)
    domain.svc.evaluate_node(db,1,NOW);db.commit()
    assert len(calls)==1, 'same observation scope must share query even with different thresholds'


def test_event_work_budget_defers_visibly(domain,db,monkeypatch):
    a=intent();b=intent();b['condition']['direction']='in'
    domain.svc.save(db,a,now=NOW-timedelta(seconds=10));domain.svc.save(db,b,now=NOW-timedelta(seconds=10));db.commit();sample(domain,db)
    assert hasattr(domain.svc,'monotonic'), 'event evaluation has no wall-clock budget'
    ticks=iter([0,0,3]);monkeypatch.setattr(domain.svc,'monotonic',lambda:next(ticks))
    domain.svc.evaluate_node(db,1,NOW);db.commit()
    states=db.query(domain.alert.AlertState).order_by(domain.alert.AlertState.rule_id).all()
    assert states[1].preview['reason']=='evaluation_lag'
    assert states[1].watermark==NOW-timedelta(seconds=10)


def test_fixed_volume_100k_input_budget_receipt(domain,db):
    import json,time
    count=100000;step=5;start=NOW-timedelta(seconds=count*step)
    db.execute(text("""INSERT INTO node_metrics(node_id,iface,ts,interval_start,elapsed_seconds,quality,rx_delta,tx_delta)
      SELECT 1,'eth0',:start + i*interval '5 seconds',:start+(i-1)*interval '5 seconds',5,'valid',0,100
      FROM generate_series(1,:n) i"""),{'start':start,'n':count});db.commit()
    c={'metric':'network.volume','interface':'eth0','direction':'out','threshold':str(count*100),'window':{'kind':'fixed','start':start.isoformat(),'end':NOW.isoformat(),'timezone':'UTC'}}
    tick=time.monotonic();p=domain.svc.preview(db,1,c,NOW);elapsed=time.monotonic()-tick
    assert p['value']==str(count*100) and p['quality']=='valid'
    plan=db.execute(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+domain.svc._VOLUME_SQL.text),dict(node=1,iface='eth0',start=start,end=NOW,stop=NOW+timedelta(seconds=300),direction='out')).scalar_one()
    (ROOT/'docs/alerts-evidence/query-budget.json').write_text(json.dumps({'rows':count,'preview_seconds':elapsed,'value':p['value'],'plan':plan},indent=2))


def test_query_timeout_is_unknown_and_transaction_survives(domain,db,monkeypatch):
    monkeypatch.setattr(domain.svc,'_VOLUME_SQL',text('SELECT pg_sleep(6)'))
    c={'metric':'network.volume','interface':'eth0','direction':'out','threshold':'100','window':{'kind':'fixed','start':(NOW-timedelta(days=1)).isoformat(),'end':NOW.isoformat(),'timezone':'UTC'}}
    p=domain.svc.preview(db,1,c,NOW)
    assert p['reason']=='query_unavailable' and p['value'] is None and p['bad'] is None
    assert db.execute(text('SELECT 1')).scalar_one()==1


@pytest.mark.parametrize('name',[
 'test_create_rule_validates_and_rejects_duplicate','test_update_and_delete_rule_cascades_state',
 'test_node_offline_debounce_then_fire_and_resolve','test_firing_repeat_reminder_respects_interval',
 'test_disabled_rule_is_not_evaluated','test_pending_or_removed_node_does_not_fire',
 'test_rule_on_deleted_target_preserves_incident_and_stays_quiet','test_monitor_down_fires_and_recovers',
 'test_wg_link_fires_on_failed_only_and_unknown_is_not_bad','test_wg_link_missing_from_topology_is_neutral'])
def test_original_legacy_cases_on_owned_pg(domain,db,monkeypatch,name):
    import inspect,importlib.util
    # Only unused history-query imports are isolated; original CRUD, sampling,
    # monitor/node repositories and alert evaluators are actual product code.
    stub=types.ModuleType('app.services.node')
    def forbidden(*a,**k):raise AssertionError('unapproved history path')
    stub.query_window=stub.run_history_query=forbidden
    with patch.dict(sys.modules,{'app.services.node':stub}):
        spec=importlib.util.spec_from_file_location('_legacy_alert_cases',ROOT/'tests/test_alerts.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        calls=old.no_side_effects.__wrapped__(monkeypatch,db)
        fn=getattr(old,name)
        args={'db_session':db,'no_side_effects':calls,'monkeypatch':monkeypatch}
        fn(**{key:args[key] for key in inspect.signature(fn).parameters})

