"""Final externally reviewed alerts source/request contract, SQLite/ASGI only."""
import hashlib
import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_node_monitor_policy import db

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/'app/api_response_node_interruptions_review.json'


def test_approved_alert_overlay_exact_sources_and_disk_gate():
    from app import api_response_contracts as r
    assert OVERLAY.is_file()
    overlay=json.loads(OVERLAY.read_text())
    assert overlay['worker_source_approved'] is True
    assert len(overlay['sources'])==53
    from api_response_evidence_fixture import reviews, successor
    layers = reviews()
    assert hashlib.sha256(OVERLAY.read_bytes()).hexdigest() == layers[0]['historical_ledgers'][str(OVERLAY.relative_to(ROOT))]
    # Historical approval binds its recorded source hashes, not later files.
    for f, sha in overlay['approved_production_hashes'].items():
        historical = [s for s in overlay['sources'].values() if s['file'] == f]
        assert historical and all(s['sha256'] == sha for s in historical)
        for key, source in overlay['sources'].items():
            if source['file'] != f:
                continue
            assert r.SOURCE_EVIDENCE[key] == source
            current_key = successor(key)
            current = r.SOURCE_EVIDENCE[current_key]
            if any(current_key in row['sources'] for row in r.INVENTORY):
                assert hashlib.sha256((ROOT/current['file']).read_bytes()).hexdigest() == current['sha256']
    for row in r.INVENTORY:
        for key in row['sources']:
            if r.SOURCE_EVIDENCE[key]['file']=='app/services/node_deadlines.py':
                assert key.endswith('@alerts-recheck-d2bf1f44')
    records=[(v['method'],v['path'],v['endpoint'],None) for v in r.INVENTORY]
    assert r.validate_response_sources(ROOT,records)==[]
    assert len([v for v in r.DECLARATIONS.values() if v['status']=='incomplete'])==3


@pytest.fixture
def installed(db):
    from app.routers.alerts import router
    from app.routers.auth import current_user,admin_user
    from app.database import get_db
    from app.models.alert import AlertRule, AlertState
    AlertRule.__table__.create(db.get_bind(), checkfirst=True)
    AlertState.__table__.create(db.get_bind(), checkfirst=True)
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[current_user]=lambda:object()
    app.dependency_overrides[admin_user]=lambda:object()
    with TestClient(app) as c:
        yield app,c


def test_native_alert_request_schema_is_exact_reviewed_contract(installed):
    app,_=installed
    overlay=json.loads(OVERLAY.read_text())
    schema=app.openapi()
    for operation,name in [('POST /alerts/rules','RuleCreate'),('PATCH /alerts/rules/{rule_id}','RulePatch')]:
        method,path=operation.split(' ',1)
        expected=overlay['request_contract_proposal'][operation]
        assert schema['paths'][path][method.lower()]['requestBody']==expected['requestBody']
        assert schema['components']['schemas'][name]==expected['schema']
    from app.openapi_contract import install_openapi_contract
    install_openapi_contract(app)
    decorated=app.openapi()
    for path,method in [('/alerts/rules','post'),('/alerts/rules/{rule_id}','patch')]:
        from api_response_evidence_fixture import named_reviews
        layers = named_reviews()
        expected_maps = ['app/api_response_v12_final_review.json']
        for name in ('api_response_v13_source_metadata_review.json',
                     'api_response_v14_ci167_review.json', 'api_response_v15_agent_rollout_review.json',
                     'api_response_v16_monitor_ux_review.json', 'api_response_v17_nav_files_review.json',
                      'api_response_v18_nav_files_validation_review.json',
                      'api_response_v19_unified_files_review.json'):
            if (method.upper(), path) in {(row['method'], row['path'])
                    for row in layers[name]['operation_source_updates']}:
                expected_maps.append('app/'+name)
        expected_map = expected_maps if len(expected_maps) > 1 else expected_maps[0]
        assert decorated['paths'][path][method]['x-stella-contract-evidence']['source-map'] == expected_map
        assert decorated['paths'][path][method]['requestBody']==schema['paths'][path][method]['requestBody']


def test_native_alert_create_and_patch_zero_defaults_read_back(installed,db):
    from app.models.alert import AlertRule
    _,c=installed
    response=c.post('/alerts/rules',json=dict(kind='node_offline',target='contract-fixture'))
    assert response.status_code==201,response.text
    rid=response.json()['id'];db.expire_all();rule=db.get(AlertRule,rid)
    assert rule.email is False and rule.repeat_minutes==0 and rule.debounce==2
    response=c.patch('/alerts/rules/'+str(rid),json=dict(repeat_minutes=0,debounce=1))
    assert response.status_code==200,response.text
    db.expire_all();rule=db.get(AlertRule,rid)
    assert rule.repeat_minutes==0 and rule.debounce==1 and rule.email is False
    response=c.patch('/alerts/rules/'+str(rid),json=dict(label='metadata only'))
    assert response.status_code==200,response.text
    db.expire_all();rule=db.get(AlertRule,rid)
    assert rule.label=='metadata only' and rule.repeat_minutes==0 and rule.debounce==1 and rule.email is False


@pytest.mark.parametrize('bad',[True,False,0.5,'1'])
@pytest.mark.parametrize('field',['debounce','repeat_minutes'])
def test_native_alert_post_patch_strict_integer_no_writes(installed,db,bad,field):
    from app.models.alert import AlertRule
    _,c=installed
    payload=dict(kind='node_offline',target='strict-contract')
    assert c.post('/alerts/rules',json=payload|{field:bad}).status_code==422
    assert db.query(AlertRule).count()==0
    created=c.post('/alerts/rules',json=payload)
    assert created.status_code==201,created.text
    rid=created.json()['id']
    assert c.patch('/alerts/rules/'+str(rid),json={field:bad}).status_code==422
    db.expire_all();rule=db.get(AlertRule,rid)
    assert rule.repeat_minutes==0 and rule.debounce==2 and rule.email is False
