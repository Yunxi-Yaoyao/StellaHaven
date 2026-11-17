"""Merged response acceptance; AST/isolated functions only, no live application."""
import ast
import copy
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from test_api_response_contract import response_module, body_namespace, validate_payload
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install


def test_merged_templates_alerts_and_source_gate():
    module = response_module()
    records = static_inventory()[0]
    assert module.validate_response_sources(ROOT, records) == []
    app, _ = source_shaped_app()
    contract = install(app)
    contract.validate_contract(app, require_all_overrides=True)
    paths = app.openapi()['paths']
    for method, path in [('post','/website-templates'),('delete','/website-templates/{tid}'),
                         ('post','/alerts/v2/preview'),('post','/alerts/v2/rules'),
                         ('put','/alerts/v2/rules/{rule_id}')]:
        op = paths[path][method]
        assert op['x-stella-contract-status'] == 'reviewed'
        assert op['x-stella-auth-type'] == 'cookie-access'
        # The separate management password/grant is retired; admin_user now
        # revalidates the same persisted owner/access session.
        assert op['x-stella-elevation'] == 'none'
        assert op['security'] == [{'StellaAccessCookie': []}]
    assert paths['/alerts/v2/rules']['get']['x-stella-contract-status'] == 'reviewed'
    assert not module.UPSTREAM_DECLARATIONS
    assert module.DECLARATIONS['POST','/documents/delete-preview']['status']=='reviewed'


def test_actual_merged_builtin_catalog_includes_provenance(monkeypatch):
    import sys
    from types import ModuleType
    m = ModuleType('app.services.openlist_access'); m.READ_POST = {'api/fs/list'}
    monkeypatch.setitem(sys.modules, m.__name__, m)
    ns = body_namespace('app/services/website_templates.py', ['catalog'], copy=copy,
                        export_code=lambda *a, **kw:dict(enabled=True,css='',js='',timing='ready'))
    payload = ns['catalog']()
    assert all(p['provenance']=='builtin' for p in payload)
    validate_payload('GET','/website-templates',payload)


def map_namespace():
    from datetime import datetime, timezone
    from ipaddress import ip_address, ip_interface, ip_network
    from typing import Annotated, Literal
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
    ns = dict(datetime=datetime, timezone=timezone, ip_address=ip_address,
              ip_interface=ip_interface, ip_network=ip_network, Annotated=Annotated,
              Literal=Literal, BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
              ValidationError=ValidationError, field_validator=field_validator, model_validator=model_validator,
              node_status=lambda n, now: n.status)
    tree = ast.parse((ROOT/'app/services/server_map.py').read_text())
    nodes = [n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'map-fixture','exec'),ns)
    return ns


@pytest.mark.parametrize('kind',['missing','manual','nat','stale','invalid'])
def test_real_map_location_topology_probe_shapes(kind):
    from datetime import datetime, timezone
    ns = map_namespace(); now=datetime(2026,1,1,tzinfo=timezone.utc)
    n = SimpleNamespace(id=1,name='fixture',status='online',public_ip=None,public_ip_source=None)
    snapshot = dict(observed_at=now.isoformat(),location=dict(status='located',source='nat',provider='ip2location',public_ip='8.8.8.8',latitude=1.0,longitude=2.0),wireguard=dict(status='ok',interfaces=[]))
    snapshots = {} if kind=='missing' else {1:snapshot}
    manual={1:dict(latitude=3.0,longitude=4.0,label=None)} if kind=='manual' else {}
    if kind=='stale':snapshot['observed_at']='2020-01-01T00:00:00+00:00'
    if kind=='invalid':snapshot['location']['latitude']='bad'
    result=ns['build_topology']([n],snapshots,manual,now=now)
    validate_payload('GET','/nodes/map-topology',result)
    validate_payload('PATCH','/nodes/{node_id}/map-location',result['nodes'][0])
    targets = ns['build_probe_targets'](1,[n],snapshots,now=now)
    assert targets == []  # No WireGuard peers in these location fixtures.
    # Exercise the real HTTP handler: the service returns a list, not the
    # agent response envelope reviewed by the schema.
    route = body_namespace('app/routers/monitor.py', ['agent_map_targets'],
        server_map=SimpleNamespace(get_probe_targets=lambda db, token: targets))
    payload = route['agent_map_targets']('fixture-token', None)
    assert payload == {'targets': targets}
    validate_payload('GET','/agent/map-targets',payload)
    for key in [('GET','/nodes/map-topology'),('PATCH','/nodes/{node_id}/map-location'),('GET','/agent/map-targets')]:
        assert response_module().DECLARATIONS[key]['status']=='reviewed'


def test_real_injection_validation_and_nonproxy_check():
    import asyncio
    from contextlib import contextmanager
    @contextmanager
    def edit(db): yield {'modules':{'m':{'target_id':None,'injection':{}}},'targets':{}}
    value=dict(enabled=True,css='',js='',timing='dom_ready',csp_policy='reject')
    ns=body_namespace('app/services/integrations_injection.py',['validate_draft'],
        store=SimpleNamespace(edit=edit),errors=lambda *a:['fixture invalid'])
    payload=ns['validate_draft'](None,'m',SimpleNamespace(model_dump=lambda:value))
    validate_payload('POST','/external-modules/{mid}/injection/validate',payload)
    ns=body_namespace('app/routers/integrations.py',['check'],service=SimpleNamespace(get_module=lambda *a:dict(mode='iframe',injection={'active':None})))
    validate_payload('POST','/external-modules/{mid}/check',asyncio.run(ns['check']('m',None)))
    assert response_module().DECLARATIONS['POST','/external-modules/{mid}/injection/validate']['status']=='reviewed'
    # Merged check uses public_module before reading the stored version.
    assert response_module().DECLARATIONS['POST','/external-modules/{mid}/check']['status']=='reviewed'


def agent_methods(*names, **ns):
    tree=ast.parse((ROOT/'agent/stella_agent.py').read_text())
    agent=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Agent')
    nodes=[n for n in agent.body if isinstance(n,ast.FunctionDef) and n.name in names]
    for n in nodes: n.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'agent-fixture','exec'),ns)
    return ns


def test_node_hardware_current_shape_and_live_public_filter():
    from datetime import datetime
    from pydantic import BaseModel, field_validator
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    module=response_module()
    assert 'Hardware' in module.CURRENT_SHAPES
    ns=agent_methods('_empty_hardware')
    hardware=ns['_empty_hardware'](SimpleNamespace(_os_static_cache=None),'collecting')
    Draft202012Validator(module.CURRENT_SHAPES['Hardware']).validate(hardware)
    from app.schemas.monitor import NodeRead
    env={'NodeRead':NodeRead}
    app=FastAPI()
    payload=dict(id=1,name='fixture',platform='linux',host='fixture.invalid',status='online',created_at='2026-01-01T00:00:00Z',token='fixture-secret',sys_info={'hardware':hardware})
    @app.get('/nodes/',response_model=list[env['NodeRead']],response_model_exclude={'__all__':{'token'}})
    def read_nodes():return [payload]
    before=TestClient(app).get('/nodes/').json()
    read_nodes.__module__='app.routers.monitor';read_nodes.__qualname__='list_nodes'
    install(app);after=TestClient(app).get('/nodes/').json()
    assert before==after and 'token' not in after[0]
    validate_payload('GET','/nodes/',after)
    assert module.DECLARATIONS['GET','/nodes/']['status']=='reviewed'
    schema=module.DECLARATIONS['GET','/nodes/']['responses']['200']['content']['application/json']['schema']
    assert 'x-stella-current-writer-schema' not in json.dumps(schema)
    # The actual read model now projects legacy corruption before serialization.
    payload['sys_info']={'hardware':{'cpu':'legacy-wrong-type'}}
    malformed=TestClient(app).get('/nodes/').json()
    validate_payload('GET','/nodes/',malformed)
    assert malformed[0]['sys_info']['hardware']['cpu'] is None
    assert payload['sys_info']['hardware']['cpu']=='legacy-wrong-type'


def test_current_metric_model_includes_added_sampling_fields():
    from datetime import datetime
    from pydantic import BaseModel
    n=next(n for n in ast.parse((ROOT/'app/schemas/monitor.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='MetricPoint')
    ns=dict(BaseModel=BaseModel,datetime=datetime)
    exec(compile(ast.Module(body=[n],type_ignores=[]),'metric-schema','exec'),ns)
    payload=ns['MetricPoint'](iface='eth0',ts='2026-01-01T00:00:00Z',rx_delta=1,tx_delta=2).model_dump(mode='json')
    schema=response_module().MODELS['list[MetricPoint]']['items']
    assert set(payload)==set(schema['properties'])
    Draft202012Validator(schema).validate(payload)


def test_typed_network_task_variants_and_unvalidated_result_boundary():
    module=response_module()
    assert set(module.CURRENT_SHAPES['NetResults'])=={'ip_change','firewall_scan','docker_scan','docker_ctl','docker_logs','docker_inspect','pbr_scan'}
    ns=agent_methods('_docker_logs','_docker_ctl',re=__import__('re'))
    receiver=SimpleNamespace(_docker_run=lambda *a,**k:SimpleNamespace(returncode=0,stdout='fixture',stderr=''))
    for kind, method, value in [('docker_logs','_docker_logs',{'container':'demo'}),('docker_ctl','_docker_ctl',{'action':'restart','container':'demo'})]:
        result=ns[method](receiver,value)
        Draft202012Validator(module.CURRENT_SHAPES['NetResults'][kind]).validate(result)
    payload=dict(id=1,node_id=1,kind='docker_logs',status='done',result_json={'malformed_internal_result':True},created_at='2026-01-01T00:00:00Z')
    from app.schemas.monitor import NetTaskRead
    output=NetTaskRead.model_validate(payload).model_dump(mode='json')
    validate_payload('GET','/nodes/net-tasks/{task_id}',output)
    assert 'malformed_internal_result' not in output['result_json']
    assert module.DECLARATIONS['GET','/nodes/net-tasks/{task_id}']['status']=='reviewed'


def test_agent_config_has_sourced_user_configuration_extension():
    module=response_module()
    validate_payload('GET','/agent/config',dict(node_id=1,monitored_ifaces={'eth0':{'color':'blue','future':[True,None]}},monitors_version=0,monitors=[]))
    assert module.DECLARATIONS['GET','/agent/config']['status']=='reviewed'


def test_remaining_old_incomplete_operations_have_explicit_field_review():
    module=response_module()
    for key, declaration in module.DECLARATIONS.items():
        if declaration['status']!='incomplete':continue
        for code,response in declaration['responses'].items():
            if code.startswith('2'):
                assert not response.get('x-stella-body-undeclared'), key
                assert 'application/json' in response['content'], key
                assert declaration['reason']


def test_real_new_target_projection_is_not_legacy_target_read():
    ns=body_namespace('app/services/integrations_proxy.py',['masked_target'])
    value=dict(id='fixture',name='Demo',upstream_url='https://example.invalid/',allowed_ips=['192.0.2.1'],controlled=False,headers={'authorization':'fixture-not-exported'})
    payload=ns['masked_target'](value)
    assert 'headers' not in payload and payload['credential_headers']==['authorization']
    validate_payload('POST','/integration-targets',payload,'201')
    assert response_module().DECLARATIONS['POST','/integration-targets']['status']=='reviewed'
    assert response_module().DECLARATIONS['GET','/integration-targets']['status']=='reviewed'


def test_real_unvalidated_config_and_audit_fields_remain_incomplete():
    from test_api_response_reconcile import small_public_module
    from fastapi.encoders import jsonable_encoder
    from contextlib import contextmanager
    small=small_public_module()
    stored=dict(host=['wrong'],port='legacy',username=None,from_name=False,enabled='yes',password='fixture',legacy_extra={'nested':True})
    @contextmanager
    def locked(*args):yield stored
    ns=body_namespace('app/routers/admin_email.py',['get_config'],
        ha_state=SimpleNamespace(enabled=lambda:True,locked_state=locked),DEFAULTS=stored,
        public_smtp_config=small.public_smtp_config)
    payload=jsonable_encoder(ns['get_config'](None))
    validate_payload('GET','/admin/email/config',payload)
    assert payload['password']=='••••••' and payload['host'] is None and 'legacy_extra' not in payload
    # The old storage reader remains unchanged; the route now adds a projection.
    ns=body_namespace('app/services/backup_health.py',['_audit_entries'],json=json,AUDIT_LIMIT=200)
    raw=ns['_audit_entries'](json.dumps([dict(action=['not-a-string'],timestamp=123,secret='not-exported')]))
    # Import only the public helper body with its constant set boundary.
    import re
    from datetime import datetime
    from uuid import UUID
    env=body_namespace('app/services/small_public_outputs.py',['public_audit_event','_public_uuid','_public_text'],
        re=re,datetime=datetime,UUID=UUID,PublicAuditEvent=small.PublicAuditEvent)
    import sys
    from types import ModuleType
    backup=ModuleType('app.services.backup_health');backup.AUDIT_FIELDS={'action','timestamp','actor_id','resource_id','changed_fields'}
    from unittest.mock import patch as mock_patch
    with mock_patch.dict(sys.modules,{'app.services.backup_health':backup}):
        events=[jsonable_encoder(env['public_audit_event'](item)) for item in raw]
    validate_payload('GET','/operations/change-audit',{'events':events,'limit':200})
    assert events[0]['action'] is None and events[0]['timestamp'] is None
    for key in [('GET','/admin/email/config'),('GET','/operations/change-audit')]:
        assert response_module().DECLARATIONS[key]['status']=='reviewed'


def test_new_shapes_have_supporting_source_evidence():
    m=response_module()
    for row in m.INVENTORY:
        for path in m.EXTRA_SOURCES.get(row['endpoint'],()):
            assert path in {m.SOURCE_EVIDENCE[s]['file'] for s in row['sources']}, (row['endpoint'],path)
        if row.get('model') in m.MODEL_BLOCKERS:
            assert 'agent/stella_agent.py' in {m.SOURCE_EVIDENCE[s]['file'] for s in row['sources']}


def test_strict_cli_distinguishes_classification_from_completeness(tmp_path):
    import subprocess,sys
    # Default classification succeeds, while strict normalization must keep
    # rejecting the three reviewed-but-unvalidated notification JSONB readers.
    result=subprocess.run([sys.executable,str(ROOT/'tools/check_api_response_contracts.py'),'--output',str(tmp_path)],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0, result.stdout + result.stderr
    report=json.loads((tmp_path/'response-completion-coverage.json').read_text())
    strict=subprocess.run([sys.executable,str(ROOT/'tools/check_api_response_contracts.py'),'--require-complete'],cwd=ROOT,text=True,capture_output=True)
    assert strict.returncode==1, strict.stdout + strict.stderr
    strict_report=json.loads(strict.stdout)
    incomplete={('GET','/notifications'),('GET','/notifications/{notification_id}'),
                ('GET','/alerts/incidents/{incident_id}')}
    assert {(op['method'],op['path']) for op in report['operations'] if op['status']=='incomplete'}==incomplete
    expected_errors={f'{method} {path}: incomplete response contract: ' +
                     response_module().DECLARATIONS[method,path]['reason']
                     for method,path in incomplete}
    assert set(strict_report['errors'])==expected_errors and len(strict_report['errors'])==3
    assert report['require_complete'] is False and strict_report['require_complete'] is True
    assert report['errors']==[]
    for value in (report,strict_report):
        assert value['source_and_classification_gate_passed'] is True
        assert value['normalization_complete'] is False
        assert value['classification'].get('incomplete',0)==3
        assert sum(value['classification'].values())==value['operation_count']==len(static_inventory()[0])


def test_pinned_notes_preview_is_readonly_and_not_active_before_merge():
    import hashlib
    from api_pinned_sources import read_pinned_source
    from uuid import uuid4
    from fastapi import HTTPException
    m=response_module()
    key=('POST','/documents/delete-preview')
    assert key not in m.UPSTREAM_DECLARATIONS
    assert key in m.DECLARATIONS
    pending=dict(m._notes_pending,responses=m.DECLARATIONS[key]['responses'])
    assert pending['revision'].startswith('6b01e8e')
    texts={}
    for source in pending['sources']:
        raw=read_pinned_source(source, pending['revision'])
        assert hashlib.sha256(raw).hexdigest()==source['sha256']
        texts[source['file']]=raw.decode()
    ws,doc=uuid4(),uuid4()
    tree={doc:SimpleNamespace(id=doc,deleted_at=None)}
    ns=body_namespace('app/services/notes_delete_scope.py',['scope_data','preview_delete'],
        source_text=texts['app/services/notes_delete_scope.py'],HTTPException=HTTPException,
        subtree=lambda tree,doc:[],owned_tree=lambda *args:tree,token_for=lambda *args:'v1.123.'+'a'*64,
        DBAPIError=type('FixtureDBError',(Exception,),{}))
    calls=[]
    db=SimpleNamespace(get_bind=lambda:SimpleNamespace(dialect=SimpleNamespace(name='fixture')),rollback=lambda:calls.append('rollback'))
    result=ns['preview_delete'](db,SimpleNamespace(workspace_id=ws,doc_id=doc,mode='trash',cascade=True),'owner')
    from fastapi.encoders import jsonable_encoder
    Draft202012Validator(pending['responses']['200']['content']['application/json']['schema']).validate(jsonable_encoder(result))
    assert calls==['rollback']
    assert set(pending['responses']['409']['content']['application/json']['schema']['properties']['detail']['properties']['code']['enum'])=={'document_tree_invalid','document_tree_check_incomplete'}


def test_pinned_source_fixtures_reject_tampering_and_missing_bytes(tmp_path):
    import hashlib
    from api_pinned_sources import read_pinned_source
    source = response_module()._notes_pending['sources'][0]
    raw = read_pinned_source(source)
    assert hashlib.sha256(raw).hexdigest() == source['sha256']
    with pytest.raises(FileNotFoundError):
        read_pinned_source(source, root=tmp_path)
    target = tmp_path / source['revision'] / (source['file'] + '.txt')
    target.parent.mkdir(parents=True)
    target.write_bytes(raw + b'\n# tampered\n')
    with pytest.raises(AssertionError, match='pinned source hash mismatch'):
        read_pinned_source(source, root=tmp_path)


def test_iperf_progress_current_writer_is_typed_not_raw_tool_json():
    captured=[]
    ns=body_namespace('app/routers/task.py',['iperf_progress'],task_svc=SimpleNamespace(authorize_agent_task=lambda *a,**k:None,append_iperf_progress=lambda db,id,point:captured.append(point)))
    ns['iperf_progress'](1,'fixture','not-validated-as-date',2.0,None,None,'client',True,2,'retry','warming',None)
    schema=response_module().CURRENT_SHAPES['IperfProgress']
    Draft202012Validator(schema).validate(captured[0])
    assert captured[0]['retry'] is True


def test_real_current_module_projection_and_legacy_extensions(monkeypatch):
    import sys
    from typing import Literal
    from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
    from types import ModuleType
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Literal=Literal)
    tree=ast.parse((ROOT/'app/services/website_connection.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'ConnectionInput','RequestPolicy'}]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'connection-schema','exec'),ns)
    ns=body_namespace('app/services/website_connection.py',['effective_connection','public_connection'],**ns)
    connection=ModuleType('app.services.website_connection');connection.__dict__.update(ns)
    monkeypatch.setitem(sys.modules,connection.__name__,connection)
    env=body_namespace('app/services/integrations.py',['present'],copy=copy)
    module=dict(id='m',name='Demo',icon='globe',mode='iframe',adapter='generic',browser_url='https://example.invalid/',target_id=None,initial_path='/',enabled=True,keep_alive=False,origin='https://app-m.invalid',injection=dict(draft=None,active=None,previous=None))
    payload=env['present'](module)
    validate_payload('POST','/external-modules',payload,'201')
    assert response_module().DECLARATIONS['POST','/external-modules']['status']=='reviewed'
    payload['name']=['historical-invalid-type'];payload['legacy_extension']={'x':True}
    validate_payload('GET','/external-modules/{mid}',env['present'](payload))


def test_real_prometheus_adapter_and_comparison_without_network():
    import math,time
    from datetime import timezone
    # Actual pure adapter class; constructor bypassed to prevent HTTP transport.
    ns=dict(math=math,time=time,json=json)
    tree=ast.parse((ROOT/'app/services/prometheus_metrics.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PrometheusMetrics')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'prometheus-class','exec'),ns)
    cls=ns['PrometheusMetrics']; adapter=object.__new__(cls)
    adapter.clock=lambda:100.0;adapter.stale_after=60
    adapter._expression=lambda key,*args:key
    adapter._request=lambda endpoint,params,result_type:[]
    snapshot=adapter.snapshot('node','fixture');spacing=adapter.sample_spacing('node','fixture')
    class Adapter:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def snapshot(self,*a):return snapshot
        def sample_spacing(self,*a):return spacing
    class DB:
        def get(self,*a):return SimpleNamespace(status='online')
        def query(self,*a):return self
        def filter(self,*a):return self
        def order_by(self,*a):return self
        def limit(self,*a):return self
        def all(self):return []
    metric=SimpleNamespace(node_id=1,ts=SimpleNamespace(desc=lambda:None))
    import httpx
    env=body_namespace('app/routers/metrics_source.py',['compare_metrics'],Node=object,NodeSysMetric=metric,
        _load=lambda db:SimpleNamespace(enabled=True,nodes={'1':SimpleNamespace(job='node',instance='fixture')},url='https://fixture.invalid'),
        PrometheusMetrics=Adapter,PinnedTransport=lambda url:None,PrometheusError=ValueError,httpx=httpx,math=math,time=SimpleNamespace(time=lambda:100.0))
    payload=env['compare_metrics'](1,DB())
    validate_payload('GET','/nodes/{node_id}/metrics-comparison',payload)
    assert payload['prometheus']['snapshot']['freshness']=='no_sample'
    assert response_module().DECLARATIONS['GET','/nodes/{node_id}/metrics-comparison']['status']=='reviewed'


def test_entire_openapi_structure_and_all_response_metaschemas():
    from fastapi.openapi.models import OpenAPI
    app,_=source_shaped_app(); install(app); schema=app.openapi()
    OpenAPI.model_validate(schema)
    m=response_module()
    for entry in list(m.DECLARATIONS.values())+list(m.UPSTREAM_DECLARATIONS.values()):
        for response in entry['responses'].values():
            for media in response.get('content',{}).values():
                Draft202012Validator.check_schema(media['schema'])
    for value in schema['components']['schemas'].values():Draft202012Validator.check_schema(value)
    # Promoted components are isolated and included in the tamper gate.
    first=m.response_components();first.clear()
    assert m.response_components()
