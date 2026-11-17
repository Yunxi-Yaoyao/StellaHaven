"""v17 exact predecessor/operation/model/WS/source closure; offline, no bootstrap."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module, body_namespace
from test_api_response_v11_integration import check_metadata
from test_api_response_ci167_evidence import ast_node
from nav_files_evidence_fixture import REVIEW,DIGEST,review,frozen,history_rows,current_agent
from nav_files_validation_evidence_fixture import advance_validation_row, validation_source_maps

@pytest.fixture(scope='module')
def current():return review(),response_module(),static_inventory()[0]


def test_exact_115_retirements_164_sources_287_edges_29_http_one_ws(current):
    r,m,records=current
    assert (len(r['source_preconditions']),len(r['sources']),len(r['operation_source_updates']),len(r['operations']),len(r['websockets']))==(115,164,287,29,1)
    assert r['source_approval'] is True and r['release_approval'] is False
    assert set(r['source_replacements'])==set(r['source_preconditions'])
    assert set(r['source_replacements'].values())|set(r['new_source_keys'])==set(r['sources'])
    assert len(r['new_source_keys'])==len(set(r['new_source_keys']))==49
    assert m.validate_response_sources(ROOT,records)==[]
    assert Counter((x['method'],x['path'],x['endpoint']) for x in m.INVENTORY)==Counter(x[:3] for x in records)
    assert all(n==1 for n in Counter(x[:3] for x in records).values())
    actual={(x['method'],x['path']):x for x in m.INVENTORY}
    active={s for x in [*m.INVENTORY,*m.WEBSOCKET_DECLARATIONS] for s in x['sources']}
    assert not active.intersection(r['source_preconditions'])
    from unified_files_evidence_fixture import successor, advance_row
    assert {successor(s) for s in r['sources']}<=active
    for key,old in r['source_preconditions'].items():
        assert m.SOURCE_EVIDENCE[key]==old
        assert old['sha256']==hashlib.sha256(frozen(old['file'],old['sha256'])).hexdigest()
    for u in r['operation_source_updates']:
        assert u['before_operation']['sources']==u['before_sources']
        assert u['sources']==sorted({r['source_replacements'].get(s,s) for s in u['before_sources']}|set(u['source_additions']))
        assert u['operation']=={**u['before_operation'],'sources':u['sources']}
        assert actual[u['method'],u['path']]==advance_row(u['operation'])
    for row in r['operations']:assert actual[row['method'],row['path']]==advance_validation_row(row)
    for endpoint,key in r['handler_source_preconditions'].items():
        assert m._V5_HANDLERS[endpoint]==successor(r['source_replacements'][key])==successor(r['handler_source_replacements'][endpoint])


def test_history_literal_blobs_work_when_git_is_unavailable(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Git forbidden')))
    _,rows=history_rows()
    assert {x['commit'] for x in rows}=={'77d122c69b17a7670ead0a492b0f804b069acc8d','29333cdd22aee6515331de5e44f504e108d9a504'}
    for row in rows:assert len(frozen(row['file'],row['sha256']))==row['size']


def test_every_predecessor_symbol_and_complete_module_classification_is_exact(current):
    r,_,_=current;changed=[]
    for comparison in r['symbol_comparison']['rows']:
        old=r['source_preconditions'][comparison['key']];new=r['sources'][comparison['successor']]
        from unified_files_evidence_fixture import historical_body
        before=frozen(old['file'],old['sha256']);after=historical_body(new)
        if old['file'].endswith('.ts'):
            same=before==after
        else:
            a,b=ast_node(old,before),ast_node(new,after)
            same=ast.dump(a)==ast.dump(b)
        assert same==comparison['ast_equal']==comparison['segment_equal']
        if not same:changed.append(old['symbol'])
    assert len(changed)==12
    assert {'app.routers.auth.update_profile','app.routers.homebg.delete_homebg','agent.stella_agent.Agent','main.py'}<=set(changed)


def check_v17_source(source,body,historical=False):
    if not historical:return check_metadata(source,body)
    assert hashlib.sha256(body).hexdigest()==source['sha256']
    whole=source['symbol']==source['file'] or source['symbol'].startswith(source['file']+':')
    node=None if not source['file'].endswith('.py') else ast_node(source,body)
    if whole:
        lines=(1,len(body.splitlines()));segment=body
    else:
        assert node is not None
        lines=(node.lineno,node.end_lineno);segment=ast.get_source_segment(body.decode(),node).encode()
    assert (source['line'],source['end_line'])==lines
    if 'symbol_sha256' in source:
        # These two literal historical markers hashed a line join without EOF.
        if source['symbol'] in {
            'app/services/backup_projection.py:round4-final-667bb1d@v5-integration-6b31345',
            'app/services/backup_projection.py:round4-final-667bb1d@c950d86a2fde@v5-integration-6b31345'}:
            segment=b'\n'.join(body.splitlines()[source['line']-1:source['end_line']])
        assert hashlib.sha256(segment).hexdigest()==source['symbol_sha256']


@pytest.mark.parametrize('field',['line','end_line','symbol','sha256','symbol_sha256'])
def test_all_old_and_new_metadata_have_real_negative_controls(current,field):
    r,_,_=current
    for records,old in [(r['source_preconditions'],True),(r['sources'],False)]:
        for source in records.values():
            from unified_files_evidence_fixture import historical_body
            body=frozen(source['file'],source['sha256']) if old else historical_body(source)
            check_v17_source(source,body,old)
            if field=='symbol_sha256' and field not in source:continue
            bad=deepcopy(source);bad[field]=source[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field=='symbol' else '0'*64
            with pytest.raises((AssertionError,ValueError,StopIteration,SyntaxError)):check_v17_source(bad,body,old)


FILES=tuple(sorted({x['file'] for x in review()['sources'].values()}))
@pytest.mark.parametrize('file',FILES)
@pytest.mark.parametrize('damage',['byte','missing'])
def test_each_changed_and_new_dependency_is_live_fail_closed(current,monkeypatch,file,damage):
    _,m,records=current;assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes;exists=Path.is_file
    if damage=='byte':monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    else:monkeypatch.setattr(Path,'is_file',lambda p:False if p==ROOT/file else exists(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


@pytest.mark.parametrize('damage',['old_hash','old_range','missing_old','new_hash','new_symbol','missing_source','collision','before','endpoint','missing_edge','duplicate_edge','status','errors','validation','model','model_extra','operation_extra','operation_missing','operation_duplicate','handler','ws_origin','ws_message'])
def test_loader_rejects_actual_review_damage_before_any_replay(monkeypatch,damage):
    r=deepcopy(review());old=next(iter(r['source_preconditions']));new=r['source_replacements'][old]
    if damage=='old_hash':r['source_preconditions'][old]['sha256']='0'*64
    elif damage=='old_range':r['source_preconditions'][old]['line']+=1
    elif damage=='missing_old':del r['source_preconditions'][old]
    elif damage=='new_hash':r['sources'][new]['sha256']='0'*64
    elif damage=='new_symbol':r['sources'][new]['symbol']='missing.symbol'
    elif damage=='missing_source':del r['sources'][new]
    elif damage=='collision':r['source_replacements'][old]=old
    elif damage=='before':r['operation_source_updates'][0]['before_sources']=[]
    elif damage=='endpoint':r['operation_source_updates'][0]['endpoint']='wrong'
    elif damage=='missing_edge':r['operation_source_updates'].pop()
    elif damage=='duplicate_edge':r['operation_source_updates'][-1]=r['operation_source_updates'][0]
    elif damage in {'status','errors','validation','model'}:
        field={'status':'status_code','errors':'error_statuses','validation':'request_validation','model':'model'}[damage]
        r['operations'][0][field]=False if damage=='validation' else [] if damage=='errors' else 'wrong'
    elif damage=='model_extra':r['models']['Unapproved']={}
    elif damage=='operation_extra':r['operations'].append({**r['operations'][0],'path':'/unapproved'})
    elif damage=='operation_missing':r['operations'].pop()
    elif damage=='operation_duplicate':r['operations'][-1]=r['operations'][0]
    elif damage=='handler':r['new_handler_sources'][next(iter(r['new_handler_sources']))]='wrong'
    elif damage=='ws_origin':r['websockets'][0]['origin']='any'
    else:r['websockets'][0]['message_schema']={}
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:json.dumps(r) if p==ROOT/'app'/REVIEW else read(p,*a,**k))
    with pytest.raises(ValueError,match='v17 nav files immutable review drift'):response_module()


def test_agent_artifact_exact_old_control_and_only_finite_optional_file_hooks(tmp_path):
    current,previous=current_agent();text=current.decode()
    tree=ast.parse(text);agent=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Agent')
    method=next(n for n in agent.body if isinstance(n,ast.FunctionDef) and n.name=='_file_tick')
    lines=text.splitlines(keepends=True);start=method.lineno-1;stop=method.end_lineno
    while stop<len(lines) and not lines[stop].strip():stop+=1
    del lines[start:stop];trimmed=''.join(lines)
    for line in ["        file_scheduler = _BackgroundScheduler(max_workers=1)\n","                    file_scheduler.submit('files', self._file_tick)\n","            file_scheduler.close()\n"]:
        assert trimmed.count(line)==1;trimmed=trimmed.replace(line,'')
    assert trimmed.encode()==previous
    r=review()['agent_artifacts']
    from agent.node_files_delivery import build_release,release_id
    from unified_files_evidence_fixture import frozen as unified_frozen
    for name, metadata in r['files_manifest']['files'].items():
        body=(ROOT/'agent'/name).read_bytes()
        if hashlib.sha256(body).hexdigest()!=metadata['sha256']:
            body=unified_frozen('agent/'+name,metadata['sha256'])
        (tmp_path/name).write_bytes(body)
    manifest,bodies=build_release(tmp_path)
    assert manifest==r['files_manifest'] and release_id(manifest)==r['files_release_id']=='05e1854f7d3e1476a997c82d8def28dbb2099b985e2544ccbe58da54e6d4b484'
    assert bodies['stella_agent.py']==current
    assert bodies['node_files.py']==frozen('agent/node_files.py',manifest['files']['node_files.py']['sha256'])


def test_new_openapi_exact_auth_status_source_union_and_no_holes(current):
    r,m,_=current;app,_=source_shaped_app();install(app);doc=app.openapi()
    for row in r['operations']:
        op=doc['paths'][row['path']][row['method'].lower()]
        codes={row['status_code'],*row['error_statuses']}|({'422'} if row['request_validation'] else set())
        assert set(op['responses'])==codes
        assert op['x-stella-contract-status']=='reviewed'
        assert op['security']==([{'StellaAgentBearer':[]},{'StellaAgentQueryLegacy':[]}] if row['path'].startswith('/agent/') else [{'StellaAccessCookie':[]}])
        assert op['x-stella-contract-evidence']=={'handler':m.SOURCE_EVIDENCE[m._V5_HANDLERS[row['endpoint']]],'source-map':validation_source_maps(row),'supporting-symbols':advance_validation_row(row)['sources']}
        for response in m.DECLARATIONS[row['method'],row['path']]['responses'].values():
            for media in response.get('content',{}).values():assert m.schema_holes(media['schema'])==[]
    assert {(k) for k,v in m.DECLARATIONS.items() if v['status']=='incomplete'}=={('GET','/notifications'),('GET','/notifications/{notification_id}'),('GET','/alerts/incidents/{incident_id}')}
    from tools.check_api_response_contracts import document_errors
    assert document_errors(doc)==[]


def test_ws_is_separate_read_only_closed_protocol_not_an_http_operation(current):
    r,m,_=current;ws,=r['websockets']
    assert ws['path']=='/ws/native-nav/changes' and ws['poll_seconds']==2 and ws['read_only'] is True
    assert ws['path'] not in {row['path'] for row in m.INVENTORY}
    source=m.SOURCE_EVIDENCE[ws['handler']];check_metadata(source)
    n=ast_node(source,(ROOT/source['file']).read_bytes());segment=ast.get_source_segment((ROOT/source['file']).read_text(),n)
    for token in ["len(origins)!=1","origins[0] not in trusted_origins()","ws.query_params","current_user(Request(","db.rollback()","await asyncio.sleep(2)","await ws.close(code=1008)"]:
        assert token in segment
    validator=Draft202012Validator(ws['message_schema']);validator.validate(dict(type='nav_revision',revision=0))
    for bad in [dict(type='nav_revision'),dict(type='nav_revision',revision='0'),dict(type='nav_revision',revision=1,owner='other')]:assert not validator.is_valid(bad)


def test_real_body_projection_models_and_operation_local_media_409(current):
    r,m,_=current
    from app.schemas.native_nav import NavData
    snapshot=body_namespace('app/routers/native_nav.py',['snapshot'],NavData=NavData)['snapshot']
    value=snapshot(None);schema=m.MODELS['V17NavSnapshot'];validator=Draft202012Validator(schema);validator.validate(value)
    assert not validator.is_valid(value|{'private_owner':'no'})
    assert not validator.is_valid(dict(revision=0,data={'preferences':{},'groups':'bad'}))
    for path,body in [('/homebg/{entry_id}',dict(detail=dict(code='media_in_use',message='retained',references=['saved nav']))),('/auth/me',dict(detail=dict(code='media_missing',message='not persisted')))]:
        key=('DELETE' if path.startswith('/homebg') else 'PATCH',path)
        response=m.DECLARATIONS[key]['responses']['409']['content']['application/json']['schema']
        Draft202012Validator(response).validate(body)
    assert not Draft202012Validator(m.HTTP_ERROR).is_valid(dict(detail=dict(code='media_in_use',message='x',references=['private'])))
