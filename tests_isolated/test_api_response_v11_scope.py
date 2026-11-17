"""Selected real config route and scope bodies; DB/channel inputs are synthetic."""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.schemas.monitor import AgentConfig
from test_api_openapi_contract import ROOT


@pytest.fixture(autouse=True)
def isolated_scope_import_boundary(monkeypatch):
    import sys
    import types
    package=types.ModuleType('app.services');package.__path__=[]
    module=types.ModuleType('app.services.entry_targets')
    exec(compile((ROOT/'app/services/entry_targets.py').read_text(),'real-entry-targets','exec'),module.__dict__)
    monkeypatch.setitem(sys.modules,'app.services',package)
    monkeypatch.setitem(sys.modules,'app.services.entry_targets',module)


def scope_namespace():
    ns={}
    tree=ast.parse((ROOT/'app/services/entry_monitoring.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='effective_scope')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-effective-scope','exec'),ns)
    return ns


def native_scope():
    ns={}
    tree=ast.parse((ROOT/'agent/stella_agent.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_entry_scope','_parse_entry_scope','_entry_ip_allowed'}]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-native-scope','exec'),ns)
    return ns


def test_actual_config_decorator_omits_null_targets_native_parser_accepts(monkeypatch):
    monkeypatch.delenv('STELLA_ENTRY_APPROVED_RANGES',raising=False)
    cap={'ready':True,'types':['ping']};effective=scope_namespace()['effective_scope'](cap)
    plan=dict(entries=[],interval=60,max_ips=4,deadline_seconds=12,icmp_available=True,
              targets=effective.get('targets'),approved_ranges=effective.get('approved_ranges',[]))
    auth=next(n for n in ast.parse((ROOT/'app/security.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='agent_token')
    ns=dict(Request=Request,HTTPException=HTTPException)
    exec(compile(ast.Module(body=[auth],type_ignores=[]),'actual-token-dependency','exec'),ns)
    ns.update(Annotated=Annotated,Depends=Depends,Session=object,AgentConfig=AgentConfig,
              agent_router=APIRouter(prefix='/agent'),get_db=lambda:None,
              node_svc=SimpleNamespace(get_agent_config=lambda db,token:SimpleNamespace(id=7,monitored_ifaces=None)),
              monitor_svc=SimpleNamespace(list_monitors_for_node=lambda db,node_id:[]),
              config_repo=SimpleNamespace(get_monitors_version=lambda db:3),
              entry_monitoring=SimpleNamespace(manifest=lambda node,db:plan),
              agent_channels=SimpleNamespace(optional_config=lambda db,node:None))
    route=next(n for n in ast.parse((ROOT/'app/routers/monitor.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='agent_config')
    exec(compile(ast.Module(body=[route],type_ignores=[]),'actual-config-route','exec'),ns)
    app=FastAPI();app.include_router(ns['agent_router']);c=TestClient(app)
    assert c.get('/agent/config').status_code==401
    response=c.get('/agent/config',headers={'Authorization':'Bearer owned'})
    assert response.status_code==200
    wire=response.json();assert 'report_channel' not in wire and 'monitored_ifaces' not in wire
    assert 'targets' not in wire['entry_monitoring']
    native=native_scope();native['_entry_scope'](wire['entry_monitoring'])
    assert native['_entry_ip_allowed']('8.8.8.8',wire['entry_monitoring'].get('targets'),[])
    assert not native['_entry_ip_allowed']('192.168.0.103',wire['entry_monitoring'].get('targets'),[])


def test_precise_deployment_scope_merges_without_widening_or_mutating(monkeypatch):
    monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES','["192.168.0.103/32"]')
    cap={'ready':True,'types':['ping'],'targets':[],'approved_ranges':['10.9.8.7/32']}
    result=scope_namespace()['effective_scope'](cap)
    assert result['approved_ranges']==['10.9.8.7/32','192.168.0.103/32']
    assert cap['approved_ranges']==['10.9.8.7/32']
    native=native_scope();native['_entry_scope'](result)
    for ip,allowed in [('192.168.0.103',True),('10.9.8.7',True),('192.168.0.104',False),('8.8.8.8',False),('169.254.169.254',False),('127.0.0.1',False)]:
        assert native['_entry_ip_allowed'](ip,result.get('targets'),result['approved_ranges']) is allowed
    with pytest.raises(ValueError):scope_namespace()['effective_scope']({'targets':None})


@pytest.mark.parametrize('raw',['null','{}','[null]','["192.168.0.103"]','["192.168.0.103/24"]','["bad"]','not-json'])
def test_invalid_deployment_consent_remains_closed(monkeypatch,raw):
    monkeypatch.setenv('STELLA_ENTRY_APPROVED_RANGES',raw)
    with pytest.raises((ValueError,TypeError)):scope_namespace()['effective_scope']({})
