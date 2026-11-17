"""7790dcf response audit: real AST bodies, synthetic DB/locks/auth, no PG."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from test_api_response_contract import body_namespace, response_module, validate_payload
from api_response_evidence_fixture import check_metadata, successor
from test_api_response_v7_integration import history
from test_web_project_response_contract import project_http, ROOT, NEW_OPERATIONS


def setup_project(h):
    imported, _ = h.imported()
    base = '/web-projects/' + imported['id']
    manifest = h.call('GET', '/web-projects/{root_id}', path=base)
    return imported['id'], base, manifest


def detach(h, manifest):
    item = next(f for f in manifest['files'] if f['path'] == 'index.html')
    doc = h.db.get(h.Document, h.UUID(item['id']))
    h.projects.guard_project_move(h.db, doc, None)
    doc.parent_id = None
    return doc


def test_entry_cas_and_detached_real_http(project_http, record_property):
    h = project_http
    root, base, manifest = setup_project(h)
    assert manifest['directories'] == [{'id': str(h.db.get(h.Document, h.UUID(next(f['id'] for f in manifest['files'] if f['path'] == 'js/app.js'))).parent_id), 'path': 'js', 'kind': 'directory'}]
    for item in manifest['files']:
        doc = h.db.get(h.Document, h.UUID(item['id']))
        size = len((doc.content or '').encode()) if item['kind'] == 'text' else len(b'\x89PNG\r\nfixture')
        assert item['size'] == size
    entry_path = '/web-project-files/' + root + '/entry'
    template = '/web-project-files/{root_id}/entry'
    payload = {'file_id': manifest['entry_file_id'], 'expected_entry_file_id': manifest['entry_file_id']}
    assert h.call('PATCH', template, path=entry_path, json=payload) == manifest
    h.call('PATCH', template, path=entry_path, json=dict(payload, expected_entry_file_id=None), status=409)
    h.call('PATCH', template, path=entry_path, json={'file_id': payload['file_id']}, status=422)
    for item in manifest['files']:
        if item['path'] != 'index.html':
            h.call('PATCH', template, path=entry_path, json=dict(payload, file_id=item['id']), status=409)
    doc = detach(h, manifest)
    cleared = h.call('GET', '/web-projects/{root_id}', path=base)
    assert cleared['entry'] is None and cleared['entry_file_id'] is None
    assert str(doc.id) not in {f['id'] for f in cleared['files']}
    url = '/detached-sources/' + str(doc.id)
    listing = h.call('GET', '/detached-sources', params={'workspace_id': str(h.workspace.id)})
    read = h.call('GET', '/detached-sources/{file_id}', path=url)
    assert listing == [{k:v for k,v in read.items() if k != 'content'}]
    assert read['id'] == str(doc.id) and read['kind'] == 'detached-source'
    saved = h.call('PUT', '/detached-sources/{file_id}', path=url,
                   json={'updated_at': read['updated_at'], 'content': '<script>const 中文=1</script>'})
    assert saved['content'] == doc.content and saved['updated_at'] == doc.updated_at.isoformat()
    h.call('PUT', '/detached-sources/{file_id}', path=url,
           json={'updated_at': read['updated_at'], 'content': 'stale'}, status=409)
    forbidden = {'owner_id', 'source_root_id', 'original_path', 'attachment_id', 'original_attachment', 'write_id', 'digest', 'sid', 'expires'}
    for value in [manifest, *manifest['files'], *manifest['directories'], *listing, read, saved]:
        assert not forbidden.intersection(value)
    assert set(NEW_OPERATIONS) <= {(m,p) for m,p,s,_ in h.receipts if s == 200}
    record_property('real_body_http_responses', json.dumps(h.receipts, ensure_ascii=False))


@pytest.mark.parametrize('case', ['foreign', 'deleted', 'public', 'folder', 'metadata-owner', 'metadata-kind', 'missing'])
def test_detached_denial_does_not_expose_private_source(project_http, case, record_property):
    h = project_http
    _, _, manifest = setup_project(h)
    doc = detach(h, manifest)
    meta_row = h.db.get(h.AppConfig, h.projects.DETACHED_PREFIX + str(doc.id))
    meta = json.loads(meta_row.value)
    if case == 'foreign': h.workspace.user_id = h.uuid4()
    elif case == 'deleted': doc.deleted_at = h.datetime(2026, 1, 3)
    elif case == 'public': doc.visibility = 'public'
    elif case == 'folder': doc.is_folder = True
    elif case == 'metadata-owner': meta['owner_id'] = str(h.uuid4())
    elif case == 'metadata-kind': meta['kind'] = 'binary'
    elif case == 'missing': h.db.delete(meta_row)
    meta_row.value = json.dumps(meta)
    for method in ['GET', 'PUT']:
        kwargs = {'json': {'updated_at': doc.updated_at.isoformat(), 'content': 'new'}} if method == 'PUT' else {}
        body = h.call(method, '/detached-sources/{file_id}', path='/detached-sources/' + str(doc.id), status=404, **kwargs)
        assert set(body) == {'detail'} and doc.content not in json.dumps(body)
    record_property('real_body_http_responses', json.dumps(h.receipts, ensure_ascii=False))


@pytest.mark.parametrize('content,status', [('x\x00',422), ('中' * (2 * 1024 * 1024),413), ('x' * (5 * 1024 * 1024 + 1),422)], ids=['nul', 'utf8-budget', 'character-budget'])
def test_detached_validation_http(project_http, content, status, record_property):
    h = project_http
    _, _, manifest = setup_project(h)
    doc = detach(h, manifest)
    h.call('PUT', '/detached-sources/{file_id}', path='/detached-sources/' + str(doc.id),
           json={'updated_at': doc.updated_at.isoformat(), 'content': content}, status=status)
    record_property('real_body_http_responses', json.dumps(h.receipts, ensure_ascii=False))


@pytest.mark.parametrize('case,status', [('origin',403), ('duplicate-origin',403), ('wrong-cap',403), ('epoch',409),
    ('grace',200), ('expired',403), ('missing-row',403), ('revoked',401), ('reset',409), ('new-launch',403),
    ('invalid-epoch',422), ('extra-field',422), ('oversize',413)])
def test_renew_http_in_place_and_fail_closed(project_http, monkeypatch, case, status, record_property):
    h = project_http
    root, base, _ = setup_project(h)
    origin = {'Origin': 'https://stella.test'}
    launched = h.call('POST', '/web-projects/{root_id}/launch', path=base+'/launch', headers=origin)
    cap = launched['capability']
    row = h.db.get(h.AppConfig, h.runtime.key(cap))
    original_keys = set(h.db.rows)
    payload = {'capability': cap, 'epoch': 0}
    if case == 'origin': origin = {'Origin': 'https://wrong.test'}
    elif case == 'duplicate-origin': origin = [('Origin','https://stella.test'), ('Origin','https://stella.test')]
    elif case == 'wrong-cap': payload['capability'] = 'x' * 43
    elif case == 'epoch': payload['epoch'] = 1
    elif case in {'grace','expired'}:
        grant = json.loads(row.value); grant['expires'] = h.time.time() - (30 if case == 'grace' else 301); row.value = json.dumps(grant)
        with pytest.raises(h.HTTPException) as exc: h.runtime.authorize(h.db, cap, 'https://pages.test')
        assert exc.value.status_code == 403
    elif case == 'missing-row': h.db.delete(row)
    elif case == 'revoked': h.session.revoked = True
    elif case == 'reset': h.call('DELETE', '/web-projects/{root_id}/state', path=base+'/state')
    elif case == 'new-launch': h.call('POST', '/web-projects/{root_id}/launch', path=base+'/launch', headers=origin)
    elif case == 'invalid-epoch': payload['epoch'] = True
    elif case == 'extra-field': payload['owner_id'] = str(h.owner.id)
    kwargs = {'json': payload} if case != 'oversize' else {'content': b'x'*1025, 'headers': {'content-type': 'application/json'}}
    kwargs.setdefault('headers', origin)
    output = h.call('POST', '/web-projects/{root_id}/renew', path=base+'/renew', status=status, **kwargs)
    if status == 200:
        assert output == dict(capability=cap, epoch=0, expires_in=900, renew_after=840)
        assert set(h.db.rows) == original_keys
        assert h.db.get(h.AppConfig, h.runtime.key(cap)) is row
        assert 'state' not in output and 'url' not in output
    record_property('real_body_http_responses', json.dumps(h.receipts, ensure_ascii=False))


@pytest.mark.parametrize('doc_bound,owner_case,expected', [(True,'none',200),(True,'same',200),(True,'foreign',404),
    (False,'same',200),(False,'foreign',404),(False,'none',404)])
def test_attachment_authorization_real_body_does_not_serialize_model(project_http, doc_bound, owner_case, expected):
    h = project_http
    root, _, _ = setup_project(h)
    doc = h.db.get(h.Document, h.UUID(root))
    att = h.Attachment(doc_id=doc.id if doc_bound else None,
        owner_id={'none':None,'same':h.owner.id,'foreign':h.uuid4()}[owner_case], filename='fixture.png', mime='image/png')
    h.db.add(att)
    calls = []
    def response(db, key, request, **kwargs):
        calls.append((key, kwargs)); return b'fixture bytes'
    serve = body_namespace('app/routers/attachment.py', ['serve'], Attachment=h.Attachment,
        HTTPException=h.HTTPException, require_doc_owner=h.auth_ns['require_doc_owner'],
        blob_store=SimpleNamespace(enabled=lambda:True, response=response))['serve']
    if expected == 200:
        assert serve(att.id, SimpleNamespace(), h.db, h.owner) == b'fixture bytes'
        assert calls == [('attachments/'+str(att.id), {'filename':'fixture.png','private':True})]
    else:
        with pytest.raises(h.HTTPException) as exc: serve(att.id, SimpleNamespace(), h.db, h.owner)
        assert exc.value.status_code == expected and exc.value.headers['Cache-Control'] == 'no-store'
        validate_payload('GET','/attachments/{att_id}',{'detail':exc.value.detail},'404')
        assert not calls


def test_closed_new_schemas_and_internal_mutations(project_http):
    h = project_http
    root, base, manifest = setup_project(h)
    doc = detach(h, manifest)
    read = h.call('GET','/detached-sources/{file_id}',path='/detached-sources/'+str(doc.id))
    module = response_module()
    examples = [(module.PROJECT_MANIFEST, manifest), (module.DETACHED_SOURCE, read),
        (module.PROJECT_RENEWAL, dict(capability='a'*43,epoch=0,expires_in=900,renew_after=840))]
    for schema, valid in examples:
        validator = Draft202012Validator(schema); validator.validate(valid)
        for key in ['owner_id','source_root_id','original_path','attachment_id','sid','digest','write_id','expires']:
            assert not validator.is_valid(dict(valid, **{key:'private sentinel'}))
        for key in schema['required']:
            changed = deepcopy(valid); del changed[key]
            assert not validator.is_valid(changed)
    for field in ['size', 'kind']:
        wrong = deepcopy(manifest)
        wrong['files'][0][field] = -1 if field == 'size' else 'directory'
        assert not Draft202012Validator(module.PROJECT_MANIFEST).is_valid(wrong)


def test_attachment_model_nullability_is_not_the_list_response_contract():
    import ast
    from datetime import datetime
    from uuid import UUID, uuid4
    from sqlalchemy import ForeignKey, Integer, DateTime, CheckConstraint, Index, text
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from sqlalchemy.sql import func
    class Base(DeclarativeBase): pass
    ns = dict(locals(), __name__='attachment_model_contract_fixture')
    tree = ast.parse((ROOT/'app/models/attachment.py').read_text())
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, 'app/models/attachment.py', 'exec'), ns)
    table = ns['Attachment'].__table__
    assert table.c.doc_id.nullable and table.c.owner_id.nullable
    assert any(str(getattr(c, 'sqltext', '')) == 'doc_id IS NOT NULL OR owner_id IS NOT NULL' for c in table.constraints)
    props = response_module().SUCCESS['app.routers.attachment.list_attachments']['items']['properties']
    assert props['doc_id'] == {'type': 'string'} and 'owner_id' not in props
    # Verify the real mapper's list is an inner join, rather than assuming ORM nullability propagates.
    source = ast.parse((ROOT/'app/routers/attachment.py').read_text())
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'list_attachments')
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'join' for n in ast.walk(fn))
    assert not any(isinstance(n, ast.Attribute) and n.attr == 'outerjoin' for n in ast.walk(fn))


def test_real_attachment_list_projection_omits_private_provenance(project_http):
    h = project_http
    class Expr:
        def __eq__(self, value): return self
        def desc(self): return self
    attachment_model = SimpleNamespace(doc_id=Expr(), created_at=Expr())
    document_model = SimpleNamespace(id=Expr(), workspace_id=Expr())
    doc = SimpleNamespace(id=h.uuid4(), title='trash note', deleted_at=h.datetime(2026,1,1))
    att = SimpleNamespace(id=h.uuid4(), filename='fixture.png', mime='image/png', size=13,
        owner_id=h.owner.id, created_at=h.datetime(2026,1,1))
    class Query:
        def join(self, *args): return self
        def filter(self, *args): return self
        def order_by(self, *args): return self
        def all(self): return [(att,doc)]
    fn = body_namespace('app/routers/attachment.py', ['list_attachments'], Attachment=attachment_model,
        Document=document_model, require_ws_owner=lambda *args:None)['list_attachments']
    result = fn(h.workspace.id, SimpleNamespace(query=lambda *args:Query()), h.owner)
    validate_payload('GET','/attachments/',result)
    assert result[0]['doc_id'] == str(doc.id) and result[0]['doc_in_trash'] is True
    assert 'owner_id' not in result[0] and set(result[0]) == set(response_module().SUCCESS['app.routers.attachment.list_attachments']['items']['properties'])


@pytest.mark.parametrize('kind,referenced,unknown,expected', [
    ('project',True,False,'retain'), ('project',False,True,'retain'), ('project',False,False,'delete'),
    ('ordinary',True,False,'conflict'), ('ordinary',False,True,'conflict'), ('ordinary',False,False,'delete'),
    ('mismatch',False,False,'owner-conflict')])
def test_release_plan_actual_helpers_and_private_conflict(kind, referenced, unknown, expected, project_http):
    h = project_http
    class Expr:
        def __eq__(self, value): return self
    h.module('app.models.workspace', Workspace=SimpleNamespace(user_id=Expr(), id=Expr()))
    model = SimpleNamespace(workspace_id=Expr(), id=Expr())
    att = SimpleNamespace(id=h.uuid4(), doc_id=h.uuid4(), owner_id=None if kind=='ordinary' else h.owner.id)
    class Query:
        def join(self, *args): return self
        def filter(self, *args): return self
        def scalar(self): return h.uuid4() if kind=='mismatch' else h.owner.id
    def references(db, candidates, **kwargs):
        return ({att.id} if referenced and candidates else set(), unknown if candidates else False)
    ns = body_namespace('app/services/attachment_lifecycle.py', ['plan_document_release','preflight_delete'],
        Document=model, HTTPException=h.HTTPException, referenced_candidates=references)
    db = SimpleNamespace(query=lambda *args: Query())
    if expected.endswith('conflict'):
        with pytest.raises(h.HTTPException) as exc: ns['plan_document_release'](db,[att],excluding_docs={att.doc_id})
        assert exc.value.status_code == 409
        assert exc.value.detail['code'] == ('attachment_owner_mismatch' if expected=='owner-conflict' else 'attachment_in_use' if referenced else 'attachment_reference_check_incomplete')
        for method,path in [('DELETE','/documents/{doc_id}/permanent'),('POST','/documents/trash/empty')]:
            validate_payload(method,path,{'detail':exc.value.detail},'409')
        assert set(exc.value.detail) == {'code','message'}
        assert not any(str(value) in json.dumps(exc.value.detail) for value in [att.id,att.doc_id,h.owner.id])
    else:
        assert ns['plan_document_release'](db,[att],excluding_docs={att.doc_id}) == ({att.id} if expected=='retain' else set())


def test_changed_helpers_are_linked_to_new_and_existing_operations():
    module = response_module()
    expected = {
        ('POST','/web-projects/{root_id}/renew'): ['app/services/web_project_runtime.py:renewal-detached-review','app/routers/web_project_renew_limits.py:renewal-detached-review'],
        ('PATCH','/web-project-files/{root_id}/entry'): ['app/services/web_projects.py:renewal-detached-review'],
        ('PUT','/detached-sources/{file_id}'): ['app/services/detached_sources.py:renewal-detached-review','app/services/document.py:renewal-detached-review'],
        ('DELETE','/documents/{doc_id}/permanent'): ['app/services/attachment_lifecycle.py:renewal-detached-review','app/models/attachment.py:renewal-detached-review'],
        ('GET','/attachments/{att_id}'): ['app/models/attachment.py:renewal-detached-review'],
    }
    for key, sources in expected.items():
        assert {successor(symbol) for symbol in sources} <= set(module.DECLARATIONS[key]['sources'])
        for symbol in sources:
            evidence = module.SOURCE_EVIDENCE[successor(symbol)]
            # Old whole-file review is pinned to literal historical bytes. Current
            # evidence is checked separately; matching live hash + wrong range
            # remains an active ledger failure, never treated as dormant history.
            historical = json.loads((ROOT/'app/api_response_web_projects.json').read_text())['sources'][symbol]
            body = history(historical['file'], historical['sha256'])
            assert historical['line'] == 1 and historical['end_line'] == len(body.splitlines())
            assert evidence['sha256'] == __import__('hashlib').sha256((ROOT/evidence['file']).read_bytes()).hexdigest()
            check_metadata(successor(symbol), evidence)
            assert evidence['line'] == 1 and evidence['end_line'] == len((ROOT / evidence['file']).read_text().splitlines())
