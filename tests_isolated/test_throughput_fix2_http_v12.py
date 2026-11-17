"""Real FastAPI transport/token/route/service/repository with in-memory DB double.
AST allowlist avoids signing key/config/bootstrap; no TCP/real DB or auth login.
"""
import ast, json, os
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from copy import deepcopy
from unittest.mock import Mock
import pytest
from fastapi import FastAPI, APIRouter, Depends, Request, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.services import task as svc
from app.schemas.monitor import IperfTaskRead
from tests_isolated.test_throughput_fix2_v12 import GO, IPERF, NATIVE, OOKLA, CLI
ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def http(monkeypatch):
    row = SimpleNamespace(id=7, status='running', mode='speedtest', direction='forward', speedtest_server=None,
        progress_json=[], result_json=None, client_node_id=1, server_node_id=None, server_started=True,
        duration=10, parallel=1, created_at='2026-10-22T00:00:00Z')
    class DB:
        locks = 0
        def get(self, model, ident): return row if ident == 7 else None
        def query(self, *a): return self
        def filter(self, *a): return self
        def with_for_update(self): self.locks += 1; return self
        def first(self): return row
        def commit(self): pass
    db = DB()
    def get_db(): return db
    node_lookup = {'client': SimpleNamespace(id=1, status='online'), 'server': SimpleNamespace(id=2, status='online'),
             'other': SimpleNamespace(id=3, status='online'), 'removed': SimpleNamespace(id=1, status='removed')}
    monkeypatch.setattr(svc.node_repo, 'get_by_token', lambda db, token: node_lookup.get(token))
    ns = dict(Request=Request, HTTPException=HTTPException)
    token = next(n for n in ast.parse((ROOT/'app/security.py').read_text()).body if isinstance(n, ast.FunctionDef) and n.name=='agent_token')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[token], type_ignores=[])), str(ROOT/'app/security.py'), 'exec'), ns)
    ns.update(APIRouter=APIRouter, Annotated=Annotated, Depends=Depends, Session=Session, get_db=get_db, task_svc=svc)
    tree = ast.parse((ROOT/'app/routers/task.py').read_text())
    route_nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='agent_task_router' for t in n.targets))
             or (isinstance(n, ast.FunctionDef) and n.name in ('finish_iperf', 'get_iperf_status', 'iperf_progress'))]
    exec(compile(ast.fix_missing_locations(ast.Module(body=route_nodes, type_ignores=[])), str(ROOT/'app/routers/task.py'), 'exec'), ns)
    app = FastAPI(); app.include_router(ns['agent_task_router'])
    with TestClient(app) as client:
        yield client, row, db

@pytest.mark.parametrize('headers,query,expected', [({}, '', 401), ({}, '&token=unknown', 401),
    ({'Authorization': 'invalid'}, '&token=client', 401), ({'Authorization': 'Bearer other'}, '', 403),
    ({'Authorization': 'Bearer removed'}, '', 401), ({'Authorization': 'Bearer server'}, '', 403)])
def test_http_permissions_are_not_bypassed_by_invalid_done(http, headers, query, expected):
    client, row, db = http
    response = client.post('/agent/iperf-tasks/7/result?status=done'+query, headers=headers, json={})
    assert response.status_code == expected
    assert row.status == 'running' and row.result_json is None

@pytest.mark.parametrize('mode,payload', [('speedtest', {}), ('speedtest', IPERF), ('iperf3', GO),
    ('speedtest', dict(GO, error='synthetic failure')), ('iperf3', {'role': 'client'})])
def test_http_mode_invalid_done_fails_and_status_readback_agrees(http, mode, payload):
    client, row, db = http; row.mode = mode
    response = client.post('/agent/iperf-tasks/7/result?status=done', headers={'Authorization':'Bearer client'}, json=payload)
    assert response.status_code == 200 and row.status == 'failed' and row.result_json.get('error')
    assert db.locks == 1
    assert client.get('/agent/iperf-tasks/7/status', headers={'Authorization':'Bearer client'}).json() == {'status':'failed'}
    assert IperfTaskRead.model_validate(row).model_dump(mode='json')['result_json']['raw_origin'] == 'task_error'

@pytest.mark.parametrize('terminal', ['done', 'failed', 'cancelled'])
def test_http_late_result_and_progress_cannot_reopen_terminal(http, terminal):
    client, row, db = http; row.status = terminal; row.result_json = {'error':'original'}
    for endpoint, query, data in [('result','status=done',GO), ('progress','ts=fixture&bitrate=10',None)]:
        response = client.post('/agent/iperf-tasks/7/'+endpoint+'?'+query, headers={'Authorization':'Bearer client'}, json=data)
        assert response.status_code == 409
    assert row.status == terminal and row.result_json == {'error':'original'}


def test_http_actual_service_cancel_then_late_result(http):
    client, row, db = http
    svc.cancel_iperf(db, 7)
    response = client.post('/agent/iperf-tasks/7/result?status=done', headers={'Authorization':'Bearer client'}, json=GO)
    assert response.status_code == 409
    assert client.get('/agent/iperf-tasks/7/status?token=client').json() == {'status':'cancelled'}


def test_http_wrong_role_status_and_server_failure(http):
    client, row, db = http; row.mode='iperf3'; row.server_node_id=2
    for token, payload, status, expected in [('server',IPERF,'done',403), ('client',dict(IPERF,role='server'),'done',403),
        ('client',dict(IPERF,role='stage'),'done',422), ('client',IPERF,'cancelled',422)]:
        r=client.post('/agent/iperf-tasks/7/result?status='+status, headers={'Authorization':'Bearer '+token}, json=payload)
        assert r.status_code == expected
    assert row.status == 'running'
    row.status='pending'
    r=client.post('/agent/iperf-tasks/7/result?status=failed', headers={'Authorization':'Bearer server'}, json={'role':'server','error':'bind failed'})
    assert r.status_code == 200 and row.status == 'failed'


def test_http_valid_data_contract_and_export(http):
    client, row, db = http; fixtures=[]
    for mode, payload in [('iperf3', IPERF), ('iperf3', NATIVE), ('speedtest', GO), ('speedtest', OOKLA), ('speedtest', CLI),
                          ('iperf3', dict(IPERF, avg_bitrate=0, total_bytes=0, udp=True, lost_pct=None)),
                          ('speedtest', {}), ('speedtest', dict(GO, error='synthetic failure')), ('speedtest', IPERF)]:
        row.mode=mode; row.status='running'; row.result_json=None
        for field in ('avg_mbps', 'peak_mbps', 'lost_pct', 'jitter_ms'):
            setattr(row, field, None)
        expected = 'failed' if mode == 'speedtest' and (not payload or 'error' in payload or 'avg_bitrate' in payload) else 'done'
        r=client.post('/agent/iperf-tasks/7/result?status=done', headers={'Authorization':'Bearer client'}, json=deepcopy(payload))
        assert r.status_code == 200 and row.status == expected
        public = IperfTaskRead.model_validate(row).model_dump(mode='json')
        assert (public['result_json']['raw_origin'] == 'task_error') == (expected == 'failed')
        fixtures.append({'request':payload, 'read':public})
    output=os.getenv('THROUGHPUT_FIXTURES_OUT')
    if output:
        with Path(output).open('x') as f: json.dump(fixtures,f,ensure_ascii=False,indent=2)
