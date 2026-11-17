"""v19 candidate contracts: offline/source-shaped, never release approval."""
import sys
from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module


def test_config_exact_bearer_only_and_legacy_unchanged():
    app, _ = source_shaped_app()
    module = install(app)
    schema = app.openapi()
    config = schema['paths']['/agent/files/config']['get']
    assert config['security'] == [{'StellaAgentBearer': []}]
    assert schema['paths']['/agent/files/claim']['post']['security'] == [
        {'StellaAgentBearer': []}, {'StellaAgentQueryLegacy': []}]
    for endpoint, deps in [('wrong', frozenset({'app.database.get_db', 'app.security.agent_token'})),
                           ('app.routers.node_files.config', frozenset({'app.security.agent_token'}))]:
        assert module.classify_auth('GET', '/agent/files/config', endpoint, deps) is module.UNKNOWN
    assert not {'main', 'app.config', 'app.database'} & set(sys.modules)


def test_config_strict_closed_union_and_whole_inventory():
    m = response_module()
    records, _, _ = static_inventory()
    assert m.validate_response_sources(ROOT, records) == []
    schema = m.DECLARATIONS['GET', '/agent/files/config']['responses']['200']['content']['application/json']['schema']
    validator = Draft202012Validator(schema)
    enabled = {'enabled': True, 'roots': {'system': {'path': '/', 'write': True}}, 'revision': 'a'*64}
    disabled = {'enabled': False, 'roots': {}, 'revision': 'b'*64}
    for body in [enabled, disabled]: validator.validate(body)
    for body in [dict(enabled, enabled=1), dict(disabled, enabled=0), dict(enabled, extra=True),
                 dict(disabled, roots=enabled['roots']), dict(enabled, roots={}), dict(enabled, revision='X'*64),
                 dict(enabled, roots={'system': {'path': '/', 'write': 1}}),
                 dict(enabled, roots={'system': {'path': '/tmp', 'write': True}})]:
        assert list(validator.iter_errors(body)), body
    assert m.DECLARATIONS['GET','/agent/files/config']['responses']['200']['headers']['Cache-Control']['schema']['const'] == 'no-store'


def test_real_dto_schema_parity_and_numeric_boolean_rejection():
    from app.schemas.node_file import AgentFilesConfig, FileRequest
    from pydantic import TypeAdapter, ValidationError
    adapter = TypeAdapter(AgentFilesConfig)
    assert response_module().MODELS['V19AgentFilesConfig'] == adapter.json_schema(mode='serialization')
    enabled = dict(enabled=True, roots={'system': {'path': '/', 'write': True}}, revision='a'*64)
    assert adapter.validate_python(enabled).model_dump(mode='json') == enabled
    for bad in [dict(enabled, enabled=1), dict(enabled, enabled=0),
                dict(enabled, roots={'system': {'path': '/', 'write': 1}})]:
        with pytest.raises(ValidationError): adapter.validate_python(bad)
    with pytest.raises(ValidationError):
        FileRequest.model_validate(dict(node_id=1, root='system', path='/etc', op='list', request_key='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'))


def test_actual_http_config_auth_no_store_and_readonly_authority(monkeypatch, record_property):
    """Real handler/auth/config bodies; explicit query/DB identity boundary, NO PG."""
    import ast, hashlib, json, os, types
    from uuid import UUID, uuid4
    from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
    from fastapi.testclient import TestClient
    from app.schemas.node_file import AgentFilesConfig
    from test_api_response_contract import body_namespace
    nonce = str(uuid4())
    monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','1')
    monkeypatch.setenv('STELLA_OWNER_ID',nonce)
    monkeypatch.delenv('STELLA_NODE_FILE_POLICY',raising=False)
    user = types.SimpleNamespace(is_active=True)
    node = types.SimpleNamespace(id=17,platform='linux',os_name='Linux',status='online',token='owned')
    class Column:
        def __init__(self,name):self.name=name
        def __eq__(self,v):return self.name,'eq',v
        def __ne__(self,v):return self.name,'ne',v
    Node=types.SimpleNamespace(token=Column('token'),status=Column('status'))
    class Query:
        def where(self,*terms):self.terms=terms;return self
    class DB:
        writes=0
        def scalar(self,q):
            return node if all((getattr(node,k)==v if op=='eq' else getattr(node,k)!=v) for k,op,v in q.terms) else None
        def get(self,model,key):assert key==UUID(nonce);return user
        def add(self,*a):raise AssertionError('read must not add')
        def commit(self):raise AssertionError('read must not commit')
    state={'owner_id':nonce}
    admin=types.ModuleType('app.services.admin_security');admin.read_state=lambda db:(None,deepcopy(state))
    monkeypatch.setitem(sys.modules,admin.__name__,admin)
    service=body_namespace('app/services/node_files.py', ['automatic_owner','automatic_policy','agent_config','digest','node_agent'],
        os=os,UUID=UUID,User=object(),Node=Node,select=lambda _:Query(),HTTPException=HTTPException,hashlib=hashlib,json=json)
    auth=body_namespace('app/security.py',['agent_token'],HTTPException=HTTPException)['agent_token']
    auth.__annotations__={'request':Request,'return':str}
    ns=dict(__name__='app.routers.node_files',agent_router=APIRouter(prefix='/agent/files'),Request=Request,Response=Response,
        AgentFilesConfig=AgentFilesConfig,Depends=Depends,agent_token=auth,Session=object,get_db=lambda:DB(),
        HTTPException=HTTPException,svc=types.SimpleNamespace(**service))
    tree=ast.parse((ROOT/'app/routers/node_files.py').read_text())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='config']
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'real-file-config-handler','exec'),ns)
    app=FastAPI();app.include_router(ns['agent_router'])
    samples=[]
    with TestClient(app) as client:
        for path,headers in [('/agent/files/config',{}),('/agent/files/config?token=owned',{}),
                             ('/agent/files/config',{'Cookie':'stella_at=browser'}),
                             ('/agent/files/config?token=owned',{'Authorization':'Bearer invalid'}),
                             ('/agent/files/config?token=owned',{'Authorization':'Basic invalid'})]:
            result=client.get(path,headers=headers);assert result.status_code==401
        result=client.get('/agent/files/config',headers={'Authorization':'Bearer owned'})
        assert result.status_code==200 and result.headers['cache-control']=='no-store'
        enabled=result.json();samples.append(enabled)
        assert enabled['enabled'] is True and enabled['roots']=={'system':{'path':'/','write':True}}
        assert state=={'owner_id':nonce}
        for field,value in [('status','removed'),('token','rotated')]:
            old=getattr(node,field);setattr(node,field,value)
            assert client.get('/agent/files/config',headers={'Authorization':'Bearer owned'}).status_code==401
            setattr(node,field,old)
        monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','0')
        result=client.get('/agent/files/config',headers={'Authorization':'Bearer owned'})
        assert result.status_code==200 and result.headers['cache-control']=='no-store'
        disabled=result.json();samples.append(disabled)
        assert disabled['enabled'] is False and disabled['roots']=={} and disabled['revision']!=enabled['revision']
    schema=response_module().MODELS['V19AgentFilesConfig']
    for sample in samples: Draft202012Validator(schema).validate(sample)
    record_property('actual_http_json',json.dumps(samples,sort_keys=True))
    assert not {'main','app.config','app.database'} & set(sys.modules)


def test_exact_successor_closure_retains_history_and_no_git_needed(monkeypatch):
    import hashlib, subprocess
    from unified_files_evidence_fixture import review, frozen, successor, advance_row
    from test_api_response_v11_integration import check_metadata
    r=review();m=response_module()
    assert r['status']=='PENDING_INDEPENDENT_REVIEW_NOT_APPROVED' and r['release_approval'] is False
    assert r['baseline']=='fa44f76715beb1f117149311f625de4d15dfda16'
    assert r['installer_revision']=='fbfad972a70674c61089e3a5d19e1671d4d30b4e'
    assert len(r['source_preconditions'])==114 and len(r['sources'])==144 and len(r['operation_source_updates'])==106
    assert set(r['source_link_preconditions'])=={'app.models.node.Node','app.models.user.User','app.models.user.AuthSession','app.security.agent_token'}
    for key,source in r['source_link_preconditions'].items():
        assert m.SOURCE_EVIDENCE[key]==source
        assert key in r['operations'][0]['sources']
    for row in r['operation_source_updates']:
        if row['endpoint'].startswith(('app.routers.node_files.','app.routers.node_files_release.')):
            assert set(r['source_link_preconditions'])<=set(row['sources'])
    active={s for row in [*m.INVENTORY,*m.WEBSOCKET_DECLARATIONS] for s in row['sources']}
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Git forbidden')))
    for k,old in r['source_preconditions'].items():
        assert m.SOURCE_EVIDENCE[k]==old and k not in active and successor(k) in active
        check_metadata(old,frozen(old['file'],old['sha256']))
        check_metadata(m.SOURCE_EVIDENCE[successor(k)])
    rows={(x['method'],x['path']):x for x in m.INVENTORY}
    for u in r['operation_source_updates']:
        from fnos_policy_evidence_fixture import advance_row as fnos_row
        assert rows[u['method'],u['path']]==advance_row(u['before_operation'])==fnos_row(u['operation'])
    assert hashlib.sha256((ROOT/'agent/install.sh').read_bytes()).hexdigest()=='6aad32623683c0bc0a6900d7450e36007d3104bc19c47269bbb3f7551fc65df4'


def test_literal_ast_and_raw_segments_distinguish_changed_from_shifted_symbols():
    import ast
    from unified_files_evidence_fixture import review, frozen, historical_body
    r=review();changed=[]
    def segment(source,body):
        name,file=source['symbol'],source['file']
        if name==file:return body,ast.dump(ast.parse(body)) if file.endswith('.py') else body
        text=body.decode()
        if name=='agent/install.sh:embedded.install':
            prefix,embedded=text.split("<<'STELLA_INSTANCE_INSTALLER'\n",1)
            tree=ast.parse('\n'*(prefix.count('\n')+1)+embedded.rsplit('\nSTELLA_INSTANCE_INSTALLER',1)[0]);parts=['install']
        else:
            tree=ast.parse(text);parts=name.removeprefix(file.removesuffix('.py').replace('/','.')+'.').split('.')
        nodes=tree.body
        for part in parts:
            n,=[n for n in nodes if getattr(n,'name',None)==part or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==part for t in n.targets) or isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id==part]
            nodes=getattr(n,'body',[])
        return ast.get_source_segment(text,n).encode(),ast.dump(n)
    for row in r['symbol_comparison']:
        old=r['source_preconditions'][row['key']];new=r['sources'][row['successor']]
        a,at=segment(old,frozen(old['file'],old['sha256']));b,bt=segment(new,historical_body(new))
        assert (at==bt)==row['ast_equal'] and (a==b)==row['segment_equal']
        if at!=bt:changed.append(old['symbol'])
    assert sorted(changed)==sorted(['agent.stella_agent.Agent','agent/install.sh:embedded.install','agent/install.sh','agent/node_files.py','agent/stella_agent.py','app.routers.monitor.agent_version','app.routers.node_files.by_key','app.routers.node_files.download','app.routers.node_files.nodes','app.routers.node_files.read','app/routers/monitor.py','app/routers/node_files.py','app/schemas/node_file.py','app/services/node_files.py'])


def test_current_release_manifest_and_raw_artifact_real_bodies_match_contract():
    import hashlib,json
    from pathlib import Path
    from fastapi import HTTPException
    from fastapi.responses import Response
    from agent.node_files_delivery import FILES,build_release,canonical,release_id
    from test_api_response_contract import body_namespace
    ns=body_namespace('app/routers/node_files_release.py',['snapshot','manifest','artifact'],
        __file__=str(ROOT/'app/routers/node_files_release.py'),Path=Path,HTTPException=HTTPException,
        Response=Response,FILES=FILES,build_release=build_release,canonical=canonical,release_id=release_id,
        node_agent=lambda db,token:17)
    manifest=ns['manifest']('owned',None);value=json.loads(manifest.body)
    assert manifest.status_code==200 and manifest.headers['cache-control']=='no-store'
    assert value['version']=='0.6.21'
    schema=response_module().DECLARATIONS['GET','/agent/files/release']['responses']['200']['content']['application/json']['schema']
    Draft202012Validator(schema).validate(value)
    for name in FILES:
        response=ns['artifact'](release_id(value),name,'owned',None)
        body=(ROOT/'agent'/name).read_bytes()
        assert response.status_code==200 and response.body==body
        assert response.headers['cache-control']=='no-store'
        assert response.headers['x-artifact-sha256']==hashlib.sha256(body).hexdigest()==value['files'][name]['sha256']
        assert len(body)==value['files'][name]['size']
    with pytest.raises(HTTPException) as error:ns['artifact']('0'*64,'stella_agent.py','owned',None)
    assert error.value.status_code==409
    with pytest.raises(HTTPException) as error:ns['artifact'](release_id(value),'unknown','owned',None)
    assert error.value.status_code==404


@pytest.mark.parametrize('field',['line','end_line','sha256','symbol_sha256','symbol'])
def test_every_new_source_keeps_metadata_negative_controls(field):
    from unified_files_evidence_fixture import review, historical_body
    from test_api_response_v11_integration import check_metadata
    for original in review()['sources'].values():
        body = historical_body(original)
        check_metadata(original, body)
        bad=deepcopy(original);bad[field]=bad[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field=='symbol' else '0'*64
        with pytest.raises((AssertionError,ValueError,StopIteration,SyntaxError)):
            check_metadata(bad, body)


@pytest.mark.parametrize('file',['agent/install.sh','agent/node_files.py','agent/stella_agent.py','app/routers/monitor.py','app/routers/node_files.py','app/schemas/node_file.py','app/services/node_files.py','app/models/node.py','app/models/user.py','app/security.py','app/services/admin_security.py'])
@pytest.mark.parametrize('damage',['byte','missing'])
def test_complete_changed_file_scope_stays_live_fail_closed(monkeypatch,file,damage):
    from pathlib import Path
    m=response_module();records=static_inventory()[0]
    assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;exists=Path.is_file
    if damage=='byte':monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    else:monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else exists(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


@pytest.mark.parametrize('damage',['before','endpoint','missing_edge','duplicate_edge','handler','schema','auth','source','release','status'])
def test_candidate_bytes_are_exact_and_not_self_signed(monkeypatch,damage):
    import json
    from pathlib import Path
    from unified_files_evidence_fixture import review, REVIEW
    r=deepcopy(review())
    if damage=='before':r['operation_source_updates'][0]['before_sources']=[]
    elif damage=='endpoint':r['operation_source_updates'][0]['endpoint']='wrong'
    elif damage=='missing_edge':r['operation_source_updates'].pop()
    elif damage=='duplicate_edge':r['operation_source_updates'][-1]=r['operation_source_updates'][0]
    elif damage=='handler':r['handler_source_replacements'][next(iter(r['handler_source_replacements']))]='wrong'
    elif damage=='schema':r['models']['V19AgentFilesConfig']={}
    elif damage=='auth':r['auth_override']['security'].append({'StellaAgentQueryLegacy':[]})
    elif damage=='source':r['sources'].pop(next(iter(r['sources'])))
    elif damage=='release':r['release_approval']=True
    else:r['status']='APPROVED'
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:json.dumps(r) if p==ROOT/'app'/REVIEW else read(p,*a,**k))
    with pytest.raises(ValueError,match='v19 unified files immutable candidate drift'):response_module()
