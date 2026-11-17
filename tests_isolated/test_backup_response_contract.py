"""Backup response review at 859cc4b; offline AST/body fixtures, NOT PG/full-main.

The owner's auth/SQL, archive workers and HA availability need owning acceptance.
These tests never import business routers, main, settings or database modules.
"""
import ast
import copy
from collections import Counter
from api_response_evidence_fixture import successor, current_handler
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from test_api_openapi_contract import ROOT, source_shaped_app, install, static_inventory
from test_api_response_contract import response_module, body_namespace, validate_payload


PREFIX = '/operations/backups'
# Pinned original operation identities; the current owner/session policy no
# longer advertises separate management elevation.
OPERATIONS = {
    ('GET', PREFIX): ('status', '200', 'none'),
    ('PATCH', PREFIX + '/config'): ('patch', '200', 'management-policy'),
    ('GET', PREFIX + '/client-preferences'): ('client_preferences', '200', 'none'),
    ('PUT', PREFIX + '/client-preferences'): ('save_client_preferences', '200', 'none'),
    ('POST', PREFIX): ('backup', '202', 'management-policy'),
    ('HEAD', PREFIX + '/{id}/download'): ('download_head', '200', 'management-policy'),
    ('GET', PREFIX + '/{id}/download'): ('download', '200', 'management-policy'),
    ('POST', PREFIX + '/{id}/verify'): ('verify', '202', 'management-policy'),
    ('POST', PREFIX + '/{id}/restore'): ('restore', '202', 'management-policy'),
    ('DELETE', PREFIX + '/{id}'): ('delete', '204', 'management-policy'),
}


MANAGEMENT_OPERATIONS = {key for key, (_, _, elevation) in OPERATIONS.items() if elevation == 'management-policy'}


def test_exact_ten_backup_operations_are_reviewed_with_real_status_and_auth():
    module = response_module()
    mounted = {row[:2]: row for row in static_inventory()[0] if row[1].startswith(PREFIX)}
    assert set(mounted) == set(OPERATIONS)
    app, _ = source_shaped_app()
    install(app)
    paths = app.openapi()['paths']
    for key, (name, status, elevation) in OPERATIONS.items():
        declaration = module.DECLARATIONS.get(key)
        assert declaration is not None, ('missing exact backup review', key)
        assert declaration['endpoint'] == 'app.routers.backups.' + name
        assert declaration['status'] == 'reviewed' and declaration['reason'] == ''
        op = paths[key[1]][key[0].lower()]
        assert op['security'] == [{'StellaAccessCookie': []}]
        assert op['x-stella-auth-type'] == 'cookie-access'
        assert op['x-stella-elevation'] == 'none'
        if key in MANAGEMENT_OPERATIONS:
            assert 'app.routers.auth.admin_user' in mounted[key][3]
        assert {code for code in op['responses'] if code.startswith(('2', '3'))} == {status}
        # Even Request-parsed owner dependencies can fail validation; no cookie
        # scheme parameter is invented, and the shared builder remains explicit.
        assert {'401', '403', '422', '503'} <= set(op['responses'])
        assert op['x-stella-contract-status'] == 'reviewed'
        for response in declaration['responses'].values():
            for media in response.get('content', {}).values():
                assert not module.schema_holes(media['schema'])
                Draft202012Validator.check_schema(media['schema'])


def backup_models():
    """Load the standalone DTO file without app.schemas package initialization."""
    spec = importlib.util.spec_from_file_location('standalone_backup_response_review', ROOT / 'app/schemas/backups.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('name', ['Config', 'Job', 'Status', 'ClientPreferences', 'LayoutPreferences'])
def test_backup_snapshots_match_exact_current_serialization_dtos(name):
    model = getattr(backup_models(), name)
    frozen = response_module().MODELS['Backup' + name]
    assert frozen == model.model_json_schema(mode='serialization')
    if name == 'Status':
        assert frozen['$defs']['Storage']['properties']['can_initialize_default']['default'] is False
    if name == 'ClientPreferences':
        assert set(frozen['properties']) == {'revision', 'appearance', 'customAppearance', 'home', 'ui'}
        assert frozen['properties']['appearance']['enum'] == ['A', 'B', 'custom']
        assert frozen['$defs']['CustomAppearance']['additionalProperties'] is False
        assert frozen['$defs']['CustomAppearance']['properties']['overrides']['maxProperties'] == 28
        assert len(frozen['$defs']['HomePreferences']['properties']) == 9
        assert len(frozen['$defs']['LayoutPreferences']['properties']) == 9
        assert frozen['$defs']['HomePreferences']['properties']['siteTitle']['maxLength'] == 120
        assert frozen['$defs']['HomePreferences']['properties']['signature']['maxLength'] == 512


def test_all_restore_real_maintenance_error_is_operation_scoped():
    from contextlib import contextmanager
    from types import SimpleNamespace
    from fastapi import HTTPException
    import shlex

    row = dict(id='record', filename='stella-all-record.zip', scope='all', sha256='a' * 64)
    def never_submit(*args, **kwargs):
        raise AssertionError('all restore must not admit a worker')
    instance = SimpleNamespace(store=lambda: SimpleNamespace(records=lambda: [row], path=Path('/owned backups')), submit=never_submit)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(backup_center=instance)))
    # Only pure exception identities/DB rollback are synthetic; restore and its
    # command builder are the actual selected source bodies, never hand-written.
    ns = body_namespace('app/routers/backups.py', ['center', 'errors', 'release', 'record_for', 'restore'],
        HTTPException=HTTPException, shlex=shlex, Busy=type('Busy', (ValueError,), {}),
        Conflict=type('Conflict', (ValueError,), {}), InvalidArchive=type('InvalidArchive', (ValueError,), {}),
        ValidationError=__import__('pydantic').ValidationError)
    ns['errors'] = contextmanager(ns['errors'])
    with pytest.raises(HTTPException) as exc:
        ns['restore']('record', backup_models().Confirmation(confirm=row['filename']), request,
                      SimpleNamespace(id='owner'), SimpleNamespace(rollback=lambda: None))
    assert exc.value.status_code == 409
    payload = {'detail': exc.value.detail}
    key = ('POST', PREFIX + '/{id}/restore')
    validate_payload(*key, payload, '409')
    assert payload['detail']['code'] == 'maintenance_required'
    assert "'/owned backups/stella-all-record.zip'" in payload['detail']['command']
    assert '--maintenance' in payload['detail']['command'] and '--sha256 ' + row['sha256'] in payload['detail']['command']
    module = response_module()
    assert not Draft202012Validator(module.HTTP_ERROR).is_valid(payload), 'do not widen global HTTP_ERROR'
    schema = module.DECLARATIONS[key]['responses']['409']['content']['application/json']['schema']
    for damaged in [dict(payload, unexpected=True), {'detail': dict(payload['detail'], code='unreviewed')},
                    {'detail': {k: v for k, v in payload['detail'].items() if k != 'command'}}]:
        assert not Draft202012Validator(schema).is_valid(damaged)
    for other, declaration in module.DECLARATIONS.items():
        if other != key and other in OPERATIONS and '409' in declaration['responses']:
            error = declaration['responses']['409']['content']['application/json']['schema']
            assert not Draft202012Validator(error).is_valid(payload), other


def test_backup_source_gate_and_each_operation_evidence_are_complete():
    module = response_module()
    assert module.validate_response_sources(ROOT, static_inventory()[0]) == []
    ledger = json.loads((ROOT / 'app/api_response_backups.json').read_text())
    assert ledger['review']['verified_parent_revision'] == 'fbc6c699840b2141b3bbf86d9c743d09fb8f51c1'
    assert {(r['method'], r['path']) for r in ledger['operations']} == set(OPERATIONS)
    for row in ledger['operations']:
        key = row['method'], row['path']
        files = {module.SOURCE_EVIDENCE[s]['file'] for s in row['sources']}
        assert {'main.py', 'app/routers/backups.py', 'app/schemas/backups.py', 'app/services/backup_center.py',
                'app/validation_errors.py', 'app/services/request_security.py', 'app/services/ha_readiness.py',
                'app/routers/auth.py', 'app/services/admin_security.py'} <= files
        if row['endpoint'].endswith(('client_preferences', 'save_client_preferences')):
            assert 'app/services/backup_preferences.py' in files
        if row['elevation'] == 'management-policy':
            assert successor('app.routers.auth.admin_user') in module.DECLARATIONS[key]['sources']
        else:
            assert 'app.routers.auth.admin_user' not in row['sources']
        op = {}
        module.decorate_response(op, *key, row['endpoint'])
        from api_response_evidence_fixture import named_reviews
        layers = named_reviews()
        expected_maps = ['app/api_response_v12_final_review.json']
        for name in ('api_response_v13_source_metadata_review.json',
                     'api_response_v14_ci167_review.json', 'api_response_v15_agent_rollout_review.json',
                     'api_response_v16_monitor_ux_review.json', 'api_response_v17_nav_files_review.json',
                      'api_response_v18_nav_files_validation_review.json',
                      'api_response_v19_unified_files_review.json',
                      'api_response_v21_refresh_timeout_review.json',
                      'api_response_v22_private_remediation_review.json',
                      'api_response_v23_final_offload_review.json'):
            if key in {(u['method'], u['path']) for u in layers[name]['operation_source_updates']}:
                expected_maps.append('app/'+name)
        expected_map = expected_maps if len(expected_maps) > 1 else expected_maps[0]
        assert op['x-stella-contract-evidence']['source-map'] == expected_map
        assert op['x-stella-contract-evidence']['handler'] == module.SOURCE_EVIDENCE[current_handler(row['endpoint'],row['endpoint'])]
        assert op['x-stella-contract-evidence']['supporting-symbols'] == module.DECLARATIONS[key]['sources']


def test_backup_source_shaped_openapi_keeps_real_inputs_and_layout_dto():
    app, records = source_shaped_app()
    install(app)
    document = app.openapi()
    bodies = {
        ('PATCH', PREFIX + '/config'): 'ConfigPatch',
        ('PUT', PREFIX + '/client-preferences'): 'ClientPreferencesWrite',
        ('POST', PREFIX): 'BackupRequest',
        ('POST', PREFIX + '/{id}/restore'): 'Confirmation',
        ('DELETE', PREFIX + '/{id}'): 'Confirmation',
    }
    for key in OPERATIONS:
        op = document['paths'][key[1]][key[0].lower()]
        assert op['tags'] == ['backups']
        if key in bodies:
            assert op['requestBody']['required'] is True
            assert op['requestBody']['content']['application/json']['schema'] == {
                '$ref': '#/components/schemas/' + bodies[key]}
        else:
            assert 'requestBody' not in op
        params = op.get('parameters', [])
        assert {(p['name'], p['in']) for p in params} == ({('id', 'path')} if '{id}' in key[1] else set())
        # Request.cookies-based auth must not be invented as a normal parameter.
        assert not any(p['in'] == 'cookie' for p in params)
    schema = document['components']['schemas']['LayoutPreferences']
    assert schema == backup_models().LayoutPreferences.model_json_schema()
    assert Counter((m,p,e) for m,p,e,_ in records) == Counter((r['method'],r['path'],r['endpoint']) for r in response_module().INVENTORY)
    assert all(n==1 for n in Counter((m,p) for m,p,_,_ in records).values())
    assert not {'main', 'app.config', 'app.database'}.intersection(sys.modules)


def test_backup_download_contract_has_zip_headers_and_no_head_or_204_body():
    module = response_module()
    path = PREFIX + '/{id}/download'
    for method in ('GET', 'HEAD'):
        op = {}
        module.decorate_response(op, method, path, 'app.routers.backups.' + ('download' if method == 'GET' else 'download_head'), document={})
        responses = op['responses']
        headers = responses['200']['headers']
        assert headers['Content-Length']['schema'] == {'type': 'integer', 'minimum': 0}
        assert headers['Cache-Control']['schema']['const'] == 'no-store'
        assert headers['X-Content-Type-Options']['schema']['const'] == 'nosniff'
        assert headers['Referrer-Policy']['schema']['const'] == 'no-referrer'
        assert headers['Content-Disposition']['schema']['type'] == 'string'
        assert headers['Content-Type']['schema']['const'] == 'application/zip'
        if method == 'GET':
            assert responses['200']['content'] == {'application/zip': {'schema': {'type': 'string', 'format': 'binary'}}}
            assert {'401', '403', '404', '421', '422', '503'} <= set(responses)
        else:
            assert all('content' not in response for response in responses.values())
        assert not {'206', '304', '416'}.intersection(responses), 'StreamingResponse does not implement ranges or ETags'
    assert 'content' not in module.DECLARATIONS['DELETE', PREFIX + '/{id}']['responses']['204']


def isolated_source(relative, namespace):
    """Keep real bodies/classes/decorators, replace only module import boundaries."""
    tree = ast.parse((ROOT / relative).read_text())
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, relative, 'exec'), namespace)
    return namespace


@pytest.fixture
def backup_http(tmp_path, monkeypatch):
    """Actual router, center/status/admission, prefs and real ZIP/file bodies.

    Cookie identity/pinned-owner checks, center SQL/locks, worker launch and HA
    checker are explicit synthetic boundaries. Preference transactions use owned
    SQLite and real file-reference guards, not PostgreSQL advisory/row locking.
    No PG, JWT, background execution or main.
    """
    import errno, fcntl, hashlib, hmac, io, logging, os, re, shlex, socket, stat, subprocess, tempfile, threading, uuid
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace, ModuleType
    from zoneinfo import ZoneInfo
    from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient
    from pydantic import ValidationError
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    from app.backup_diagnostics import BackupFailure, REASON_CODES, STAGES
    from app.validation_errors import validation_exception_handler

    models = backup_models()
    spec = importlib.util.spec_from_file_location('standalone_backup_archive_review', ROOT / 'app/services/backup_archive.py')
    assert spec is not None and spec.loader is not None
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    storage_ns = isolated_source('app/services/backup_storage.py', dict(
        __name__='fixture_backup_storage', contextmanager=contextmanager, datetime=datetime, timezone=timezone,
        fcntl=fcntl, hashlib=hashlib, hmac=hmac, json=json, os=os, Path=Path, re=re, stat=stat, uuid=uuid,
        create_archive=archive.create_archive, validate_archive=archive.validate_archive,
        hash_stream=archive.hash_stream, InvalidArchive=archive.InvalidArchive))

    class ThreadBoundary:
        def __init__(self, **kwargs): self.kwargs = kwargs; self.started = False
        def start(self): self.started = True  # No worker body or background task.
        def join(self, *args): pass
        def is_alive(self): return False

    center_ns = isolated_source('app/services/backup_center.py', dict(
        __name__='fixture_backup_center', deepcopy=copy.deepcopy, datetime=datetime, timedelta=timedelta,
        timezone=timezone, errno=errno, json=json, os=os, Path=Path, socket=socket,
        logging=logging, subprocess=subprocess, tempfile=tempfile, SQLAlchemyError=SQLAlchemyError,
        BackupFailure=BackupFailure, REASON_CODES=REASON_CODES, STAGES=STAGES, InvalidArchive=archive.InvalidArchive,
        threading=SimpleNamespace(Thread=ThreadBoundary, Event=threading.Event), uuid=uuid,
        ZoneInfo=ZoneInfo, ValidationError=ValidationError, text=text,
        Config=models.Config, ConfigPatch=models.ConfigPatch,
        settings_supported=lambda: True, UnsupportedSettingsMode=type('UnsupportedSettingsMode', (ValueError,), {}),
        **{k: storage_ns[k] for k in ('BackupDirectory', 'Busy', 'directory_fd', 'ensure_private_directory')}))
    # Only errors()'s lazy import resolves here; it is the actual safe_error body.
    safe_module = ModuleType('app.services.backup_center')
    safe_module.safe_error = center_ns['safe_error']
    monkeypatch.setitem(sys.modules, safe_module.__name__, safe_module)

    class Connection:
        def __init__(self, engine): self.engine = engine
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=None):
            sql = str(statement); params = params or {}
            if sql.startswith('SELECT value FROM app_config'):
                value = self.engine.values.get(params['key'])
            elif sql.startswith('INSERT INTO app_config'):
                self.engine.values[params['key']] = params['value']; value = None
            elif 'pg_try_advisory' in sql:
                value = not self.engine.busy
            else:
                value = True  # Explicit SQL/primary/lock boundary, never sent to PG.
            return SimpleNamespace(scalar_one_or_none=lambda: value, scalar_one=lambda: value)
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    engine = SimpleNamespace(values={}, busy=False, owner_matches=True, dialect=SimpleNamespace(name='postgresql'))
    engine.connect = engine.begin = lambda: Connection(engine)
    path = tmp_path / 'owned-backups'; path.mkdir(mode=0o700)
    instance = center_ns['BackupCenter'](engine, tmp_path, key='synthetic-offline-ownership-key',
        node='fixture-node', default_directory=path, clock=lambda: datetime(2026, 10, 18, tzinfo=timezone.utc))
    store = instance.store()
    settings = store.create('settings', {'settings.json': io.BytesIO(b'{}')})
    full = store.create('all', {'database.dump': io.BytesIO(b'fixture-not-a-PG-dump')})
    # The full ZIP is integrity-only fixture data, NOT a restorable PostgreSQL dump.
    # Preferences now own a Session transaction and the shared-media reference
    # guard. Keep both real bodies; only the DB dialect/lock and storage mode
    # boundaries are adapted to a private in-memory SQLite + owned file library.
    import posixpath
    from urllib.parse import unquote, urlsplit
    from sqlalchemy import Column, String, create_engine, event
    from sqlalchemy.orm import Session, declarative_base
    from sqlalchemy.pool import StaticPool
    preference_engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base = declarative_base()
    class AppConfig(Base):
        __tablename__ = 'app_config'
        key = Column(String, primary_key=True)
        value = Column(String, nullable=False)
    Base.metadata.create_all(preference_engine)
    @event.listens_for(preference_engine, 'before_cursor_execute', retval=True)
    def sqlite_lock_boundary(conn, cursor, statement, params, context, executemany):
        if statement.startswith('SELECT pg_advisory_xact_lock('):
            return 'SELECT 1', ()  # No PG cross-process lock claim in SQLite.
        return statement.removesuffix(' FOR UPDATE'), params
    class PreferenceSession(Session):
        def __init__(self, bound):
            assert bound is engine
            super().__init__(preference_engine)
        def __exit__(self, *args):
            try:
                return super().__exit__(*args)
            finally:
                # Publish committed SQL state to the existing synthetic center
                # engine's read adapter; failed transactions publish no writes.
                with preference_engine.connect() as conn:
                    values = dict(conn.execute(text('SELECT key,value FROM app_config')).all())
                engine.values.update(values)
    homebg_dir = tmp_path/'owned-homebg'; homebg_dir.mkdir(mode=0o700)
    def boundary_module(name, **values):
        module = ModuleType(name); module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
        return module
    boundary_module('app.models.config', AppConfig=AppConfig)
    boundary_module('app.routers.homebg', HOMEBG_DIR=homebg_dir)
    # Request-origin normalization is pure and independent of app bootstrap.
    origins = body_namespace('app/services/request_security.py', ['canonical_origin', 'trusted_origins'],
                             os=os, urlsplit=urlsplit)
    reference_ns = body_namespace('app/services/homebg_references.py',
        ['local_key', 'keys', '_release_file_lock', 'lock_library', 'validate_new'],
        posixpath=posixpath, unquote=unquote, urlsplit=urlsplit, re=re, HTTPException=HTTPException,
        blob_store=SimpleNamespace(enabled=lambda: False), homebg_media=SimpleNamespace(PREFIX='/assets/homebg/'),
        canonical_origin=origins['canonical_origin'], trusted_origins=origins['trusted_origins'])
    boundary_module('app.services.homebg_references', **{name: reference_ns[name] for name in
        ('local_key', 'keys', '_release_file_lock', 'lock_library', 'validate_new')})
    pref_ns = isolated_source('app/services/backup_preferences.py', dict(
        __name__='fixture_backup_preferences', text=text, Session=PreferenceSession,
        ClientPreferences=models.ClientPreferences, ClientPreferencesWrite=models.ClientPreferencesWrite,
        Conflict=center_ns['Conflict']))
    db = Connection(engine)
    def get_db(): return db
    def current_user(request: Request):
        if request.cookies.get('stella_at') != 'synthetic-owner-session':
            raise HTTPException(401, '未登录')
        return SimpleNamespace(id='fixture-owner', is_admin=False)
    def admin_user(request: Request, user=Depends(current_user)):
        if not engine.owner_matches:
            raise HTTPException(403, '固定所有者不匹配')
        return user
    ns = dict(vars(models), __name__='app.routers.backups', APIRouter=APIRouter, Depends=Depends,
        Request=Request, Response=Response, HTTPException=HTTPException, StreamingResponse=StreamingResponse,
        Session=object, ValidationError=ValidationError, contextmanager=contextmanager, os=os, shlex=shlex,
        get_db=get_db, current_user=current_user, admin_user=admin_user,
        Conflict=center_ns['Conflict'], Busy=storage_ns['Busy'], InvalidArchive=archive.InvalidArchive,
        read_preferences=pref_ns['read_preferences'], write_preferences=pref_ns['write_preferences'])
    isolated_source('app/routers/backups.py', ns)
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(ns['router'])
    app.state.backup_center = instance
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'https://backup.test')
    security_spec = importlib.util.spec_from_file_location('fixture_main_security', ROOT / 'app/services/request_security.py')
    assert security_spec is not None and security_spec.loader is not None
    security = importlib.util.module_from_spec(security_spec); security_spec.loader.exec_module(security)
    app.add_middleware(security.MainSiteSecurityMiddleware)
    client = TestClient(app, base_url='https://backup.test')
    client.cookies.set('stella_at', 'synthetic-owner-session')
    declarations = response_module().DECLARATIONS
    validators = {(method, route, code): Draft202012Validator(response['content']['application/json']['schema'])
                  for (method, route), declaration in declarations.items() if (method, route) in OPERATIONS
                  for code, response in declaration['responses'].items() if 'application/json' in response.get('content', {})}
    receipts = []
    def call(method, route, *, status=200, record=None, **kwargs):
        url = route.replace('{id}', (record or settings)['id'])
        headers = dict(kwargs.pop('headers', {}))
        # Identity/pin is the synthetic auth boundary, never a second password.
        response = client.request(method, url, headers=headers, **kwargs)
        assert response.status_code == status, (method, route, response.status_code, response.text)
        assert str(status) in declarations[method, route]['responses']
        if method == 'HEAD' or status == 204:
            assert response.content == b''
            payload = None
        elif response.headers.get('content-type', '').startswith('application/zip'):
            payload = {'binary_bytes': len(response.content), 'sha256': hashlib.sha256(response.content).hexdigest()}
        else:
            payload = response.json()
            validators[method, route, str(status)].validate(payload)
        receipts.append((method, route, status, payload))
        return response
    try:
        yield SimpleNamespace(**locals())
    finally:
        client.close()
        preference_engine.dispose()


def test_real_http_all_ten_successes_use_exact_status_and_payload(backup_http, record_property):
    h = backup_http
    initial = h.call('GET', PREFIX).json()
    assert initial['config']['enabled'] is False and initial['job'] is None
    assert initial['storage']['can_initialize_default'] is False
    assert len(initial['records']) == 2
    prefs = h.call('GET', PREFIX + '/client-preferences').json()
    incoming = dict(expected_revision=prefs['revision'], appearance='B', home=prefs['home'],
                    ui=dict(prefs['ui'], noteEditMode='markdown', backgroundQuality='original'))
    saved = h.call('PUT', PREFIX + '/client-preferences', json=incoming).json()
    assert saved['revision'] == 1 and saved['ui']['noteEditMode'] == 'markdown'
    assert h.call('GET', PREFIX + '/client-preferences').json() == saved
    config = h.call('PATCH', PREFIX + '/config', json=dict(expected_revision=0, frequency='weekly', weekday=2)).json()
    assert config['revision'] == 1 and config['enabled'] is False
    job = h.call('POST', PREFIX, status=202, json={'scope': 'all'}).json()
    assert (job['kind'], job['scope'], job['state'], job['stage']) == ('backup', 'all', 'queued', 'admitted')
    assert h.instance.worker.started is True
    assert h.call('GET', PREFIX).json()['job'] == job
    url = PREFIX + '/{id}/download'
    head = h.call('HEAD', url)
    download = h.call('GET', url)
    assert download.content == (h.path / h.settings['filename']).read_bytes()
    assert head.headers['content-length'] == download.headers['content-length'] == str(h.settings['bytes'])
    for response in (head, download):
        assert response.headers['content-type'] == 'application/zip'
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['referrer-policy'] == 'no-referrer'
        assert h.settings['filename'] in response.headers['content-disposition']
    verified = h.call('POST', PREFIX + '/{id}/verify', status=202).json()
    restored = h.call('POST', PREFIX + '/{id}/restore', status=202, json={'confirm': h.settings['filename']}).json()
    assert (verified['kind'], restored['kind']) == ('verify', 'restore')
    assert verified['state'] == restored['state'] == 'queued', '202 is admission, not completion'
    h.call('DELETE', PREFIX + '/{id}', status=204, json={'confirm': h.settings['filename']})
    assert not (h.path / h.settings['filename']).exists()
    assert {(method, path) for method, path, status, _ in h.receipts if status in (200, 202, 204)} == set(OPERATIONS)
    # Installing documentation must not change any existing router response filter.
    before = [(r.path, r.endpoint, r.response_model, r.status_code) for r in h.ns['router'].routes]
    install(h.app)
    assert before == [(r.path, r.endpoint, r.response_model, r.status_code) for r in h.ns['router'].routes]
    record_property('backup_real_body_http', json.dumps(h.receipts, ensure_ascii=False))


def test_real_http_errors_conflict_maintenance_confirmation_and_missing(backup_http, record_property):
    h = backup_http
    h.call('PATCH', PREFIX + '/config', status=409, json={'expected_revision': 2})
    prefs = h.models.ClientPreferences().model_dump()
    h.call('PUT', PREFIX + '/client-preferences', status=409,
           json=dict(expected_revision=2, appearance='A', home=prefs['home'], ui=prefs['ui']))
    h.engine.busy = True
    for method, route, body in [('POST', PREFIX, {'scope': 'settings'}),
                                ('PATCH', PREFIX + '/config', {'expected_revision': 0}),
                                ('POST', PREFIX + '/{id}/verify', None),
                                ('POST', PREFIX + '/{id}/restore', {'confirm': h.settings['filename']}),
                                ('DELETE', PREFIX + '/{id}', {'confirm': h.settings['filename']})]:
        result = h.call(method, route, status=409, **({'json': body} if body is not None else {})).json()
        assert result['detail']['code'] == 'backup_busy'
    h.engine.busy = False
    result = h.call('POST', PREFIX + '/{id}/restore', status=409, record=h.full,
                    json={'confirm': h.full['filename']}).json()
    assert set(result['detail']) == {'code', 'message', 'command'}
    assert result['detail']['code'] == 'maintenance_required' and '--maintenance' in result['detail']['command']
    for method in ('POST', 'DELETE'):
        route = PREFIX + ('/{id}/restore' if method == 'POST' else '/{id}')
        h.call(method, route, status=422, json={'confirm': 'wrong-filename'})
    for method, route in [('GET', PREFIX + '/{id}/download'), ('HEAD', PREFIX + '/{id}/download'),
                          ('POST', PREFIX + '/{id}/verify'), ('POST', PREFIX + '/{id}/restore'), ('DELETE', PREFIX + '/{id}')]:
        kwargs = {'json': {'confirm': 'missing.zip'}} if route.endswith('/restore') or method == 'DELETE' else {}
        h.call(method, route, record={'id': 'not-present'}, status=404, **kwargs)
    record_property('backup_real_body_errors', json.dumps(h.receipts, ensure_ascii=False))


def test_real_http_owner_and_management_dependency_boundaries(backup_http, record_property):
    h = backup_http
    prefs = h.call('GET', PREFIX + '/client-preferences').json()
    h.call('PUT', PREFIX + '/client-preferences',
           json=dict(expected_revision=0, appearance='A', home=prefs['home'], ui=prefs['ui']))
    h.engine.owner_matches = False
    for method, route in MANAGEMENT_OPERATIONS:
        h.call(method, route, status=403)
    h.engine.owner_matches = True
    h.client.cookies.clear()
    for method, route in OPERATIONS:
        h.call(method, route, status=401)
    h.client.cookies.set('stella_at', 'synthetic-owner-session')
    for method in ('GET', 'HEAD'):
        h.call(method, PREFIX + '/{id}/download', headers={'Host': 'unapproved.test'}, status=421)
    h.call('PUT', PREFIX + '/client-preferences', headers={'Origin': 'https://unapproved.test'}, status=403)
    h.app.state.backup_center = None
    for method, route in [('GET', PREFIX), ('GET', PREFIX + '/client-preferences'), ('HEAD', PREFIX + '/{id}/download')]:
        h.call(method, route, status=503)
    record_property('backup_fixture_auth_and_real_middleware', json.dumps(h.receipts, ensure_ascii=False))


def test_real_http_preference_reference_validation_and_transaction_rollback(backup_http):
    h = backup_http
    route = PREFIX + '/client-preferences'
    before = h.call('GET', route).json()
    def incoming(value, revision):
        return dict(expected_revision=revision, appearance='A', home=dict(before['home'], bgImage=value), ui=before['ui'])
    missing = '/assets/homebg/missing-owned.png'
    rejected = h.call('PUT', route, status=409, json=incoming(missing, 0)).json()
    assert rejected['detail']['code'] == 'media_missing'
    assert h.call('GET', route).json() == before
    assert h.engine.values == {}, 'reference rejection must roll back the preference transaction'
    media = h.homebg_dir/'existing-owned.png'
    media.write_bytes(b'owned-fixture-media')
    saved = h.call('PUT', route, json=incoming('/assets/homebg/'+media.name, 0)).json()
    assert saved['revision'] == 1 and saved['home']['bgImage'].endswith(media.name)
    media.unlink()
    # Retain unchanged legacy references, but never accept a new missing one.
    saved_again = h.call('PUT', route, json=incoming(saved['home']['bgImage'], 1)).json()
    assert saved_again['revision'] == 2
    # Fail after a real SQL INSERT has executed, not before the transaction has
    # done any work. Both SQLite and the center read adapter must retain rev 2.
    from sqlalchemy import event, text
    def failed_after_insert(conn, cursor, statement, params, context, executemany):
        if statement.startswith('INSERT INTO app_config'):
            raise OSError(h.errno.EIO, 'synthetic owned SQL failure')
    event.listen(h.preference_engine, 'after_cursor_execute', failed_after_insert)
    try:
        h.call('PUT', route, status=422, json=incoming(saved['home']['bgImage'], 2))
    finally:
        event.remove(h.preference_engine, 'after_cursor_execute', failed_after_insert)
    with h.preference_engine.connect() as conn:
        stored = conn.execute(text('SELECT value FROM app_config WHERE key=:key'),
                              {'key':'client-preferences:fixture-owner'}).scalar_one()
    assert json.loads(stored)['revision'] == 2
    assert h.call('GET', route).json() == saved_again
    h.call('PUT', route, status=409, json=incoming(missing, 2))
    assert h.call('GET', route).json() == saved_again
    stale = h.call('PUT', route, status=409, json=incoming(missing, 0)).json()
    assert stale['detail']['code'] == 'revision_conflict'
    assert h.call('GET', route).json() == saved_again


@pytest.mark.parametrize('field,value', [
    ('siteTitle', 'x' * 121), ('signature', 'x' * 513), ('siteTitle', 'control\x01text'),
    ('meetDate', '0000-01-01'), ('meetDate', '2026-02-30'),
    ('bgImage', 'https://external.invalid/wallpaper.png'), ('avatar', '/assets/homebg/not-avatar.png'),
    ('bgImage', '/assets/homebg/../private'),
])
def test_real_http_strict_preferences_request_validation(backup_http, field, value):
    h = backup_http
    prefs = h.models.ClientPreferences().model_dump()
    prefs['home'][field] = value
    response = h.call('PUT', PREFIX + '/client-preferences', status=422,
                      json=dict(expected_revision=0, appearance='A', home=prefs['home'], ui=prefs['ui']))
    assert all(set(item) == {'loc', 'type', 'msg'} for item in response.json()['detail'])
    assert h.engine.values == {}, 'validation did not persist a preference slot'


def test_real_http_business_validation_archive_and_safe_oserror(backup_http, monkeypatch, record_property):
    h = backup_http
    h.call('POST', PREFIX, status=422, json={'scope': 'unknown'})
    h.call('PATCH', PREFIX + '/config', status=422, json={'expected_revision': 0, 'time': '27:90'})
    h.call('PATCH', PREFIX + '/config', status=422, json={'expected_revision': 0, 'enabled': None})
    h.call('PATCH', PREFIX + '/config', status=422, json={'expected_revision': 0, 'timezone': 'not-a-timezone'})
    h.call('PATCH', PREFIX + '/config', status=404, json={'expected_revision': 0, 'directory': str(h.path / 'missing')})
    # HEAD checks size only; GET verifies ZIP contents/hash before headers.
    path = h.path / h.settings['filename']; original = path.read_bytes()
    path.write_bytes(original.replace(b'PK', b'XX', 1))
    h.call('HEAD', PREFIX + '/{id}/download')
    h.call('GET', PREFIX + '/{id}/download', status=422)
    path.write_bytes(original[:-1])
    h.call('HEAD', PREFIX + '/{id}/download', status=422)
    path.write_bytes(original)
    def denied(*args, **kwargs):
        raise PermissionError(h.errno.EACCES, 'synthetic-sensitive-server-path')
    monkeypatch.setattr(h.instance, 'store', denied)
    response = h.call('GET', PREFIX + '/{id}/download', status=422)
    assert response.json()['detail'] == '目录权限不足，旧备份保留'
    assert 'synthetic-sensitive' not in response.text
    record_property('backup_real_validation_and_io', json.dumps(h.receipts, ensure_ascii=False))


@pytest.mark.parametrize('relative', ['app/routers/backups.py', 'app/schemas/backups.py', 'app/services/backup_preferences.py', 'main.py'])
def test_backup_gate_refuses_each_reviewed_source_drift(relative, tmp_path):
    module = response_module()
    for source in module.SOURCE_EVIDENCE.values():
        target = tmp_path / source['file']
        if target.exists(): continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(ROOT / source['file'])
    changed = tmp_path / relative
    changed.unlink()
    changed.write_bytes((ROOT / relative).read_bytes() + b'\n# synthetic unreviewed change\n')
    errors = module.validate_response_sources(tmp_path, static_inventory()[0])
    assert errors == ['source drift or missing source: ' + relative]
