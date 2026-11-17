"""CI158 source metadata acceptance; no handler/schema changes or bootstrap."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module
from test_api_response_v11_integration import approved_reviews, apply_review, check_metadata

REVIEW='api_response_v13_source_metadata_review.json'
DIGEST='0f9d5694370840dcccf02807726070bacde0b3eb0a5162f275d28f6c508b0e39'
# Independent acceptance inventory, not candidate-derived counts or symbols.
KEYS=(
 'app.repositories.node.create', 'app.repositories.node.get_latest_metrics',
 'app.repositories.node.get_latest_sys_metric', 'app.repositories.node.heartbeat',
 'app.repositories.node.insert_metrics', 'app.repositories.node.insert_sys_metrics',
 'app.repositories.node.mark_offline', 'app.repositories.node.remove',
 'app.repositories.node.set_installed', 'app.repositories.node.set_uninstall_status',
 'app.routers.auth_provider._call', 'app.routers.auth_provider.client',
 'app.routers.auth_provider.clients', 'app.routers.auth_provider.create',
 'app.routers.auth_provider.delete', 'app.routers.auth_provider.provider_config',
 'app.routers.auth_provider.rotate', 'app.routers.auth_provider.update',
 'app.routers.config.get_public_host', 'app.routers.config.get_site_background',
 'app.routers.config.set_public_host', 'app.services.integrations_sessions.issue',
 'app.services.oidc._public_client', 'app.services.oidc.create_authorization_code',
 'app.services.oidc.jwks', 'app.services.oidc.list_clients',
 'app.services.oidc.openid_configuration', 'app.services.oidc.userinfo',
 'app.services.oidc.validate_authorization', 'app.services.web_project_runtime.authorize',
 'app.services.web_project_runtime.destination', 'app.services.web_project_runtime.launch',
)

ENTRY_KEYS = ('app/services/entry_registry.py@v6-websites-1d7d992', 'app.services.entry_registry._origin@v6-integration-42495ded', 'app.services.entry_registry.parent_context@v6-integration-42495ded', 'app.services.entry_registry.records@v6-integration-42495ded', 'app.services.entry_registry.request_origin@v6-integration-42495ded', 'app/services/entry_registry.py:backup-response-review@v6-integration-42495ded', 'app/services/entry_registry.py:integrated-review@v6-integration-42495ded', 'app/services/entry_registry.py:web-project-review@v6-integration-42495ded')

@pytest.fixture(scope='module')
def metadata():
    body=(ROOT/'app'/REVIEW).read_bytes()
    assert hashlib.sha256(body).hexdigest()==DIGEST
    return json.loads(body),response_module(),static_inventory()[0]


def test_exact_32_append_only_successors_same_file_hash_and_27_edges(metadata):
    review,module,records=metadata
    assert tuple(review['source_replacements'])==(*KEYS, 'app/services/web_project_runtime.py:renewal-detached-review', *ENTRY_KEYS)
    assert len(review['sources'])==41 and len(review['operation_source_updates'])==240
    addition=review['validation_source_additions']
    assert addition['source']=='app/validation_errors.py:response-projection'
    assert module.SOURCE_EVIDENCE[addition['source']]==addition['source_precondition']
    assert len(addition['operations'])==11
    assert review['source_approval'] is True and review['release_approval'] is False
    assert module.validate_response_sources(ROOT,records)==[]
    active={s for row in module.INVENTORY for s in row['sources']}
    for old,new in review['source_replacements'].items():
        before=review['source_preconditions'][old];after=review['sources'][new]
        assert module.SOURCE_EVIDENCE[old]==before
        assert module.SOURCE_EVIDENCE[new]==after
        assert old not in active and new in active
        if old in ENTRY_KEYS:
            assert new==old+'@website-origin-fix'
            assert before['sha256']=='47052ebd26f8283efad3a654c2d60a6ae5fb158ecaa840bb976e01924853f64a'
            assert after['sha256']=='2b8a5a19126274aeb912f4e617ca94e15b7695a49d8e138654aea19af6197455'
            check_metadata(after)
            continue
        assert new==old+'@v13-source-metadata'
        assert {k:v for k,v in before.items() if k not in {'line','end_line'}}=={k:v for k,v in after.items() if k not in {'line','end_line','symbol_sha256'}}
        if old in KEYS:
            check_metadata(after)
        else:
            body=(ROOT/after['file']).read_bytes()
            assert after['symbol']==old and after['line']==1
            assert after['end_line']==len(body.splitlines())==164
            assert after['sha256']==after['symbol_sha256']==hashlib.sha256(body).hexdigest()
    current={(r['method'],r['path']):r for r in module.INVENTORY}
    for update in review['operation_source_updates']:
        key=update['method'],update['path']
        expected={review['source_replacements'].get(s,s) for s in update['before_sources']}
        if [update['method'],update['path']] in addition['operations']:
            expected.add(addition['source'])
        assert update['sources']==sorted(expected)
        assert current[key]['endpoint']==update['endpoint']
        # Preserve the exact historical V13 union, then replay its approved
        # successor edge instead of asserting an obsolete union is still live.
        expected_sources = update['sources']
        layers=approved_reviews();at=next(i for i,r in enumerate(layers) if r==review)
        for feedback in layers[at+1:]:
            later = next((r for r in feedback['operation_source_updates']
                          if (r['method'], r['path']) == key), None)
            if later is not None:
                assert later['before_sources'] == expected_sources
                expected_sources = later['sources']
        assert current[key]['sources'] == expected_sources


@pytest.mark.parametrize('damage', ['old_range', 'line', 'end_line', 'sha256', 'missing'])
def test_renewal_whole_file_range_is_exact_and_drift_is_rejected(metadata, monkeypatch, damage):
    review, module, records = metadata
    key = 'app/services/web_project_runtime.py:renewal-detached-review'
    source = deepcopy(review['sources'][review['source_replacements'][key]])
    path = ROOT/source['file']
    if damage == 'old_range': source['end_line'] = 154
    elif damage in {'line', 'end_line'}: source[damage] += 1
    elif damage == 'sha256': source['sha256'] = '0'*64
    else:
        original = Path.is_file
        monkeypatch.setattr(Path, 'is_file', lambda p: False if p == path else original(p))
        assert any(source['file'] in error for error in module.validate_response_sources(ROOT, records))
        return
    with pytest.raises(AssertionError):
        body = path.read_bytes()
        assert (source['line'], source['end_line']) == (1, len(body.splitlines()))
        assert source['sha256'] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('damage',['old_range','line','end_line','sha256','symbol','symbol_sha256'])
def test_every_corrected_symbol_keeps_exact_range_hash_segment_negatives(metadata,key,damage):
    review,module,_=metadata
    source=deepcopy(review['sources'][review['source_replacements'][key]])
    check_metadata(source)
    if damage=='old_range':
        before=review['source_preconditions'][key]
        source.update(line=before['line'],end_line=before['end_line'])
    elif damage in {'line','end_line'}:source[damage]+=1
    elif damage=='symbol':source['symbol']='missing.symbol'
    else:source[damage]='0'*64
    with pytest.raises((AssertionError,StopIteration,SyntaxError)):
        check_metadata(source)


@pytest.mark.parametrize('damage',['source_precondition','handler_precondition','endpoint','before_sources','missing_source','missing_update'])
def test_metadata_overlay_damage_is_not_accepted(metadata,monkeypatch,damage):
    review,_,records=metadata
    changed=deepcopy(review)
    if damage=='source_precondition':changed['source_preconditions'][KEYS[0]]['line']=1
    elif damage=='handler_precondition':changed['handler_source_preconditions']['app.routers.config.get_public_host']='missing'
    elif damage in {'endpoint','before_sources'}:changed['operation_source_updates'][0][damage]=[] if damage=='before_sources' else 'missing'
    elif damage=='missing_source':del changed['sources'][changed['source_replacements'][KEYS[0]]]
    else:
        # Remove a replacement edge, not the newest dependency-only addition.
        index=next(i for i,row in enumerate(changed['operation_source_updates']) if KEYS[0] in row['before_sources'])
        changed['operation_source_updates'].pop(index)
    read=Path.read_text;read_bytes=Path.read_bytes
    target=ROOT/'app'/REVIEW
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**kw:json.dumps(changed) if p==target else read(p,*a,**kw))
    monkeypatch.setattr(Path,'read_bytes',lambda p:json.dumps(changed).encode() if p==target else read_bytes(p))
    # Immutable approval first: omissions cannot become accepted current evidence.
    with pytest.raises(AssertionError,match=REVIEW):approved_reviews()
    if damage in {'source_precondition','handler_precondition','endpoint','before_sources'}:
        with pytest.raises(ValueError,match='v13 source metadata'):response_module()
    elif damage=='missing_source':
        damaged=response_module()
        with pytest.raises(KeyError):damaged.validate_response_sources(ROOT,records)
    else:
        # Preserve the original pre-v17 omission oracle on literal prior loader.
        from nav_files_evidence_fixture import frozen
        old=frozen('app/api_response_contracts.py','77f42446db3fccabe18f6bd96abdc03f3614725b1a8b8c87ba7f6c16dd87aa6c')
        ns={'__file__':str(ROOT/'app/api_response_contracts.py')}
        exec(compile(old,'literal-pre-v17-loader','exec'),ns)
        active={s for row in ns['INVENTORY'] for s in row['sources']}
        assert active.intersection(review['source_replacements'])
        with pytest.raises(ValueError,match='v17 nav files exact before operation/source union drift'):
            response_module()


@pytest.mark.parametrize('damage',['missing','reordered','duplicate','extra'])
def test_identity_latest_metadata_source_map_and_union_are_exact(metadata,damage):
    from test_api_response_v11_integration import assert_identity_evidence
    _,module,_=metadata
    operation={};module.decorate_response(operation,'GET','/agent/identity','app.routers.monitor.agent_identity')
    assert_identity_evidence(operation,module)
    maps=operation['x-stella-contract-evidence']['source-map']
    if damage=='missing':maps.pop()
    elif damage=='reordered':maps.reverse()
    elif damage=='duplicate':maps.append(maps[-1])
    else:maps.append('extra.json')
    with pytest.raises(AssertionError):assert_identity_evidence(operation,module)
