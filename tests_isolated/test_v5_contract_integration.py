"""Bounded merged router/request/response contract fixture, owned SQLite only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from pydantic import TypeAdapter

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from test_node_monitor_policy import db, node
from test_report_channels import channels

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / 'app/api_response_v5_integration.json'


def test_disk_overlay_classifies_union_and_preserves_incomplete():
    from app import api_response_contracts as r
    assert OVERLAY.is_file()
    overlay = json.loads(OVERLAY.read_text())
    assert overlay['worker_approval'] is False
    new = {('GET','/monitors/groups/receipts/{request_key}'),
           ('GET','/nodes/report-channels'), ('PUT','/nodes/report-channels'),
           ('GET','/agent/entry-probe')}
    assert all(r.DECLARATIONS[key]['status'] == 'reviewed' for key in new)
    incomplete = {key: value['reason'] for key, value in r.DECLARATIONS.items() if value['status'] == 'incomplete'}
    assert len(incomplete) == 3
    assert all('notification' in reason.lower() or 'context' in reason.lower() for reason in incomplete.values())
    # V5 is historical; approved later overlays own the current read DTOs.
    from api_response_evidence_fixture import reviews
    from app.schemas.monitor import MonitorRead, MonitorGroupRead
    reviews()  # Independently pinned successor layers, not today's bytes as a pin.
    for key, dto in [('MonitorRead', MonitorRead), ('list[MonitorRead]', list[MonitorRead]),
                     ('MonitorGroupRead', MonitorGroupRead), ('list[MonitorGroupRead]', list[MonitorGroupRead])]:
        assert r.MODELS[key] == TypeAdapter(dto).json_schema(mode='serialization')
    from app.schemas import channel
    for name in overlay['channel_DTO_names']:
        assert r.MODELS[name] == getattr(channel, name).model_json_schema()
    # Preserve normalized legacy constraints, not the native legacy Any schema.
    assert r.MODELS['AgentConfig'] == overlay['models']['AgentConfig']
    assert not r.schema_holes(r.MODELS['AgentConfig'])
    for suffix in ('logical_key','ensure_logical_monitor','entry_reason'):
        for endpoint in ('agent_config','agent_report','list_monitors','list_monitor_groups'):
            rows = [v for v in r.INVENTORY if v['endpoint'] == 'app.routers.monitor.'+endpoint]
            assert rows and any(suffix in key for key in rows[0]['sources'])
    # The initial pending overlay stays immutable; only the subsequent external
    # exact approval may make the active source union pass.
    assert r._NODE_INTERRUPTION_REVIEW['worker_source_approved'] is True
    errors = r.validate_response_sources(ROOT, [(v['method'],v['path'],v['endpoint'],None) for v in r.INVENTORY])
    assert errors == []


@pytest.fixture
def native(db, channels):
    from app.routers.monitor import monitor_router, node_router, agent_router
    from app.routers.auth import current_user, admin_user
    from app.database import get_db
    app = FastAPI()
    for router in (monitor_router, node_router, agent_router):
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    state = {'sid': UUID('12345678-1234-4234-8234-123456789abc')}
    def authenticated(request: Request):
        from datetime import datetime, timezone
        request.state.auth_session = SimpleNamespace(id=state['sid'],revoked=False,
                                                     remember=False,last_seen=datetime.now(timezone.utc))
        return object()
    app.dependency_overrides[current_user] = authenticated
    app.dependency_overrides[admin_user] = lambda: object()
    with TestClient(app,base_url='https://main.test') as client:
        yield app, client, state


def body(nid):
    return dict(name='contract group',items=[dict(name='new item',type='ping',target='owned.example',node_id=nid)],
                request_key='12345678-1234-4234-8234-123456789abc')


def validate_response(method,path,response):
    from app import api_response_contracts as r
    schema = r.DECLARATIONS[(method,path)]['responses'][str(response.status_code)]['content']['application/json']['schema']
    Draft202012Validator(schema).validate(response.json())


def test_native_auth_boundaries_remain_enforced(native,db):
    from app.routers.auth import current_user, admin_user
    from app.models.monitor import Monitor, MonitorGroup
    from app.models.user import AuthSession, User
    from app.models.config import AppConfig
    from datetime import datetime, timezone
    User.__table__.create(db.get_bind(), checkfirst=True)
    AuthSession.__table__.create(db.get_bind(), checkfirst=True)
    owner = User(id=UUID('32345678-1234-4234-8234-123456789abc'), username='owner', display_name='owner')
    foreign = User(id=UUID('42345678-1234-4234-8234-123456789abc'), username='foreign', display_name='foreign')
    db.add_all([owner, foreign]); db.flush()
    now = datetime.now(timezone.utc)
    db.add(AuthSession(id=UUID('12345678-1234-4234-8234-123456789abc'), user_id=foreign.id,
                       refresh_hash='v5-foreign-fixture', created_at=now, last_seen=now))
    db.add(AppConfig(key='security.owner_admin.v1', value=json.dumps({'owner_id': str(owner.id)})))
    db.commit()
    app,client,_ = native
    authenticated = app.dependency_overrides.pop(current_user)
    for path in ('/monitors/groups/receipts/12345678-1234-4234-8234-123456789abc',
                 '/nodes/report-channels', '/agent/config', '/agent/entry-probe'):
        assert client.get(path).status_code == 401
    app.dependency_overrides[current_user] = authenticated
    app.dependency_overrides.pop(admin_user)
    n = node(db,token='auth-boundary-node')
    assert client.post('/monitors/groups',json=body(n.id)).status_code == 403
    assert client.put('/nodes/report-channels',json=dict(revision=0,node_ids=[n.id],mode='auto')).status_code == 403
    assert db.query(Monitor).count() == db.query(MonitorGroup).count() == 0


def test_native_request_openapi_pins_post_put_and_nullable_agent_report(native):
    app, _, _ = native
    document = app.openapi()
    overlay = json.loads(OVERLAY.read_text())
    for name, schema in overlay['native_request_schemas'].items():
        # V6 explicitly added scheduling switches and permits an empty member
        # DTO; the service still rejects an unusable group without writes.
        expected = deepcopy(schema)
        if name == 'MonitorGroupWrite':
            expected['properties'].update({
                'visible': {'anyOf': [{'type': 'boolean'}, {'type': 'null'}], 'title': 'Visible'},
                'enabled': {'anyOf': [{'type': 'boolean'}, {'type': 'null'}], 'title': 'Enabled'},
            })
            expected['properties']['child_ids']['anyOf'][0]['minItems'] = 0
        assert document['components']['schemas'][name] == expected
    for operation in overlay['native_operations']:
        actual = document['paths'][operation['path']][operation['method'].lower()]
        assert actual.get('requestBody') == operation['requestBody']
    create = document['components']['schemas']['MonitorGroupCreate']
    item = document['components']['schemas']['MonitorGroupItemCreate']
    assert create['additionalProperties'] is item['additionalProperties'] is False
    assert 'child_ids' not in create['properties']
    write = document['components']['schemas']['MonitorGroupWrite']
    assert 'child_ids' not in write['required']
    assert write['properties']['child_ids']['anyOf'][0]['minItems'] == 0
    report = document['components']['schemas']['AgentReport']
    assert 'channel_receipt' not in report.get('required',[])
    assert {'type':'null'} in report['properties']['channel_receipt']['anyOf']
    # Installed OpenAPI importer must bind the on-disk helper, not a memory overlay.
    from app.openapi_contract import install_openapi_contract
    install_openapi_contract(app)
    decorated = app.openapi()
    metadata = ROOT/'app/api_response_v13_source_metadata_review.json'
    assert hashlib.sha256(metadata.read_bytes()).hexdigest() == '0f9d5694370840dcccf02807726070bacde0b3eb0a5162f275d28f6c508b0e39'
    assert json.loads(metadata.read_text())['source_approval'] is True
    from tools.check_api_response_contracts import document_errors
    assert document_errors(decorated) == []
    for operation in overlay['native_operations']:
        actual = decorated['paths'][operation['path']][operation['method'].lower()]
        assert actual['x-stella-contract-status'] == 'reviewed'
        expected_maps = [
            'app/api_response_v12_final_review.json',
            'app/api_response_v13_speedtest_duration_review.json',
            'app/api_response_v13_monitor404_review.json',
        ]
        reviewed_metadata_operations = {(r['method'], r['path']) for r in json.loads(metadata.read_text())['operation_source_updates']}
        if (operation['method'], operation['path']) in reviewed_metadata_operations:
            expected_maps.append('app/api_response_v13_source_metadata_review.json')
        from api_response_evidence_fixture import named_reviews
        layers = named_reviews()
        for name in ('api_response_v14_ci167_review.json', 'api_response_v15_agent_rollout_review.json',
                     'api_response_v16_monitor_ux_review.json', 'api_response_v17_nav_files_review.json',
                      'api_response_v18_nav_files_validation_review.json',
                      'api_response_v19_unified_files_review.json',
                      'api_response_v21_refresh_timeout_review.json',
                      'api_response_v22_private_remediation_review.json',
                      'api_response_v23_final_offload_review.json',
                       'api_response_v24_servers_audit_review.json'):
            feedback = layers[name]
            if (operation['method'], operation['path']) in {
                    (r['method'], r['path']) for r in feedback['operation_source_updates']}:
                expected_maps.append('app/'+name)
        assert actual['x-stella-contract-evidence']['source-map'] == expected_maps
        assert actual.get('requestBody') == operation['requestBody']


def test_group_requests_strict_create_receipt_and_metadata_preservation(native, db):
    from app.models.monitor import Monitor, MonitorGroup
    app, client, state = native
    n = node(db, token='contract-node-token')
    payload = body(n.id)
    first = client.post('/monitors/groups',json=payload)
    assert first.status_code == 201, first.text
    validate_response('POST','/monitors/groups',first)
    value = first.json()
    gid, mids = value['id'], value['child_ids']
    assert len(mids) == 1 and value['up_count'] == 0
    receipt = client.get('/monitors/groups/receipts/'+payload['request_key'])
    assert receipt.status_code == 200
    assert receipt.json() == dict(group_id=gid,monitor_ids=mids)
    validate_response('GET','/monitors/groups/receipts/{request_key}',receipt)
    assert client.post('/monitors/groups',json=payload).json()['id'] == gid
    for changes in ({}, {'child_ids':None}):
        saved = client.put('/monitors/groups/'+str(gid),json=dict(name='metadata only',**changes))
        assert saved.status_code == 200, saved.text
        assert saved.json()['child_ids'] == mids
        validate_response('PUT','/monitors/groups/{group_id}',saved)
    assert db.get(MonitorGroup,gid).name == 'metadata only'
    for path,key in [('/monitors/','status_reason'),('/monitors/groups','up_count')]:
        result = client.get(path)
        assert result.status_code == 200,result.text
        assert result.json() and all(key in row for row in result.json())
        validate_response('GET',path,result)
    state['sid'] = UUID('22345678-1234-4234-8234-123456789abc')
    assert client.get('/monitors/groups/receipts/'+payload['request_key']).status_code == 404
    assert db.query(Monitor).count() == len(mids)


@pytest.mark.parametrize('alter',[
    {'child_ids':[1]}, {'items':[]}, {'items':[{'name':'bad','type':'ping','target':'x','node_id':1,'extra':True}]},
    {'items':[{'name':'bad','type':'tcp','target':'x:99999','node_id':1}]},
    {'items':[{'name':'bad','type':'ping','target':'  ','node_id':1}]}, {'request_key':'not-a-uuid'},
])
def test_create_post_rejects_invalid_dto_without_writes(native,db,alter):
    from app.models.monitor import Monitor, MonitorGroup
    _,client,_=native
    n=node(db,token='negative-dto-node')
    response=client.post('/monitors/groups',json=body(n.id)|alter)
    assert response.status_code == 422,response.text
    assert db.query(MonitorGroup).count() == db.query(Monitor).count() == 0


def test_group_put_empty_members_and_post_atomic_failure_do_not_damage_state(native,db):
    from app.models.monitor import Monitor,MonitorGroup
    _,client,_=native
    n=node(db,token='atomic-negative-node')
    invalid=body(n.id)
    invalid['items'].append(dict(name='missing source',type='ping',target='x',node_id=99999))
    result=client.post('/monitors/groups',json=invalid)
    assert result.status_code == 400,result.text
    assert db.query(Monitor).count() == db.query(MonitorGroup).count() == 0
    valid=client.post('/monitors/groups',json=body(n.id))
    assert valid.status_code == 201,valid.text
    result=client.put('/monitors/groups/'+str(valid.json()['id']),json=dict(name='invalid',child_ids=[]))
    assert result.status_code == 400, result.text
    assert db.get(MonitorGroup,valid.json()['id']).name == 'contract group'
    assert db.query(Monitor).count() == 1


def test_channel_real_requests_legacy_optional_receipt_and_ack(native,db,channels,monkeypatch):
    from app.models.alert import AlertRule
    from app.models.node import NodeStatusEvent
    from sqlalchemy import Integer
    monkeypatch.setattr(NodeStatusEvent.__table__.c.id, 'type', Integer())
    AlertRule.__table__.create(db.get_bind(), checkfirst=True)
    NodeStatusEvent.__table__.create(db.get_bind())
    _,client,_=native
    n=node(db,token='contract-channel-node')
    headers={'Authorization':'Bearer '+n.token}
    for request in ({}, {'channel_receipt':None}):
        response=client.post('/agent/report',headers=headers,json=request)
        assert response.status_code == 200,response.text
        validate_response('POST','/agent/report',response)
        assert response.json()['channel_revision'] == 0
    config=client.get('/agent/config',headers=headers)
    assert config.status_code == 200,config.text
    validate_response('GET','/agent/config',config)
    assert config.json()['report_channel']['mode'] == 'default'
    probe=client.get('/agent/entry-probe',headers=headers)
    assert probe.status_code == 200,probe.text
    validate_response('GET','/agent/entry-probe',probe)
    get=client.get('/nodes/report-channels')
    assert get.status_code == 200,get.text
    validate_response('GET','/nodes/report-channels',get)
    write=dict(revision=0,node_ids=[n.id],mode='auto')
    for bad in (write|{'node_ids':[True]},write|{'node_ids':['1']},write|{'extra':True}):
        assert client.put('/nodes/report-channels',json=bad).status_code == 422
        assert channels.read(db)['revision'] == 0
    saved=client.put('/nodes/report-channels',json=write)
    assert saved.status_code == 200,saved.text
    validate_response('PUT','/nodes/report-channels',saved)
    assert saved.json()['nodes'][0]['state'] == 'pending'
    cfg=client.get('/agent/config',headers=headers).json()['report_channel']
    receipt={k:cfg[k] for k in ('revision','epoch','nonce','center_id')}
    receipt.update(sequence=1,origin='https://main.test',state='applied')
    ack=client.post('/agent/report',headers=headers,json={'channel_receipt':receipt})
    assert ack.status_code == 200,ack.text
    validate_response('POST','/agent/report',ack)
    assert channels.read(db)['nodes'][0]['state'] == 'applied'
    assert client.post('/agent/report',headers=headers,json={'channel_receipt':{'state':'applied'}}).status_code == 422
    cfg=deepcopy(receipt);cfg['nonce']='b'*64;cfg['sequence']=2
    assert client.post('/agent/report',headers=headers,json={'channel_receipt':cfg}).status_code == 409
    assert channels.read(db)['nodes'][0]['state'] == 'applied'
