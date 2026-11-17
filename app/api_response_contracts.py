"""Schema-only response declarations, NOT handler response_model filters.

A frozen method/path/callable inventory prevents new routes from inheriting a
blanket policy. Source hashes are checked by the offline release gate, not HTTP.
Incomplete and external pass-through contracts are explicit, never counted as
fully modeled JSON. This module does not implement validation or redact errors.
"""
import json
from copy import deepcopy
from pathlib import Path

S = {'type': 'string'}
I = {'type': 'integer'}
F = {'type': 'number'}
B = {'type': 'boolean'}
N = {'type': 'null'}
DATE = {'type': 'string', 'format': 'date-time'}


def obj(**properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def array(items):
    return {'type': 'array', 'items': items}


def nullable(schema):
    return {'anyOf': [schema, N]}


def optional(schema, *names):
    schema = deepcopy(schema)
    schema['required'] = [k for k in schema['required'] if k not in names]
    return schema


def json_response(schema, description):
    schema = deepcopy(schema)
    definitions = {}
    def lift(value):
        if isinstance(value, dict):
            definitions.update(value.pop('$defs', {}))
            for child in value.values():
                lift(child)
        elif isinstance(value, list):
            for child in value:
                lift(child)
    lift(schema)
    if definitions:
        schema['$defs'] = definitions
    return {'description': description, 'content': {'application/json': {'schema': schema}}}


# Real dynamic JSON is limited to explicitly sourced user/tool/legacy fields.
# Never use this to invent an unknown operation's success shape.
JSON_VALUE = {'anyOf': [S, F, B, N, {'type': 'array', 'items': {'$ref': '#/$defs/JsonValue'}},
    {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/JsonValue'}}]}
JSON_OBJECT = {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/JsonValue'},
               'description': 'User-defined JSON key/value data; not a fixed application record.'}
PREFERENCES = obj(revision=I, delete_action={'enum': ['trash', 'permanent'], 'type': 'string'}, ask_before_delete=B,
    font_size=I, line_height=F, read_width=I, code_line_numbers=B, code_wrap=B,
    directory_sort={'enum': ['updated', 'title', 'created'], 'type': 'string'}, hidden_folders=array(S))
CODE_MESSAGE = obj(code=S, message=S)
DETAIL = {'anyOf': [S, CODE_MESSAGE, obj(code=S), obj(message=S),
    obj(message=S, editor=obj(ip=S, ua=S)), obj(code=S, current=PREFERENCES),
    obj(message=S, managed_settings=S),
    optional(obj(code={'const': 'protected_notes_folder'}, folder_id=S, message=S), 'message')]}
HTTP_ERROR = obj(detail=DETAIL)

OK = obj(ok=B)
UPLOAD = obj(id=S, url=S, filename=S)
USER = obj(id=S, username=S, display_name=S, is_admin=B, avatar_url=S, home_bg=S, email=S, email_verified=B)
SECURITY = obj(enabled=B, configured=B, elevated=B, expires_at=nullable(DATE), single_user=B, setup_required=B)
SESSION = obj(id=S, device=S, ip=S, remember=B, created_at=DATE, last_seen=DATE, expires_at=nullable(DATE), current=B, owner=S, mine=B,
    browser_id=nullable(S), browser_name=nullable(S), os_name=nullable(S), login_origin=nullable(S), ip_location=N)
SESSION_HISTORY = obj(**{**SESSION['properties'], 'expires_at':nullable(DATE)}, state={'type': 'string', 'enum': ['revoked', 'expired']})
MAIL_SENT = optional(obj(ok=B, minutes=I, already_sent=B), 'already_sent')
ZIP_ENTRY = obj(path=S, title=S, kind={'type': 'string', 'enum': ['directory', 'document', 'attachment']}, parent_path=nullable(S))
ZIP_PREVIEW = obj(entries=array(ZIP_ENTRY), warnings=array(S), counts=obj(documents=I, attachments=I))
ZIP_IMPORT = obj(documents=array(obj(id=S, title=S, path=S, parent_id=nullable(S))), attachments=I, warnings=array(S), reused=B)
CLIENT = obj(client_id=S, name=S, enabled=B, redirect_uris=array(S), has_secret=B, scopes=array(S), last_used_at=nullable(DATE))
CLIENT_SECRET = obj(**CLIENT['properties'], client_secret=S)
DISCOVERY = obj(**{k: S for k in ['issuer', 'authorization_endpoint', 'token_endpoint', 'userinfo_endpoint', 'jwks_uri']},
    **{k: array(S) for k in ['response_types_supported', 'subject_types_supported', 'id_token_signing_alg_values_supported',
        'scopes_supported', 'grant_types_supported', 'token_endpoint_auth_methods_supported', 'code_challenge_methods_supported', 'claims_supported']})
TIMELINE_ITEM = obj(kind=S, id=S, label=S, ts=DATE, node_id=nullable(I), path=S, state=nullable(S))
TIMELINE = obj(items=array(TIMELINE_ITEM), has_more=B, unknown_notes_present=B, history_path=nullable(S))
SEARCH = obj(items=array({'anyOf': [TIMELINE_ITEM, obj(kind={'const': 'note'}, id=S, label=S, path=S, ts=DATE),
    obj(kind={'const': 'node'}, id=S, label=S, path=S)]}))

_BASE = Path(__file__).parent
_SNAPSHOT = json.loads((_BASE / 'api_response_inventory.json').read_text())
SOURCE_EVIDENCE = _SNAPSHOT['sources']
INVENTORY = _SNAPSHOT['operations']
_OVERHAUL = json.loads((_BASE / 'api_response_overhaul.json').read_text())
SOURCE_EVIDENCE.update(_OVERHAUL['sources'])
INVENTORY = [*INVENTORY, *_OVERHAUL['operations']]
_WEB_PROJECTS = json.loads((_BASE / 'api_response_web_projects.json').read_text())
SOURCE_EVIDENCE.update(_WEB_PROJECTS['sources'])
INVENTORY.extend(_WEB_PROJECTS['operations'])
_BACKUPS = json.loads((_BASE / 'api_response_backups.json').read_text())
SOURCE_EVIDENCE.update(_BACKUPS['sources'])
INVENTORY.extend(_BACKUPS['operations'])
_FEEDBACK = json.loads((_BASE / 'api_response_feedback.json').read_text())
SOURCE_EVIDENCE.update(_FEEDBACK['sources'])
INVENTORY.extend(_FEEDBACK['operations'])
_INTEGRATED = json.loads((_BASE / 'api_response_integrated.json').read_text())
SOURCE_EVIDENCE.update(_INTEGRATED['sources'])
INVENTORY.extend(_INTEGRATED['operations'])
for _operation in INVENTORY:
    _operation['sources'] = sorted(set(_operation['sources']) | set(_INTEGRATED['source_additions'].get(_operation['endpoint'], [])))
_ENTRY_MONITORING = json.loads((_BASE / 'api_response_entry_monitoring.json').read_text())
SOURCE_EVIDENCE.update(_ENTRY_MONITORING['sources'])
INVENTORY.extend(_ENTRY_MONITORING['operations'])
for _operation in INVENTORY:
    _operation['sources'] = sorted(set(_operation['sources']) | set(_ENTRY_MONITORING['source_additions'].get(_operation['endpoint'], [])))
# Append the independently approved auth snapshot after scoped overlays;
# historical ledgers stay untouched and request evidence is linked, not a DTO.
_AUTH_REVIEW = json.loads((_BASE / 'api_response_auth_review.json').read_text())
SOURCE_EVIDENCE.update(_AUTH_REVIEW['sources'])
SOURCE_EVIDENCE['app.routers.auth.ProfileIn'] = _AUTH_REVIEW['new_request_source']
for _operation in INVENTORY:
    _operation['sources'] = sorted(set(_operation['sources']) | set(_AUTH_REVIEW['request_source_additions'].get(_operation['endpoint'], [])))
# Bounded independent R1 approval; retain historical evidence, retarget live references.
_ENTRY_SCOPE_REVIEW = json.loads((_BASE / 'api_response_entry_scope_review.json').read_text())
SOURCE_EVIDENCE.update(_ENTRY_SCOPE_REVIEW['sources'])
for _operation in INVENTORY:
    _operation['sources'] = sorted({_ENTRY_SCOPE_REVIEW['source_replacements'].get(_symbol, _symbol)
                                    for _symbol in _operation['sources']})
# Bounded independent round-four closure; historical ledgers remain immutable.
_ROUND4_REVIEW = json.loads((_BASE / 'api_response_round4_review.json').read_text())
SOURCE_EVIDENCE.update(_ROUND4_REVIEW['sources'])
INVENTORY.extend(_ROUND4_REVIEW['operations'])
for _operation in INVENTORY:
    _operation['sources'] = sorted(
        {_ROUND4_REVIEW['source_replacements'].get(_symbol, _symbol)
         for _symbol in _operation['sources']} |
        set(_ROUND4_REVIEW['source_additions'].get(_operation['endpoint'], [])))
_ROUND4_ENDPOINTS = frozenset(_ROUND4_REVIEW['affected_endpoints'])
# Apply the reviewed lane union AFTER round four, BEFORE DTO initialization.
# The new worker deliberately retains its stale expectation: NOT approved.
_V5_REVIEW = json.loads((_BASE / 'api_response_v5_integration.json').read_text())
SOURCE_EVIDENCE.update(_V5_REVIEW['sources'])
INVENTORY.extend(_V5_REVIEW['operations'])
_V5_MODELS = {(_item['method'], _item['path']): _item['model']
              for _item in _V5_REVIEW['inventory_model_replacements']}
for _operation in INVENTORY:
    _operation['sources'] = sorted({
        _V5_REVIEW['source_replacements'].get(_symbol, _symbol)
        for _symbol in [*_operation['sources'],
                        *_V5_REVIEW['source_additions'].get(_operation['endpoint'], [])]})
    _model = _V5_MODELS.get((_operation['method'], _operation['path']))
    if _model is not None:
        _operation['model'] = _model
# Final external alert source approval follows the monitor/channel union.
# Keep both prior overlays immutable, including the historical pending receipt.
_NODE_INTERRUPTION_REVIEW = json.loads((_BASE / 'api_response_node_interruptions_review.json').read_text())
SOURCE_EVIDENCE.update(_NODE_INTERRUPTION_REVIEW['sources'])
for _operation in INVENTORY:
    _operation['sources'] = sorted({
        _NODE_INTERRUPTION_REVIEW['source_replacements'].get(_symbol, _symbol)
        for _symbol in [*_operation['sources'],
                        *_NODE_INTERRUPTION_REVIEW['source_additions'].get(_operation['endpoint'], [])]})
_V5_HANDLERS = {**_ROUND4_REVIEW['handler_source_replacements'],
                **_V5_REVIEW['handler_source_replacements']}
for _operation in INVENTORY:
    _endpoint = _operation['endpoint']
    _symbol = _V5_HANDLERS.get(_endpoint, _endpoint)
    _symbol = _V5_REVIEW['source_replacements'].get(_symbol, _symbol)
    _V5_HANDLERS[_endpoint] = _NODE_INTERRUPTION_REVIEW['source_replacements'].get(_symbol, _symbol)
_NODE_INTERRUPTION_ENDPOINTS = frozenset(
    _operation['endpoint'] for _operation in INVENTORY
    if _V5_HANDLERS[_operation['endpoint']] in _NODE_INTERRUPTION_REVIEW['sources'])
_V5_ENDPOINTS = frozenset(_V5_REVIEW['affected_endpoints']) | frozenset(
    _operation['endpoint'] for _operation in INVENTORY
    if any(_symbol in _V5_REVIEW['sources'] for _symbol in _operation['sources']))
# Append the exact reviewed source/DTO union; historical JSON stays immutable.
# This loader is separately reviewable and is not a release approval.
_V6_REVIEW = json.loads((_BASE / 'api_response_v6_integration.json').read_text())
SOURCE_EVIDENCE.update(_V6_REVIEW['sources'])
_V6_ROWS = {(_row['method'], _row['path']): _row
            for _row in _V6_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V6_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v6 source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
_V5_HANDLERS.update(_V6_REVIEW['handler_source_replacements'])
_V6_ENDPOINTS = frozenset(
    _operation['endpoint'] for _operation in INVENTORY
    if any(_symbol in _V6_REVIEW['sources'] for _symbol in _operation['sources']))
# The current Agent approval already inherits the exact reviewed Ping methods.
# Never activate the superseded standalone Ping overlay.
_IPV6_UDP_REVIEW = json.loads((_BASE / 'api_response_ipv6_udp_source_review.json').read_text())
SOURCE_EVIDENCE.update(_IPV6_UDP_REVIEW['sources'])
for _operation in INVENTORY:
    _operation['sources'] = sorted({
        _IPV6_UDP_REVIEW['source_replacements'].get(_symbol, _symbol)
        for _symbol in [*_operation['sources'],
                        *_IPV6_UDP_REVIEW['source_additions'].get(_operation['endpoint'], [])]})
# Scoped v8 approval: exact before-source preconditions; retain all old ledgers.
_V8_REVIEW = json.loads((_BASE / 'api_response_v8_review.json').read_text())
SOURCE_EVIDENCE.update(_V8_REVIEW['sources'])
_V8_ROWS = {(_row['method'], _row['path']): _row
            for _row in _V8_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V8_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v8 source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
INVENTORY.extend(_V8_REVIEW['operations'])
_V5_HANDLERS.update(_V8_REVIEW['handler_source_replacements'])
_V8_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                          [*_V8_REVIEW['operation_source_updates'], *_V8_REVIEW['operations']])
# Bounded v11 append-only approval: exact prior rows, never a dynamic rebase.
_V11_REVIEW = json.loads((_BASE / 'api_response_v11_review.json').read_text())
SOURCE_EVIDENCE.update(_V11_REVIEW['sources'])
_V11_ROWS = {(_row['method'], _row['path']): _row
             for _row in _V11_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V11_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v11 source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
INVENTORY.extend(_V11_REVIEW['operations'])
_V5_HANDLERS.update(_V11_REVIEW['handler_source_replacements'])
_V11_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                           [*_V11_REVIEW['operation_source_updates'], *_V11_REVIEW['operations']])
# Exact bounded V12 source/DTO approval; native deployment remains unapproved.
_V12_REVIEW = json.loads((_BASE / 'api_response_v12_final_review.json').read_text())
SOURCE_EVIDENCE.update(_V12_REVIEW['sources'])
_V12_ROWS = {(_row['method'], _row['path']): _row
             for _row in _V12_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V12_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v12 source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
INVENTORY.extend(_V12_REVIEW['operations'])
_V5_HANDLERS.update(_V12_REVIEW['handler_source_replacements'])
_V12_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                           [*_V12_REVIEW['operation_source_updates'], *_V12_REVIEW['operations']])
# Notes is a separately approved layer, not a rewrite of historical approval.
_V12_NOTES_REVIEW = json.loads((_BASE / 'api_response_v12_notes_review.json').read_text())
SOURCE_EVIDENCE.update(_V12_NOTES_REVIEW['sources'])
_V12_NOTES_ROWS = {(_row['method'], _row['path']): _row
                   for _row in _V12_NOTES_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V12_NOTES_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v12 notes source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
_V12_NOTES_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                                 _V12_NOTES_REVIEW['operation_source_updates'])
# Exact installer umask review; historical records remain immutable.
_V12_UMASK_REVIEW = json.loads((_BASE / 'api_response_v12_installer_umask_review.json').read_text())
for _key, _expected in _V12_UMASK_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v12 installer umask source precondition drift')
if set(SOURCE_EVIDENCE).intersection(_V12_UMASK_REVIEW['sources']):
    raise ValueError('v12 installer umask source key collision')
SOURCE_EVIDENCE.update(_V12_UMASK_REVIEW['sources'])
_V12_UMASK_ROWS = {(_row['method'], _row['path']): _row
                   for _row in _V12_UMASK_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V12_UMASK_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v12 installer umask source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
_V12_UMASK_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                                _V12_UMASK_REVIEW['operation_source_updates'])
# V13 exact duration review: append sources, retain every historical record.
_V13_DURATION_REVIEW = json.loads((_BASE / 'api_response_v13_speedtest_duration_review.json').read_text())
for _key, _expected in _V13_DURATION_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v13 duration source precondition drift')
if set(SOURCE_EVIDENCE).intersection(_V13_DURATION_REVIEW['sources']):
    raise ValueError('v13 duration source key collision')
SOURCE_EVIDENCE.update(_V13_DURATION_REVIEW['sources'])
_V13_DURATION_ROWS = {(_row['method'], _row['path']): _row
                      for _row in _V13_DURATION_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V13_DURATION_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v13 duration source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
_V13_DURATION_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                                   _V13_DURATION_REVIEW['operation_source_updates'])
# Exact independent monitor missing/removed 404 approval; historical JSON immutable.
_V13_MONITOR404_REVIEW = json.loads((_BASE / 'api_response_v13_monitor404_review.json').read_text())
for _key, _expected in _V13_MONITOR404_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v13 monitor404 source precondition drift')
if set(SOURCE_EVIDENCE).intersection(_V13_MONITOR404_REVIEW['sources']):
    raise ValueError('v13 monitor404 source key collision')
SOURCE_EVIDENCE.update(_V13_MONITOR404_REVIEW['sources'])
_V13_MONITOR404_ROWS = {(_row['method'], _row['path']): _row
                        for _row in _V13_MONITOR404_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V13_MONITOR404_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v13 monitor404 source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
for _endpoint, _expected in _V13_MONITOR404_REVIEW['handler_source_preconditions'].items():
    if _V5_HANDLERS.get(_endpoint, _endpoint) != _expected:
        raise ValueError('v13 monitor404 handler precondition drift')
_V5_HANDLERS.update(_V13_MONITOR404_REVIEW['handler_source_replacements'])
_V13_MONITOR404_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                                     _V13_MONITOR404_REVIEW['operation_source_updates'])
# CI158 metadata-only successors at the SAME reviewed full-file hashes.
# Keep erroneous historical rows immutable; require exact source/edge preconditions.
_V13_SOURCE_METADATA_REVIEW = json.loads((_BASE / 'api_response_v13_source_metadata_review.json').read_text())
for _key, _expected in _V13_SOURCE_METADATA_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v13 source metadata source precondition drift')
if set(SOURCE_EVIDENCE).intersection(_V13_SOURCE_METADATA_REVIEW['sources']):
    raise ValueError('v13 source metadata source key collision')
SOURCE_EVIDENCE.update(_V13_SOURCE_METADATA_REVIEW['sources'])
_V13_SOURCE_METADATA_ROWS = {(_row['method'], _row['path']): _row
                             for _row in _V13_SOURCE_METADATA_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V13_SOURCE_METADATA_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v13 source metadata source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
for _endpoint, _expected in _V13_SOURCE_METADATA_REVIEW['handler_source_preconditions'].items():
    if _V5_HANDLERS.get(_endpoint, _endpoint) != _expected:
        raise ValueError('v13 source metadata handler precondition drift')
_V5_HANDLERS.update(_V13_SOURCE_METADATA_REVIEW['handler_source_replacements'])
_V13_SOURCE_METADATA_ENDPOINTS = frozenset(_row['endpoint'] for _row in
                                          _V13_SOURCE_METADATA_REVIEW['operation_source_updates'])
# CI167 bounded feedback evidence: append exact successors, never refresh history.
_V14_CI167_REVIEW = json.loads((_BASE / 'api_response_v14_ci167_review.json').read_text())
for _key, _expected in _V14_CI167_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v14 ci167 source precondition drift')
if set(SOURCE_EVIDENCE).intersection(_V14_CI167_REVIEW['sources']):
    raise ValueError('v14 ci167 source key collision')
SOURCE_EVIDENCE.update(_V14_CI167_REVIEW['sources'])
_V14_CI167_ROWS = {(_row['method'], _row['path']): _row
                  for _row in _V14_CI167_REVIEW['operation_source_updates']}
for _operation in INVENTORY:
    _reviewed = _V14_CI167_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources']):
            raise ValueError('v14 ci167 source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
for _endpoint, _expected in _V14_CI167_REVIEW['handler_source_preconditions'].items():
    if _V5_HANDLERS.get(_endpoint, _endpoint) != _expected:
        raise ValueError('v14 ci167 handler precondition drift')
if {(r['method'], r['path']) for r in INVENTORY}.intersection(
        (r['method'], r['path']) for r in _V14_CI167_REVIEW['operations']):
    raise ValueError('v14 ci167 operation collision')
INVENTORY.extend(_V14_CI167_REVIEW['operations'])
_V5_HANDLERS.update(_V14_CI167_REVIEW['handler_source_replacements'])
_V14_CI167_ENDPOINTS = frozenset(_row['endpoint'] for _row in
    [*_V14_CI167_REVIEW['operation_source_updates'], *_V14_CI167_REVIEW['operations']])
# Actual parked .15 pin: append only this router's 65 active source successors.
_V15_AGENT_ROLLOUT_REVIEW = json.loads((_BASE / 'api_response_v15_agent_rollout_review.json').read_text())
_V15_AGENT_ROLLOUT_ACTIVE = {s for r in INVENTORY for s in r['sources']
                            if SOURCE_EVIDENCE.get(s, {}).get('file') == 'app/routers/monitor.py'}
if (len(_V15_AGENT_ROLLOUT_ACTIVE) != 65 or
        set(_V15_AGENT_ROLLOUT_REVIEW['source_preconditions']) != _V15_AGENT_ROLLOUT_ACTIVE or
        set(_V15_AGENT_ROLLOUT_REVIEW['source_replacements']) != _V15_AGENT_ROLLOUT_ACTIVE or
        set(_V15_AGENT_ROLLOUT_REVIEW['source_replacements'].values()) != set(_V15_AGENT_ROLLOUT_REVIEW['sources']) or
        len(_V15_AGENT_ROLLOUT_REVIEW['sources']) != 65):
    raise ValueError('v15 agent rollout source scope drift')
for _key, _expected in _V15_AGENT_ROLLOUT_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v15 agent rollout source precondition drift')
    _successor = _V15_AGENT_ROLLOUT_REVIEW['sources'][_V15_AGENT_ROLLOUT_REVIEW['source_replacements'][_key]]
    if any(_successor.get(_field) != _expected[_field] for _field in ('file', 'symbol', 'line', 'end_line')):
        raise ValueError('v15 agent rollout symbol scope drift')
if set(SOURCE_EVIDENCE).intersection(_V15_AGENT_ROLLOUT_REVIEW['sources']):
    raise ValueError('v15 agent rollout source key collision')
_V15_AGENT_ROLLOUT_ROWS = {(_row['method'], _row['path']): _row
                          for _row in _V15_AGENT_ROLLOUT_REVIEW['operation_source_updates']}
_V15_AGENT_ROLLOUT_EXPECTED_ROWS = {(_r['method'], _r['path']) for _r in INVENTORY
                                   if _V15_AGENT_ROLLOUT_ACTIVE.intersection(_r['sources'])}
if (len(_V15_AGENT_ROLLOUT_REVIEW['operation_source_updates']) != 88 or
        len(_V15_AGENT_ROLLOUT_ROWS) != 88 or
        set(_V15_AGENT_ROLLOUT_ROWS) != _V15_AGENT_ROLLOUT_EXPECTED_ROWS or
        _V15_AGENT_ROLLOUT_REVIEW['operations'] or _V15_AGENT_ROLLOUT_REVIEW['models']):
    raise ValueError('v15 agent rollout operation scope drift')
for _operation in INVENTORY:
    _reviewed = _V15_AGENT_ROLLOUT_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources'] or
                _reviewed['sources'] != sorted(_V15_AGENT_ROLLOUT_REVIEW['source_replacements'].get(s, s)
                                               for s in _operation['sources'])):
            raise ValueError('v15 agent rollout source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
_V15_AGENT_ROLLOUT_HANDLERS = {k: v for k, v in _V5_HANDLERS.items() if v in _V15_AGENT_ROLLOUT_ACTIVE}
if (_V15_AGENT_ROLLOUT_REVIEW['handler_source_preconditions'] != _V15_AGENT_ROLLOUT_HANDLERS or
        _V15_AGENT_ROLLOUT_REVIEW['handler_source_replacements'] != {
            k: _V15_AGENT_ROLLOUT_REVIEW['source_replacements'][v] for k, v in _V15_AGENT_ROLLOUT_HANDLERS.items()}):
    raise ValueError('v15 agent rollout handler precondition drift')
SOURCE_EVIDENCE.update(_V15_AGENT_ROLLOUT_REVIEW['sources'])
_V5_HANDLERS.update(_V15_AGENT_ROLLOUT_REVIEW['handler_source_replacements'])
_V15_AGENT_ROLLOUT_ENDPOINTS = frozenset(_row['endpoint'] for _row in _V15_AGENT_ROLLOUT_ROWS.values())
# Merged monitor UX: exact append-only successors and two bounded operations.
_V16_MONITOR_UX_REVIEW = json.loads((_BASE / 'api_response_v16_monitor_ux_review.json').read_text())
_V16_MONITOR_UX_ACTIVE = {s for r in INVENTORY for s in r['sources']
    if SOURCE_EVIDENCE.get(s, {}).get('file') in ('app/routers/monitor.py', 'app/schemas/monitor.py')}
_V16_MONITOR_UX_NEW = {
    symbol + '@v16-monitor-ux' for symbol in (
        'app.routers.monitor.monitor_batch_receipt', 'app.routers.monitor.create_monitor_batch',
        'app.schemas.monitor.MonitorBatchCreate', 'app.schemas.monitor.MonitorBatchReceipt',
        'app/services/monitor_batches.py', 'app.services.monitor_batches.BatchConflict',
        'app.services.monitor_batches.create', 'app.services.monitor_batches.receipt',
        'app/repositories/config.py', 'app.services.monitor_groups._receipt_slot',
        'app.services.entry_monitor_groups.lock')}
if (len(_V16_MONITOR_UX_ACTIVE) != 81 or
        set(_V16_MONITOR_UX_REVIEW['source_preconditions']) != _V16_MONITOR_UX_ACTIVE or
        _V16_MONITOR_UX_REVIEW['source_replacements'] != {
            s: s + '@v16-monitor-ux' for s in _V16_MONITOR_UX_ACTIVE} or
        len(_V16_MONITOR_UX_REVIEW['new_source_keys']) != 11 or
        set(_V16_MONITOR_UX_REVIEW['new_source_keys']) != _V16_MONITOR_UX_NEW or
        set(_V16_MONITOR_UX_REVIEW['sources']) !=
        set(_V16_MONITOR_UX_REVIEW['source_replacements'].values()) | _V16_MONITOR_UX_NEW):
    raise ValueError('v16 monitor UX source scope drift')
for _key, _expected in _V16_MONITOR_UX_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v16 monitor UX source precondition drift')
    _successor = _V16_MONITOR_UX_REVIEW['sources'][_V16_MONITOR_UX_REVIEW['source_replacements'][_key]]
    if any(_successor.get(f) != _expected[f] for f in ('file', 'symbol')):
        raise ValueError('v16 monitor UX symbol scope drift')
for _key in _V16_MONITOR_UX_NEW:
    _source = _V16_MONITOR_UX_REVIEW['sources'][_key]
    _symbol = _key.removesuffix('@v16-monitor-ux')
    _file = (_symbol if _symbol.endswith('.py') else
             '/'.join(_symbol.split('.')[:3]) + '.py')
    if _source.get('symbol') != _symbol or _source.get('file') != _file:
        raise ValueError('v16 monitor UX new source symbol drift')
if set(SOURCE_EVIDENCE).intersection(_V16_MONITOR_UX_REVIEW['sources']):
    raise ValueError('v16 monitor UX source key collision')
_V16_MONITOR_UX_ROWS = {(_r['method'], _r['path']): _r
    for _r in _V16_MONITOR_UX_REVIEW['operation_source_updates']}
if (len(_V16_MONITOR_UX_REVIEW['operation_source_updates']) != 88 or
        len(_V16_MONITOR_UX_ROWS) != 88 or set(_V16_MONITOR_UX_ROWS) != {
            (_r['method'], _r['path']) for _r in INVENTORY
            if _V16_MONITOR_UX_ACTIVE.intersection(_r['sources'])}):
    raise ValueError('v16 monitor UX old operation scope drift')
for _operation in INVENTORY:
    _reviewed = _V16_MONITOR_UX_ROWS.get((_operation['method'], _operation['path']))
    if _reviewed is not None:
        if (_reviewed['endpoint'] != _operation['endpoint'] or
                _reviewed['before_sources'] != _operation['sources'] or
                _reviewed['sources'] != sorted(_V16_MONITOR_UX_REVIEW['source_replacements'].get(s, s)
                                               for s in _operation['sources'])):
            raise ValueError('v16 monitor UX source-union precondition drift')
        _operation['sources'] = list(_reviewed['sources'])
_V16_MONITOR_UX_HANDLERS = {k: v for k, v in _V5_HANDLERS.items() if v in _V16_MONITOR_UX_ACTIVE}
if (_V16_MONITOR_UX_REVIEW['handler_source_preconditions'] != _V16_MONITOR_UX_HANDLERS or
        _V16_MONITOR_UX_REVIEW['handler_source_replacements'] != {
            k: _V16_MONITOR_UX_REVIEW['source_replacements'][v] for k, v in _V16_MONITOR_UX_HANDLERS.items()}):
    raise ValueError('v16 monitor UX handler precondition drift')
_V16_MONITOR_UX_OPERATIONS = {
    ('POST', '/monitors/batches'): ('app.routers.monitor.create_monitor_batch', '201', ['400', '409', '401', '403', '503']),
    ('GET', '/monitors/batches/receipts/{request_key}'): ('app.routers.monitor.monitor_batch_receipt', '200', ['404', '401', '403', '503'])}
_V16_MONITOR_UX_NEW_ROWS = {(_r['method'], _r['path']): _r for _r in _V16_MONITOR_UX_REVIEW['operations']}
if (len(_V16_MONITOR_UX_REVIEW['operations']) != 2 or
        set(_V16_MONITOR_UX_NEW_ROWS) != set(_V16_MONITOR_UX_OPERATIONS)):
    raise ValueError('v16 monitor UX new operation scope drift')
if {(_r['method'], _r['path']) for _r in INVENTORY}.intersection(_V16_MONITOR_UX_NEW_ROWS):
    raise ValueError('v16 monitor UX operation collision')
_V16_MONITOR_UX_SHARED = next(_r['sources'] for _r in INVENTORY
    if (_r['method'], _r['path']) == ('POST', '/monitors/groups'))
for _key, (_endpoint, _code, _errors) in _V16_MONITOR_UX_OPERATIONS.items():
    _row = _V16_MONITOR_UX_NEW_ROWS[_key]
    if (_row['endpoint'] != _endpoint or _row['status_code'] != _code or
            _row['model'] != 'MonitorBatchReceipt' or _row['error_statuses'] != _errors or
            _row['request_validation'] is not True or
            _row['sources'] != sorted(set(_V16_MONITOR_UX_SHARED) | _V16_MONITOR_UX_NEW)):
        raise ValueError('v16 monitor UX new operation closure drift')
if _V16_MONITOR_UX_REVIEW['new_handler_sources'] != {
        endpoint: endpoint + '@v16-monitor-ux' for endpoint, _, _ in _V16_MONITOR_UX_OPERATIONS.values()}:
    raise ValueError('v16 monitor UX new handler closure drift')
if _V16_MONITOR_UX_REVIEW['models'] != {'MonitorBatchReceipt': {
        'properties': {'group_id': {'anyOf': [{'type': 'integer'}, {'type': 'null'}], 'title': 'Group Id'},
                       'monitor_ids': {'items': {'type': 'integer'}, 'title': 'Monitor Ids', 'type': 'array'}},
        'required': ['group_id', 'monitor_ids'], 'title': 'MonitorBatchReceipt', 'type': 'object'}}:
    raise ValueError('v16 monitor UX model closure drift')
SOURCE_EVIDENCE.update(_V16_MONITOR_UX_REVIEW['sources'])
INVENTORY.extend(_V16_MONITOR_UX_REVIEW['operations'])
_V5_HANDLERS.update(_V16_MONITOR_UX_REVIEW['handler_source_replacements'])
_V5_HANDLERS.update(_V16_MONITOR_UX_REVIEW['new_handler_sources'])
_V16_MONITOR_UX_ENDPOINTS = frozenset(_r['endpoint'] for _r in
    [*_V16_MONITOR_UX_ROWS.values(), *_V16_MONITOR_UX_NEW_ROWS.values()])
# v17: literal approved Nav/Files union, including complete prior records.
# Hashing the review is an approval boundary, never a source-refresh fallback.
import hashlib as _review_hashlib
_V17_TEXT = (_BASE / 'api_response_v17_nav_files_review.json').read_text()
if _review_hashlib.sha256(_V17_TEXT.encode()).hexdigest() != 'dd1bd79485b43553522c66ef9123efa091fb660878b2a9e1eb1a8d3fb856ff75':
    raise ValueError('v17 nav files immutable review drift')
_V17_REVIEW = json.loads(_V17_TEXT)
for _key, _expected in _V17_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v17 nav files source precondition drift')
if set(SOURCE_EVIDENCE).intersection(_V17_REVIEW['sources']):
    raise ValueError('v17 nav files source collision')
_V17_ROWS = {(_r['method'], _r['path']): _r for _r in _V17_REVIEW['operation_source_updates']}
if len(_V17_ROWS) != len(_V17_REVIEW['operation_source_updates']):
    raise ValueError('v17 nav files duplicate predecessor')
for _operation in INVENTORY:
    _key = _operation['method'], _operation['path']
    _update = _V17_ROWS.get(_key)
    if _update is not None:
        if (_operation != _update['before_operation'] or
                _operation['sources'] != _update['before_sources'] or
                _update['endpoint'] != _operation['endpoint'] or
                _update['sources'] != sorted({
                    _V17_REVIEW['source_replacements'].get(s, s) for s in _operation['sources']
                } | set(_update['source_additions'])) or
                _update['operation'] != {**_operation, 'sources': _update['sources']}):
            raise ValueError('v17 nav files exact before operation/source union drift')
        _operation['sources'] = list(_update['sources'])
for _endpoint, _key in _V17_REVIEW['handler_source_preconditions'].items():
    if _V5_HANDLERS.get(_endpoint, _endpoint) != _key:
        raise ValueError('v17 nav files handler precondition drift')
_V17_NEW_ROWS = {(_r['method'], _r['path']): _r for _r in _V17_REVIEW['operations']}
if (len(_V17_NEW_ROWS) != len(_V17_REVIEW['operations']) or
        {(_r['method'], _r['path']) for _r in INVENTORY}.intersection(_V17_NEW_ROWS)):
    raise ValueError('v17 nav files operation collision')
SOURCE_EVIDENCE.update(_V17_REVIEW['sources'])
INVENTORY.extend(deepcopy(_V17_REVIEW['operations']))
_V5_HANDLERS.update(_V17_REVIEW['handler_source_replacements'])
_V5_HANDLERS.update(_V17_REVIEW['new_handler_sources'])
_V17_ENDPOINTS = frozenset(_r['endpoint'] for _r in
    [*_V17_REVIEW['operation_source_updates'], *_V17_REVIEW['operations']])
WEBSOCKET_DECLARATIONS = deepcopy(_V17_REVIEW['websockets'])
# v18 closes only the missing validation evidence on 23 new v17 HTTP rows.
# Reuse existing reviewed bytes: no source replacement, DTO or runtime change.
_V18_TEXT = (_BASE / 'api_response_v18_nav_files_validation_review.json').read_text()
_V18_NAV_FILES_VALIDATION_REVIEW = json.loads(_V18_TEXT)
_V18_REVIEW = _V18_NAV_FILES_VALIDATION_REVIEW
_V18_ADDITIONS = ['app/validation_errors.py:response-projection',
                  'main.py@v11-review@v17-nav-files']
_V18_BEFORE = [_r for _r in _V17_REVIEW['operations'] if _r['request_validation']]
if (_V18_REVIEW['version'] != 18 or _V18_REVIEW['source_approval'] is not True or
        _V18_REVIEW['release_approval'] is not False or
        _V18_REVIEW['sources'] != {} or _V18_REVIEW['operations'] != [] or
        _V18_REVIEW['source_additions'] != _V18_ADDITIONS or
        _V18_REVIEW['source_preconditions'] != {
            _s: SOURCE_EVIDENCE[_s] for _s in _V18_ADDITIONS} or
        len(_V18_BEFORE) != 23 or
        [(_r['method'], _r['path'], _r['endpoint']) for _r in
         _V18_REVIEW['operation_source_updates']] !=
        [(_r['method'], _r['path'], _r['endpoint']) for _r in _V18_BEFORE]):
    raise ValueError('v18 nav files validation scope/source precondition drift')
_V18_ACTIVE = {(_r['method'], _r['path']): _r for _r in INVENTORY}
for _before, _update in zip(_V18_BEFORE, _V18_REVIEW['operation_source_updates'], strict=True):
    _operation = _V18_ACTIVE[_before['method'], _before['path']]
    if (_operation != _before or _update['before_operation'] != _operation or
            _update['before_sources'] != _operation['sources'] or
            _update['sources'] != sorted(set(_operation['sources']) | set(_V18_ADDITIONS))):
        raise ValueError('v18 nav files validation exact before operation/source union drift')
# The semantic guards above remain independently exercised by damage tests.
if _review_hashlib.sha256(_V18_TEXT.encode()).hexdigest() != '6fd0076187200906416dcfb155e06cdc73e162b2afde7cf0f587e194d2e8a232':
    raise ValueError('v18 nav files validation immutable review drift')
for _update in _V18_REVIEW['operation_source_updates']:
    _V18_ACTIVE[_update['method'], _update['path']]['sources'] = list(_update['sources'])
_V18_ENDPOINTS = frozenset(_r['endpoint'] for _r in _V18_BEFORE)
# Candidate v19 source union: pending independent acceptance, NOT release approval.
# source_approval is the historical loader format, not the author's signature.
_V19_TEXT = (_BASE / 'api_response_v19_unified_files_review.json').read_text()
if _review_hashlib.sha256(_V19_TEXT.encode()).hexdigest() != '8beb2030ad77a5773bc43d2195337cdec9f7dc3ce0861a630383821bee2317a9':
    raise ValueError('v19 unified files immutable candidate drift')
_V19_REVIEW = json.loads(_V19_TEXT)
for _key, _expected in _V19_REVIEW['source_link_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v19 unified files authority source precondition drift')
_V19_ACTIVE = {s for r in [*INVENTORY, *WEBSOCKET_DECLARATIONS] for s in r['sources']
               if SOURCE_EVIDENCE.get(s, {}).get('file') in _V19_REVIEW['scope_files']}
if (len(_V19_ACTIVE) != 114 or set(_V19_REVIEW['source_preconditions']) != _V19_ACTIVE or
        set(_V19_REVIEW['source_replacements']) != _V19_ACTIVE or
        set(_V19_REVIEW['sources']) != set(_V19_REVIEW['source_replacements'].values()) | set(_V19_REVIEW['new_source_keys']) or
        set(SOURCE_EVIDENCE).intersection(_V19_REVIEW['sources'])):
    raise ValueError('v19 unified files source scope drift')
for _key, _expected in _V19_REVIEW['source_preconditions'].items():
    if SOURCE_EVIDENCE.get(_key) != _expected:
        raise ValueError('v19 unified files source precondition drift')
_V19_ROWS = {(_r['method'], _r['path']): _r for _r in _V19_REVIEW['operation_source_updates']}
if (len(_V19_ROWS) != len(_V19_REVIEW['operation_source_updates']) or
        set(_V19_ROWS) != {(_r['method'], _r['path']) for _r in INVENTORY
                         if _V19_ACTIVE.intersection(_r['sources'])}):
    raise ValueError('v19 unified files operation scope drift')
for _operation in INVENTORY:
    _update = _V19_ROWS.get((_operation['method'], _operation['path']))
    if _update is not None:
        if (_operation != _update['before_operation'] or _update['before_sources'] != _operation['sources'] or
                _update['endpoint'] != _operation['endpoint'] or
                _update['sources'] != sorted({_V19_REVIEW['source_replacements'].get(s, s)
                    for s in _operation['sources']} | set(_update['source_additions'])) or
                _update['operation'] != {**_operation, 'sources': _update['sources']}):
            raise ValueError('v19 unified files exact operation/source union drift')
        _operation['sources'] = list(_update['sources'])
for _endpoint, _expected in _V19_REVIEW['handler_source_preconditions'].items():
    if _V5_HANDLERS.get(_endpoint, _endpoint) != _expected:
        raise ValueError('v19 unified files handler precondition drift')
_V19_NEW_ROWS = {(_r['method'], _r['path']): _r for _r in _V19_REVIEW['operations']}
if (len(_V19_REVIEW['operations']) != 1 or set(_V19_NEW_ROWS) != {('GET', '/agent/files/config')} or
        {(_r['method'], _r['path']) for _r in INVENTORY}.intersection(_V19_NEW_ROWS)):
    raise ValueError('v19 unified files new operation collision/scope drift')
SOURCE_EVIDENCE.update(_V19_REVIEW['sources'])
INVENTORY.extend(deepcopy(_V19_REVIEW['operations']))
_V5_HANDLERS.update(_V19_REVIEW['handler_source_replacements'])
_V5_HANDLERS.update(_V19_REVIEW['new_handler_sources'])
_V19_ENDPOINTS = frozenset(_r['endpoint'] for _r in
    [*_V19_REVIEW['operation_source_updates'], *_V19_REVIEW['operations']])
# v20 changes only the fnOS automatic-policy predicate's service source pins.
# No DTO, operation, Agent artifact or release approval changes.
_V20_TEXT = (_BASE / 'api_response_v20_fnos_policy_review.json').read_text()
_V20_REVIEW = json.loads(_V20_TEXT)
_V20_ACTIVE = {s for r in [*INVENTORY, *WEBSOCKET_DECLARATIONS] for s in r['sources']
               if SOURCE_EVIDENCE.get(s, {}).get('file') == 'app/services/node_files.py'}
if (_V20_REVIEW['version'] != 20 or _V20_REVIEW['source_approval'] is not True or
        _V20_REVIEW['release_approval'] is not False or
        _V20_REVIEW['scope_files'] != ['app/services/node_files.py'] or
        _V20_REVIEW['operations'] != [] or _V20_REVIEW['models'] != {} or
        len(_V20_ACTIVE) != 13 or set(_V20_REVIEW['source_preconditions']) != _V20_ACTIVE or
        set(_V20_REVIEW['source_replacements']) != _V20_ACTIVE or
        set(_V20_REVIEW['sources']) != set(_V20_REVIEW['source_replacements'].values()) or
        set(SOURCE_EVIDENCE).intersection(_V20_REVIEW['sources']) or
        any(SOURCE_EVIDENCE[k] != v for k, v in _V20_REVIEW['source_preconditions'].items())):
    raise ValueError('v20 fnos policy source scope/precondition drift')
_V20_ROWS = {(_r['method'], _r['path']): _r for _r in _V20_REVIEW['operation_source_updates']}
if (len(_V20_ROWS) != len(_V20_REVIEW['operation_source_updates']) or
        set(_V20_ROWS) != {(_r['method'], _r['path']) for _r in INVENTORY
                         if _V20_ACTIVE.intersection(_r['sources'])}):
    raise ValueError('v20 fnos policy operation scope drift')
for _operation in INVENTORY:
    _update = _V20_ROWS.get((_operation['method'], _operation['path']))
    if _update is not None:
        if (_operation != _update['before_operation'] or
                _operation['sources'] != _update['before_sources'] or
                _operation['endpoint'] != _update['endpoint'] or
                _update['sources'] != sorted(_V20_REVIEW['source_replacements'].get(s, s)
                                             for s in _operation['sources']) or
                _update['operation'] != {**_operation, 'sources': _update['sources']}):
            raise ValueError('v20 fnos policy exact operation/source union drift')
if _review_hashlib.sha256(_V20_TEXT.encode()).hexdigest() != '96c47ca8ec9f5dab1310346f8d057c59e12b2d5037e38513b62b4daf1663cbbd':
    raise ValueError('v20 fnos policy immutable candidate drift')
for _operation in INVENTORY:
    if (_operation['method'], _operation['path']) in _V20_ROWS:
        _operation['sources'] = list(_V20_ROWS[_operation['method'], _operation['path']]['sources'])
SOURCE_EVIDENCE.update(_V20_REVIEW['sources'])
# v21 binds the already implemented .20 refresh-timeout source, not new API
# behavior. Format compatibility is not independent review or release approval.
_V21_TEXT = (_BASE / 'api_response_v21_refresh_timeout_review.json').read_text()
_V21_REVIEW = json.loads(_V21_TEXT)
_V21_SCOPE = ['agent/stella_agent.py', 'app/routers/monitor.py']
_V21_NEW_KEY = 'agent.stella_agent._FileNetworkTimeout@v21-refresh-timeout'
_V21_ACTIVE = {s for r in [*INVENTORY, *WEBSOCKET_DECLARATIONS] for s in r['sources']
               if SOURCE_EVIDENCE.get(s, {}).get('file') in _V21_SCOPE}
if (_V21_REVIEW['version'] != 21 or _V21_REVIEW['source_approval'] is not True or
        _V21_REVIEW['release_approval'] is not False or
        _V21_REVIEW['scope_files'] != _V21_SCOPE or
        _V21_REVIEW['operations'] != [] or _V21_REVIEW['models'] != {} or
        _V21_REVIEW['new_source_keys'] != [_V21_NEW_KEY] or
        len(_V21_ACTIVE) != 102 or set(_V21_REVIEW['source_preconditions']) != _V21_ACTIVE or
        set(_V21_REVIEW['source_replacements']) != _V21_ACTIVE or
        set(_V21_REVIEW['sources']) != set(_V21_REVIEW['source_replacements'].values()) | {_V21_NEW_KEY} or
        set(SOURCE_EVIDENCE).intersection(_V21_REVIEW['sources']) or
        any(SOURCE_EVIDENCE[k] != v for k, v in _V21_REVIEW['source_preconditions'].items())):
    raise ValueError('v21 refresh timeout source scope/precondition drift')
_V21_HANDLERS = {e: k for e, k in _V5_HANDLERS.items() if k in _V21_ACTIVE}
if (_V21_REVIEW['handler_source_preconditions'] != _V21_HANDLERS or
        _V21_REVIEW['handler_source_replacements'] != {
            e: _V21_REVIEW['source_replacements'][k] for e, k in _V21_HANDLERS.items()}):
    raise ValueError('v21 refresh timeout handler precondition/successor drift')
_V21_ROWS = {(_r['method'], _r['path']): _r for _r in _V21_REVIEW['operation_source_updates']}
if (len(_V21_ROWS) != 107 or len(_V21_ROWS) != len(_V21_REVIEW['operation_source_updates']) or
        set(_V21_ROWS) != {(_r['method'], _r['path']) for _r in INVENTORY
                         if _V21_ACTIVE.intersection(_r['sources'])}):
    raise ValueError('v21 refresh timeout operation scope drift')
for _operation in INVENTORY:
    _update = _V21_ROWS.get((_operation['method'], _operation['path']))
    if _update is not None:
        _additions = [_V21_NEW_KEY] if any(SOURCE_EVIDENCE[s]['file'] == _V21_SCOPE[0]
                                         for s in _operation['sources']) else []
        if (_operation != _update['before_operation'] or
                _operation['sources'] != _update['before_sources'] or
                _operation['endpoint'] != _update['endpoint'] or
                _update['source_additions'] != _additions or
                _update['sources'] != sorted({_V21_REVIEW['source_replacements'].get(s, s)
                                             for s in _operation['sources']} | set(_additions)) or
                _update['operation'] != {**_operation, 'sources': _update['sources']}):
            raise ValueError('v21 refresh timeout exact operation/source union drift')
if _review_hashlib.sha256(_V21_TEXT.encode()).hexdigest() != 'c1f31ea58a78205bcda43f1ff2c78e7df4278a4312c2b64b8297635b031fd73b':
    raise ValueError('v21 refresh timeout immutable candidate drift')
for _operation in INVENTORY:
    if (_operation['method'], _operation['path']) in _V21_ROWS:
        _operation['sources'] = list(_V21_ROWS[_operation['method'], _operation['path']]['sources'])
SOURCE_EVIDENCE.update(_V21_REVIEW['sources'])
_V5_HANDLERS.update(_V21_REVIEW['handler_source_replacements'])
# v22 reconciles the approved private remediation source delta. Compatibility
# admission is not independent review, CI, image or release approval.
_V22_TEXT = (_BASE / 'api_response_v22_private_remediation_review.json').read_text()
_V22_REVIEW = json.loads(_V22_TEXT)
_V22_SCOPE = ['app/routers/integrations.py', 'app/routers/website_settings.py',
              'app/services/access_entries.py', 'app/services/ha_readiness.py',
              'app/services/integrations.py', 'app/services/openlist_compat.py',
              'app/services/website_settings.py', 'frontend/src/api/websiteSettings.ts',
              'frontend/src/modules/settings/WebsiteSettings.vue',
              'frontend/src/shell/ExternalModuleCache.vue', 'frontend/src/stores/navigation.ts']
_V22_ACTIVE = {s for r in [*INVENTORY, *WEBSOCKET_DECLARATIONS] for s in r['sources']
               if SOURCE_EVIDENCE.get(s, {}).get('file') in _V22_SCOPE}
_V22_NEW_HANDLER = 'app.routers.website_settings.receipt@v22-private-remediation'
if (_V22_REVIEW['version'] != 22 or _V22_REVIEW['source_approval'] is not True or
        _V22_REVIEW['release_approval'] is not False or
        _V22_REVIEW['status'] != 'PENDING_INDEPENDENT_REVIEW_NOT_APPROVED' or
        _V22_REVIEW['scope_files'] != _V22_SCOPE or len(_V22_ACTIVE) != 54 or
        set(_V22_REVIEW['source_preconditions']) != _V22_ACTIVE or
        set(_V22_REVIEW['source_replacements']) != _V22_ACTIVE or
        len(_V22_REVIEW['new_source_keys']) != 13 or
        len(set(_V22_REVIEW['new_source_keys'])) != 13 or
        set(_V22_REVIEW['sources']) != set(_V22_REVIEW['source_replacements'].values()) | set(_V22_REVIEW['new_source_keys']) or
        set(SOURCE_EVIDENCE).intersection(_V22_REVIEW['sources']) or
        any(SOURCE_EVIDENCE[k] != v for k, v in _V22_REVIEW['source_preconditions'].items())):
    raise ValueError('v22 private remediation source scope/precondition drift')
_V22_HANDLERS = {e: k for e, k in _V5_HANDLERS.items() if k in _V22_ACTIVE}
if (_V22_REVIEW['handler_source_preconditions'] != _V22_HANDLERS or
        _V22_REVIEW['handler_source_replacements'] != {
            e: _V22_REVIEW['source_replacements'][k] for e, k in _V22_HANDLERS.items()} or
        _V22_REVIEW['new_handler_sources'] != {'app.routers.website_settings.receipt': _V22_NEW_HANDLER}):
    raise ValueError('v22 private remediation handler precondition/successor drift')
_V22_ROWS = {(r['method'], r['path']): r for r in _V22_REVIEW['operation_source_updates']}
if (len(_V22_ROWS) != 68 or len(_V22_ROWS) != len(_V22_REVIEW['operation_source_updates']) or
        set(_V22_ROWS) != {(r['method'], r['path']) for r in INVENTORY if _V22_ACTIVE.intersection(r['sources'])}):
    raise ValueError('v22 private remediation operation scope drift')
for _operation in INVENTORY:
    _update = _V22_ROWS.get((_operation['method'], _operation['path']))
    if _update is not None:
        _owned = {SOURCE_EVIDENCE.get(s, {}).get('file') for s in _operation['sources']}
        _additions = sorted(k for k in _V22_REVIEW['new_source_keys']
                            if _V22_REVIEW['sources'][k]['file'] in _owned and k != _V22_NEW_HANDLER)
        if (_operation != _update['before_operation'] or
                _operation['sources'] != _update['before_sources'] or
                _operation['endpoint'] != _update['endpoint'] or
                _update['source_additions'] != _additions or
                _update['sources'] != sorted({_V22_REVIEW['source_replacements'].get(s, s)
                                             for s in _operation['sources']} | set(_additions)) or
                _update['operation'] != {**_operation, 'sources': _update['sources']}):
            raise ValueError('v22 private remediation exact operation/source union drift')
if (_review_hashlib.sha256(_V22_TEXT.encode()).hexdigest() != 'd93542ae89b386a5325ec7ec8616f5e7f33d92aa66d2a40ac8f0a5df087d0b82' or
        [(r['method'], r['path'], r['endpoint']) for r in _V22_REVIEW['operations']] !=
        [('GET', '/website-settings/{mid}/receipt', 'app.routers.website_settings.receipt')]):
    raise ValueError('v22 private remediation immutable candidate/new operation drift')
for _operation in INVENTORY:
    if (_operation['method'], _operation['path']) in _V22_ROWS:
        _operation['sources'] = list(_V22_ROWS[_operation['method'], _operation['path']]['sources'])
SOURCE_EVIDENCE.update(_V22_REVIEW['sources'])
_V5_HANDLERS.update(_V22_REVIEW['handler_source_replacements'])
_V5_HANDLERS.update(_V22_REVIEW['new_handler_sources'])
INVENTORY.extend(deepcopy(_V22_REVIEW['operations']))
# v23: independently reviewed exact final SQL-offload/cache source; no release approval.
_V23_TEXT = (_BASE / 'api_response_v23_final_offload_review.json').read_text()
if _review_hashlib.sha256(_V23_TEXT.encode()).hexdigest() != '179a95e5cc73def47e2b7c7b79c97366c700bd1f8f2b5b227e5ce61020b30ed1':
    raise ValueError('v23 final offload immutable overlay drift')
_V23_REVIEW = json.loads(_V23_TEXT)
_V23_SCOPE = ['agent/node_files_delivery.py', 'app/routers/integrations_host.py', 'app/routers/website_settings.py', 'app/services/access_entries.py', 'app/services/website_settings.py']
_V23_ACTIVE = {s for r in [*INVENTORY, *WEBSOCKET_DECLARATIONS] for s in r['sources']
               if SOURCE_EVIDENCE.get(s, {}).get('file') in _V23_SCOPE}
if (_V23_REVIEW['version'] != 23 or _V23_REVIEW['source_approval'] is not True or
        _V23_REVIEW['release_approval'] is not False or
        _V23_REVIEW['status'] != 'INDEPENDENT_BOUNDED_SOURCE_REVIEW_PASS_NOT_RELEASE_APPROVAL' or
        _V23_REVIEW['baseline'] != '22a55697cb83c41b4d7dd39e601fe1105d8b47f6' or
        _V23_REVIEW['candidate'] != 'f8643fdd08efa85ac442abe2d526883021a01928' or
        _V23_REVIEW['scope_files'] != _V23_SCOPE or len(_V23_ACTIVE) != 23 or
        _V23_REVIEW['operations'] != [] or _V23_REVIEW['models'] != {} or
        _V23_REVIEW['new_source_keys'] != [] or
        set(_V23_REVIEW['source_preconditions']) != _V23_ACTIVE or
        set(_V23_REVIEW['source_replacements']) != _V23_ACTIVE or
        len(set(_V23_REVIEW['source_replacements'].values())) != 23 or
        set(_V23_REVIEW['sources']) != set(_V23_REVIEW['source_replacements'].values()) or
        set(SOURCE_EVIDENCE).intersection(_V23_REVIEW['sources']) or
        any(SOURCE_EVIDENCE[k] != v for k,v in _V23_REVIEW['source_preconditions'].items())):
    raise ValueError('v23 final offload exact scope/preconditions drift')
_V23_HANDLERS = {e:k for e,k in _V5_HANDLERS.items() if k in _V23_ACTIVE}
if (_V23_REVIEW['handler_source_preconditions'] != _V23_HANDLERS or
        _V23_REVIEW['handler_source_replacements'] != {
            e:_V23_REVIEW['source_replacements'][k] for e,k in _V23_HANDLERS.items()}):
    raise ValueError('v23 final offload exact handler successors drift')
_V23_ROWS = {(r['method'],r['path']):r for r in _V23_REVIEW['operation_source_updates']}
if (len(_V23_ROWS) != 68 or len(_V23_REVIEW['operation_source_updates']) != 68 or
        set(_V23_ROWS) != {(r['method'],r['path']) for r in INVENTORY if _V23_ACTIVE.intersection(r['sources'])}):
    raise ValueError('v23 final offload exact operation scope drift')
for _operation in INVENTORY:
    _update = _V23_ROWS.get((_operation['method'],_operation['path']))
    if _update is not None:
        if (_operation != _update['before_operation'] or
                _operation['sources'] != _update['before_sources'] or
                _operation['endpoint'] != _update['endpoint'] or
                _update['source_additions'] != [] or
                _update['sources'] != sorted(_V23_REVIEW['source_replacements'].get(s,s) for s in _operation['sources']) or
                _update['operation'] != {**_operation,'sources':_update['sources']}):
            raise ValueError('v23 final offload exact before/after operation union drift')
        _operation['sources'] = list(_update['sources'])
SOURCE_EVIDENCE.update(_V23_REVIEW['sources'])
_V5_HANDLERS.update(_V23_REVIEW['handler_source_replacements'])

# v24 preserves every earlier source record and advances only the audited files.
_V24_TEXT = (_BASE / 'api_response_v24_servers_audit_review.json').read_text()
if _review_hashlib.sha256(_V24_TEXT.encode()).hexdigest() != 'fea8cfe9e08568d9ea62706da4172444b0c3ee601d19e89ab244fc1b5b14bc57':
    raise ValueError('v24 servers audit immutable overlay drift')
_V24_REVIEW = json.loads(_V24_TEXT)
_V24_ACTIVE = {s for r in [*INVENTORY, *WEBSOCKET_DECLARATIONS] for s in r['sources']
               if s in _V24_REVIEW['source_preconditions']}
if (_V24_REVIEW['version'] != 24 or _V24_REVIEW['release_approval'] is not False or
        len(_V24_ACTIVE) != 139 or set(_V24_REVIEW['source_preconditions']) != _V24_ACTIVE or
        set(_V24_REVIEW['source_replacements']) != _V24_ACTIVE or
        any(SOURCE_EVIDENCE[k] != v for k, v in _V24_REVIEW['source_preconditions'].items()) or
        len(set(_V24_REVIEW['source_replacements'].values())) != 139 or
        _V24_REVIEW['new_source_keys'] != ['app.services.task._require_mtr_node@v24-servers-audit'] or
        set(_V24_REVIEW['sources']) != set(_V24_REVIEW['source_replacements'].values()) | set(_V24_REVIEW['new_source_keys']) or
        set(SOURCE_EVIDENCE).intersection(_V24_REVIEW['sources']) or
        _V24_REVIEW['operations'] != [] or _V24_REVIEW['models'] != {}):
    raise ValueError('v24 servers audit source precondition drift')
_V24_HANDLERS = {e: k for e, k in _V5_HANDLERS.items() if k in _V24_ACTIVE}
if (_V24_REVIEW['handler_source_preconditions'] != _V24_HANDLERS or
        _V24_REVIEW['handler_source_replacements'] != {e: _V24_REVIEW['source_replacements'][k] for e, k in _V24_HANDLERS.items()}):
    raise ValueError('v24 servers audit handler drift')
_V24_ROWS = {(u['method'], u['path']): u for u in _V24_REVIEW['operation_source_updates']}
if (len(_V24_ROWS) != 107 or len(_V24_REVIEW['operation_source_updates']) != 107 or
        set(_V24_ROWS) != {(r['method'], r['path']) for r in INVENTORY if _V24_ACTIVE.intersection(r['sources'])}):
    raise ValueError('v24 servers audit operation scope drift')
for _operation in INVENTORY:
    _update = _V24_ROWS.get((_operation['method'], _operation['path']))
    if _update is not None:
        _additions = _V24_REVIEW['new_source_keys'] if any(SOURCE_EVIDENCE.get(s, {}).get('symbol') in
            ['app.services.task.create_mtr_job', 'app.services.task.create_mtr_for_monitor'] for s in _operation['sources']) else []
        if (_operation != _update['before_operation'] or _operation['sources'] != _update['before_sources'] or
                _operation['endpoint'] != _update['endpoint'] or _update['source_additions'] != _additions or
                _update['sources'] != sorted({_V24_REVIEW['source_replacements'].get(s, s) for s in _operation['sources']} | set(_additions)) or
                _update['operation'] != {**_operation, 'sources': _update['sources']}):
            raise ValueError('v24 servers audit exact source union drift')
        _operation['sources'] = list(_update['sources'])
SOURCE_EVIDENCE.update(_V24_REVIEW['sources'])
_V5_HANDLERS.update(_V24_REVIEW['handler_source_replacements'])

MODELS = json.loads((_BASE / 'api_response_models.json').read_text())
MODELS.update(_INTEGRATED['models'])
MODELS.update(_ENTRY_MONITORING['models'])
MODELS.update(_ROUND4_REVIEW['models'])
MODELS.update(_V5_REVIEW['models'])
MODELS.update(_V6_REVIEW['models'])
MODELS.update(_V8_REVIEW['models'])
MODELS.update(_V11_REVIEW['models'])
MODELS.update(_V12_REVIEW['models'])
MODELS.update(_V14_CI167_REVIEW['models'])
if set(MODELS).intersection(_V16_MONITOR_UX_REVIEW['models']):
    raise ValueError('v16 monitor UX model collision')
MODELS.update(_V16_MONITOR_UX_REVIEW['models'])
if set(MODELS).intersection(_V17_REVIEW['models']):
    raise ValueError('v17 nav files model collision')
MODELS.update(deepcopy(_V17_REVIEW['models']))
if set(MODELS).intersection(_V19_REVIEW['models']):
    raise ValueError('v19 unified files model collision')
MODELS.update(deepcopy(_V19_REVIEW['models']))
if set(MODELS).intersection(_V22_REVIEW['models']):
    raise ValueError('v22 private remediation model collision')
MODELS.update(deepcopy(_V22_REVIEW['models']))
VALIDATION_ITEM = MODELS['PublicValidationItem']
# The shared global/private builder emits only loc/type/msg. Explicit business
# HTTPException details remain separate and are not a global redaction promise.
VALIDATION_ERROR = obj(detail={'anyOf': [DETAIL, array(VALIDATION_ITEM)]})


def _replace_frontmatter(schema):
    """Document frontmatter really is JSONB; constrain values to JSON, not Any."""
    schema = deepcopy(schema)
    def visit(value):
        if isinstance(value, dict):
            if 'frontmatter' in value.get('properties', {}):
                value['properties']['frontmatter'] = nullable(JSON_OBJECT)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema)
    if '#/$defs/JsonValue' in json.dumps(schema):
        schema.setdefault('$defs', {}).setdefault('JsonValue', JSON_VALUE)
    return schema


def schema_holes(value, path='$'):
    """Identify unconstrained schema nodes, not arbitrary example/default objects."""
    holes = []
    if value == {} or value is True:
        return [path]
    if not isinstance(value, dict):
        return holes
    if value.get('type') == 'object' and not value.get('properties') and value.get('additionalProperties') is not False and not isinstance(value.get('additionalProperties'), dict):
        holes.append(path)
    if value.get('additionalProperties') is True:
        holes.append(path + '.additionalProperties')
    for key in ('properties', '$defs'):
        for name, child in value.get(key, {}).items():
            holes.extend(schema_holes(child, f'{path}.{key}.{name}'))
    for key in ('items', 'additionalProperties'):
        if key in value and value[key] is not False:
            holes.extend(schema_holes(value[key], f'{path}.{key}'))
    for key in ('anyOf', 'oneOf', 'allOf'):
        for i, child in enumerate(value.get(key, [])):
            holes.extend(schema_holes(child, f'{path}.{key}[{i}]'))
    return sorted(set(holes))


# Separate unfiltered ORM serialization from DocumentRead: PUT includes persisted
# draft_content/deleted_at/last_viewed_at, and does NOT invent has_draft.
DOCUMENT_ORM = obj(id=S, title=S, file_path=S, content=nullable(S), deleted_at=nullable(DATE),
    frontmatter=nullable(JSON_OBJECT), is_folder=B, visibility=S, is_pinned=B, is_favorite=B,
    status=S, word_count=nullable(I), content_hash=S, created_at=DATE, updated_at=DATE,
    updated_at_display=nullable(DATE),
    last_viewed_at=nullable(DATE), workspace_id=S, parent_id=nullable(S), draft_content=nullable(S),
    draft_updated_at=nullable(DATE), draft_device=nullable(S))
DOCUMENT_ORM['$defs'] = {'JsonValue': JSON_VALUE}

# Endpoint-name registrations below bind ONLY to exact frozen inventory rows.
# A newly added method/path, even with the same callable, stays unclassified.
SUCCESS = {}
DESCRIPTIONS = {row['endpoint']: row['review'] for row in _BACKUPS['operations']}
EXTRA_SOURCES = {}


def success(module, names, schema, description, *sources):
    for name in names.split():
        endpoint = 'app.routers.' + module + '.' + name
        SUCCESS[endpoint] = schema
        DESCRIPTIONS[endpoint] = description
        EXTRA_SOURCES[endpoint] = sources


success('attachment', 'upload', UPLOAD, 'Attachment reference; identical fields on idempotent replay.')
success('attachment', 'list_attachments', array(obj(**UPLOAD['properties'], mime=S, size=I, created_at=DATE,
    doc_id=S, doc_title=S, doc_in_trash=B)), 'Workspace document-bound attachment metadata including trash. Inner join excludes detached rows: doc_id stays non-null in this API; server-owned owner_id is never serialized.')
success('document', 'update_one', DOCUMENT_ORM, 'Unfiltered persisted document fields, including draft slots; no response_model filtering.', 'app/models/document.py')
success('document', 'preview_zip', ZIP_PREVIEW, 'Bounded ZIP preview; directory/document/attachment entries and unresolved-link warnings.')
success('document', 'import_zip', ZIP_IMPORT, 'Committed import result; reused=true on receipt replay, false on first commit.')
HTML_CONVERSION = obj(documents=array(obj(source=S,target=S,title=S,losses=array(S),markdown=S)),converted_count=I,original_path=S,source_sha256=S,warnings=array(S))
TEMPLATE_CATALOG = obj(root_id=nullable(S),items=array(obj(id=S,parent_id=S,title=S,is_folder=B)),recent_ids=array(S))
success('document', 'preview_html', HTML_CONVERSION, 'Inert bounded HTML conversion preview, explicit layout/script loss and retained original archive identity.')
success('document', 'import_html', obj(**ZIP_IMPORT['properties'],conversion=HTML_CONVERSION), 'Transactional converted notes and independent attachments; original bytes retained, idempotent replay supported.')
success('notes_tools', 'initialize_templates list_templates', TEMPLATE_CATALOG, 'Server-owned template root and currently valid descendants; up to two recent successful templates.')
success('notes_tools', 'copy_template save_template', _replace_frontmatter(MODELS['DocumentRead']), 'Independent copied document, latest template membership checked under document graph lock.')
# Project APIs return JSON metadata, never executable resource bytes. The latter
# are host middleware /p/<capability>/<path>, not mounted OpenAPI operations.
PROJECT_FILE = obj(id=S, path=S, kind={'enum': ['text', 'binary'], 'type': 'string'}, mime=S,
    size={'type': 'integer', 'minimum': 0}, updated_at=S)  # raw ISO CAS, not a display event
PROJECT_DIRECTORY = obj(id=S, path=S, kind={'const': 'directory'})
PROJECT_MANIFEST = obj(id=S, workspace_id=S, title=S, entry=nullable(S), entry_file_id=nullable(S),
    files=array(PROJECT_FILE), directories=array(PROJECT_DIRECTORY))
PROJECT_RENEWAL = obj(capability={'type': 'string', 'pattern': '^[A-Za-z0-9_-]{43}$'},
    epoch={'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991},
    expires_in={'const': 900, 'type': 'integer'}, renew_after={'const': 840, 'type': 'integer'})
DETACHED_ITEM = obj(id=S, workspace_id=S, title=S, kind={'const': 'detached-source'}, mime=S, updated_at=S)
DETACHED_SOURCE = obj(**DETACHED_ITEM['properties'], content=S)
PROJECT_STATE = obj(revision={'type': 'integer', 'minimum': 0}, epoch={'type': 'integer', 'minimum': 0},
    data={'type': 'object', 'additionalProperties': S, 'maxProperties': 1000,
          'description': 'User webpage localStorage strings; serialized UTF-8 JSON budget 1 MiB. No IndexedDB or JS heap snapshot.'})
PROJECT_SOURCE = {'oneOf': [
    obj(**{**PROJECT_FILE['properties'], 'kind': {'const': 'text'}}, content=S, url=N),
    obj(**{**PROJECT_FILE['properties'], 'kind': {'const': 'binary'}}, content=N, url=S)]}
success('web_projects', 'catalog', array(PROJECT_MANIFEST), 'Owner workspace active project manifests; no original attachment IDs or grant internals.')
success('web_projects', 'preview', obj(files=array(obj(path=S, size={'type': 'integer', 'minimum': 0},
    kind={'enum': ['text', 'binary'], 'type': 'string'})), entries=array(S), suggested_entry=nullable(S), warnings=array(S)),
    'Bounded ZIP/HTML metadata preview; multiple non-index HTML candidates require explicit choice. No project is written.')
success('web_projects', 'import_project', obj(id=S, reused=B), 'HTTP 200 on first import and exact receipt replay; not a full manifest. UUID encoded as string.')
success('web_projects', 'manifest', PROJECT_MANIFEST, 'Current relative paths; entry is null after moving/deleting entry out of the active project. Invalid/duplicate paths fail 409.')
success('web_projects', 'source', PROJECT_SOURCE, 'Text content with null URL, or binary metadata with null content and owner-authenticated attachment URL; not resource bytes.')
success('web_projects', 'update_source', obj(id=S, updated_at=S, content=S), 'Saved source and raw ISO CAS token; invalid version 422, binary or stale version 409. No automatic runtime reload.')
success('web_projects', 'state', PROJECT_STATE, 'Owner state projection; absent state is revision=epoch=0, data={}. Internal write_id/digest are omitted.')
success('web_projects', 'write_state', PROJECT_STATE, 'Cookie owner plus exact Origin and project/session/epoch-bound capability, revalidated under locks. Exact write receipt replay returns same state; stale/different replay 409.')
success('web_projects', 'reset', PROJECT_STATE, 'HTTP 200 JSON, not 204: revision and epoch increment; data cleared, files unchanged. Previous runtime grants become invalid.')
success('web_projects', 'launch', obj(url=S, capability={'type': 'string', 'pattern': '^[A-Za-z0-9_-]{43}$'},
    source_origin=S, target_origin=S, state=PROJECT_STATE, expires_in={'const': 900, 'type': 'integer'}),
    'Owner cookie, presented live session and exact Origin required. Registered separate runtime origin, 900-second opaque grant, current state; not redirect or bootstrap POST fields. Supersedes same-session/project grant; no user credentials in runtime URL.')
success('web_projects', 'copy_asset', UPLOAD, 'Independent target-note attachment reference; same request ID/scope replay returns identical fields, not a reused flag.')
success('web_projects', 'renew', PROJECT_RENEWAL, 'In-place renewal of the same capability; live original owner SID, exact Origin, target and epoch rechecked after locks. Expired access remains denied during 300s renewal grace. Never creates a missing grant, returns state, reloads iframe, or changes source.')
success('project_files', 'update_entry', PROJECT_MANIFEST, 'Owner-locked entry CAS: expected_entry_file_id required but nullable; stale token or non-member/non-HTML/binary candidate 409. Returns full current manifest, no runtime reload.')
success('detached_sources', 'catalog', array(DETACHED_ITEM), 'Owner workspace private active detached text source identities; no source text, original path, root/owner provenance or grant internals.')
success('detached_sources', 'read save', DETACHED_SOURCE, 'Same original private Document identity and raw ISO CAS. PUT returns full source projection; Unicode/NUL 422, UTF-8 >5 MiB 413, stale CAS 409. No owner_id/source_root_id/original_path metadata.')
success('document', 'finalize_import', obj(synced=I), 'Number of imported documents whose links were synchronized.')
success('document', 'empty_trash_endpoint', obj(purged=I), 'Count of permanently removed trash documents.')
success('document', 'clear_all_endpoint', obj(trashed=I), 'Count moved to trash, not a permanent deletion.')
success('document', 'restore_one', obj(doc=_replace_frontmatter(MODELS['DocumentRead']), reattached=B, restored=I),
    'Restored document, root reattachment flag and restored count.')
success('document_version', 'diff_version', obj(version_id=S, against=nullable(S), diff=S), 'Unified text diff against current document or explicit version.')
success('notes_tools', 'read_node link_node', obj(node_id=nullable(I)), 'Linked node ID, or null when no node is associated.')
success('auth', 'register login refresh me update_profile upload_avatar login_by_code verify_email_code pick_avatar', USER,
    'Owner profile projection; session issuance/rotation is conveyed separately by Set-Cookie.')
success('auth', 'security', SECURITY, 'Compatibility status for authenticated owner; no independent management protection or grant.')
success('auth', 'update_security change_management_password admin_setup admin_lock logout revoke_session', OK, 'Operation acknowledgement.')
success('auth', 'status', obj(has_users=B, initialized=B, email_enabled=B, single_user=B), 'Single-owner initialization and email availability.')
success('auth', 'activity', obj(ok=B, expires_at=DATE), 'Explicit activity acknowledgement and session expiry.')
success('auth', 'change_password reset_password', obj(ok=B, hint=S), 'Password change acknowledgement; all sessions are revoked.')
success('auth', 'email_service_status', obj(ready=B, configured=B, enabled=B), 'Email-service availability, without SMTP credentials.')
success('auth', 'send_email_code forgot_password send_login_code resend_code', MAIL_SENT,
    'Code send acknowledgement; already_sent appears only for an existing valid code.')
success('auth', 'session_location', obj(ip=S, ip_location=nullable(S)), 'Opt-in bounded lookup of an owner session IP; null on unavailable external lookup.', 'app/services/session_location.py')
success('auth', 'my_sessions', array(SESSION), 'Owner-only active sessions, access SID current identity and policy expiry (not online status). current_only bypasses pagination; exclude_current filters before pagination. Reads never extend expiry.')
success('auth', 'session_history', obj(items=array(SESSION_HISTORY), total=I, page=I, page_size=I), 'Owner-only inactive session history page.')
success('admin_email', 'put_config', OK, 'SMTP configuration save acknowledgement, both local and shared-state modes.')
success('admin_email', 'test_mail', obj(ok=B, to=S), 'SMTP test delivery acknowledgement.')
success('alerts', 'create_rule', obj(id=I), 'Created alert rule ID.')
success('alerts', 'patch_rule delete_rule mark_read', OK, 'Alert/notification acknowledgement.')
success('alerts', 'mark_all_read', obj(ok=B, marked=I), 'Bulk-read acknowledgement and affected count.')
success('alerts', 'unread_count', obj(count=I), 'Unread notification count.')
success('alerts', 'list_events', array(obj(id=I, rule_id=I, event=S, ts=DATE, message=S)), 'Alert event records.')
success('alerts', 'list_notifications', array(obj(id=I, rule_id=nullable(I), title=S, body=S, severity=S, kind=S, link=S, read=B, ts=DATE)), 'Notification records.')
success('alerts', 'list_rules', array(optional(obj(id=I, kind=S, target=S, label=S, link=S, severity=S, debounce=I,
    repeat_minutes=I, email=B, enabled=B, created_at=DATE, state=S, last_change_at=nullable(DATE), message=nullable(S),
    wg_manual=nullable(obj(node_id=I,interface=S,target=S,interface_key_id=S,peer_key_id=S)),
    wg_observation=obj(health={'enum':['ok','degraded','failed','unknown']},reason=nullable(S),checked_at=nullable(DATE))),
    'wg_manual','wg_observation')), 'Rules with current state slots and optional bound manual WG observation.')
success('monitor', 'install_command', obj(url=S, token=S, command=S), 'Sensitive single-node install command; no-store.')
success('monitor', 'get_host', obj(os=S, installed=B, local_install_supported=B, node_id=nullable(I), node_status=nullable(S)), 'Local host installation metadata.')
success('monitor', 'agent_report', obj(ok=B, node_id=I, status=S, monitors_version=I), 'Agent report receipt and current node/config state.')
success('monitor', 'agent_mtr_report agent_monitor_check', OK, 'Agent result acknowledgement.')
success('monitor', 'agent_version', {'anyOf': [obj(version=S), obj(version=S, sha256=S, size=I)]}, 'Version-only fallback or script integrity manifest.')
success('task', 'cancel_iperf finish_iperf iperf_progress finish_component finish_net_task mtr_live finish_command finish_uninstall', OK, 'Task acknowledgement.')
success('task', 'get_iperf_status', obj(status=S), 'Current task status.')
success('task', 'finish_mtr', N, 'Implicit JSON null response (not 204).')
success('config', 'get_public_host get_site_background', obj(value=S), 'Configured value, or empty string.')
success('config', 'set_public_host', obj(ok=B, value=S), 'Saved public host value.')
success('homebg', 'delete_homebg', OK, 'Background deletion acknowledgement.')
success('drive', 'status', obj(configured=B, auth_mode=S), 'Drive configuration status.')
success('drive', 'connection save_connection', obj(service_url=S, auth_mode=S, has_token=B), 'Masked drive connection; no token value.')
success('drive', 'test_connection', obj(ok=B, message=S, warning=S), 'Probe result; failures can be HTTP 200 with ok=false.')
success('drive', 'reveal_token', obj(token=S), 'Sensitive token disclosure; no-store.')
success('drive', 'login_url', obj(url=S), 'Credential-free local proxy launch URL.')
success('gallery', 'status', obj(configured=B, browser_url=S, auth_mode=S), 'Gallery configuration status.')
success('gallery', 'test_connection', obj(ok=B, message=S, warning=S), 'Probe result; failures can be HTTP 200 with ok=false.')
success('oidc', 'openid_configuration', DISCOVERY, 'OIDC discovery metadata.')
success('oidc', 'token', obj(access_token=S, token_type=S, expires_in=I, id_token=S, scope=S), 'Authorization-code exchange result, never a browser session token.')
success('oidc', 'userinfo', optional(obj(sub=S, name=S, preferred_username=S, email=S), 'name', 'preferred_username', 'email'), 'Claims depend on granted profile/email scopes; sub is always present.')
success('auth_provider', 'clients', array(CLIENT), 'Registered clients; secrets are not returned.')
success('auth_provider', 'client update', CLIENT, 'Public registered-client projection.')
success('auth_provider', 'create rotate', CLIENT_SECRET, 'One-time client-secret delivery with public client fields.')
success('auth_provider', 'delete', OK, 'Client deletion acknowledgement.')
success('auth_provider', 'reveal', obj(client_id=S,client_secret=S), 'Sensitive same-Origin POST of an existing secret; current owner/admin rechecked after lock, no-store on success and denial. No generation/rotation/version change.')
success('auth_provider', 'provider_config', obj(**{k:S for k in ['issuer','authorization_endpoint','token_endpoint','userinfo_endpoint','jwks_uri','discovery_url']},
    clients=array(CLIENT), capabilities=obj(grant_types_supported=array(S), token_endpoint_auth_methods_supported=array(S),
    code_challenge_methods_supported=array(S), scopes_supported=array(S), secret_reveal=B)), 'Provider endpoints, client projections and capability metadata.')
success('timeline', 'read_timeline', TIMELINE, 'Bounded metadata events; timestamps are event/creation times, not invented completion times.')
success('unified_search', 'search', SEARCH, 'Bounded metadata union of notes, nodes and timeline records; node hits omit ts.')


HELP = obj(title=S, location=nullable(S), instructions=array(S), external_url=nullable(S))
# Optional on transport failures and historical receipts; explicit HTML product
# hints and inert Stella appearance code are observations, never authority.
WEBSITE_CHECK = optional(obj(normalized_url=S, name_suggestion=S, access=obj(status=S, http_status=nullable(I)),
    embedding=obj(status=S, reason_code=S, reason=S), injection=obj(status=S, reason=S), help=nullable(HELP),
    can_save=B, recommended_behavior=S, issues=array(S),
    software=obj(type={'type':'string','enum':['unknown','openlist','immich']}, source=nullable({'type':'string','enum':['html:generator','html:application-name']})),
    compatibility=nullable(obj(enabled=B, css=S, js=S, timing={'type':'string','enum':['document_start','dom_ready']}))), 'software', 'compatibility')
# Use the same reviewed check DTO in success AND nested HTTP-error consumers.
WEBSITE_CHECK = deepcopy(MODELS['PublicWebsiteCheck'])
DETAIL['anyOf'].extend([obj(errors=array(S)), obj(code=S, check=WEBSITE_CHECK),
    obj(code={'const':'incomplete_injection'}, projection=obj(state={'const':'incomplete'}, invalid_fields=array(S)))])
CONNECTION = obj(browser_url=S, upstream_url=S, alternate_browser_url=S, use_proxy=B, auth_mode=S, has_token=B)
PORTABLE_CONNECTION = obj(transport=S, auth_mode=S, header_name=S, injection_delivery=S)
CUSTOM = obj(enabled=B, css=S, js=S, timing=S)
REQUEST_POLICY = obj(management_prefixes=array(S), read_post_paths=array(S), protect_other_writes=B)
PORTABLE_DRAFT = optional(obj(name=S, icon=S, open_behavior=S, keep_alive=B, background=S,
    custom=CUSTOM, connection=PORTABLE_CONNECTION, request_policy=REQUEST_POLICY), 'name')
# Builtin drafts omit keep_alive; catalog records now carry builtin provenance.
BUILTIN_DRAFT = optional(PORTABLE_DRAFT, 'keep_alive')
BUILTIN_TEMPLATE = obj(id=S, name=S, provenance={'const': 'builtin'}, description=S, draft=BUILTIN_DRAFT)
SAVED_TEMPLATE = obj(id=S, name=S, provenance={'const': 'user'}, description=S, draft=PORTABLE_DRAFT)
MEDIA_METADATA = optional(obj(url=S, status=S, poster=nullable(S), thumbnail=nullable(S),
    variants={'type':'object','additionalProperties':S}, error=S, width=I, height=I), 'error','width','height')
BACKGROUND = obj(media=MEDIA_METADATA, id=S, name=S, ext=S, url=S, isDefault=B, isSystem=B, owner=nullable(S))
LAUNCH = {'anyOf': [optional(obj(mode=S, url=S, method={'const': 'GET'}, target_origin=S), 'target_origin'),
    obj(mode={'const': 'isolated_proxy'}, url=S, source_origin=S, target_origin=S,
        method={'const': 'POST'}, fields=obj(ticket=S), expires_in=I, entry_revision=I)]}
success('gallery', 'connection save_connection', CONNECTION, 'Masked external connection; no token/clear_token field.')
success('website_settings', 'check', WEBSITE_CHECK, 'Bounded server-side probe observations; not proof of browser embedding or login.')
success('website_settings', 'templates', array(BUILTIN_TEMPLATE), 'Built-in inert template catalog on this baseline; upstream saved-template delta is recorded separately.')
success('homebg', 'get_media optimize_homebg', MEDIA_METADATA, 'Media derivative metadata; missing/queued/processing/ready/error modes have optional size/error fields.')
success('homebg', 'list_homebg', array(BACKGROUND), 'Visible background records with media derivative metadata.')
success('homebg', 'upload_homebg rename_homebg', BACKGROUND, 'Background record; local queue versus synchronous PostgreSQL optimization uses the same optional media fields.')
success('operations_status','backup_health',obj(timestamp=nullable(S),status={'type':'string','enum':['missing','invalid','verified','unverified','failed','stale']},checksumverified=B,restoreverified=B,source={'anyOf':[{'enum':['postgres-dump','postgres-snapshot']},N]}),'Read-only backup receipt projection; no backup/restore operation is performed.')
success('metrics_source','get_connection put_connection',obj(enabled=B,url=nullable(S),nodes={'type':'object','additionalProperties':obj(job=S,instance=S)}),'Explicit Prometheus comparison configuration; node-keyed typed target mappings.')
success('monitor','read_traffic_stats',obj(rx_95=F,tx_95=F,rx_max=F,rx_min=F,tx_max=F,tx_min=F,rx_total=I,tx_total=I,sample_count=I),'Aggregated interface traffic statistics; empty aggregates normalize to zero.')
success('integrations','resolve_target',obj(normalized_origin=S,resolved_ips=array(S),status=S,private_addresses=B),'Resolved/pinned address preview, not a saved integration.')
success('integrations','launch',LAUNCH,'GET browser launch or isolated-proxy POST bootstrap with ticket fields and expiry.')
success('integrations','presets',obj(openlist=obj(css=S,js=S,readonly=B,status=S,managed_settings=S),immich=obj(css=S,js=S,readonly=B,status=S,managed_settings=S),generic=obj(css=S,js=S,readonly=B,status=S)),'Read-only code presets; generic injection-loaded is not application-ready.')


def _media(description, mime='*/*'):
    return {'description': description, 'content': {mime: {'schema': {'type': 'string', 'format': 'binary'}}}}


def _error_responses(record):
    result = {code: json_response(HTTP_ERROR, 'Application/dependency HTTPException; string or documented structured detail.')
              for code in record['error_statuses']}
    if record.get('request_validation') or '422' in result:
        result['422'] = json_response(VALIDATION_ERROR, 'Shared public request-validation builder (loc/type/msg), or explicit business HTTPException detail; no global error/log redaction claim.')
    # Backup conflicts are closed, per-operation envelopes. The maintenance CLI
    # command is not an arbitrary global HTTPException detail or a JSON success.
    conflict_codes = {
        'app.routers.backups.patch': ['backup_busy', 'revision_conflict'],
        'app.routers.backups.save_client_preferences': ['revision_conflict'],
        'app.routers.backups.backup': ['backup_busy'],
        'app.routers.backups.verify': ['backup_busy'],
        'app.routers.backups.restore': ['backup_busy', 'revision_conflict'],
        'app.routers.backups.delete': ['backup_busy'],
    }.get(record['endpoint'])
    if conflict_codes is not None:
        details = [obj(code={'type': 'string', 'enum': conflict_codes}, message=S)]
        if record['endpoint'] == 'app.routers.backups.restore':
            details.append(obj(code={'type': 'string', 'const': 'maintenance_required'}, message=S, command=S))
        result['409'] = json_response(obj(detail={'anyOf': details}), 'Backup operation conflict; only all-scope restore adds the required offline maintenance command.')
    return result


INCOMPLETE_REASONS = {}


from app.api_response_shapes import register as _register_shapes
SHAPE_BLOCKERS, CURRENT_SHAPES = _register_shapes(globals())
from app.api_response_feedback import register as _register_feedback
SHAPE_BLOCKERS.update(_register_feedback(globals()))
INCOMPLETE_REASONS.update(SHAPE_BLOCKERS)

DECLARATIONS = {}
for _row in INVENTORY:
    _key = (_row['method'], _row['path'])
    _endpoint = _row['endpoint']
    _responses = _error_responses(_row)
    _status, _reason = 'reviewed', ''
    _description = DESCRIPTIONS.get(_endpoint, '')
    _payload = SUCCESS.get(_endpoint)
    if _payload is None and 'model' in _row:
        _payload = _replace_frontmatter(MODELS[_row['model']])
        _description = (_row['review'] if _endpoint.startswith('app.routers.backups.') else
                        'Serialized ' + _row['model'] + '; declaration mirrors the existing handler response model.')
        _holes = schema_holes(_payload)
        if _holes:
            _status, _reason = 'incomplete', 'Existing model has unreviewed dynamic fields: ' + ', '.join(_holes)
    if _row['status_code'] == '204':
        _responses['204'] = {'description': 'Completed successfully; no response body.'}
        _description = 'No-content operation; success is HTTP 204.'
    elif _payload is not None:
        _responses[_row['status_code']] = json_response(_payload, _description)
    else:
        _status, _reason = 'incomplete', 'Success helper/storage-mode payload has not been fully declared; see pinned source evidence. No empty JSON schema substituted.'
        _responses[_row['status_code']] = {'description': 'Success body exists but its structure is not fully declared; see x-stella-contract-reason.', 'x-stella-body-undeclared': True}
    if _endpoint in {'app.routers.backups.download', 'app.routers.backups.download_head'}:
        _responses['200'] = _media(_row['review'], 'application/zip')
        _responses['200']['headers'] = {
            'Content-Length': {'schema': {'type': 'integer', 'minimum': 0}},
            'Content-Disposition': {'schema': S, 'description': 'Owned manifest ZIP filename; attachment disposition.'},
            'Content-Type': {'schema': {'type': 'string', 'const': 'application/zip'}},
            'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}},
            'X-Content-Type-Options': {'schema': {'type': 'string', 'const': 'nosniff'}},
            'Referrer-Policy': {'schema': {'type': 'string', 'const': 'no-referrer'}},
        }
        _status, _reason, _description = 'reviewed', '', _row['review']
    if _endpoint in {'app.routers.admin_email.get_config', 'app.routers.oidc.jwks', 'app.routers.operations_status.change_audit'}:
        _responses['503'] = json_response(HTTP_ERROR, 'Controlled invalid public-source configuration; no rejected values returned.')
    if _endpoint == 'app.routers.auth.retired_invitation_api':
        _responses = {'410': json_response(HTTP_ERROR, 'Permanently retired invitation endpoint; never succeeds.')}
        _status, _reason, _description = 'reviewed', '', 'Retired in single-owner mode. Always HTTP 410; no successful JSON response.'
    if _endpoint in {'app.routers.auth.' + name for name in (
            'update_security', 'change_management_password', 'admin_setup', 'admin_unlock', 'admin_lock')}:
        _responses.pop('200', None)
        _responses['410'] = json_response(obj(detail=obj(
            code={'type': 'string', 'const': 'management_password_retired'}, message=S)),
            'Independent management password retired; authenticated owner receives 410 without mutation.')
        _status, _reason, _description = 'reviewed', '', 'Retired management-password API; no success or grant issuance. Owner authentication still required.'
    if _endpoint in {'app.routers.attachment.serve', 'app.routers.dynamic_assets.background_asset', 'app.routers.dynamic_assets.avatar_asset'}:
        _responses.update({'200': _media('Stored MIME bytes; local FileResponse or PostgreSQL blob materialization.'),
            '206': _media('FileResponse byte range or multipart/byteranges response.'),
            '304': {'description': 'Matching If-None-Match in PostgreSQL blob mode; no body.'},
            '400': {'description': 'Malformed range in FileResponse.', 'content': {'text/plain': {'schema': S}}},
            '416': {'description': 'Unsatisfiable byte range; no body.', 'headers': {'Content-Range': {'schema': S}}}})
        _status, _reason, _description = 'reviewed', '', 'Binary/media download. 304 is PostgreSQL-mode conditional handling; HEAD has no body. MIME varies by object.'
    if _endpoint == 'app.routers.task.download_speedtest_go':
        _responses['200'] = _media('Platform executable attachment; FileResponse MIME inferred from file.')
        _responses['206'] = _media('Range response.')
        _responses['400'] = {'description': 'Malformed range.', 'content': {'text/plain': {'schema': S}}}
        _responses['416'] = {'description': 'Unsatisfiable range; no body.'}
        _status, _reason, _description = 'reviewed', '', 'Binary executable download, not JSON.'
    if _endpoint in {'app.routers.monitor.' + n for n in ('agent_script', 'agent_install_sh', 'agent_install_ps1', 'agent_run_ps1', 'agent_hardware_sensors_ps1')}:
        _responses['200'] = {'description': 'Credential-free agent program/installer text.', 'content': {'text/plain': {'schema': S}}}
        _status, _reason, _description = 'reviewed', '', 'Plain text program or installer; not JSON.'
    if _endpoint == 'app.routers.website_settings.website_asset':
        _responses['200'] = {'description': 'Safe baseline or owner-only custom JavaScript.', 'content': {'application/javascript': {'schema': S}}}
        _status, _reason, _description = 'reviewed', '', 'JavaScript loader; persisted owner session controls custom content.'
    if _endpoint in {'app.routers.gallery.connect', 'app.routers.oidc.authorize'}:
        _responses.pop('200', None)
        _responses['307'] = {'description': 'RedirectResponse; destination in Location header.', 'headers': {'Location': {'schema': S}}}
        _status, _reason, _description = 'reviewed', '', 'HTTP 307 redirect, not a JSON URL. OIDC callback errors can also be redirected.'
    if _endpoint in {'app.routers.oidc.authorize', 'app.routers.oidc.token', 'app.routers.oidc.userinfo'}:
        for _code in (('400',) if _endpoint.endswith('authorize') else ('401',) if _endpoint.endswith('userinfo') else ('400', '401')):
            _responses[_code] = json_response(obj(error=S), 'OIDC protocol error, not FastAPI detail envelope.')
    if _endpoint == 'app.routers.drive.openlist_proxy':
        _responses.pop('200', None)
        if _row['method'] == 'OPTIONS':
            _responses['204'] = {'description': 'Local authenticated preflight; no upstream request or response body.', 'headers': {'Allow': {'schema': S}}}
            _status = 'reviewed'
        else:
            _responses['default'] = _media('Upstream status/MIME/bytes pass-through (HTML theme injection for uncompressed HTTP 200 HTML); no fixed JSON contract.')
            _status = 'passthrough'
        _reason = ''
        _description = 'Authenticated OpenList proxy. Upstream statuses and media are variable; OPTIONS is local 204. No fixed upstream JSON schema.'
    if _row['method'] == 'HEAD':
        for _response in _responses.values():
            _response.pop('content', None)
    if _row.get('model') in MODEL_BLOCKERS:
        _status, _reason = 'incomplete', MODEL_BLOCKERS[_row['model']]
    if _endpoint.removeprefix('app.routers.') in SHAPE_BLOCKERS:
        _status = 'incomplete'
    if _status == 'incomplete':
        _reason = INCOMPLETE_REASONS.get(_endpoint.removeprefix('app.routers.'), _reason)
        if not _description:
            _description = 'Response contract incomplete: ' + _reason
    DECLARATIONS[_key] = dict(endpoint=_endpoint, responses=_responses, status=_status, reason=_reason,
        description=_description, sources=_row['sources'])

DECLARATIONS[('GET', '/agent/release')]['responses']['200']['headers'] = {
    'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}}}


# Revision-pinned upstream evidence retained as history; active mappings above
# are reconciled against this checkout, never auto-activated from a hash match.
TEMPLATE_INTEGRATION_EVIDENCE = {}
UPSTREAM_DECLARATIONS = {}
for _pending in json.loads((_BASE / 'api_response_upstream.json').read_text()):
    _method = _pending['method']
    _pending_responses = {code: json_response(HTTP_ERROR, 'Owner/management dependency or template operation failure.')
                          for code in ('401', '403', '503')}
    if _method == 'GET':
        _pending_responses['200'] = json_response(array({'anyOf': [BUILTIN_TEMPLATE, SAVED_TEMPLATE]}),
            'Built-in catalog plus owner-scoped saved portable templates; secrets and website addresses excluded.')
    elif _method == 'POST':
        _pending_responses.update({'201': json_response(SAVED_TEMPLATE, 'Saved template or same-key replay; identical response shape.'),
            '409': json_response(HTTP_ERROR, 'Idempotency content conflict or deleted original template.'),
            '413': json_response(HTTP_ERROR, 'Body exceeds bounded template upload budget.'),
            '422': json_response(VALIDATION_ERROR, 'Sanitized route validation or explicit template error.')})
    else:
        _pending_responses.update({'204': {'description': 'Deleted; no body.'}, '404': json_response(HTTP_ERROR, 'Missing, foreign or built-in template.')})
    TEMPLATE_INTEGRATION_EVIDENCE[(_method, _pending['path'])] = dict(_pending, responses=_pending_responses)
    _active = DECLARATIONS[(_method, _pending['path'])]
    _active.update(responses=_pending_responses, status='reviewed', reason='',
                   description='Owner-scoped portable template; no website addresses or credentials exported.')
    if _method == 'DELETE':
        # Full-main adds validation for the typed path parameter. Keep the active
        # offline declaration in parity without rewriting historical evidence.
        _active['responses'] = {**_pending_responses, '422': json_response(
            VALIDATION_ERROR, 'Typed path request validation.')}

for _merged in json.loads((_BASE / 'api_response_alerts_upstream.json').read_text())['operations']:
    if _merged['endpoint'] in SUCCESS:
        continue  # the stored list uses its real public serialization model
    _active = DECLARATIONS[(_merged['method'], _merged['path'])]
    _active.update(responses=_merged['responses'], status=_merged['status'], reason=_merged.get('reason', ''),
                   description='Merged metric alert contract; legacy rules remain separately filtered to schema_version=1.')
    if '422' in _active['responses']:
        _active['responses']['422'] = json_response(VALIDATION_ERROR, 'Shared public request validation or explicit metric-rule business error.')


_notes_pending = json.loads((_BASE / 'api_response_notes_upstream.json').read_text())
_UUID = {'type': 'string', 'format': 'uuid'}
DELETE_PREVIEW = obj(scope_token=S, target_ids=array(_UUID), descendant_count={'type':'integer','minimum':0},
    mode={'enum':['trash','permanent','empty-trash']},cascade=B,workspace_id=_UUID,doc_id=nullable(_UUID))
_notes_responses = {code:json_response(HTTP_ERROR,'Owner/session or lookup failure.') for code in ('401','403','404','503')}
_notes_responses.update({
    '200':json_response(DELETE_PREVIEW,'Read-only complete active+trash scope, rolled back after read. scope_token is a ten-minute comparison fingerprint, never authorization.'),
    '409':json_response(obj(detail=obj(code={'enum':['document_tree_invalid','document_tree_check_incomplete']},message=S)),
        'Invalid/incomplete tree, bounded lock/statement timeout or reported connection failure; never a partial inventory.'),
    '422':json_response(VALIDATION_ERROR,'Invalid mode/root/cascade input.')})
DECLARATIONS[('POST','/documents/delete-preview')].update(responses=_notes_responses, status='reviewed', reason='',
    description='Merged read-only deletion scope preview; no token authorization or persisted receipt.')
for _key in [('DELETE','/documents/{doc_id}'), ('DELETE','/documents/{doc_id}/permanent'), ('POST','/documents/trash/empty')]:
    DECLARATIONS[_key]['responses']['409'] = json_response(HTTP_ERROR, 'Tree/reference conflict or delete_scope_changed (code/message); zero partial writes.')
for _name in ('apply','rollback'):
    _key=('POST', '/external-modules/{mid}/injection/'+_name)
    DECLARATIONS[_key]['responses']['409'] = json_response(HTTP_ERROR, 'No prior version, origin mismatch, or incomplete_injection with typed projection marker.')


def _definitions(schema):
    """Collect response-local definitions before promoting them to document scope."""
    definitions = {}
    def visit(value):
        if isinstance(value, dict):
            for name, definition in value.get('$defs', {}).items():
                if name in definitions and definitions[name] != definition:
                    raise ValueError('Conflicting response-local definition: ' + name)
                definitions[name] = definition
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(schema)
    return definitions


def _definition_names(definitions):
    import hashlib
    return {name: ('StellaResponseJsonValue' if name == 'JsonValue' else
        'StellaResponse' + name + '_' + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12])
        for name, value in definitions.items()}


def _openapi_schema(schema, definitions=None):
    """Promote ALL local refs, including discriminator mappings, not just JSONValue."""
    names = _definition_names(_definitions(schema) if definitions is None else definitions)
    names['JsonValue'] = 'StellaResponseJsonValue'
    def visit(value):
        if isinstance(value, str) and value.startswith('#/$defs/'):
            name = value.removeprefix('#/$defs/')
            return '#/components/schemas/' + names[name]
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items() if k != '$defs'}
        if isinstance(value, list):
            return [visit(v) for v in value]
        return value
    return visit(schema)


def _build_response_components():
    result = {name: _openapi_schema(value) for name, value in {
        'StellaHTTPError': HTTP_ERROR, 'StellaValidationError': VALIDATION_ERROR,
        'StellaResponseJsonValue': JSON_VALUE}.items()}
    for record in DECLARATIONS.values():
        for response in record['responses'].values():
            for media in response.get('content', {}).values():
                definitions = _definitions(media.get('schema', {}))
                names = _definition_names(definitions)
                for name, definition in definitions.items():
                    result[names[name]] = _openapi_schema(definition, definitions)
    return result


# Lane-specific response overrides follow all historical declarations. Keep the
# three notification-context incomplete records unchanged.
for _override in _V5_REVIEW['response_overrides']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    for _field in ('responses', 'status', 'reason', 'description'):
        _active[_field] = deepcopy(_override[_field])


for _override in _V6_REVIEW['success_schema_replacements']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if _active['endpoint'] != _override['endpoint']:
        raise ValueError('v6 DTO operation precondition drift')
    for _code, _schema in _override['success_schema_replacements'].items():
        _active['responses'][_code]['content']['application/json']['schema'] = deepcopy(_schema)

for _override in _V8_REVIEW['success_schema_replacements']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if _active['endpoint'] != _override['endpoint']:
        raise ValueError('v8 DTO operation precondition drift')
    for _code, _schema in _override['success_schema_replacements'].items():
        _active['responses'][_code]['content']['application/json']['schema'] = deepcopy(_schema)

for _override in _V11_REVIEW['success_schema_replacements']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if _active['endpoint'] != _override['endpoint']:
        raise ValueError('v11 DTO operation precondition drift')
    for _code, _schema in _override['success_schema_replacements'].items():
        _active['responses'][_code]['content']['application/json']['schema'] = deepcopy(_schema)

for _override in _V11_REVIEW['error_response_additions']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if _active['endpoint'] != _override['endpoint']:
        raise ValueError('v11 error operation precondition drift')
    _active['responses'][_override['code']] = deepcopy(_override['response'])

DECLARATIONS[('GET', '/agent/identity')]['responses']['200']['headers'] = {
    'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}}}

# Materialized copies follow every historical response layer.
for _override in _V12_REVIEW['response_overrides']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if (_active['endpoint'] != _override['endpoint'] or
            _active['responses'] != _override['before_responses']):
        raise ValueError('v12 response operation precondition drift')
    _active['responses'] = deepcopy(_override['responses'])

# Preserve 404/422/auth shapes; document the unchanged service ValueError 400.
for _override in _V13_MONITOR404_REVIEW['response_overrides']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if (_active['endpoint'] != _override['endpoint'] or
            _active['responses'] != _override['before_responses']):
        raise ValueError('v13 monitor404 response precondition drift')
    _active['responses'] = deepcopy(_override['responses'])

for _override in _V17_REVIEW['response_overrides']:
    _key = _override['method'], _override['path']
    _active = DECLARATIONS[_key]
    if 'before_response' in _override and _key not in _V17_NEW_ROWS:
        if _active['responses'].get(_override['code']) != _override['before_response']:
            raise ValueError('v17 nav files error response precondition drift')
    _active['responses'][_override['code']] = deepcopy(_override['response'])
    if _key in _V17_NEW_ROWS and _V17_NEW_ROWS[_key].get('binary'):
        _active.update(status='reviewed', reason='', description=_V17_NEW_ROWS[_key]['review'])

for _override in _V19_REVIEW['response_overrides']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    _active['responses'][_override['code']]['headers'] = deepcopy(_override['headers'])

for _override in _V22_REVIEW['response_overrides']:
    _active = DECLARATIONS[(_override['method'], _override['path'])]
    if (_active['endpoint'] != _override['endpoint'] or
            _active['responses'] != _override['before_responses']):
        raise ValueError('v22 private remediation response precondition drift')
    _active['responses'] = deepcopy(_override['responses'])
for _declaration in _V22_REVIEW['new_declarations']:
    _key = _declaration['method'], _declaration['path']
    _row, = [r for r in _V22_REVIEW['operations'] if (r['method'], r['path']) == _key]
    if _declaration['endpoint'] != _row['endpoint'] or _declaration['sources'] != _row['sources']:
        raise ValueError('v22 private remediation new declaration source drift')
    DECLARATIONS[_key] = {k: deepcopy(v) for k, v in _declaration.items() if k not in {'method', 'path'}}

# v22's late new-declaration materialization uses immutable historical sources.
# Advance only its exact v23-reviewed union after retaining the original v22 guard.
for _declaration in _V22_REVIEW['new_declarations']:
    _key = _declaration['method'], _declaration['path']
    if _key in _V23_ROWS:
        if DECLARATIONS[_key]['sources'] != _V23_ROWS[_key]['before_sources']:
            raise ValueError('v23 final offload late declaration source precondition drift')
        DECLARATIONS[_key]['sources'] = list(_V23_ROWS[_key]['sources'])

_RESPONSE_COMPONENTS = _build_response_components()


def response_components():
    # Build once from the immutable reviewed registry, isolate every caller.
    return deepcopy(_RESPONSE_COMPONENTS)


def decorate_response(operation, method, path, endpoint, *, document=None):
    record = DECLARATIONS.get((method.upper(), path))
    if record is None or record['endpoint'] != endpoint:
        operation['x-stella-contract-status'] = 'unclassified'
        operation['x-stella-contract-reason'] = 'No exact reviewed response contract for method/path/callable.'
        return
    # Preserve request/schema/security extensions and pre-existing typed response
    # models for incomplete routes. Replace only declared status codes; never keep
    # FastAPI's fictitious 200 on redirects, retirement, 204 or proxy operations.
    responses = deepcopy(record['responses'])
    original = operation.get('responses', {})
    if record['status'] == 'incomplete':
        for code, value in original.items():
            if code not in responses:
                responses[code] = deepcopy(value)
    if '422' in original or '422' in responses:
        responses['422'] = json_response(VALIDATION_ERROR, 'Global and private-route validation use the shared public loc/type/msg builder: schema-owned fields/indexes retained, dynamic keys/union labels redacted, constant messages/types. Explicit business HTTPException and logs are not covered by a global redaction claim.')
    if method.upper() == 'HEAD':
        for response in responses.values():
            response.pop('content', None)
    if document is not None:
        components = document.setdefault('components', {}).setdefault('schemas', {})
        components.update(response_components())
        for response in responses.values():
            for media in response.get('content', {}).values():
                payload = media.get('schema')
                if payload == HTTP_ERROR:
                    media['schema'] = {'$ref': '#/components/schemas/StellaHTTPError'}
                elif payload == VALIDATION_ERROR:
                    media['schema'] = {'$ref': '#/components/schemas/StellaValidationError'}
                elif payload is not None:
                    media['schema'] = _openapi_schema(payload)
    operation['responses'] = responses
    operation['x-stella-contract-status'] = record['status']
    operation['x-stella-contract-reason'] = record['reason']
    operation['x-stella-contract-evidence'] = {
        'handler': deepcopy(SOURCE_EVIDENCE[
            _V5_HANDLERS.get(record['endpoint'], record['endpoint'])]),
        'source-map': (['app/api_response_v12_final_review.json', 'app/api_response_v12_installer_umask_review.json']
                       if endpoint in _V12_UMASK_ENDPOINTS
                       else ['app/api_response_v12_final_review.json', 'app/api_response_v12_notes_review.json']
                       if endpoint in _V12_ENDPOINTS and endpoint in _V12_NOTES_ENDPOINTS
                       else 'app/api_response_v12_notes_review.json' if endpoint in _V12_NOTES_ENDPOINTS
                       else 'app/api_response_v12_final_review.json' if endpoint in _V12_ENDPOINTS
                       else 'app/api_response_v11_review.json' if endpoint in _V11_ENDPOINTS
                       else 'app/api_response_v8_review.json' if endpoint in _V8_ENDPOINTS
                       else ['app/api_response_v6_integration.json', 'app/api_response_ipv6_udp_source_review.json']
                       if endpoint in _V6_ENDPOINTS and endpoint in _IPV6_UDP_REVIEW['source_map_union']
                       else 'app/api_response_v6_integration.json' if endpoint in _V6_ENDPOINTS
                       else _IPV6_UDP_REVIEW['source_map_union'][endpoint] if endpoint in _IPV6_UDP_REVIEW['source_map_union']
                       else 'app/api_response_node_interruptions_review.json' if endpoint in _NODE_INTERRUPTION_ENDPOINTS
                       else 'app/api_response_v5_integration.json' if endpoint in _V5_ENDPOINTS
                       else 'app/api_response_round4_review.json' if endpoint in _ROUND4_ENDPOINTS
                       else 'app/api_response_auth_review.json' if endpoint in _AUTH_REVIEW['sources']
                       else 'app/api_response_backups.json' if endpoint.startswith('app.routers.backups.')
                       else 'app/api_response_inventory.json'),
        'supporting-symbols': list(record['sources']),
    }
    if endpoint in _V13_DURATION_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v13_speedtest_duration_review.json']
    if endpoint in _V13_MONITOR404_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v13_monitor404_review.json']
    if endpoint in _V13_SOURCE_METADATA_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v13_source_metadata_review.json']
    if endpoint in _V14_CI167_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v14_ci167_review.json']
    if endpoint in _V15_AGENT_ROLLOUT_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v15_agent_rollout_review.json']
    if endpoint in _V16_MONITOR_UX_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v16_monitor_ux_review.json']
    if endpoint in _V17_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *([] if endpoint in _V17_REVIEW['new_handler_sources'] else
              _prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v17_nav_files_review.json']
    if endpoint in _V18_ENDPOINTS:
        operation['x-stella-contract-evidence']['source-map'] = [
            *operation['x-stella-contract-evidence']['source-map'],
            'app/api_response_v18_nav_files_validation_review.json']
    if endpoint in _V19_ENDPOINTS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *([] if endpoint in _V19_REVIEW['new_handler_sources'] else
              _prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v19_unified_files_review.json']
    if (method.upper(), path) in _V20_ROWS:
        operation['x-stella-contract-evidence']['source-map'] = [
            *operation['x-stella-contract-evidence']['source-map'],
            'app/api_response_v20_fnos_policy_review.json']
    if (method.upper(), path) in _V21_ROWS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v21_refresh_timeout_review.json']
    if (method.upper(), path) in _V22_ROWS or endpoint in _V22_REVIEW['new_handler_sources']:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *([] if endpoint in _V22_REVIEW['new_handler_sources'] else
              _prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v22_private_remediation_review.json']
    if (method.upper(), path) in _V23_ROWS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps,list) else [_prior_maps]),
            'app/api_response_v23_final_offload_review.json']
    if (method.upper(), path) in _V24_ROWS:
        _prior_maps = operation['x-stella-contract-evidence']['source-map']
        operation['x-stella-contract-evidence']['source-map'] = [
            *(_prior_maps if isinstance(_prior_maps, list) else [_prior_maps]),
            'app/api_response_v24_servers_audit_review.json']
    operation['x-stella-contract-validation'] = 'Documentation only; no new runtime response filtering, input validation or redaction.'
    if record['description']:
        operation['description'] = record['description']


def response_contract_errors(operation, method, path, endpoint, *, require_complete=False):
    record = DECLARATIONS.get((method.upper(), path))
    if record is None or record['endpoint'] != endpoint:
        return ['unclassified response contract (missing or stale exact operation review)']
    expected = deepcopy(operation)
    decorate_response(expected, method, path, endpoint, document={})
    errors = []
    for field in ('responses', 'x-stella-contract-status', 'x-stella-contract-reason'):
        if operation.get(field) != expected.get(field):
            errors.append('response contract differs from reviewed declaration: ' + field)
    for code, response in record['responses'].items():
        if record['status'] != 'reviewed':
            continue
        for media in response.get('content', {}).values():
            holes = schema_holes(media.get('schema', {}))
            if holes:
                errors.append(f'reviewed response {code} has unconstrained schema: {holes}')
    if require_complete and record['status'] == 'incomplete':
        errors.append('incomplete response contract: ' + record['reason'])
    return errors


def validate_response_sources(root, records):
    """Offline fail-closed inventory/source gate; never called by HTTP handlers.

    The caller supplies an independently discovered mounted inventory. Changes
    to any pinned supporting file require source review, not auto-acceptance.
    """
    import hashlib
    actual = {(method.upper(), path): endpoint for method, path, endpoint, _ in records}
    expected = {key: value['endpoint'] for key, value in DECLARATIONS.items()}
    errors = []
    for key in sorted(set(actual) | set(expected)):
        if actual.get(key) != expected.get(key):
            errors.append(f'{key}: unclassified/new, stale or changed response operation')
    checked = set()
    for row in [*INVENTORY, *WEBSOCKET_DECLARATIONS]:
        for symbol in row['sources']:
            source = SOURCE_EVIDENCE[symbol]
            identity = (source['file'], source['sha256'])
            if identity in checked:
                continue
            checked.add(identity)
            path = Path(root) / source['file']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                errors.append('source drift or missing source: ' + source['file'])
    # WS has no OpenAPI operation: bind its actually mounted declaration alone.
    import ast
    ws_file = Path(root) / 'app/routers/native_nav.py'
    if ws_file.is_file():
        try:
            tree = ast.parse(ws_file.read_bytes())
            actual_ws = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                                and isinstance(decorator.func.value, ast.Name)
                                and decorator.func.value.id == 'events_router' and decorator.func.attr == 'websocket'):
                            actual_ws.append((ast.literal_eval(decorator.args[0]), 'app.routers.native_nav.' + node.name))
            if actual_ws != [(r['path'], r['endpoint']) for r in WEBSOCKET_DECLARATIONS]:
                errors.append('v17 websocket declaration drift')
        except (SyntaxError, ValueError, IndexError):
            errors.append('v17 websocket declaration drift')
    return errors
