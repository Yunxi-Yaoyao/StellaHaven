"""Offline response declarations; no production config, main or database imports."""
import ast
import importlib.util
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, install, source_shaped_app, static_inventory


def response_module():
    path = ROOT / 'app/api_response_contracts.py'
    assert path.exists(), 'Missing reviewed response contract declarations'
    spec = importlib.util.spec_from_file_location('response_contract_under_test', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Fresh source and fresh module every call; only equivalent plain-container
    # cloning uses a native implementation during this source-only test load.
    from evidence_graph_copy import contract_copy_dependency
    with contract_copy_dependency():
        spec.loader.exec_module(module)
    return module


def test_attachment_upload_declares_actual_three_fields_not_orm_metadata():
    module = response_module()
    op = {}
    module.decorate_response(op, 'POST', '/attachments/{doc_id}', 'app.routers.attachment.upload')
    schema = op['responses']['200']['content']['application/json']['schema']
    Draft202012Validator(schema).validate({'id': 'id', 'url': '/attachments/id', 'filename': 'x.png'})
    assert set(schema['properties']) == {'id', 'url', 'filename'}
    assert set(schema['required']) == {'id', 'url', 'filename'}
    with pytest.raises(Exception):
        Draft202012Validator(schema).validate({'id': 'id', 'url': '/attachments/id'})


def test_response_inventory_gate_fails_new_authenticated_endpoint():
    from fastapi import Depends
    from test_api_openapi_contract import source_dependency, Request, Response
    app, records = source_shaped_app()
    contract = install(app)
    schema = app.openapi()
    for m, p, _, _ in records:
        op = schema['paths'][p][m.lower()]
        assert op.get('x-stella-contract-status') in {'reviewed', 'incomplete', 'passthrough'}, (m, p)
        if op['x-stella-contract-status'] == 'incomplete':
            assert op['x-stella-contract-reason']
    ns = dict(Depends=Depends, Request=Request, Response=Response, get_db=lambda: None)
    current = source_dependency('app.routers.auth', 'current_user', ns)
    app.get('/future-authenticated', dependencies=[Depends(current)])(lambda: {'value': 1})
    with pytest.raises(contract.ContractError, match='future-authenticated.*response'):
        contract.validate_contract(app)


def test_notes_media_and_retired_routes_have_no_fake_json_success():
    app, _ = source_shaped_app()
    install(app)
    paths = app.openapi()['paths']
    for path in ['/attachments/{att_id}', '/assets/homebg/{filename}', '/assets/avatars/{filename}']:
        assert '*/*' in paths[path]['get']['responses']['200']['content']
        for response in paths[path]['head']['responses'].values():
            assert 'content' not in response
    assert 'content' not in paths['/documents/{doc_id}']['delete']['responses']['204']
    assert set(paths['/auth/invites']['get']['responses']) == {'410'}
    assert '307' in paths['/gallery/connect']['get']['responses']
    assert '200' not in paths['/gallery/connect']['get']['responses']
    assert paths['/drive/openlist/{path}']['get']['x-stella-contract-status'] == 'passthrough'


def body_namespace(relative, names, *, source_text=None, **namespace):
    """Execute real selected bodies, not module imports or production startup.

    Only annotations/decorators/dependency defaults are removed. External state
    boundaries are explicit test fixtures; these are body-level contract proofs.
    """
    import copy
    tree = ast.parse(source_text if source_text is not None else (ROOT / relative).read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            node.returns = None
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                arg.annotation = None
            node.args.defaults = [ast.Constant(None) if isinstance(d, ast.Call) and ast.unparse(d.func) in {'Depends', 'Query', 'Header', 'File', 'Form'} else d for d in node.args.defaults]
            nodes.append(node)
    assert len(nodes) == len(names), (relative, names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), relative, 'exec'), namespace)
    return namespace


def validate_payload(method, path, payload, code='200'):
    from fastapi.encoders import jsonable_encoder
    declaration = response_module().DECLARATIONS[(method, path)]
    schema = declaration['responses'][code]['content']['application/json']['schema']
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(jsonable_encoder(payload))


def test_real_client_projection_accepts_iso_last_used_not_number():
    ns = body_namespace('app/services/oidc.py', ['_public_client'], SUPPORTED_SCOPES=['openid'])
    payload = ns['_public_client']('test-client', {'last_used_at': '2026-01-01T00:00:00+00:00'})
    validate_payload('GET', '/auth/provider/clients/test-client'.replace('test-client', '{client_id}'), payload)


def test_incomplete_contract_is_not_claimed_complete_by_gate(monkeypatch):
    import copy
    from app import api_response_contracts as module
    key = ('GET', '/alerts/v2/rules')
    incomplete = copy.deepcopy(module.DECLARATIONS[key])
    incomplete.update(status='incomplete', reason='synthetic missing review')
    monkeypatch.setitem(module.DECLARATIONS, key, incomplete)
    app, _ = source_shaped_app()
    contract = install(app)
    with pytest.raises(contract.ContractError, match='incomplete response contract'):
        contract.validate_contract(app, require_complete_responses=True)


def test_reviewed_json_contracts_have_no_empty_shapes_or_untyped_dicts():
    module = response_module()
    for key, entry in module.DECLARATIONS.items():
        if entry['status'] != 'reviewed':
            continue
        for code, response in entry['responses'].items():
            for media, content in response.get('content', {}).items():
                schema = content['schema']
                assert not module.schema_holes(schema), (key, code, module.schema_holes(schema))
                Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize('mode', ['local', 'postgres-boundary'])
def test_real_attachment_upload_body_and_replay(mode, tmp_path, monkeypatch):
    import asyncio, io, json, hashlib
    from types import SimpleNamespace, ModuleType
    from uuid import UUID, uuid4
    from fastapi import HTTPException, UploadFile
    from starlette.concurrency import run_in_threadpool
    user = SimpleNamespace(id=uuid4())
    doc = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), deleted_at=None)
    class Record:
        key = None
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = kwargs.get('id', uuid4())
    class DB:
        receipt = None
        attachment = None
        def get(self, typ, id_):
            if typ == 'Document': return doc
            if typ == 'Workspace': return SimpleNamespace(user_id=user.id)
            return self.attachment
        def query(self, *args): return self
        def filter(self, *args): return self
        def populate_existing(self): return self
        def first(self): return self.receipt
        def add(self, record):
            if hasattr(record, 'key'): self.receipt = record
            else: self.attachment = record
        def flush(self): pass
        def commit(self): pass
        def rollback(self): pass
    class Attachment:
        def __init__(self, **kwargs): self.__dict__.update(kwargs); self.id = uuid4()
    db = DB()
    stored = {}
    def publish(root, key, payload):
        (root / str(key)).write_bytes(payload)
    blob = SimpleNamespace(enabled=lambda: mode != 'local', put=lambda db,key,stream,mime,cap: stored.update({key: stream.read()}))
    modules = {
        'app.models.workspace': {'Workspace': 'Workspace'},
        'app.services.notes_lifecycle': {'lock_document': lambda db,id_: doc},
        'app.services.notes_tools': {'lock_key': lambda *args: None},
        'app.services.attachment_files': {'publish': publish},
    }
    for name, attrs in modules.items():
        module = ModuleType(name); module.__dict__.update(attrs); monkeypatch.setitem(sys.modules, name, module)
    ns = body_namespace('app/routers/attachment.py', ['upload'], UUID=UUID, HTTPException=HTTPException,
        require_doc_owner=lambda *args: None, Document='Document', Attachment=Attachment, AppConfig=Record,
        MAX_SIZE=1024, run_in_threadpool=run_in_threadpool, blob_store=blob, STORAGE=tmp_path,
        hashlib=hashlib, json=json)
    results=[]
    for _ in range(2):
        file=UploadFile(filename='fixture.txt', file=io.BytesIO(b'attachment-fixture'))
        results.append(asyncio.run(ns['upload'](doc.id, file, db, user, 'stable-key')))
        validate_payload('POST', '/attachments/{doc_id}', results[-1])
    assert results[0] == results[1]
    assert (stored if mode != 'local' else list(tmp_path.iterdir()))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ns['upload'](doc.id, UploadFile(filename='changed.txt',file=io.BytesIO(b'changed')),db,user,'stable-key'))
    assert exc.value.status_code == 409
    validate_payload('POST', '/attachments/{doc_id}', {'detail':exc.value.detail}, '409')


def test_real_zip_preview_and_failure_payloads():
    import io, zipfile, posixpath, unicodedata, zlib, re
    from pathlib import PurePosixPath
    from urllib.parse import unquote, urlsplit
    from fastapi import HTTPException
    # Pure Markdown parser module has no database/config side effects.
    import importlib.util
    spec=importlib.util.spec_from_file_location('fixture_markdown_links',ROOT/'app/services/markdown_links.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    ns=body_namespace('app/services/notes_zip.py',['decode_body','parse_archive','preview_archive'],
        io=io,zipfile=zipfile,posixpath=posixpath,unicodedata=unicodedata,zlib=zlib,re=re,
        PurePosixPath=PurePosixPath,unquote=unquote,urlsplit=urlsplit,HTTPException=HTTPException,
        rewrite_markdown=mod.rewrite_markdown,MAX_COMPRESSED=32768,MAX_TOTAL=131072,MAX_FILE=32768,
        MAX_ENTRIES=2000,MAX_DEPTH=32,MAX_PATH_BYTES=1024,MAX_NAME_BYTES=255)
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('folder/README.md','[missing](absent.md)')
        z.writestr('folder/a.md','hello')
        z.writestr('folder/photo.png',b'bytes')
    output=ns['preview_archive'](stream.getvalue())
    validate_payload('POST','/documents/import/zip/preview',output)
    assert output['warnings'] and {e['kind'] for e in output['entries']} == {'directory','document','attachment'}
    with pytest.raises(HTTPException) as exc:ns['preview_archive'](b'not zip')
    validate_payload('POST','/documents/import/zip/preview',{'detail':exc.value.detail},str(exc.value.status_code))


def test_real_document_put_serializes_orm_fields_without_filtering():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import UUID, uuid4
    from sqlalchemy import ForeignKey, Boolean, DateTime, Text, func, FetchedValue
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from fastapi import HTTPException, FastAPI
    from fastapi.testclient import TestClient
    class Base(DeclarativeBase): pass
    source=ast.parse((ROOT/'app/models/document.py').read_text())
    node=next(n for n in source.body if isinstance(n,ast.ClassDef))
    namespace=dict(Base=Base,Mapped=Mapped,mapped_column=mapped_column,UUID=UUID,uuid4=uuid4,
        datetime=datetime,ForeignKey=ForeignKey,Boolean=Boolean,DateTime=DateTime,Text=Text,JSONB=JSONB,func=func,FetchedValue=FetchedValue)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'app/models/document.py','exec'),namespace)
    now=datetime(2026,1,1)
    observed=datetime(2026,1,2,tzinfo=timezone.utc)
    doc=namespace['Document'](id=uuid4(),title='a',file_path='a.md',content='body',deleted_at=None,
        frontmatter={'nested':[True,{'n':1}]},is_folder=False,visibility='private',is_pinned=False,
        is_favorite=False,status='published',word_count=1,content_hash='hash',created_at=now,updated_at=now,saved_event_at=observed,
        last_viewed_at=None,workspace_id=uuid4(),parent_id=None,draft_content='retained-draft',draft_updated_at=now,draft_device='test')
    ns=body_namespace('app/routers/document.py',['update_one'],HTTPException=HTTPException,
        require_doc_owner=lambda *args:None,update_document=lambda *args:doc,notify_sync=lambda *args:None,notify_list=lambda *args:None)
    request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),headers={})
    app=FastAPI()
    @app.put('/documents/{doc_id}')
    def endpoint(doc_id:str):return ns['update_one'](doc_id,None,request,None,None)
    endpoint.__module__='app.routers.document';endpoint.__qualname__='update_one'
    before=TestClient(app).put('/documents/id').json()
    install(app)
    after=TestClient(app).put('/documents/id').json()
    assert before == after and after['draft_content']=='retained-draft'
    assert 'has_draft' not in after and 'saved_event_at' not in after
    assert after['updated_at']==now.isoformat()
    assert after['updated_at_display']==observed.isoformat()
    validate_payload('PUT','/documents/{doc_id}',after)


def test_real_auth_profile_and_security_modes():
    from datetime import datetime,timezone,timedelta
    from types import SimpleNamespace
    ns=body_namespace('app/routers/auth.py',['_user_out','me'])
    user=SimpleNamespace(id='owner',username='owner',display_name='Owner',is_admin=True,avatar_url='',home_bg='',email='',email_verified=False)
    validate_payload('GET','/auth/me',ns['me'](user))
    sec=body_namespace('app/services/admin_security.py',['security_status'],require_admin=lambda db,session:None)
    for enabled,password,grant in [(True,'',{}),(False,'hash',{}),(True,'hash',{'version':1,'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()})]:
        result=sec['security_status'](None,SimpleNamespace(id='s'),{'enabled':enabled,'password_hash':password,'grants':{'s':grant},'version':1})
        validate_payload('GET','/auth/security',result)


@pytest.mark.parametrize('sent', [True,False])
def test_real_mail_send_success_branches(sent,monkeypatch):
    from types import ModuleType
    from fastapi import HTTPException
    for name,attrs in {
        'app.routers.admin_email':{'_load':lambda:{'enabled':True,'host':'fixture','username':'fixture','password':'fixture'},'_send':lambda *args:None},
        'app.services.email_attempts':{'issue_code':lambda *args,**kwargs:'fixture-code' if sent else None},
    }.items():
        mod=ModuleType(name);mod.__dict__.update(attrs);monkeypatch.setitem(sys.modules,name,mod)
    ns=body_namespace('app/routers/auth.py',['_send_purpose_code'],HTTPException=HTTPException,CODE_MINUTES=10,_mail_for=lambda *args:('subject','html'))
    result=ns['_send_purpose_code'](None,'fixture@example.test','login')
    validate_payload('POST','/auth/login-code/send',result)
    assert ('already_sent' in result) == (not sent)


def test_real_gallery_connection_and_website_failure_projection():
    from types import SimpleNamespace
    from urllib.parse import urlsplit
    class Config:
        token='fixture'
        def model_dump(self, **kwargs):
            return dict(browser_url='https://example.test',upstream_url='',alternate_browser_url='',use_proxy=False,auth_mode='manual')
    external=body_namespace('app/services/external_services.py',['masked'])
    validate_payload('GET','/gallery/connection',external['masked'](Config()))
    check=body_namespace('app/services/website_check.py',['failure_result'],urlsplit=urlsplit,frame_help=lambda *args:None)
    incoming=SimpleNamespace(open_behavior='external',custom_enabled=False)
    for blocked in [True,False]:
        value=check['failure_result']('https://example.test',incoming,'timeout','probe stopped',blocked)
        validate_payload('POST','/website-settings/check',value)
        validate_payload('POST','/website-settings',{'detail':{'code':'website_check_failed','check':value}},'422')


def test_upstream_saved_template_operations_have_separate_exact_mapping():
    module=response_module()
    pending=module.TEMPLATE_INTEGRATION_EVIDENCE
    for key in [('GET','/website-templates'),('POST','/website-templates'),('DELETE','/website-templates/{tid}')]:
        assert key in pending
        assert pending[key]['revision']=='050100278b153983694d83cf1209a6b157fe5a82'
        assert pending[key]['sources']
    assert pending[('GET','/website-templates')]['auth']=='cookie-access'
    assert pending[('POST','/website-templates')]['elevation']=='management-policy'
    assert 'content' not in pending[('DELETE','/website-templates/{tid}')]['responses']['204']


def test_all_local_schema_references_resolve_from_openapi_document_root():
    app,_=source_shaped_app();install(app);schema=app.openapi()
    def visit(value):
        if isinstance(value,dict):
            if '$ref' in value and value['$ref'].startswith('#/'):
                target=schema
                for part in value['$ref'][2:].split('/'):
                    assert part in target, value['$ref']
                    target=target[part]
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(schema)


def test_frozen_inventory_source_gate_catches_drift_and_new_operation(tmp_path):
    module=response_module()
    records=static_inventory()[0]
    assert module.validate_response_sources(ROOT,records)==[]
    assert any('new' in error or 'unclassified' in error for error in module.validate_response_sources(ROOT,records+[('GET','/new','example.fn',frozenset())]))
    assert any('source' in error for error in module.validate_response_sources(tmp_path,records))


@pytest.mark.parametrize('damage', ['drift', 'missing'])
def test_security_source_gate_rejects_same_inventory_source_damage(tmp_path, damage):
    """A reviewed logging-only rebind must not waive future security drift."""
    import shutil
    module = response_module()
    records = static_inventory()[0]
    for relative in {source['file'] for source in module.SOURCE_EVIDENCE.values()}:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    assert module.validate_response_sources(tmp_path, records) == []
    security = tmp_path / 'app/security.py'
    if damage == 'drift':
        security.write_bytes(security.read_bytes() + b'\n# synthetic unreviewed source drift\n')
    else:
        security.unlink()
    assert module.validate_response_sources(tmp_path, records) == [
        'source drift or missing source: app/security.py']


@pytest.mark.parametrize('damage',['success','component','classification','unknown_status'])
def test_response_gate_rejects_tampered_reviewed_schema(damage):
    import copy
    app,_=source_shaped_app();contract=install(app);schema=copy.deepcopy(app.openapi())
    op=schema['paths']['/auth/me']['get']
    if damage=='success':op['responses']['200']['content']['application/json']['schema']={}
    elif damage=='component':schema['components']['schemas']['StellaHTTPError']={}
    elif damage=='classification':op['x-stella-contract-status']='incomplete'
    else:op['responses']['299']={'description':'invented response'}
    app.openapi=lambda:schema
    with pytest.raises(contract.ContractError,match='response'):
        contract.validate_contract(app)


def test_response_gate_rejects_registry_declared_empty_success(monkeypatch):
    import copy
    from app import api_response_contracts as module
    record=copy.deepcopy(module.DECLARATIONS[('GET','/auth/me')])
    record['responses']['200']['content']['application/json']['schema']={}
    monkeypatch.setitem(module.DECLARATIONS,('GET','/auth/me'),record)
    app,_=source_shaped_app();contract=install(app)
    with pytest.raises(contract.ContractError,match='unconstrained schema'):
        contract.validate_contract(app)


@pytest.mark.parametrize('change,revision', [(False,0),(True,0),(True,1)])
def test_real_preferences_default_update_and_conflict(change,revision):
    import json
    from types import SimpleNamespace
    from fastapi import HTTPException
    class Config:
        key=None
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class DB:
        row=None
        def get(self,*args):return self.row
        def query(self,*args):return self
        def filter(self,*args):return self
        def populate_existing(self):return self
        def with_for_update(self):return self
        def first(self):return self.row
        def add(self,row):self.row=row
        def commit(self):pass
        def rollback(self):pass
    # Bind fixture defaults to the real declaration; the former three-field
    # fixture predated appearance settings and masked current conflict payloads.
    tree=ast.parse((ROOT/'app/services/notes_preferences.py').read_text())
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='DEFAULT' for t in n.targets))
    defaults={}
    exec(compile(ast.Module(body=[assignment],type_ignores=[]),'preferences-defaults','exec'),defaults)
    default=defaults['DEFAULT']
    assert {'font_size','line_height','read_width','code_line_numbers','code_wrap','directory_sort','hidden_folders'} <= set(default)
    ns=body_namespace('app/services/notes_preferences.py',['_key','get_preferences','patch_preferences'],
        json=json,HTTPException=HTTPException,AppConfig=Config,lock_key=lambda *args:None,DEFAULT=default)
    db=DB()
    validate_payload('GET','/notes-preferences',ns['get_preferences'](db,'owner'))
    data=SimpleNamespace(expected_revision=revision,model_dump=lambda **kwargs:{'ask_before_delete':not change})
    if change and revision:
        with pytest.raises(HTTPException) as exc:ns['patch_preferences'](db,'owner',data)
        assert exc.value.status_code==409
        validate_payload('PATCH','/notes-preferences',{'detail':exc.value.detail},'409')
    else:
        result=ns['patch_preferences'](db,'owner',data)
        validate_payload('PATCH','/notes-preferences',result)
        assert result['revision']==int(change)


@pytest.mark.parametrize('against', [None,'other'])
def test_real_version_diff_payload(against):
    import difflib
    from types import SimpleNamespace
    from fastapi import HTTPException
    ns=body_namespace('app/services/document_version.py',['content_diff'],unified_diff=difflib.unified_diff)
    version=SimpleNamespace(id='v',doc_id='doc',content='old\n')
    other=SimpleNamespace(doc_id='doc',content='alternative\n')
    doc=SimpleNamespace(content='current\n')
    router=body_namespace('app/routers/document_version.py',['diff_version'],
        content_diff=ns['content_diff'],HTTPException=HTTPException,
        owned_version=lambda db,id_,user:(other if id_=='other' else version,doc))
    result=router['diff_version']('v',against,None,None)
    validate_payload('GET','/document-versions/{version_id}/diff',result)
    assert result['against']==against and ('alternative' if against else 'current') in result['diff']


@pytest.mark.parametrize('mode', ['local','postgres-boundary'])
def test_real_attachment_download_media_head_range_and_conditional(mode,tmp_path,monkeypatch):
    import re
    from types import ModuleType,SimpleNamespace
    from fastapi import FastAPI,Request,HTTPException
    from fastapi.responses import FileResponse
    from fastapi.testclient import TestClient
    import sqlalchemy.orm
    path=tmp_path/'a';path.write_bytes(b'abcdef')
    class Snapshot:
        def __init__(self,*args):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(sqlalchemy.orm,'Session',Snapshot)
    cache=ModuleType('app.services.blob_cache')
    cache.acquire=lambda *args:SimpleNamespace(path=path,close=lambda:None)
    cache.CachedFileResponse=lambda lease,**kwargs:FileResponse(lease.path,**kwargs)
    monkeypatch.setitem(sys.modules,cache.__name__,cache)
    blob_ns=body_namespace('app/services/blob_store.py',['response'],re=re,validate_key=lambda key:None,
        metadata=lambda *args:{'mime':'text/plain','size':6,'sha256':'a'*64},read_range=lambda *args:[b'abcdef'])
    class DB:
        def get(self,*args):return SimpleNamespace(filename='fixture.txt',mime='text/plain',doc_id='doc',owner_id=None)
        def close(self):pass
        def get_bind(self):return SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))
    ns=body_namespace('app/routers/attachment.py',['serve'],HTTPException=HTTPException,
        FileResponse=FileResponse,Attachment=object,require_doc_owner=lambda *args:None,
        STORAGE=tmp_path,blob_store=SimpleNamespace(enabled=lambda:mode!='local',response=blob_ns['response']))
    app=FastAPI()
    @app.api_route('/attachments/{att_id}',methods=['GET','HEAD'])
    def serve(att_id:str,request:Request):return ns['serve'](att_id,request,DB(),None)
    serve.__module__='app.routers.attachment';serve.__qualname__='serve'
    install(app);client=TestClient(app)
    full=client.get('/attachments/a');assert full.status_code==200 and full.content==b'abcdef'
    assert full.headers['content-type'].startswith('text/plain')
    for method in ['get','head']:
        response=getattr(client,method)('/attachments/a')
        assert str(response.status_code) in app.openapi()['paths']['/attachments/{att_id}'][method]['responses']
        if method=='head':assert response.content==b''
    ranged=client.get('/attachments/a',headers={'Range':'bytes=1-2'})
    assert ranged.status_code==206 and ranged.content==b'bc'
    if mode!='local':
        for method in ['get','head']:
            response=getattr(client,method)('/attachments/a',headers={'If-None-Match':'"'+'a'*64+'"'})
            assert response.status_code==304 and response.content==b''


@pytest.mark.parametrize('method',['get','post','put','patch','delete','head','options','trace'])
def test_static_inventory_refuses_conditional_routes_for_every_method(method,tmp_path):
    (tmp_path/'main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\nif True:\n    @app.'+method+'("/hidden")\n    def hidden(): return None\n')
    with pytest.raises(AssertionError,match='dynamic routes'):
        static_inventory(tmp_path)


def test_pinned_upstream_saved_template_real_projection_and_sources():
    import hashlib
    from api_pinned_sources import read_pinned_source
    from types import SimpleNamespace
    from typing import Literal
    from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
    from fastapi import HTTPException
    module=response_module();pending=module.TEMPLATE_INTEGRATION_EVIDENCE
    cache={}
    for record in pending.values():
        for source in record['sources']:
            key=(source['revision'],source['file'])
            if key not in cache:cache[key]=read_pinned_source(source)
            assert hashlib.sha256(cache[key]).hexdigest()==source['sha256']
    revision=next(iter(pending.values()))['revision']
    ns=dict(__name__='fixture_template_classes',BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,
        field_validator=field_validator,model_validator=model_validator,Literal=Literal,
        store=SimpleNamespace(ICONS={'globe'}),HTTPException=HTTPException)
    for rel,names in [('app/services/website_settings.py',{'CustomInput'}),('app/services/website_connection.py',{'ConnectionInput','RequestPolicy'}),('app/services/saved_website_templates.py',{'PortableDraft'})]:
        text=cache[(revision,rel)].decode()
        nodes=[n for n in ast.parse(text).body if isinstance(n,ast.ClassDef) and n.name in names]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),rel,'exec'),ns)
    functions=body_namespace('app/services/saved_website_templates.py',['portable_draft','public_record'],
        source_text=cache[(revision,'app/services/saved_website_templates.py')].decode(),**ns)
    record={'id':'user_fixture','name':'Fixture','draft':{'address':'https://must-not-export.test','connection':{'token':'not-exported'},'custom':{'css':'body{}'}}}
    payload=functions['public_record'](record)
    schema=pending[('POST','/website-templates')]['responses']['201']['content']['application/json']['schema']
    Draft202012Validator(schema).validate(payload)
    assert 'address' not in payload['draft'] and 'token' not in payload['draft']['connection']
    Draft202012Validator(pending[('GET','/website-templates')]['responses']['200']['content']['application/json']['schema']).validate([payload])


def test_new_response_schema_does_not_claim_request_redaction():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel
    class Input(BaseModel):count:int
    app=FastAPI()
    @app.post('/fixture-validation')
    def endpoint(data:Input):return None
    payload=TestClient(app).post('/fixture-validation',json={'count':'not-number'}).json()
    schema=response_module().VALIDATION_ERROR
    # Schema metadata alone does not install runtime redaction. The merged
    # main explicitly registers the real global handler, mirrored here.
    from jsonschema import ValidationError
    with pytest.raises(ValidationError): Draft202012Validator(schema).validate(payload)
    assert payload['detail'][0]['input']=='not-number'
    from fastapi.exceptions import RequestValidationError
    from app.validation_errors import validation_exception_handler
    app.add_exception_handler(RequestValidationError,validation_exception_handler)
    app.middleware_stack=None
    safe=TestClient(app).post('/fixture-validation',json={'count':'not-number'}).json()
    Draft202012Validator(schema).validate(safe)
    assert set(safe['detail'][0])=={'loc','type','msg'}


def test_pending_alerts_v2_mapping_is_source_bound_and_real_results_match():
    import json,hashlib
    from api_pinned_sources import read_pinned_source
    from types import SimpleNamespace
    from decimal import Decimal
    from fastapi import HTTPException
    path=ROOT/'app/api_response_alerts_upstream.json'
    assert path.is_file(), 'Missing separate pinned alerts-v2 mapping'
    mapping=json.loads(path.read_text())
    texts={}
    for evidence in mapping['sources']:
        raw=read_pinned_source(evidence, mapping['revision'])
        assert hashlib.sha256(raw).hexdigest()==evidence['sha256']
        texts[evidence['file']]=raw.decode()
    pure=body_namespace('app/alert_metrics.py',['result','volume_result'],source_text=texts['app/alert_metrics.py'],Decimal=Decimal)
    condition={'metric':'cpu','threshold':'50','interface':None,'direction':None,'window':{'kind':'latest'},'capacity':None}
    c=SimpleNamespace(threshold='50',metric='cpu',model_dump=lambda **kw:condition)
    rows={(r['method'],r['path']):r for r in mapping['operations']}
    preview=rows['POST','/alerts/v2/preview']['responses']['200']['content']['application/json']['schema']
    for payload in [pure['result'](c,reason='target_missing'),pure['result'](c,value=70,quality='valid'),
                    pure['volume_result'](c,20,None,None),pure['volume_result'](c,20,20,None)]:
        Draft202012Validator(preview).validate(payload)
    class IntegrityError(Exception):pass
    db=SimpleNamespace(commit=lambda:None,rollback=lambda:None)
    service=SimpleNamespace(save=lambda *a:SimpleNamespace(id=10,revision=2))
    ns=body_namespace('app/routers/alerts.py',['_save_metric'],source_text=texts['app/routers/alerts.py'],
        alert_metrics=service,IntegrityError=IntegrityError,HTTPException=HTTPException)
    payload=ns['_save_metric'](db,{},10,1)
    for method,path,code in [('POST','/alerts/v2/rules','201'),('PUT','/alerts/v2/rules/{rule_id}','200')]:
        Draft202012Validator(rows[method,path]['responses'][code]['content']['application/json']['schema']).validate(payload)
        assert rows[method,path]['elevation']=='management-policy'
    assert set(rows).issubset(response_module().DECLARATIONS)
    assert response_module().DECLARATIONS['GET','/alerts/v2/rules']['status']=='reviewed'
    assert rows['GET','/alerts/v2/rules']['status']=='incomplete'


def test_imports_never_load_production_modules_in_focused_suite():
    assert not {'main','app.config','app.database'}.intersection(sys.modules)


def test_offline_gate_cli_reports_real_inventory_and_strict_completeness(tmp_path):
    import subprocess,json
    path=ROOT/'tools/check_api_response_contracts.py'
    assert path.is_file(), 'Missing executable response coverage gate'
    result=subprocess.run([sys.executable,str(path),'--output',str(tmp_path)],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
    coverage=json.loads((tmp_path/'response-completion-coverage.json').read_text())
    assert coverage['operation_count']==len(static_inventory()[0])
    assert coverage['classification'].get('incomplete',0)==3
    assert coverage['source_and_classification_gate_passed'] is True and coverage['errors']==[]
    assert coverage['normalization_complete'] is False
    result=subprocess.run([sys.executable,str(path),'--require-complete'],cwd=ROOT,text=True,capture_output=True)
    assert result.returncode==1, result.stdout+result.stderr
    assert 'unvalidated internal JSONB' in result.stdout


@pytest.mark.parametrize('mode',['local','postgres-boundary'])
def test_real_zip_commit_result_first_and_replay_shape(mode,tmp_path,monkeypatch):
    import hashlib,json,io,mimetypes,posixpath
    from pathlib import PurePosixPath
    from urllib.parse import urlsplit,unquote
    from uuid import uuid4
    from types import SimpleNamespace,ModuleType
    from fastapi import HTTPException
    class Field:
        def __eq__(self,other):return self
        def is_(self,other):return self
    class Document:
        workspace_id=Field();deleted_at=Field()
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class Record:
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class DB:
        receipt=None
        # Success/replay shape probe captures but never uses a database bind.
        # Keep this synthetic boundary offline; PG fault paths have owning tests.
        def get_bind(self):return None
        def get(self,typ,key):return self.receipt
        def query(self,*args):return self
        def filter(self,*args):return self
        def all(self):return []
        def add(self,record):
            if hasattr(record,'key'):self.receipt=record
        def flush(self):pass
        def commit(self):pass
        def rollback(self):pass
    db=DB();owner=SimpleNamespace(id=uuid4());workspace_id=uuid4();import_id=uuid4()
    stored={}
    blob=SimpleNamespace(enabled=lambda:mode!='local',put=lambda db,key,stream,mime,cap:stored.update({key:stream.read()}))
    packages={'app.routers':{'attachment':SimpleNamespace(STORAGE=tmp_path)},'app.services':{'blob_store':blob},
        'app.services.notes_lifecycle':{'lock_workspace':lambda *args:SimpleNamespace(user_id=owner.id)},
        'app.services.notes_tools':{'lock_key':lambda *args:None},
        'app.services.attachment_files':{'publish':lambda root,key,data:(root/str(key)).write_bytes(data)}}
    for name,attrs in packages.items():
        m=ModuleType(name);m.__dict__.update(attrs);m.__path__=[];monkeypatch.setitem(sys.modules,name,m)
    entries=[{'path':'note.md','title':'note','kind':'document','parent_path':None},
             {'path':'photo.png','title':'photo','kind':'attachment','parent_path':None}]
    parsed=(entries,{'photo.png':b'bytes'},{'note.md':'hello'},{'note.md':'note.md'})
    ns=body_namespace('app/services/notes_zip.py',['commit_archive'],parse_archive=lambda *args:parsed,
        Document=Document,Attachment=Record,AppConfig=Record,DocumentLink=Record,hashlib=hashlib,json=json,
        uuid4=uuid4,mimetypes=mimetypes,io=io,posixpath=posixpath,PurePosixPath=PurePosixPath,
        urlsplit=urlsplit,unquote=unquote,HTTPException=HTTPException,MAX_FILE=1024,rewrite_markdown=lambda body,resolve:body)
    first=ns['commit_archive'](db,owner,workspace_id,None,import_id,b'archive')
    again=ns['commit_archive'](db,owner,workspace_id,None,import_id,b'archive')
    for payload in [first,again]:validate_payload('POST','/documents/import/zip',payload)
    assert first['reused'] is False and again['reused'] is True
    assert first['documents']==again['documents'] and first['attachments']==1
    assert stored if mode!='local' else list(tmp_path.iterdir())
