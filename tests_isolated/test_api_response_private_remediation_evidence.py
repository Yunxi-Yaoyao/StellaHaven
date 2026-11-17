"""v22 candidate source/response closure; NOT independent review or release."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import pytest
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, static_inventory, source_shaped_app, install
from test_api_response_contract import response_module
from private_remediation_evidence_fixture import REVIEW,DIGEST,review,parent_loader,historical_body,advance_row


def test_v23_exact_source_only_scope_and_current_closure():
    m = response_module()
    r = m._V23_REVIEW
    assert len(r['sources']) == len(r['source_preconditions']) == 23
    assert len(r['operation_source_updates']) == 68
    assert len(r['handler_source_replacements']) == 8
    assert r['operations'] == [] and r['models'] == {} and r['new_source_keys'] == []
    assert r['source_approval'] is True and r['release_approval'] is False
    assert r['scope_files'] == ['agent/node_files_delivery.py', 'app/routers/integrations_host.py',
                                'app/routers/website_settings.py', 'app/services/access_entries.py',
                                'app/services/website_settings.py']
    active = {s for row in [*m.INVENTORY, *m.WEBSOCKET_DECLARATIONS] for s in row['sources']}
    assert set(r['source_preconditions']).isdisjoint(active)
    assert {s for s in active if m.SOURCE_EVIDENCE[s]['file'] in r['scope_files']} == set(r['sources'])
    assert m.validate_response_sources(ROOT, static_inventory()[0]) == []
    from private_remediation_evidence_fixture import v22_loader, historical_body, FINAL_DIGEST
    assert hashlib.sha256((ROOT/'app/api_response_v23_final_offload_review.json').read_bytes()).hexdigest() == FINAL_DIGEST
    before={'__file__':str(ROOT/'app/api_response_contracts.py')}
    exec(compile(v22_loader(),'literal-v22-loader','exec'),before)
    assert m.MODELS == before['MODELS']
    assert m.WEBSOCKET_DECLARATIONS == before['WEBSOCKET_DECLARATIONS']
    assert all(m.SOURCE_EVIDENCE[k] == v for k,v in before['SOURCE_EVIDENCE'].items())
    assert set(m.SOURCE_EVIDENCE)-set(before['SOURCE_EVIDENCE']) == set(r['sources'])
    from test_api_response_v11_integration import check_metadata
    from api_response_evidence_fixture import check_metadata as legacy_metadata
    for key,source in r['source_preconditions'].items():
        assert before['SOURCE_EVIDENCE'][key] == source
        if 'symbol_sha256' in source:check_metadata(source,historical_body(source))
        else:legacy_metadata(key,source,historical_body(source))
    for source in r['sources'].values():check_metadata(source)
    current={(row['method'],row['path']):row for row in m.INVENTORY}
    updates={(u['method'],u['path']):u for u in r['operation_source_updates']}
    for row in before['INVENTORY']:
        key=row['method'],row['path']
        expected=deepcopy(row)
        if key in updates:
            u=updates[key]
            assert row == u['before_operation'] and row['sources'] == u['before_sources']
            expected['sources']=sorted(r['source_replacements'].get(s,s) for s in row['sources'])
            assert expected == u['operation']
        assert current[key] == expected
        old={};new={}
        before['decorate_response'](old,*key,row['endpoint'])
        m.decorate_response(new,*key,row['endpoint'])
        old_evidence=old.pop('x-stella-contract-evidence')
        new_evidence=new.pop('x-stella-contract-evidence')
        assert new == old  # All JSON responses/security/validation remain identical.
        assert new_evidence['supporting-symbols'] == expected['sources']
        if key in updates:
            maps=old_evidence['source-map']
            assert new_evidence['source-map'] == [*(maps if isinstance(maps,list) else [maps]),'app/api_response_v23_final_offload_review.json']
        else:assert new_evidence == old_evidence
    assert m._V5_HANDLERS == before['_V5_HANDLERS'] | r['handler_source_replacements']


@pytest.mark.parametrize('damage',['hash','scope','precondition','before','after','missing-edge','duplicate-edge',
                                   'handler','release','model','operation','new-key'])
def test_v23_overlay_and_semantic_guards_reject_mutation(monkeypatch,damage):
    from private_remediation_evidence_fixture import final_review,FINAL_REVIEW,FINAL_DIGEST,v22_loader
    candidate=deepcopy(final_review())
    if damage=='scope':candidate['scope_files'].append('app/security.py')
    elif damage=='precondition':candidate['source_preconditions'][next(iter(candidate['source_preconditions']))]['sha256']='0'*64
    elif damage=='before':candidate['operation_source_updates'][0]['before_operation']['endpoint']='wrong'
    elif damage=='after':candidate['operation_source_updates'][0]['sources']=[]
    elif damage=='missing-edge':candidate['operation_source_updates'].pop()
    elif damage=='duplicate-edge':candidate['operation_source_updates'][-1]=candidate['operation_source_updates'][0]
    elif damage=='handler':candidate['handler_source_replacements'][next(iter(candidate['handler_source_replacements']))]='wrong'
    elif damage=='release':candidate['release_approval']=True
    elif damage=='model':candidate['models']={'Unreviewed':{}}
    elif damage=='operation':candidate['operations']=[{}]
    elif damage=='new-key':candidate['new_source_keys']=['unreviewed']
    text=json.dumps(candidate)
    real_read=Path.read_text;real_hash=hashlib.sha256
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:text if p==ROOT/'app'/FINAL_REVIEW else real_read(p,*a,**kw))
    if damage!='hash':
        # Exercise the independent semantic guards after the immutable-byte gate.
        # This test-only digest stand-in applies to this one mutated payload only.
        from types import SimpleNamespace
        monkeypatch.setattr(hashlib,'sha256',lambda body=b'',*a,**kw:SimpleNamespace(hexdigest=lambda:FINAL_DIGEST)
                            if body==text.encode() else real_hash(body,*a,**kw))
    with pytest.raises(ValueError,match='v23 final offload'):
        response_module()


@pytest.mark.parametrize('field',['line','end_line','sha256','symbol_sha256','symbol'])
def test_v23_current_and_retired_metadata_negatives(field):
    from private_remediation_evidence_fixture import final_review
    from test_api_response_v11_integration import check_metadata
    from api_response_evidence_fixture import check_metadata as legacy_metadata
    records=final_review()['source_preconditions'] | final_review()['sources']
    for key,original in records.items():
        body=historical_body(original)
        if 'symbol_sha256' in original:
            checker=lambda source:check_metadata(source,body)
        else:
            # Three immutable v6 whole-file records never declared a symbol hash.
            # Keep their original whole-byte/range oracle; do not invent one.
            def checker(source):
                legacy_metadata(key,source,body)
                assert (source['line'],source['end_line']) == (1,len(body.splitlines()))
            if field=='symbol_sha256':
                assert original == response_module().SOURCE_EVIDENCE[key]
                continue
        checker(original)
        bad=deepcopy(original)
        bad[field]=bad[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field=='symbol' else '0'*64
        with pytest.raises((AssertionError,ValueError,StopIteration,SyntaxError)):checker(bad)


@pytest.mark.parametrize('file',['agent/node_files_delivery.py','app/routers/integrations_host.py',
                                 'app/routers/website_settings.py','app/services/access_entries.py',
                                 'app/services/website_settings.py'])
def test_v23_one_byte_source_mutations_reach_original_validator(monkeypatch,file):
    m=response_module();records=static_inventory()[0]
    assert m.validate_response_sources(ROOT,records)==[]
    read=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda p:read(p)+b' ' if p==ROOT/file else read(p))
    assert m.validate_response_sources(ROOT,records)==['source drift or missing source: '+file]


def test_literal_parent_exact_source_response_model_and_handler_closure(monkeypatch):
    from types import SimpleNamespace
    from private_remediation_evidence_fixture import v22_loader
    literal={'__file__':str(ROOT/'app/api_response_contracts.py')}
    exec(compile(v22_loader(),'literal-v22-loader','exec'),literal)
    m=SimpleNamespace(**literal);r=review()
    assert m._V22_REVIEW==r
    assert r['status']=='PENDING_INDEPENDENT_REVIEW_NOT_APPROVED'
    assert r['source_approval'] is True and r['release_approval'] is False
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Git forbidden')))
    before={'__file__':str(ROOT/'app/api_response_contracts.py')}
    exec(compile(parent_loader(),'literal-v21-loader','exec'),before)
    assert len(before['INVENTORY'])==325 and len(m.INVENTORY)==326
    assert m.WEBSOCKET_DECLARATIONS==before['WEBSOCKET_DECLARATIONS']
    assert all(m.SOURCE_EVIDENCE[k]==v for k,v in before['SOURCE_EVIDENCE'].items())
    assert set(m.SOURCE_EVIDENCE)-set(before['SOURCE_EVIDENCE'])==set(r['sources'])
    assert {k:v for k,v in m.MODELS.items() if k not in r['models']}==before['MODELS']
    assert {k:m.MODELS[k] for k in r['models']}==r['models']
    assert len(r['source_preconditions'])==54 and len(r['sources'])==67
    assert len(r['operation_source_updates'])==68 and len(r['handler_source_preconditions'])==23
    active={s for row in [*m.INVENTORY,*m.WEBSOCKET_DECLARATIONS] for s in row['sources']}
    assert set(r['source_preconditions']).isdisjoint(active)
    assert {s for s in active if m.SOURCE_EVIDENCE[s]['file'] in r['scope_files']}==set(r['sources'])
    from api_response_evidence_fixture import check_metadata as historical_metadata
    from test_api_response_v11_integration import check_metadata
    for k,old in r['source_preconditions'].items():
        historical_metadata(k,old,historical_body(old))
        source=r['sources'][r['source_replacements'][k]]
        check_metadata(source,historical_body(source))
    for k in r['new_source_keys']:
        check_metadata(r['sources'][k],historical_body(r['sources'][k]))
    current={(x['method'],x['path']):x for x in m.INVENTORY}
    expected={}
    overrides={(x['method'],x['path']):x for x in r['response_overrides']}
    for old in before['INVENTORY']:
        key=old['method'],old['path'];expected[key]=advance_row(old,current=False)
        assert current[key]==expected[key]
        declaration=deepcopy(before['DECLARATIONS'][key]);declaration['sources']=expected[key]['sources']
        if key in overrides:
            assert declaration['responses']==overrides[key]['before_responses']
            declaration['responses']=overrides[key]['responses']
        assert m.DECLARATIONS[key]==declaration
    for row in r['operations']:expected[row['method'],row['path']]=row
    assert current==expected
    assert {k for k,v in m.DECLARATIONS.items() if v['status']=='incomplete'}=={('GET','/notifications'),('GET','/notifications/{notification_id}'),('GET','/alerts/incidents/{incident_id}')}
    for u in r['operation_source_updates']:
        assert before['INVENTORY'][before['INVENTORY'].index(u['before_operation'])]==u['before_operation']
        op={};m.decorate_response(op,u['method'],u['path'],u['endpoint'])
        prior={};before['decorate_response'](prior,u['method'],u['path'],u['endpoint'])
        maps=prior['x-stella-contract-evidence']['source-map']
        expected_maps=[*(maps if isinstance(maps,list) else [maps]),'app/'+REVIEW]
        assert op['x-stella-contract-evidence']['source-map']==expected_maps
        assert op['x-stella-contract-evidence']['supporting-symbols']==u['sources']
        handler=m._V5_HANDLERS.get(u['endpoint'],u['endpoint'])
        assert op['x-stella-contract-evidence']['handler']==m.SOURCE_EVIDENCE[handler]
    assert response_module().validate_response_sources(ROOT,static_inventory()[0])==[]


@pytest.mark.parametrize('damage',['before','before-operation','after','endpoint','scope','missing-edge','duplicate-edge','precondition','source','new-key','addition','handler-before','handler-after','release','status','model','response','new-operation','order'])
def test_exact_successor_rejects_mutation_replay_and_order(monkeypatch,damage):
    r=deepcopy(review())
    if damage=='before':r['operation_source_updates'][0]['before_sources']=[]
    elif damage=='before-operation':r['operation_source_updates'][0]['before_operation']['endpoint']='wrong'
    elif damage=='after':r['operation_source_updates'][0]['sources']=[]
    elif damage=='endpoint':r['operation_source_updates'][0]['endpoint']='wrong'
    elif damage=='scope':r['scope_files'].append('app/security.py')
    elif damage=='missing-edge':r['operation_source_updates'].pop()
    elif damage=='duplicate-edge':r['operation_source_updates'][-1]=r['operation_source_updates'][0]
    elif damage=='precondition':r['source_preconditions'][next(iter(r['source_preconditions']))]['sha256']='0'*64
    elif damage=='source':r['sources'].pop(next(iter(r['sources'])))
    elif damage=='new-key':r['new_source_keys']=[]
    elif damage=='addition':r['operation_source_updates'][0]['source_additions']=[]
    elif damage=='handler-before':r['handler_source_preconditions'][next(iter(r['handler_source_preconditions']))]='wrong'
    elif damage=='handler-after':r['handler_source_replacements'][next(iter(r['handler_source_replacements']))]='wrong'
    elif damage=='release':r['release_approval']=True
    elif damage=='status':r['status']='INDEPENDENT_PASS'
    elif damage=='model':r['models']['Unreviewed']={}
    elif damage=='response':r['response_overrides'][0]['before_responses']={}
    elif damage=='new-operation':r['operations'][0]['endpoint']='wrong'
    else:r['operation_source_updates'].reverse()
    read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(r) if p==ROOT/'app'/REVIEW else read(p,*a,**kw))
    with pytest.raises(ValueError,match='v22 private remediation'):response_module()


@pytest.mark.parametrize('field',['line','end_line','sha256','symbol_sha256','symbol'])
def test_current_symbol_and_frozen_metadata_counterfactual(field):
    from test_api_response_v11_integration import check_metadata
    from api_response_evidence_fixture import check_metadata as old_check
    r=review()
    for original in r['sources'].values():
        body=historical_body(original);check_metadata(original,body)
        bad=deepcopy(original);bad[field]=bad[field]+1 if field in {'line','end_line'} else 'missing.symbol' if field=='symbol' else '0'*64
        with pytest.raises((AssertionError,ValueError,StopIteration,SyntaxError)):check_metadata(bad,body)
    for key,old in r['source_preconditions'].items():old_check(key,old,historical_body(old))


def test_source_shaped_receipt_owner_security_and_etag_body_invariance():
    app,_=source_shaped_app();c=install(app);schema=c.validate_contract(app)
    op=schema['paths']['/website-settings/{mid}/receipt']['get']
    assert op['security']==[{'StellaAccessCookie':[]}]
    assert op['x-stella-elevation']=='none'
    assert {'200','401','403','404','409','422','503'}==set(op['responses'])
    assert op['responses']['200']['headers']['Cache-Control']['schema']['const']=='no-store'
    from private_remediation_evidence_fixture import FINAL_REVIEW
    assert op['x-stella-contract-evidence']['source-map']==['app/'+REVIEW,'app/'+FINAL_REVIEW]
    before={'__file__':str(ROOT/'app/api_response_contracts.py')};exec(compile(parent_loader(),'v21','exec'),before)
    old=before['DECLARATIONS']['GET','/external-modules/{mid}']['responses']['200']
    new=response_module().DECLARATIONS['GET','/external-modules/{mid}']['responses']['200']
    assert {k:v for k,v in new.items() if k!='headers'}==old
    assert set(new['headers'])=={'ETag','Cache-Control'}
    assert '304' not in schema['paths']['/external-modules/{mid}']['get']['responses']


@pytest.mark.parametrize('damage',['missing','byte','manifest-order','manifest-byte'])
def test_v23_literal_history_remains_depth_one_and_fail_closed(monkeypatch,damage):
    from private_remediation_evidence_fixture import final_manifest,final_frozen
    import gzip,zlib
    folder,inventory=final_manifest();row=inventory['files'][0]
    assert len(inventory['files'])==6  # Five prior product files plus the literal v22 loader.
    target=folder/row['fixture'];original=Path.read_bytes
    def read(path):
        body=original(path)
        if path==target and damage=='missing':raise FileNotFoundError(str(target))
        if path==target and damage=='byte':return body[:-1]
        if path==folder/'manifest.json' and damage=='manifest-byte':return body+b' '
        if path==folder/'manifest.json' and damage=='manifest-order':
            altered=deepcopy(inventory);altered['files'].reverse()
            return json.dumps(altered).encode()
        return body
    monkeypatch.setattr(Path,'read_bytes',read)
    with pytest.raises((FileNotFoundError,AssertionError,EOFError,gzip.BadGzipFile,zlib.error)):
        final_frozen(row['file'],row['sha256'])


@pytest.mark.parametrize('damage',['missing','byte','manifest-order','manifest-byte'])
def test_literal_history_missing_bytes_and_order_fail_closed(monkeypatch,damage):
    from private_remediation_evidence_fixture import manifest,frozen
    import gzip,zlib
    folder,inventory=manifest();row=inventory['files'][0]
    target=folder/row['fixture'];original=Path.read_bytes
    def read(path):
        body=original(path)
        if path==target and damage=='missing':raise FileNotFoundError(str(target))
        if path==target and damage=='byte':return body[:-1]
        if path==folder/'manifest.json' and damage=='manifest-byte':return body+b' '
        if path==folder/'manifest.json' and damage=='manifest-order':
            altered=deepcopy(inventory);altered['files'].reverse()
            return json.dumps(altered).encode()
        return body
    monkeypatch.setattr(Path,'read_bytes',read)
    with pytest.raises((FileNotFoundError,AssertionError,EOFError,gzip.BadGzipFile,zlib.error)):
        frozen(row['file'],row['sha256'])
