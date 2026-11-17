"""Real selected lifecycle bodies with AST models and owned memory SQLite.
Not production imports, real PostgreSQL, auth transactions or full-main acceptance.
"""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import types
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from test_api_openapi_contract import ROOT
from test_api_response_contract import response_module
from jsonschema import Draft202012Validator


@pytest.fixture
def lifecycle(monkeypatch):
    class Base(DeclarativeBase):pass
    def package(name):
        module=types.ModuleType(name);module.__path__=[]
        monkeypatch.setitem(sys.modules,name,module)
        return module
    services=package('app.services');repos=package('app.repositories');models=package('app.models')
    def load(name,file,namespace,names=None,classes=False):
        module=types.ModuleType(name);module.__dict__.update(namespace)
        tree=ast.parse((ROOT/file).read_text())
        if names is not None:
            body=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
        else:
            body=[n for n in tree.body if not isinstance(n,ast.ImportFrom) or not (n.module or '').startswith('app')]
        exec(compile(ast.Module(body=body,type_ignores=[]),file,'exec'),module.__dict__)
        monkeypatch.setitem(sys.modules,name,module)
        return module
    common=dict(Base=Base,Mapped=Mapped,mapped_column=mapped_column,datetime=datetime,uuid4=uuid4,
                **{n:getattr(sa,n) for n in ['String','Text','Integer','BigInteger','DateTime','ForeignKey','UniqueConstraint','Boolean','true']})
    cfg=load('app.models.config','app/models/config.py',common,{'AppConfig'})
    mon=load('app.models.monitor','app/models/monitor.py',common,{'Monitor','MonitorGroup','MonitorGroupMember','MonitorCheck'})
    nodes=load('app.models.node','app/models/node.py',common|dict(JSONB=sa.JSON,func=sa.func),{'Node'})
    # SQLite cannot autoincrement a BIGINT primary key; retain all other model definitions.
    mon.MonitorCheck.__table__.c.id.type=sa.Integer()
    engine=sa.create_engine('sqlite://');Base.metadata.create_all(engine)
    db=Session(engine)
    def bump(db,commit=True):
        row=db.get(cfg.AppConfig,'monitors_version')
        if row is None:row=cfg.AppConfig(key='monitors_version',value='0');db.add(row)
        row.value=str(int(row.value)+1);db.flush()
        if commit:db.commit()
    version=types.ModuleType('app.repositories.config');version.bump_monitors_version=bump
    monkeypatch.setitem(sys.modules,version.__name__,version);repos.config=version
    # Authenticated saved-access selection is an explicit boundary. Real applied_origins
    # and lifecycle bodies choose saved values; deployment private is never consent.
    access=types.ModuleType('app.services.access_entries');access.KEY='access_entries.v1'
    access.bootstrap=lambda:dict(public_origin='https://public.test',private_origin='https://deployment-private.test')
    access.current=lambda:None
    access.read=lambda db:json.loads(db.get(cfg.AppConfig,access.KEY).value)
    monkeypatch.setitem(sys.modules,access.__name__,access);services.access_entries=access
    load('app.services.entry_targets','app/services/entry_targets.py',{})
    entry=load('app.services.entry_monitoring','app/services/entry_monitoring.py',{})
    groups=load('app.services.entry_monitor_groups','app/services/entry_monitor_groups.py',dict(AppConfig=cfg.AppConfig,Monitor=mon.Monitor,MonitorGroup=mon.MonitorGroup,MonitorGroupMember=mon.MonitorGroupMember))
    services.entry_monitoring=entry;services.entry_monitor_groups=groups
    projected=types.SimpleNamespace(list_monitors=lambda db:[types.SimpleNamespace(**{k:getattr(m,k) for k in ['id','visible','enabled','status']},effective_enabled=m.enabled) for m in db.query(mon.Monitor) if m.id not in entry.superseded_ids(db)])
    group_svc=load('app.services.monitor_groups','app/services/monitor_groups.py',dict(Monitor=mon.Monitor,MonitorGroup=mon.MonitorGroup,MonitorGroupMember=mon.MonitorGroupMember,monitor_svc=projected))
    monitor_svc=load('app.services.monitor','app/services/monitor.py',dict(Session=Session,Monitor=mon.Monitor),{'remove_monitor'})
    def save(public='https://public.test',private=None):
        value=json.dumps(dict(public_origin=public,private_origin=private));row=db.get(cfg.AppConfig,access.KEY)
        if row is None:db.add(cfg.AppConfig(key=access.KEY,value=value))
        else:row.value=value
        db.flush()
    def node(connected=False):
        n=nodes.Node(name='owned',platform='linux',host='192.0.2.1',token='owned',status='online' if connected else 'pending',last_seen_at=datetime.now(timezone.utc) if connected else None)
        db.add(n);db.flush();return n
    yield types.SimpleNamespace(db=db,models=mon,config=cfg,entry=entry,groups=groups,group_svc=group_svc,monitor_svc=monitor_svc,save=save,node=node)
    db.close();engine.dispose()


def test_empty_availability_real_projection_and_pending_not_connected(lifecycle):
    x=lifecycle;x.groups.bootstrap(x.db);x.db.commit()
    body=x.group_svc.list_groups(x.db)
    assert [g['entry_id'] for g in body]==['public','private']
    assert [g['availability_reason'] for g in body]==['no_connected_nodes','entry_not_configured']
    assert [g['visible'] for g in body]==[True,False]
    assert all(g['status'] is None and g['child_ids']==[] for g in body)
    schema=response_module().MODELS['list[MonitorGroupRead]'];Draft202012Validator(schema).validate(body)
    n=x.node();x.groups.reconcile(x.db,n);x.db.commit()
    assert x.db.query(x.models.Monitor).count()==0
    owner=x.groups.owners(x.db)
    private=x.db.get(x.models.MonitorGroup,body[1]['id']);private.visible=True;x.db.commit()
    x.groups.bootstrap(x.db);x.db.commit()
    assert x.groups.owners(x.db)==owner and private.visible is True
    assert x.entry.applied_origins(x.db)['private'] is None


def test_changed_origins_removed_node_archive_history_and_caller_rollback(lifecycle):
    x=lifecycle;x.groups.bootstrap(x.db);x.db.commit();n=x.node(connected=True)
    x.groups.reconcile(x.db,n);x.db.commit()
    original=x.db.query(x.models.Monitor).one();identity=x.groups.owners(x.db)
    check=x.models.MonitorCheck(monitor_id=original.id,ts=datetime.now(timezone.utc),success=True,latency_ms=2,loss_pct=0)
    x.db.add(check);x.db.commit();mid=original.id
    x.save(public='https://new.test',private='https://saved-private.test');x.groups.reconcile(x.db);x.db.commit()
    assert x.db.get(x.models.Monitor,mid) is not None
    assert x.db.query(x.models.MonitorCheck).filter_by(monitor_id=mid).count()==1
    assert x.db.query(x.models.MonitorGroupMember).filter_by(monitor_id=mid).count()==0
    state=json.loads(x.db.get(x.config.AppConfig,x.entry.LEDGER).value)
    assert next(v for v in state.values() if v['monitor_id']==mid)['archived']=='origin_changed'
    assert {g['target_origin'] for g in x.group_svc.list_groups(x.db)}=={'https://new.test','https://saved-private.test'}
    version=x.db.get(x.config.AppConfig,'monitors_version').value
    before=x.db.query(x.models.Monitor).count()
    x.save(public='https://rolled-back.test');x.groups.reconcile(x.db);x.db.rollback()
    assert x.db.query(x.models.Monitor).count()==before
    assert x.db.get(x.config.AppConfig,'monitors_version').value==version
    n.status='removed';x.db.flush();x.groups.reconcile(x.db,n);x.db.commit()
    assert all(g['child_ids']==[] and g['status'] is None for g in x.group_svc.list_groups(x.db))
    assert x.db.query(x.models.MonitorCheck).count()==1
    assert {k:(v['group_id'],v['owner_uuid']) for k,v in x.groups.owners(x.db).items()}=={k:(v['group_id'],v['owner_uuid']) for k,v in identity.items()}


@pytest.mark.parametrize('action',['dissolve','add-child','remove-member','delete-monitor'])
def test_system_crud_real_service_refusals(lifecycle,action):
    x=lifecycle;n=x.node(connected=True);x.groups.bootstrap(x.db);x.db.commit()
    group=x.group_svc.list_groups(x.db)[0];mid=group['child_ids'][0]
    with pytest.raises(ValueError,match='系统|自动入口'):
        if action=='dissolve':x.group_svc.remove_group(x.db,group['id'])
        elif action=='add-child':x.group_svc.create_child(x.db,group['id'],None)
        elif action=='remove-member':x.group_svc.save_group(x.db,group['id'],name='test',child_ids=[])
        else:x.monitor_svc.remove_monitor(x.db,mid)
    x.db.rollback()
    assert x.db.get(x.models.Monitor,mid) is not None
    assert x.db.query(x.models.MonitorGroupMember).filter_by(monitor_id=mid).count()==1
