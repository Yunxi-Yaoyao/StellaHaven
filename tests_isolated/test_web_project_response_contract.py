"""Offline real-body response review; in-memory state boundaries, NOT PG/full-main.

No business module imports or live sockets. Registry completeness remains checked
against independently scanned mounts and SHA-256, never generated from results.
"""
import ast
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_api_openapi_contract import ROOT, source_shaped_app, install, static_inventory
from test_api_response_contract import response_module, body_namespace, validate_payload


OPERATIONS = {
    ('GET', '/web-projects/workspace/{workspace_id}'): 'catalog',
    ('POST', '/web-projects/import/preview'): 'preview',
    ('POST', '/web-projects/import'): 'import_project',
    ('GET', '/web-projects/{root_id}'): 'manifest',
    ('GET', '/web-projects/{root_id}/files/{file_id}'): 'source',
    ('PATCH', '/web-projects/{root_id}/files/{file_id}'): 'update_source',
    ('GET', '/web-projects/{root_id}/state'): 'state',
    ('POST', '/web-projects/{root_id}/launch'): 'launch',
    ('PUT', '/web-projects/{root_id}/state'): 'write_state',
    ('DELETE', '/web-projects/{root_id}/state'): 'reset',
    ('POST', '/web-projects/{root_id}/copy-asset'): 'copy_asset',
    ('POST', '/web-projects/{root_id}/renew'): 'renew',
}

SUCCESSOR_OPERATIONS = {
    ('GET', '/web-projects/workspace/{workspace_id}/identities'): 'web_projects.identities',
}

NEW_OPERATIONS = {
    ('PATCH', '/web-project-files/{root_id}/entry'): 'project_files.update_entry',
    ('GET', '/detached-sources'): 'detached_sources.catalog',
    ('GET', '/detached-sources/{file_id}'): 'detached_sources.read',
    ('PUT', '/detached-sources/{file_id}'): 'detached_sources.save',
}


def test_all_sixteen_exact_operations_are_reviewed_and_cookie_authenticated():
    module = response_module()
    records = {r[:2]: r for r in static_inventory()[0] if r[1].startswith(('/web-projects', '/web-project-files', '/detached-sources'))}
    expected = {**{key: 'web_projects.' + name for key, name in OPERATIONS.items()}, **NEW_OPERATIONS, **SUCCESSOR_OPERATIONS}
    assert set(records) == set(expected)
    app, _ = source_shaped_app()
    install(app)
    schema = app.openapi()
    for key, name in expected.items():
        declaration = module.DECLARATIONS.get(key)
        assert declaration is not None, key
        assert declaration['endpoint'] == 'app.routers.' + name
        assert declaration['status'] == 'reviewed'
        op = schema['paths'][key[1]][key[0].lower()]
        assert op['security'] == [{'StellaAccessCookie': []}]
        assert op['x-stella-auth-type'] == 'cookie-access'
        assert op['x-stella-elevation'] == 'none'
        assert {'200', '401', '403', '422', '503'} <= set(op['responses'])
        for response in declaration['responses'].values():
            for media in response.get('content', {}).values():
                assert not module.schema_holes(media['schema'])
                Draft202012Validator.check_schema(media['schema'])


def standalone_schema(relative):
    spec = importlib.util.spec_from_file_location('standalone_preferences_review', ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preferences_snapshot_matches_current_read_model_and_conflict_shape():
    model = standalone_schema('app/schemas/notes_preferences.py').NotesPreferencesRead
    module = response_module()
    assert module.MODELS['NotesPreferencesRead'] == model.model_json_schema()
    payload = model(revision=1, delete_action='trash', ask_before_delete=True).model_dump()
    validate_payload('GET', '/notes-preferences', payload)
    validate_payload('PATCH', '/notes-preferences', {'detail': {'code': 'notes_preferences_conflict', 'current': payload}}, '409')


def test_new_protected_folder_detail_and_origin_launch_fields_are_not_dropped():
    validate_payload('PUT', '/documents/{doc_id}', {'detail': {'code': 'protected_notes_folder', 'folder_id': 'root'}}, '409')
    validate_payload('DELETE', '/documents/{doc_id}', {'detail': {'code': 'protected_notes_folder', 'folder_id': 'root', 'message': 'protected'}}, '409')
    validate_payload('POST', '/external-modules/{mid}/launch', {
        'mode': 'isolated_proxy', 'url': 'https://module.test/__stella/bootstrap',
        'method': 'POST', 'fields': {'ticket': 'fixture'}, 'expires_in': 60,
        'source_origin': 'https://stella.test', 'target_origin': 'https://module.test', 'entry_revision': 0})
    for path in ['/.well-known/openid-configuration', '/oauth/authorize']:
        validate_payload('GET', path, {'detail': 'OIDC Host 未登记'}, '421')


@pytest.fixture
def project_http(monkeypatch):
    """Real router, parser, project/state/grant bodies; explicit memory DB/blob.

    JWT decoding, ownership pin storage, SQL locks and ordinary-document updater
    are fixture boundaries. This proves response serialization, NOT SQL/race/PG.
    """
    import io, hashlib, mimetypes, os, posixpath, re, secrets, sys, time, zipfile, zlib, unicodedata
    from contextvars import ContextVar
    from datetime import datetime
    from pathlib import PurePosixPath
    from types import ModuleType, SimpleNamespace
    from uuid import UUID, uuid4
    from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.testclient import TestClient
    from fastapi.exceptions import RequestValidationError
    from pydantic import BaseModel, ConfigDict, Field
    from app.validation_errors import validation_exception_handler

    class Column:
        def __init__(self, name): self.name = name
        def __eq__(self, value): return lambda row: getattr(row, self.name) == value
        def is_(self, value): return self == value
        def like(self, value): return lambda row: getattr(row, self.name).startswith(value.rstrip('%'))

    class Record:
        def __init__(self, **values):
            self.id = uuid4()
            self.deleted_at = None
            self.is_folder = False
            self.updated_at = datetime(2026, 1, 1)
            self.__dict__.update(values)

    def model(name):
        return type(name, (Record,), {key: Column(key) for key in ['id', 'workspace_id', 'deleted_at', 'key']})

    Document, Workspace, AppConfig, Attachment, AuthSession, User = [model(n) for n in
        ['Document', 'Workspace', 'AppConfig', 'Attachment', 'AuthSession', 'User']]

    class Query:
        def __init__(self, db, typ): self.rows = [v for (t, _), v in db.rows.items() if t is typ]
        def filter_by(self, **values):
            self.rows = [r for r in self.rows if all(getattr(r, k) == v for k, v in values.items())]
            return self
        def filter(self, *predicates):
            self.rows = [r for r in self.rows if all(p(r) for p in predicates)]
            return self
        def populate_existing(self): return self
        def with_for_update(self): return self
        def first(self): return next(iter(self.rows), None)
        def all(self): return list(self.rows)

    class DB:
        def __init__(self): self.rows = {}; self.commits = 0
        def get(self, typ, key): return self.rows.get((typ, key))
        def query(self, typ): return Query(self, typ)
        def add(self, row): self.rows[(type(row), row.key if isinstance(row, AppConfig) else row.id)] = row
        def delete(self, row): del self.rows[(type(row), row.key if isinstance(row, AppConfig) else row.id)]
        def flush(self): pass
        def commit(self): self.commits += 1
        def rollback(self): pass
        def expire_all(self): pass
        def close(self): pass

    def module(name, **attrs):
        mod = ModuleType(name); mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        if '.' in name and name.rsplit('.', 1)[0] in sys.modules:
            monkeypatch.setattr(sys.modules[name.rsplit('.', 1)[0]], name.rsplit('.', 1)[1], mod, raising=False)
        return mod

    for package in ['app.models', 'app.services', 'app.routers', 'app.schemas']:
        module(package, __path__=[])
    for name, typ in [('document', Document), ('workspace', Workspace), ('config', AppConfig), ('attachment', Attachment)]:
        module('app.models.' + name, **{typ.__name__: typ})
    module('app.models.user', AuthSession=AuthSession, User=User)
    db = DB(); owner = User(is_active=True); db.add(owner)
    workspace = Workspace(user_id=owner.id); db.add(workspace)
    session = AuthSession(user_id=owner.id, revoked=False); db.add(session)
    claims = {'uid': str(owner.id), 'sid': str(session.id)}
    module('app.services.admin_security', require_owner=lambda db, user: None)
    auth_ns = body_namespace('app/routers/auth.py', ['current_user', 'require_ws_owner', 'require_doc_owner', '_presented_session'],
        UUID=UUID, HTTPException=HTTPException, AT_COOKIE='stella_at', RT_COOKIE='stella_rt',
        read_access_token=lambda token: claims if token == 'fixture-session' else None,
        AuthSession=AuthSession, User=User, expired=lambda s: False)
    module('app.routers.auth', **{n: auth_ns[n] for n in ['current_user','require_ws_owner','require_doc_owner','_presented_session']})
    entry = standalone_schema('app/services/entry_registry.py')
    module('app.services.entry_registry', **{k: v for k, v in vars(entry).items() if not k.startswith('__')})
    entry_ns = body_namespace('app/services/access_entries.py', ['current', 'lane'],
        HTTPException=HTTPException, _snapshot=ContextVar('fixture_entry_snapshot', default=None))
    module('app.services.access_entries', current=entry_ns['current'], lane=entry_ns['lane'])
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id': 'stella', 'public': 'https://stella.test'},
        {'service_id': 'web-project-runtime', 'public': 'https://pages.test'}]))
    module('app.services.notes_tools', lock_key=lambda *args: None)
    zip_ns = body_namespace('app/services/notes_zip.py', ['decode_body','parse_archive'],
        io=io,zipfile=zipfile,posixpath=posixpath,unicodedata=unicodedata,zlib=zlib,re=re,
        PurePosixPath=PurePosixPath,HTTPException=HTTPException,
        MAX_COMPRESSED=32*1024*1024,MAX_TOTAL=128*1024*1024,MAX_FILE=25*1024*1024,
        MAX_ENTRIES=2000,MAX_DEPTH=32,MAX_PATH_BYTES=1024,MAX_NAME_BYTES=255)
    pack = body_namespace('app/services/html_note_conversion.py', ['pack'], io=io,zipfile=zipfile)['pack']
    blobs = {}
    def put(db, key, stream, mime, max_bytes):
        value = stream.read(); assert len(value) <= max_bytes; blobs[key] = value
    blob = SimpleNamespace(enabled=lambda: True, put=put,
        read_range=lambda db,key,start,length: [blobs[key][start:start+length]])
    names = [n.name for n in ast.parse((ROOT/'app/services/web_projects.py').read_text()).body if isinstance(n,ast.FunctionDef)]
    project_ns = body_namespace('app/services/web_projects.py', names,
        io=io,json=json,hashlib=hashlib,mimetypes=mimetypes,posixpath=posixpath,PurePosixPath=PurePosixPath,
        UUID=UUID,uuid4=uuid4,HTTPException=HTTPException,AppConfig=AppConfig,Document=Document,
        Workspace=Workspace,Attachment=Attachment,blob_store=blob,pack=pack,
        parse_archive=zip_ns['parse_archive'],decode_body=zip_ns['decode_body'],MAX_FILE=25*1024*1024,
        PREFIX='web-project:', DETACHED_PREFIX='web-project-source:', TEXT={'.html','.htm','.css','.js','.mjs','.json','.txt','.md','.svg','.xml','.csv'},
        lock_workspace=lambda db, wid: db.get(Workspace, wid),lock_key=lambda *args: None)
    projects = module('app.services.web_projects', **{k:v for k,v in project_ns.items() if not k.startswith('__')})
    alive = lambda db, sid: str(session.id) == sid and not session.revoked and owner.is_active
    runtime_ns = body_namespace('app/services/web_project_runtime.py', ['key','destination','deployed_grant_destination','launch','authorize','renew'],
        hashlib=hashlib,json=json,re=re,secrets=secrets,time=time,HTTPException=HTTPException,
        AppConfig=AppConfig,projects=projects,session_alive=alive,records=entry.records,
        parent_context=entry.parent_context,lock_key=lambda *args: None,TTL=900,RENEW_GRACE=300,RENEW_AFTER=840)
    runtime = module('app.services.web_project_runtime', **{k:v for k,v in runtime_ns.items() if not k.startswith('__')})
    locked = body_namespace('app/services/web_project_write_auth.py', ['authorize_locked_write'],
        HTTPException=HTTPException,AppConfig=AppConfig,AuthSession=AuthSession,User=User,runtime=runtime)
    module('app.services.web_project_write_auth', authorize_locked_write=locked['authorize_locked_write'])
    doc_schema = standalone_schema('app/schemas/document.py')
    module('app.schemas.document', DocumentUpdate=doc_schema.DocumentUpdate)
    def update_document(db, ident, data, *, source_edit=False):
        doc = db.get(Document, ident)
        if doc.updated_at != data.updated_at: raise ValueError('Conflict')
        doc.content = data.content; doc.updated_at = datetime(2026, 1, 2)
        return doc
    module('app.services.document', update_document=update_document)
    module('app.routers.document', notify_list=lambda *args: None)
    limits = standalone_schema('app/routers/web_project_limits.py')
    module('app.routers.web_project_limits', ProjectStateRoute=limits.ProjectStateRoute)
    renew_limits = standalone_schema('app/routers/web_project_renew_limits.py')
    detached_ns = body_namespace('app/services/detached_sources.py',
        ['owned', 'projection', 'catalog', 'read', 'save'], json=json, HTTPException=HTTPException,
        AppConfig=AppConfig, Document=Document, Workspace=Workspace, uid=projects.uid,
        DETACHED_PREFIX=projects.DETACHED_PREFIX, lock_workspace=projects.lock_workspace)
    detached = module('app.services.detached_sources', **{k:v for k,v in detached_ns.items() if not k.startswith('__')})
    def get_db(): return db
    def current_user(request: Request): return auth_ns['current_user'](request, db)
    ns = dict(__name__='fixture_web_project_router', UUID=UUID, APIRouter=APIRouter,Depends=Depends,
        File=File,Form=Form,UploadFile=UploadFile,Request=Request,HTTPException=HTTPException,
        BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,get_db=get_db,current_user=current_user,
        require_ws_owner=auth_ns['require_ws_owner'],require_doc_owner=auth_ns['require_doc_owner'],
        service=projects,ProjectRuntimeRoute=renew_limits.ProjectRuntimeRoute)
    tree=ast.parse((ROOT/'app/routers/web_projects.py').read_text())
    tree.body=[n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    exec(compile(tree,'app/routers/web_projects.py','exec'),ns)
    app=FastAPI();app.add_exception_handler(RequestValidationError,validation_exception_handler);app.include_router(ns['router'])
    for filename, bindings in [('project_files', {'web_projects': projects}), ('detached_sources', {'detached_sources': detached, 'datetime': datetime})]:
        extra_ns = dict(ns, **bindings)
        extra_tree = ast.parse((ROOT / ('app/routers/' + filename + '.py')).read_text())
        extra_tree.body = [n for n in extra_tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        exec(compile(extra_tree, 'app/routers/' + filename + '.py', 'exec'), extra_ns)
        app.include_router(extra_ns['router'])
    client=TestClient(app,base_url='https://stella.test');client.cookies.set('stella_at','fixture-session')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('index.html','<!doctype html><script src="js/app.js"></script>')
        z.writestr('js/app.js','localStorage.setItem("score","1")')
        z.writestr('image.png',b'\x89PNG\r\nfixture')
    receipts=[]
    declarations=response_module().DECLARATIONS
    validators={(method,path,code):Draft202012Validator(response['content']['application/json']['schema'])
                for (method,path),declaration in declarations.items() if (method,path) in (OPERATIONS | NEW_OPERATIONS | SUCCESSOR_OPERATIONS)
                for code,response in declaration['responses'].items() if 'content' in response}
    def call(method, template, *, status=200, path=None, **kwargs):
        response=client.request(method,path or template,**kwargs)
        assert response.status_code==status,(method,template,response.status_code,response.text)
        body=response.json();validators[(method,template,str(status))].validate(body)
        receipts.append((method,template,status,body));return body
    def imported():
        ident=str(uuid4())
        args=dict(data={'workspace_id':str(workspace.id),'import_id':ident,'entry':'index.html'},
                  files={'file':('fixture.zip',archive.getvalue(),'application/zip')})
        result=call('POST','/web-projects/import',**args)
        return result,args
    yield SimpleNamespace(**locals())
    client.close()


def test_real_http_all_twelve_project_json_responses_and_replays(project_http, record_property):
    h=project_http
    h.call('POST','/web-projects/import/preview',data={'workspace_id':str(h.workspace.id)},
        files={'file':('fixture.zip',h.archive.getvalue(),'application/zip')})
    imported,args=h.imported(); root=imported['id']; assert imported['reused'] is False
    replay=h.call('POST','/web-projects/import',**args);assert replay==dict(imported,reused=True)
    base='/web-projects/'+root
    catalog=h.call('GET','/web-projects/workspace/{workspace_id}',path='/web-projects/workspace/'+str(h.workspace.id))
    manifest=h.call('GET','/web-projects/{root_id}',path=base);assert catalog==[manifest]
    source_template='/web-projects/{root_id}/files/{file_id}'
    for item in manifest['files']:
        source=h.call('GET',source_template,path=base+'/files/'+item['id'])
        assert (source['content'] is None)==(item['kind']=='binary')
        if item['kind']=='text':
            h.call('PATCH',source_template,path=base+'/files/'+item['id'],json={'updated_at':item['updated_at'],'content':source['content']+'\n'})
    state=h.call('GET','/web-projects/{root_id}/state',path=base+'/state')
    assert state=={'revision':0,'epoch':0,'data':{}}
    launched=h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',headers={'Origin':'https://stella.test'})
    assert launched['state']==state and launched['target_origin']=='https://pages.test'
    renewed=h.call('POST','/web-projects/{root_id}/renew',path=base+'/renew',headers={'Origin':'https://stella.test'},
        json={'capability':launched['capability'],'epoch':state['epoch']})
    assert renewed == dict(capability=launched['capability'], epoch=0, expires_in=900, renew_after=840)
    payload=dict(state,write_id=str(h.uuid4()),capability=launched['capability']);payload['data']={'score':'2'}
    saved=h.call('PUT','/web-projects/{root_id}/state',path=base+'/state',json=payload,headers={'Origin':'https://stella.test'})
    assert saved=={'revision':1,'epoch':0,'data':{'score':'2'}}
    assert h.call('PUT','/web-projects/{root_id}/state',path=base+'/state',json=payload,headers={'Origin':'https://stella.test'})==saved
    assert h.call('GET','/web-projects/{root_id}/state',path=base+'/state')==saved
    target=h.Document(workspace_id=h.workspace.id,parent_id=None,title='target',content='');h.db.add(target)
    copy={'target_doc_id':str(target.id),'request_id':str(h.uuid4()),'path':'image.png'}
    copied=h.call('POST','/web-projects/{root_id}/copy-asset',path=base+'/copy-asset',json=copy)
    assert h.call('POST','/web-projects/{root_id}/copy-asset',path=base+'/copy-asset',json=copy)==copied
    assert h.blobs['attachments/'+copied['id']]==b'\x89PNG\r\nfixture'
    assert h.db.get(h.Attachment, h.UUID(copied['id'])).owner_id is None
    reset=h.call('DELETE','/web-projects/{root_id}/state',path=base+'/state')
    assert reset=={'revision':2,'epoch':1,'data':{}}
    assert set((m,p) for m,p,s,_ in h.receipts if s==200)==set(OPERATIONS)
    record_property('real_body_http_responses',json.dumps(h.receipts,ensure_ascii=False))


def test_real_http_project_errors_auth_and_state_fences(project_http, record_property):
    h=project_http;imported,args=h.imported();root=imported['id'];base='/web-projects/'+root
    manifest=h.call('GET','/web-projects/{root_id}',path=base)
    text=next(f for f in manifest['files'] if f['kind']=='text');binary=next(f for f in manifest['files'] if f['kind']=='binary')
    for file,stamp,status in [(text,'bad-version',422),(text,'2000-01-01T00:00:00',409),(binary,binary['updated_at'],409)]:
        h.call('PATCH','/web-projects/{root_id}/files/{file_id}',path=base+'/files/'+file['id'],status=status,json={'updated_at':stamp,'content':'x'})
    h.call('GET','/web-projects/{root_id}/files/{file_id}',path=base+'/files/'+str(h.uuid4()),status=404)
    h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',status=403)
    h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',headers={'Origin':'https://evil.test'},status=403)
    launched=h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',headers={'Origin':'https://stella.test'})
    payload=dict(revision=0,epoch=0,write_id=str(h.uuid4()),capability=launched['capability'],data={'score':'3'})
    state_path='/web-projects/{root_id}/state';origin={'Origin':'https://stella.test'}
    h.call('PUT',state_path,path=base+'/state',json=payload,headers=origin)
    h.call('PUT',state_path,path=base+'/state',json=dict(payload,data={'score':'4'}),headers=origin,status=409)
    h.call('PUT',state_path,path=base+'/state',json=dict(payload,write_id=str(h.uuid4())),headers=origin,status=409)
    h.call('PUT',state_path,path=base+'/state',json=dict(payload,data={'secret-user-key':4}),headers=origin,status=422)
    h.call('PUT',state_path,path=base+'/state',json=dict(payload,revision=True),headers=origin,status=422)
    h.call('PUT',state_path,path=base+'/state',json=dict(payload,data={'large':'x'*(1024*1024)}),headers=origin,status=413)
    h.call('PUT',state_path,path=base+'/state',json=dict(payload,capability='x'*43),headers=origin,status=403)
    h.call('PUT',state_path,path=base+'/state',json=payload,headers={'Origin':'https://evil.test'},status=403)
    h.call('DELETE',state_path,path=base+'/state')
    h.call('PUT',state_path,path=base+'/state',json=payload,headers=origin,status=403)
    # Owner mismatch and deletion never return private state or manifest.
    foreign=h.User(is_active=True);h.db.add(foreign);old=h.workspace.user_id;h.workspace.user_id=foreign.id
    h.call('GET','/web-projects/{root_id}',path=base,status=404)
    h.call('GET',state_path,path=base+'/state',status=404);h.workspace.user_id=old
    h.db.get(h.Document,h.UUID(root)).deleted_at=h.datetime(2026,1,2)
    h.call('GET','/web-projects/{root_id}',path=base,status=404)
    h.client.cookies.clear()
    for method,template in OPERATIONS | NEW_OPERATIONS | SUCCESSOR_OPERATIONS:
        path=template.replace('{root_id}',root).replace('{file_id}',text['id']).replace('{workspace_id}',str(h.workspace.id))
        h.call(method,template,path=path,status=401)
    # malformed path with an authenticated owner uses shared loc/type/msg 422.
    h.client.cookies.set('stella_at','fixture-session')
    h.call('GET','/web-projects/{root_id}',path='/web-projects/not-a-uuid',status=422)
    record_property('real_body_error_responses',json.dumps(h.receipts,ensure_ascii=False))


def test_real_http_import_failure_variants_and_runtime_limits(project_http, monkeypatch, record_property):
    h=project_http;preview='/web-projects/import/preview';wid=str(h.workspace.id)
    h.call('POST',preview,data={'workspace_id':wid},files={'file':('bad.zip',b'not zip')},status=400)
    h.call('POST',preview,data={'workspace_id':wid},files={'file':('bad.pdf',b'pdf')},status=415)
    h.blob.enabled=lambda:False
    h.call('POST',preview,data={'workspace_id':wid},files={'file':('a.html',b'<p>x</p>')},status=409)
    h.blob.enabled=lambda:True
    multiple=h.io.BytesIO()
    with h.zipfile.ZipFile(multiple,'w') as z:
        z.writestr('one.htm','one');z.writestr('two.html','two')
    output=h.call('POST',preview,data={'workspace_id':wid},files={'file':('two.zip',multiple.getvalue())})
    assert output['suggested_entry'] is None and len(output['entries'])==2
    traversal=h.io.BytesIO()
    with h.zipfile.ZipFile(traversal,'w') as z:z.writestr('../index.html','bad')
    h.call('POST',preview,data={'workspace_id':wid},files={'file':('bad.zip',traversal.getvalue())},status=400)
    no_html=h.io.BytesIO()
    with h.zipfile.ZipFile(no_html,'w') as z:z.writestr('style.css','body{}')
    h.call('POST',preview,data={'workspace_id':wid},files={'file':('none.zip',no_html.getvalue())},status=400)
    oversized=h.io.BytesIO()
    with h.zipfile.ZipFile(oversized,'w',compression=h.zipfile.ZIP_DEFLATED) as z:z.writestr('index.html','x'*100000)
    h.call('POST',preview,data={'workspace_id':wid},files={'file':('bomb.zip',oversized.getvalue())},status=413)
    imported,args=h.imported();root=imported['id'];base='/web-projects/'+root
    h.call('POST','/web-projects/import',files=args['files'],data=dict(args['data'],entry='missing.html'),status=400)
    h.call('POST','/web-projects/import',files={'file':('different.html',b'<p>new</p>')},
        data=dict(args['data'],entry='different.html'),status=409)
    manifest=h.call('GET','/web-projects/{root_id}',path=base)
    entry_doc=h.db.get(h.Document,h.UUID(next(f['id'] for f in manifest['files'] if f['path']=='index.html')))
    entry_doc.deleted_at=h.datetime(2026,1,2)
    assert h.call('GET','/web-projects/{root_id}',path=base)['entry'] is None
    origin={'Origin':'https://stella.test'}
    h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',headers=origin,status=409)
    entry_doc.deleted_at=None
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':'https://stella.test'}]))
    h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',headers=origin,status=503)
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([
        {'service_id':'stella','public':'https://stella.test'},
        {'service_id':'web-project-runtime','public':'https://pages.test'}]))
    for n in range(512):
        h.db.add(h.AppConfig(key='wp-grant:fixture-'+str(n),value=json.dumps({'expires':h.time.time()+900,'sid':'other','root':'other'})))
    h.call('POST','/web-projects/{root_id}/launch',path=base+'/launch',headers=origin,status=429)
    # Real APIRoute wire boundary acts before JSON parsing, without a declared length.
    h.call('PUT','/web-projects/{root_id}/state',path=base+'/state',headers={'content-type':'application/json'},
        content=(b'x'*1024 for _ in range(6200)),status=413)
    h.session.revoked=True
    h.call('GET','/web-projects/{root_id}/state',path=base+'/state',status=401)
    record_property('real_body_limit_responses',json.dumps(h.receipts,ensure_ascii=False))


def test_reviewed_shared_drift_uses_actual_helper_outputs(project_http):
    h=project_http
    # Real protected-folder business error; no hand-built invented envelope.
    guard=body_namespace('app/services/notes_templates.py',['guard_protected'],
        protected_ids=lambda db,wid:{h.workspace.id},HTTPException=h.HTTPException)['guard_protected']
    with pytest.raises(h.HTTPException) as exc:guard(h.db,[h.SimpleNamespace(id=h.workspace.id,workspace_id=h.workspace.id)])
    assert exc.value.status_code==409
    validate_payload('DELETE','/documents/{doc_id}',{'detail':exc.value.detail},'409')
    resolver=body_namespace('app/services/oidc.py',['resolve_issuer'],ALLOWED_HOSTS={'stella.test':'https://stella.test'},os=h.os, HTTPException=h.HTTPException)['resolve_issuer']
    assert resolver('stella.test')=='https://stella.test'
    with pytest.raises(h.HTTPException) as exc:resolver('unregistered.test')
    assert exc.value.status_code==421
    for path in ['/.well-known/openid-configuration','/oauth/authorize']:
        validate_payload('GET',path,{'detail':exc.value.detail},'421')
    from contextlib import contextmanager
    config={'tickets':{},'grants':{}}
    @contextmanager
    def edit(db):yield config
    issue_ns=body_namespace('app/services/integrations_sessions.py',['digest','prune','issue'],
        hashlib=h.hashlib,time=h.time,secrets=h.secrets,HTTPException=h.HTTPException,
        session_alive=lambda db,sid:True,store=h.SimpleNamespace(edit=edit),TICKET_SECONDS=30)
    h.module('app.services.integrations_sessions',issue=issue_ns['issue'])
    module={'id':'external-fixture','enabled':True,'mode':'isolated_proxy','origin':'https://module.test',
        'browser_url':'https://module.test/path','adapter':'generic'}
    fn=body_namespace('app/routers/integrations.py',['launch'],
        service=h.SimpleNamespace(get_module=lambda db,mid:module),HTTPException=h.HTTPException)['launch']
    from fastapi import Response, Request
    request=Request({'type':'http','scheme':'https','server':('stella.test',443),'path':'/',
        'headers':[(b'host',b'stella.test'),(b'origin',b'https://stella.test'),(b'cookie',b'stella_at=fixture-session')]})
    result=fn(module['id'],request,Response(),h.owner,h.db)
    assert result['source_origin']=='https://stella.test' and result['target_origin']=='https://module.test'
    validate_payload('POST','/external-modules/{mid}/launch',result)
    module['mode']='iframe'
    result=fn(module['id'],request,Response(),h.owner,h.db)
    assert result['target_origin']=='https://module.test' and result['method']=='GET'
    validate_payload('POST','/external-modules/{mid}/launch',result)


def test_source_gate_rejects_reviewed_web_project_helper_drift(tmp_path):
    module=response_module()
    from copy import deepcopy
    row=next(r for r in module.INVENTORY if r['endpoint']=='app.routers.web_projects.write_state')
    # Provide unchanged files via symlinks except one real changed helper copy.
    for evidence in module.SOURCE_EVIDENCE.values():
        dest=tmp_path/evidence['file']
        if dest.exists():continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.symlink_to(ROOT/evidence['file'])
    changed=tmp_path/'app/services/web_project_write_auth.py'
    changed.unlink();changed.write_text((ROOT/'app/services/web_project_write_auth.py').read_text()+'\n# synthetic unreviewed change\n')
    errors=module.validate_response_sources(tmp_path,static_inventory()[0])
    assert errors==['source drift or missing source: app/services/web_project_write_auth.py']
    assert 'app/services/web_project_write_auth.py:web-project-review' in row['sources']


def test_closed_project_schemas_reject_payload_drift():
    module=response_module()
    for key in OPERATIONS:
        schema=module.DECLARATIONS[key]['responses']['200']['content']['application/json']['schema']
        assert not Draft202012Validator(schema).is_valid({'unexpected':'unmodeled response'})
    state=Draft202012Validator(module.PROJECT_STATE)
    for payload in [dict(revision=True,epoch=0,data={}),dict(revision=0,epoch=-1,data={}),
                    dict(revision=0,epoch=0,data={'x':1}),dict(revision=0,epoch=0,data={},digest='internal')]:
        assert not state.is_valid(payload)
    item=dict(id='id',path='image.png',kind='binary',mime='image/png',updated_at='raw-cas')
    assert not Draft202012Validator(module.PROJECT_SOURCE).is_valid(dict(item,content='wrong',url=None))
