"""Final merged source contract reconciliation; isolated, no main imports."""
import json
import pytest
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module, validate_payload
from api_response_evidence_fixture import check_metadata, frozen, reviews, successor


def test_projection_dependencies_and_exact_symbol_ranges_are_pinned():
    m=response_module()
    for row in m.INVENTORY:
        files={m.SOURCE_EVIDENCE[s]['file'] for s in row['sources']}
        if 'app/public_website.py' in files:
            assert 'app/navigation_icons.py' in files
    # SOURCE_EVIDENCE is append-only. Only referenced records describe live
    # bytes; the old owner_id range remains frozen, never silently rewritten.
    reviews()
    old = m.SOURCE_EVIDENCE['app.services.admin_security.owner_id']
    check_metadata('app.services.admin_security.owner_id', old,
                   frozen(old['file'], old['sha256']))
    assert (old['line'], old['end_line']) == (59, 88)
    active = {s for row in m.INVENTORY for s in row['sources']}
    assert 'app.services.admin_security.owner_id' not in active
    assert successor('app.services.admin_security.owner_id') in active
    for symbol in sorted(active):
        check_metadata(symbol, m.SOURCE_EVIDENCE[symbol])


def test_document_gate_resolves_refs_mappings_and_detects_schema_damage():
    from tools.check_api_response_contracts import document_errors
    doc={'openapi':'3.1.0','info':{'title':'fixture','version':'1'},'paths':{},'components':{'schemas':{'Variant':{'type':'string'},'Union':{'oneOf':[{'$ref':'#/components/schemas/Variant'}], 'discriminator':{'propertyName':'kind','mapping':{'variant':'#/components/schemas/Variant'}}}}}}
    assert document_errors(doc)==[]
    doc['components']['schemas']['Union']['discriminator']['mapping']['variant']='#/components/schemas/Missing'
    assert any('Missing' in e for e in document_errors(doc))
    doc['components']['schemas']['Variant']={'type':'not-a-json-type'}
    assert any('schema' in e.lower() for e in document_errors(doc))


@pytest.mark.parametrize('damage', ['sha256', 'line', 'end_line', 'symbol'])
def test_current_successor_metadata_rejects_damage(damage):
    from copy import deepcopy
    m = response_module()
    key = successor('app.services.admin_security.owner_id')
    source = deepcopy(m.SOURCE_EVIDENCE[key])
    assert (source['line'], source['end_line']) == (59, 91)
    check_metadata(key, source)
    source[damage] = ('0'*64 if damage == 'sha256' else
                      'app.services.admin_security.no_such_symbol' if damage == 'symbol' else 1)
    with pytest.raises(AssertionError):
        check_metadata(key, source)


def test_real_public_samples_validate_every_network_kind_and_projection():
    from test_public_node_tasks import NET_CASES, http, node, STAMP
    from app.schemas.monitor import NodeDetail, NetTaskRead, MtrTaskRead, IperfTaskRead
    from app.schemas.public_node import PublicRecord
    from app import public_website as w
    from jsonschema import Draft202012Validator
    from copy import deepcopy
    assert PublicRecord.model_validate({'secret':'drop'}).model_dump(mode='json') == {}
    for kind, (payload,result) in NET_CASES.items():
        original=deepcopy(result)
        output=http(NetTaskRead,dict(id=1,node_id=2,kind=kind,status='done',created_at=STAMP,payload=payload,result_json=result))
        validate_payload('GET','/nodes/net-tasks/{task_id}',output)
        validate_payload('POST','/nodes/{node_id}/ip-change',output,'201')
        assert result==original
    value=node(sys_info={'hardware':{'cpu':{'logical_cores':False,'temperature_c':'bad'},'password':'drop'}})
    validate_payload('GET','/nodes/{node_id}',http(NodeDetail,value))
    validate_payload('GET','/iperf-tasks/{task_id}',http(IperfTaskRead,dict(id=1,mode='iperf3',client_node_id=2,direction='upload',duration=10,parallel=1,status='done',created_at=STAMP,result_json={'error':'missing tool'})))
    validate_payload('GET','/monitors/{monitor_id}/mtr',[http(MtrTaskRead,dict(id=1,node_id=2,target='host',protocol='icmp',status='done',created_at=STAMP,result_json={'error':'missing tool'}))])
    for raw in ({}, {'id':'demo','name':False,'icon':'heart','mode':'iframe','browser_url':'','enabled':True,'origin':'','injection':{'draft':{'css':'body{}','js':'owner()','enabled':True,'timing':'dom_ready','csp_policy':'reject'},'active':None,'previous':None}}):
        validate_payload('GET','/external-modules/{mid}',w.public_module(raw))
        # This serializer returns PublicWebsiteResult, not the save route's
        # committed navigation/idempotency envelope. Never fabricate those fields.
        projected = w.public_website_result(raw, {'secret': 'discard'})
        Draft202012Validator(response_module().MODELS['PublicWebsiteResult']).validate(projected)
        save_schema = response_module().DECLARATIONS['POST', '/website-settings']['responses']['201']['content']['application/json']['schema']
        assert not Draft202012Validator(save_schema).is_valid(projected)
        assert 'navigation' not in projected and 'idempotency_key' not in projected
        validate_payload('POST','/external-modules/{mid}/injection/apply',w.public_versions(raw.get('injection')))
    fixture=json.loads((ROOT/'frontend/tests/fixtures/publicWebsiteProjection.json').read_text())
    # Fixture is generated by real public projections in its owning lane.
    assert set(fixture)=={'saved','malformed','navigation'}
    for name, schema_name in [('saved','PublicWebsiteResult'),('malformed','PublicModule'),('navigation','PublicNavigation')]:
        Draft202012Validator(response_module().MODELS[schema_name]).validate(fixture[name])


def test_alert_list_projects_real_rows_without_writes_or_incident_changes(record_property):
    from copy import deepcopy
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import TypeAdapter
    from app.alert_metrics import Condition
    from app.public_alert_metrics import PublicMetricRule, public_metric_rule
    from test_api_response_contract import body_namespace
    raw={'secret_extension':{'nested':True}}
    rule=SimpleNamespace(id=1,target='2',label='x',condition=raw,severity='warning',debounce=2,repeat_minutes=0,email=False,enabled=True,revision=7)
    state=SimpleNamespace(state='firing',preview=['not-a-preview'],evaluated_at=None)
    healthy=deepcopy(rule); healthy.id=2
    healthy.condition=Condition(metric='cpu',threshold='80').model_dump(mode='json')
    historical=deepcopy(healthy); historical.id=3; historical.enabled=False
    historical.condition=Condition(metric='network.volume',interface='eth0',direction='out',threshold='80',window=dict(kind='fixed',start='2001-01-01T00:00:00Z',end='2001-01-02T00:00:00Z',timezone='UTC')).model_dump(mode='json')
    rows=[(rule,state),(healthy,None),(historical,SimpleNamespace(state='firing',preview=None,evaluated_at=None))]
    before=deepcopy(rows)
    class Query:
        def query(self,*a):return self
        def outerjoin(self,*a):return self
        def filter(self,*a):return self
        def order_by(self,*a):return self
        def all(self):return rows
        def commit(self):raise AssertionError('GET committed')
        def flush(self):raise AssertionError('GET flushed')
        def add(self,*a):raise AssertionError('GET wrote')
        def delete(self,*a):raise AssertionError('GET deleted')
    fn=body_namespace('app/services/alert_metrics.py',['list_rules'],public_metric_rule=public_metric_rule,AlertRule=SimpleNamespace(id=1,schema_version=2,archived=SimpleNamespace(is_=lambda value: None)),AlertState=SimpleNamespace(rule_id=1))['list_rules']
    route=body_namespace('app/routers/alerts.py',['metric_rules'],alert_metrics=SimpleNamespace(list_rules=fn))['metric_rules']
    app=FastAPI()
    @app.get('/alerts/v2/rules')
    def get_rules():return route(Query())
    with TestClient(app) as client:
        response=client.get('/alerts/v2/rules')
    assert response.status_code==200
    result=response.json()
    assert result[0]['condition'] is None and result[0]['preview'] is None
    assert result[0]['projection']==dict(state='incomplete',invalid_fields=['condition','preview'])
    assert (result[0]['enabled'],result[0]['state'],result[0]['revision'])==(True,'firing',7)
    assert result[1]['condition']==healthy.condition and result[1]['preview'] is None
    assert 'projection' not in result[1]
    assert result[2]['condition']==historical.condition
    assert (result[2]['enabled'],result[2]['state'])==(False,'firing')
    assert rows==before
    validate_payload('GET','/alerts/v2/rules',result)
    declaration=response_module().DECLARATIONS['GET','/alerts/v2/rules']
    assert declaration['status']=='reviewed'
    assert declaration['responses']['200']['content']['application/json']['schema']==TypeAdapter(list[PublicMetricRule]).json_schema(mode='serialization')
    record_property('selected_body_sample', json.dumps({'alerts': result}, ensure_ascii=True))


def test_merged_session_preview_errors_and_redacted_422_contracts():
    from jsonschema import Draft202012Validator, ValidationError
    from test_api_response_contract import body_namespace
    from types import SimpleNamespace
    m = response_module()
    session=body_namespace('app/services/browser_sessions.py',['session_metadata'])['session_metadata'](SimpleNamespace(browser_id=None,browser_name=None,os_name=None,login_origin=None))
    assert set(session) <= set(m.SESSION['properties'])
    assert ('GET','/auth/sessions/{session_id}/location') in m.DECLARATIONS
    assert ('POST','/documents/delete-preview') in m.DECLARATIONS
    assert ('POST','/documents/delete-preview') not in m.UPSTREAM_DECLARATIONS
    validate_payload('GET','/auth/sessions/{session_id}/location',{'ip':'127.0.0.1','ip_location':'局域网'})
    for key in [('DELETE','/documents/{doc_id}'),('DELETE','/documents/{doc_id}/permanent'),('POST','/documents/trash/empty')]:
        schema=m.DECLARATIONS[key]['responses']['409']['content']['application/json']['schema']
        Draft202012Validator(schema).validate({'detail':{'code':'delete_scope_changed','message':'scope changed'}})
    schema=m.VALIDATION_ERROR
    Draft202012Validator(schema).validate({'detail':[{'loc':['body','x'],'msg':'Invalid value','type':'value_error'}]})
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate({'detail':[{'loc':['body'],'msg':'x','type':'value_error','input':'private'}]})
    schema=m.DECLARATIONS['POST','/external-modules/{mid}/injection/apply']['responses']['409']['content']['application/json']['schema']
    Draft202012Validator(schema).validate({'detail':{'code':'incomplete_injection','projection':{'state':'incomplete','invalid_fields':['draft']}}})


def small_public_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('contract_small_public', ROOT/'app/services/small_public_outputs.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_website_and_small_public_schema_parity_and_outputs():
    from pydantic import TypeAdapter
    from app import public_website as w
    m = response_module()
    mapping = json.loads((ROOT/'docs/projection-websites-source-mapping-delta.json').read_text())
    for row in mapping['operations'] + mapping['already_complete_affected_operations']:
        if row['path'].endswith('/check'):
            assert m.DECLARATIONS[row['method'],row['path']]['status'] == 'reviewed'
            continue
        name = row['model'].removesuffix('[]')
        model = getattr(w, name)
        if row['model'].endswith('[]'): model = list[model]
        expected = TypeAdapter(model).json_schema(mode='serialization')
        d = m.DECLARATIONS[row['method'],row['path']]
        assert d['status'] == 'reviewed', row['path']
        code = '201' if row['method']=='POST' and row['path'] in ('/integration-targets','/external-modules','/website-settings') else '200'
        declared = d['responses'][code]['content']['application/json']['schema']
        # The historical mapping still owns the pure serializer. v22 expands
        # the actual navigation/save handlers, not these serializer models.
        assert m.MODELS[name] == TypeAdapter(getattr(w, name)).json_schema(mode='serialization')
        overrides = {(r['method'], r['path']): r for r in m._V22_REVIEW['response_overrides']}
        override = overrides.get((row['method'], row['path']))
        if override is not None:
            assert declared == override['responses'][code]['content']['application/json']['schema']
            if row['path'].startswith('/website-settings'):
                assert {'navigation', 'idempotency_key'} <= set(declared['required'])
                assert 'navigation' not in expected['properties']
        else:
            assert declared == expected
    small = small_public_module()
    for path, model in [('/admin/email/config',small.PublicSMTPConfig),('/operations/change-audit',small.PublicChangeAudit),('/oauth/jwks',small.PublicJWKS)]:
        d = m.DECLARATIONS['GET',path]
        assert d['status']=='reviewed'
        assert d['responses']['200']['content']['application/json']['schema']==model.model_json_schema(mode='serialization')
        assert '503' in d['responses']
    validate_payload('GET','/auth/avatars',small.public_avatar_history('[1,"/assets/a.png",{}]'))
    assert m.DECLARATIONS['GET','/auth/avatars']['status']=='reviewed'
    validate_payload('GET','/external-modules/missing'.replace('missing','{mid}'),w.public_module({'name':False,'secret':'not-public'}))
    navigation = w.public_navigation({'modules': {}, 'navigation': False}, [])
    from jsonschema import Draft202012Validator
    Draft202012Validator(m.MODELS['PublicNavigation']).validate(navigation)
    assert not Draft202012Validator(m.DECLARATIONS['GET', '/navigation']['responses']['200']['content']['application/json']['schema']).is_valid(navigation)


def test_closed_empty_record_is_not_an_unconstrained_object():
    m = response_module()
    assert m.schema_holes({'type':'object','properties':{},'additionalProperties':False}) == []
    assert m.schema_holes({'type':'object'})
    assert m.schema_holes({'type':'object','additionalProperties':True})


def test_node_task_declared_schemas_match_real_serialization_models():
    import ast
    from pydantic import TypeAdapter
    from app.schemas import monitor
    from app.schemas.public_task import AgentTasksRead
    delta = json.loads((ROOT/'docs/projection-node-tasks-delta.json').read_text())
    env = {**vars(monitor), 'AgentTasksRead': AgentTasksRead}
    m = response_module()
    for row in delta['routes']:
        expected = TypeAdapter(eval(row['response_model'], env)).json_schema(mode='serialization')
        # Pydantic emits an empty JsonValue definition; bound it recursively.
        if 'JsonValue' in expected.get('$defs', {}):
            expected['$defs']['JsonValue'] = m.JSON_VALUE
        # Empty PublicRecord drops unknown fields on actual serialization.
        if 'PublicRecord' in expected.get('$defs', {}):
            expected['$defs']['PublicRecord']['additionalProperties'] = False
        declared = m.DECLARATIONS[row['method'], row['path']]
        assert declared['status'] == 'reviewed', row['path']
        assert declared['responses'][str(row['status_code'])]['content']['application/json']['schema'] == expected
    assert 'properties' not in m.MODELS['NetTaskRead']
    assert m.MODELS['NetTaskRead']['discriminator']['propertyName'] == 'kind'


def test_merged_dependency_signatures_construct_without_main():
    app, records = source_shaped_app()
    assert any(path == '/auth/sessions' for _, path, *_ in records)


def test_exception_handler_registration_is_not_a_route(tmp_path):
    (tmp_path / 'main.py').write_text('from fastapi import FastAPI\napp = FastAPI()\napp.add_exception_handler(ValueError, handler)\n@app.get("/ok")\ndef ok(): pass\n')
    assert [(m, p) for m, p, *_ in static_inventory(tmp_path)[0]] == [('GET', '/ok')]


@pytest.mark.parametrize('method', ['get','post','put','patch','delete','head','options','trace','api_route','add_api_route','connect','route','add_route','future_http_method'])
def test_dynamic_registration_still_fails_closed(tmp_path, method):
    (tmp_path / 'main.py').write_text(f'from fastapi import FastAPI\napp = FastAPI()\napp.add_exception_handler(ValueError, handler)\nif enabled:\n    app.{method}("/hidden", methods=["CONNECT"])\n')
    with pytest.raises(AssertionError, match='Review dynamic routes'):
        static_inventory(tmp_path)
