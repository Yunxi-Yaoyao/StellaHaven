"""Closed identity HTTP contract, actual router slice, no app bootstrap/DB."""
import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
ROOT = Path(__file__).resolve().parents[1]

def client():
    source = ast.parse((ROOT/'app/routers/monitor.py').read_text())
    body = [n for n in source.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in {'AgentIdentityRead','agent_identity'}]
    assert body, 'Authenticated identity endpoint is missing'
    def token(): return 'fixture-token'
    def db(): yield None
    repo = SimpleNamespace(get_by_token=lambda db,token: SimpleNamespace(id=17,status='online'))
    ns = dict(__file__=str(ROOT/'app/routers/monitor.py'),agent_router=APIRouter(prefix='/agent'),
              BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,Depends=Depends,Annotated=Annotated,
              Session=Session,get_db=db,agent_token=token,HTTPException=HTTPException,
              identity_install_svc=SimpleNamespace(installation_center_id=lambda:'a'*64),identity_node_repo=repo)
    exec(compile(ast.Module(body=body,type_ignores=[]),'real-identity-route','exec'),ns)
    app = FastAPI(); app.include_router(ns['agent_router']); return TestClient(app),ns,repo

def test_identity_exact_response_and_removed_token_closed():
    c,ns,repo = client()
    response = c.get('/agent/identity'); assert response.status_code == 200
    body = (ROOT/'agent/stella_agent.py').read_bytes()
    assert response.json() == dict(center_id='a'*64,node_id=17,source_version='0.6.21',
        source_sha256=hashlib.sha256(body).hexdigest(),source_size=len(body))
    assert response.headers['cache-control'] == 'no-store'
    repo.get_by_token = lambda db,token: None
    assert c.get('/agent/identity').status_code == 401


def test_fresh_non_ha_center_identity_is_serialized_without_oidc_clients(tmp_path, monkeypatch):
    import concurrent.futures
    import sys
    import threading
    import time
    import types
    from authlib.jose import JsonWebKey
    # Load the REAL key bootstrap and public projection, never import app state.
    text = (ROOT/'app/services/oidc.py').read_text()
    tree = ast.parse(text)
    funcs = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_get_key','jwks'}]
    keyns = dict(Path=Path,os=__import__('os'),json=__import__('json'),ha_state=SimpleNamespace(enabled=lambda:False),OIDC_DIR=tmp_path/'oidc',
                 PRIVATE_KEY_PATH=tmp_path/'oidc/private.json',KID='stella-oidc-1',JsonWebKey=JsonWebKey)
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'actual-key-bootstrap','exec'),keyns)
    oidc = types.ModuleType('app.services.oidc')
    for key in ('jwks','_get_key','OIDC_DIR','PRIVATE_KEY_PATH','ha_state','KID'): setattr(oidc,key,keyns[key])
    monkeypatch.setitem(sys.modules,'app.services.oidc',oidc)
    services = types.ModuleType('app.services'); services.oidc = oidc
    services.__path__ = [str(ROOT/'app/services')]
    monkeypatch.setitem(sys.modules,'app.services',services)
    # Delay actual RSA generation enough to reproduce simultaneous first install.
    original = JsonWebKey.generate_key
    def slow(*args,**kwargs): time.sleep(.15); return original(*args,**kwargs)
    monkeypatch.setattr(JsonWebKey,'generate_key',slow)
    text = (ROOT/'app/services/agent_channels.py').read_text()
    fn = next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='center_id')
    ns = dict(hashlib=hashlib,json=__import__('json'))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-center-id','exec'),ns)
    channels = types.ModuleType('app.services.agent_channels'); channels.center_id = ns['center_id']
    services.agent_channels = channels
    monkeypatch.setitem(sys.modules,'app.services.agent_channels',channels)
    source = ast.parse((ROOT/'app/services/agent_install.py').read_text())
    funcs = [n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='installation_center_id']
    assert funcs, 'Authenticated identity provisioning is missing for no-OIDC fresh centers'
    bootstrap = {'os':__import__('os')}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'actual-install-center','exec'),bootstrap)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: bootstrap['installation_center_id'](),range(2)))
    assert len(set(ids)) == 1, 'Concurrent first installs must see the same persisted public key identity'
    assert ns['center_id']() == ids[0]


def test_missing_center_identity_fails_closed_without_fallback_to_url_or_token():
    c,ns,_ = client()
    def unavailable(): raise RuntimeError('missing configured signing identity')
    ns['identity_install_svc'].installation_center_id = unavailable
    assert c.get('/agent/identity').status_code == 503
