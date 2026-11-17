"""Unified website saves using the existing single-owner AppConfig transaction."""
import copy
import hashlib
import json
import time
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from app.services import integrations as store
from app.services.website_check import CheckInput, check_draft, normalize_url, origin, bounded_dns, safe_address, ProbeFailure
from app.services import integrations_proxy as proxy, integrations_injection as injection
import asyncio
from urllib.parse import urlsplit

from app.services.website_connection import ConnectionInput, RequestPolicy, effective_connection, credential_headers, public_connection

from app.navigation_icons import NAVIGATION_ICONS

class CustomInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    css: str = ''
    js: str = ''
    timing: Literal['dom_ready','document_start'] = 'dom_ready'

    @field_validator('css','js')
    @classmethod
    def bounded_code(cls, value, info):
        limit = 65536 if info.field_name == 'css' else 131072
        if len(value.encode('utf-8')) > limit or '\x00' in value: raise ValueError('代码过长或包含 NUL')
        return value

from app.services.website_mapping import WebsiteMappingInput, mapping_values

class WebsiteInput(WebsiteMappingInput):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(min_length=1,max_length=2048)
    private_address: str | None = Field(default=None, max_length=2048)
    entry_policy: Literal['follow','public'] = 'follow'
    access_adapter: Literal['auto','generic','openlist','immich'] = 'auto'
    name: str | None = Field(default=None,min_length=1,max_length=100)
    icon: str = 'globe'
    visible: bool = True
    keep_alive: bool = False
    open_behavior: Literal['embedded','external'] = 'embedded'
    custom: CustomInput | None = None
    preserve_saved_draft: bool = Field(default=False, strict=True)
    # Provenance only: snapshots never resolve a catalog ID at runtime.
    template_id: str | None = Field(default=None, pattern=r'^(openlist|immich|user_[0-9a-f]{32})$')
    connection: ConnectionInput | None = None
    background: Literal['solid','home'] = 'solid'
    request_policy: RequestPolicy | None = None
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=128,pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_revision: int | None = Field(default=None,ge=0,strict=True)

    @field_validator('icon')
    @classmethod
    def valid_icon(cls, value):
        # Legacy values need module context before deciding retention vs change.
        if value not in store.ICONS: raise ValueError('不支持的图标')
        return value

def fingerprint(incoming, *, patch=False):
    body = incoming.model_dump(exclude={'idempotency_key','preserve_saved_draft'})
    if 'expected_revision' not in incoming.model_fields_set: body.pop('expected_revision',None)
    if incoming.preserve_saved_draft: body['preserve_saved_draft'] = True
    for field in ('address_mode','alternate_address'):
        if field not in incoming.model_fields_set: body.pop(field, None)
    if patch: body['provided_fields'] = sorted(incoming.model_fields_set - ({'idempotency_key'} if incoming.preserve_saved_draft else {'idempotency_key','preserve_saved_draft'}))
    try: body['address'] = normalize_url(body['address'])
    except (ValueError,HTTPException): pass
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def retry_result(config, slot, digest, idempotency_key=None):
    entry = config.get('website_save_keys',{}).get(slot)
    if not entry or entry['expires'] <= time.time(): return None
    if entry['digest'] != digest: raise HTTPException(409,'幂等键已用于不同的网站草稿')
    module = config['modules'].get(entry['id'])
    if module is None or hashlib.sha256(json.dumps(module,sort_keys=True).encode()).hexdigest() != entry['module_digest']:
        raise HTTPException(409,'已保存的网站随后发生变更，请重新读取后保存')
    if entry.get('navigation_revision', config.get('navigation_revision',0)) != config.get('navigation_revision',0):
        raise HTTPException(409,'导航随后发生变更，请重新读取后确认')
    from app.public_website import public_website_result
    return public_website_result(module, entry['check']) | {'navigation':store.navigation_projection(config),'idempotency_key':idempotency_key}

def css_errors(css):
    """Check token and block grammar, not selector/property or unknown at-rule semantics.

    Declarations and nested rules use CSS Syntax's block-content parser. Custom
    property values are opaque component values, not declaration/rule blocks.
    Unknown at-rules get token checks only, so this is not a complete CSS validator.
    """
    if not css: return []
    try:
        import tinycss2
        budget = 131072
        def spend(depth):
            nonlocal budget
            budget -= 1
            if depth > 64 or budget < 0: raise ValueError('CSS parsing budget exceeded')

        def token_errors(nodes, depth=0):
            for node in nodes:
                spend(depth)
                if node.type == 'error': return True
                for field in ('content','prelude','arguments','value'):
                    values = getattr(node,field,None)
                    if isinstance(values,list) and token_errors(values,depth+1): return True
            return False

        groups = {'media','supports','layer','container','scope','document','-moz-document','starting-style'}
        descriptors = {'font-face','property','counter-style','font-palette-values',
                       'styleset','stylistic','character-variant','swash','ornaments','annotation',
                       'top-left-corner','top-left','top-center','top-right','top-right-corner',
                       'bottom-left-corner','bottom-left','bottom-center','bottom-right','bottom-right-corner',
                       'left-top','left-middle','left-bottom','right-top','right-middle','right-bottom'}
        options = dict(skip_comments=True,skip_whitespace=True)
        def block_errors(nodes, context='rules', depth=0):
            for node in nodes:
                spend(depth)
                if node.type == 'error': return True
                if node.type == 'qualified-rule':
                    if context == 'declarations': return True
                    body_context = 'declarations' if context == 'keyframes' else 'style'
                    parser = tinycss2.parse_declaration_list if body_context == 'declarations' else tinycss2.parse_blocks_contents
                    if block_errors(parser(node.content,**options),body_context,depth+1): return True
                elif node.type == 'at-rule' and node.content is not None:
                    name = node.lower_at_keyword
                    if name in groups:
                        inner_context = 'style' if context == 'style' else 'rules'
                        parser = tinycss2.parse_blocks_contents if inner_context == 'style' else tinycss2.parse_rule_list
                    elif name in descriptors:
                        inner_context, parser = 'declarations', tinycss2.parse_declaration_list
                    elif name == 'page':
                        inner_context, parser = 'style', tinycss2.parse_blocks_contents
                    elif name == 'font-feature-values':
                        inner_context, parser = 'rules', tinycss2.parse_rule_list
                    elif name in {'keyframes','-webkit-keyframes'}:
                        inner_context, parser = 'keyframes', tinycss2.parse_rule_list
                    else:
                        continue  # Unknown grammar: token checks only, never guess from regex.
                    if block_errors(parser(node.content,**options),inner_context,depth+1): return True
            return False

        rules = tinycss2.parse_stylesheet(css,**options)
        if token_errors(rules) or block_errors(rules): return ['CSS 语法检查失败']
    except (ImportError,RecursionError,ValueError): return ['CSS 检查失败，拒绝保存代码']
    return []

def target_fingerprint(target):
    return hashlib.sha256(json.dumps(target,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def _database_phase(bind, operation):
    """One bounded worker owns the entire fresh Session/transaction lifecycle.

    Only detached JSON snapshots/results cross awaits. Starlette copies the
    request ContextVars (including the original access-entry revision) and uses
    AnyIO's bounded, non-abandoning worker pool; no transaction spans external I/O.
    Commit failures propagate once, without retrying an uncertain acknowledgement.
    """
    from sqlalchemy.orm import Session
    with Session(bind=bind, autoflush=False) as worker_db:
        return operation(worker_db)


async def save_website(bind, incoming, actor_id, *, parent_origin, mid=None):
    """Engine-only: fresh workers own all read/write connections and transactions.

    A Session/Connection may carry an external transaction or pending ORM state.
    Reject it before any I/O; never infer its Engine and silently escape ownership.
    Mounted routes separately finish their known auth transaction synchronously.
    """
    from sqlalchemy.engine import Engine
    if not isinstance(bind, Engine):
        raise TypeError('save_website requires an Engine, not a Session or Connection')
    if mid is None and incoming.idempotency_key is None: raise HTTPException(422,'新增网站需要 idempotency_key')
    digest = fingerprint(incoming,patch=mid is not None)
    slot = str(actor_id) + ':' + (mid or 'create') + ':' + (incoming.idempotency_key or '')
    config = await run_in_threadpool(_database_phase, bind, store.state)
    result = retry_result(config,slot,digest,incoming.idempotency_key) if incoming.idempotency_key else None
    before = copy.deepcopy(config['modules'].get(mid)) if mid else None
    display_before = store.display_module(before,config) if before else None
    # Freeze this object's complete rows and positions, not a display projection
    # or the whole navigation list (unrelated sibling edits must remain valid).
    navigation_before = copy.deepcopy([(index,entry) for index,entry in enumerate(config['navigation']) if entry['id'] == mid]) if before else []
    old_target = copy.deepcopy(config['targets'].get(before.get('target_id'))) if before else None
    old_binding = (before or {}).get('alternate_binding')
    old_alternate_target = copy.deepcopy(config['targets'].get(old_binding.get('target_id'))) if isinstance(old_binding,dict) else None
    target_authority = copy.deepcopy(config.get('website_target_authority',{}))
    if before:
        override = next((e for e in config['navigation'] if e['id']==mid),{})
        defaults = dict(name=display_before['name'],icon=display_before['icon'],keep_alive=before.get('keep_alive',False),visible=override.get('visible',before['enabled']),open_behavior='external' if before['mode']=='link' else 'embedded')
        incoming = incoming.model_copy(update={key:value for key,value in defaults.items() if key not in incoming.model_fields_set})
    if result is not None: return result
    if incoming.expected_revision is not None and incoming.expected_revision != config.get('navigation_revision',0):
        raise HTTPException(409,'网站编辑版本已改变，请重新读取并保留当前草稿')
    if mid and before is None: raise HTTPException(404,'模块不存在')
    if before and before.get('adapter') in {'openlist','immich'}:
        raise HTTPException(409,'遗留专用模块须由管理员显式迁移为通用网站')
    if incoming.icon not in store.ICONS:
        raise HTTPException(422,'不支持的图标')
    if incoming.icon not in NAVIGATION_ICONS and (not display_before or incoming.icon != display_before['icon']):
        raise HTTPException(422,'不支持的新图标；已有旧图标仅可原样保留')
    try: normalize_url(incoming.address)
    except (ValueError,HTTPException):
        checked = await check_draft(CheckInput(address=incoming.address),parent_origin=parent_origin)
        raise HTTPException(422,dict(code='website_check_failed',check=checked))
    connection = incoming.connection or effective_connection(before,old_target)
    if connection.auth_mode == 'header' and incoming.open_behavior == 'external':
        raise HTTPException(422,'凭据头认证需要隔离代理嵌入；外部打开请使用原站登录')
    from app.services.website_connection import preserve_legacy_target
    legacy_target = preserve_legacy_target(before,old_target,incoming.address,connection)

    same_identity = bool(before and origin(before['browser_url']) == origin(normalize_url(incoming.address)))
    wants_proxy = incoming.open_behavior == 'embedded' and connection.transport != 'direct' and connection.injection_delivery != 'loader' and (
        connection.transport == 'proxy' or connection.auth_mode == 'header' or bool(incoming.custom and incoming.custom.enabled) or
        (connection.transport == 'auto' and urlsplit(incoming.address).scheme == 'http' and urlsplit(parent_origin).scheme == 'https') or
        (same_identity and before['mode'] == 'isolated_proxy'))
    evidence = {}

    # Probe the transport that this save will actually deliver. An omitted or
    # disabled custom draft does not switch a retained auto proxy to HTTP iframe.
    probe_connection = connection.model_copy(update={'transport':'proxy'}) if wants_proxy else connection
    # Optional fields in the existing AppConfig JSON document: no SQL migration.
    entry = dict(id=mid, browser_url=normalize_url(incoming.address), mode='isolated_proxy' if wants_proxy else 'iframe',
                 private_address=incoming.private_address if 'private_address' in incoming.model_fields_set else (before or {}).get('private_address'),
                 entry_policy=incoming.entry_policy if 'entry_policy' in incoming.model_fields_set else (before or {}).get('entry_policy','follow'))
    address_mode, alternate, mapping_configured = mapping_values(incoming,before)
    entry.update(mapping_configured=mapping_configured,alternate_address=alternate)
    from app.services.entry_registry import validate_website_entry, records
    access_adapter = incoming.access_adapter if 'access_adapter' in incoming.model_fields_set else (before or {}).get('access_adapter','auto')
    previous_policy = copy.deepcopy((before or {}).get('request_policy',RequestPolicy().model_dump()))
    request_policy = incoming.request_policy.model_dump() if incoming.request_policy else previous_policy
    if wants_proxy and mid:
        entry['origin'] = (before or {}).get('origin') or store.derived_origin(mid,dict(adapter='generic',mode='isolated_proxy'))
    # An omitted legacy alternate is retained data, not a newly authorized
    # destination. Metadata/code edits may keep its exact existing binding even
    # after operator registry drift. Any explicit connection/alternate change,
    # address, delivery mode or entry-selection change still validates normally.
    # Public probing, credential/DNS pinning and launch-time registry checks are
    # deliberately unchanged; this branch cannot authorize a stale origin.
    retained_entry = bool(before and 'private_address' not in incoming.model_fields_set
        and 'connection' not in incoming.model_fields_set
        and incoming.address == before['browser_url']
        and before.get('origin') == store.derived_origin(mid, before)
        and incoming.open_behavior == ('external' if before['mode'] == 'link' else 'embedded')
        and wants_proxy == (before['mode'] == 'isolated_proxy')
        and access_adapter == before.get('access_adapter','auto')
        and request_policy == previous_policy
        and entry['entry_policy'] == before.get('entry_policy', 'follow'))
    if not retained_entry:
        validate_website_entry(entry)
    retained_proxy = retained_entry and wants_proxy
    if retained_proxy:
        # A metadata exception retains authority; it cannot repair or approve a
        # missing/partial target. Validate before any probe or target indexing.
        fields = set(proxy.TargetInput.model_fields)
        try:
            retained_targets=[(old_target,before.get('target_id'))]
            if old_binding is not None:
                if not isinstance(old_binding,dict):
                    raise ValueError('原其他入口绑定无效')
                retained_targets.append((old_alternate_target,old_binding.get('target_id')))
            for target,target_id in retained_targets:
                if not target or target.get('id') != target_id or not fields <= target.keys():
                    raise ValueError('原目标缺失或不完整')
                proxy.TargetInput.model_validate({key:target[key] for key in fields},strict=True)
        except (ValueError,TypeError):
            raise HTTPException(422,'原目标无效，请重新读取并明确配置连接') from None
    headers = copy.deepcopy(old_target['headers']) if legacy_target else credential_headers(connection,incoming.address,before,old_target)
    # Classify actual differences, not a client-provided "metadata" flag. The
    # unchanged target is still structurally checked above; launch authority is
    # not extended and no DNS, credential or remote reachability claim is made.
    local_only = bool(retained_entry
        # First enable still needs the original document/CSP authority check.
        and (incoming.custom is None or not incoming.custom.enabled or bool(((display_before.get('injection') or {}).get('active') or {}).get('enabled')))
        and (not wants_proxy or (old_target and target_authority.get(old_target['id']) == target_fingerprint(old_target)))
        and (not old_alternate_target or target_authority.get(old_alternate_target['id']) == target_fingerprint(old_alternate_target))
        and address_mode == before.get('address_mode')
        and alternate == before.get('alternate_address')
        and mapping_configured == before.get('mapping_configured',False)
        and entry['private_address'] == before.get('private_address')
        and (incoming.connection is None or (
            incoming.connection.token is None and not incoming.connection.clear_token
            and public_connection(connection,headers) == before.get('connection'))))
    if local_only:
        from app.public_website import public_website_result
        checked = dict(normalized_url=before['browser_url'],name_suggestion=display_before['name'],
            access=dict(status='unknown',http_status=None),
            embedding=dict(status='unknown',reason_code='code_only' if incoming.custom is not None else 'metadata_only',reason='仅保存本地设置，未重新检测连接'),
            injection=dict(status='unknown',reason='未重新检测连接'),help=None,can_save=True,
            recommended_behavior=incoming.open_behavior,issues=[])
        custom = incoming.custom.model_dump() | {'csp_policy':'reject'} if incoming.custom else None
        if custom:
            problems = await asyncio.to_thread(injection.errors,custom,{'mode':before['mode'],'connection':connection.model_dump(exclude={'token'})},old_target)
            problems += css_errors(custom['css'])
            if problems:
                raise HTTPException(422,dict(code='website_check_failed',check=checked | {'can_save':False,'issues':problems}))
        def persist_metadata(db):
            with store.edit(db) as config:
                result = retry_result(config,slot,digest,incoming.idempotency_key) if incoming.idempotency_key else None
                if result is not None: return result
                if incoming.expected_revision is not None and incoming.expected_revision != config.get('navigation_revision',0):
                    raise HTTPException(409,'网站编辑版本已改变，请重新读取并保留当前草稿')
                from app.services.access_entries import current as access_snapshot, read as read_access
                snapshot = access_snapshot()
                if snapshot is not None and read_access(db)['revision'] != snapshot['revision']:
                    raise HTTPException(409,'保存期间内外网设置已改变，请重新检查')
                if config['modules'].get(mid) != before or config['targets'].get(before.get('target_id')) != old_target:
                    raise HTTPException(409,'网站或目标已改变，请重新读取')
                if old_alternate_target and config['targets'].get(old_alternate_target['id']) != old_alternate_target:
                    raise HTTPException(409,'其他入口目标已改变，请重新读取')
                if [(i,e) for i,e in enumerate(config['navigation']) if e['id']==mid] != navigation_before:
                    raise HTTPException(409,'导航已改变，请重新读取')
                previous = copy.deepcopy((config['navigation'],config['modules']))
                data = copy.deepcopy(before)
                data.update(name=incoming.name or display_before['name'],icon=incoming.icon)
                if custom:
                    versions=data['injection']
                    if not incoming.preserve_saved_draft: versions['draft']=custom
                    if custom['enabled'] or versions['active'] or custom['css'] or custom['js'] or incoming.preserve_saved_draft:
                        if versions['active']: versions['previous']=versions['active']
                        versions['active']=custom | {'version':uuid4().hex}
                        bindings=config.setdefault('website_version_origins',{}).setdefault(mid,{})
                        bindings[versions['active']['version']]=data['browser_url']
                        keep={v['version'] for v in (versions['active'],versions['previous']) if v} | {v['version'] for v in config.get('website_retired_versions',{}).get(mid,[])}
                        config['website_version_origins'][mid]={k:v for k,v in bindings.items() if k in keep}
                for field in ('keep_alive','template_id','background'):
                    if field in incoming.model_fields_set: data[field] = getattr(incoming,field)
                config['modules'][mid] = data
                nav = next((e for e in config['navigation'] if e['id']==mid),None)
                if nav is None: nav=dict(id=mid);config['navigation'].append(nav)
                nav.update(title=data['name'],icon=data['icon'],visible=incoming.visible)
                if incoming.idempotency_key:
                    keys={k:v for k,v in config.get('website_save_keys',{}).items() if v['expires']>time.time()}
                    if len(keys)>=128: keys.pop(min(keys,key=lambda k:keys[k]['expires']))
                    keys[slot]=dict(id=mid,digest=digest,module_digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),check=checked,expires=time.time()+86400,
                        navigation_revision=config.get('navigation_revision',0)+int(previous!=(config['navigation'],config['modules'])))
                    config['website_save_keys']=keys
                store.record_change(db,action='integration.update',actor_id=actor_id,resource_id=mid,changed_fields=['name','icon','navigation','visible'])
            return public_website_result(data,checked) | {'navigation':store.navigation_projection(config),'idempotency_key':incoming.idempotency_key}
        return await run_in_threadpool(_database_phase, bind, persist_metadata)
    pin = old_target if old_target and (retained_proxy or legacy_target or (headers and connection.token is None and not connection.clear_token)) else None
    probe_address = old_target['upstream_url'].rstrip('/')+before.get('initial_path','/') if legacy_target else incoming.address
    if entry['private_address'] and not mapping_configured and not wants_proxy and not retained_entry:
        private_check = await check_draft(CheckInput(address=entry['private_address'],open_behavior=incoming.open_behavior,custom_enabled=bool(incoming.custom and incoming.custom.enabled),connection=probe_connection),parent_origin=records()['stella'].get('private',parent_origin))
        if not private_check['can_save']:
            raise HTTPException(422,dict(code='website_check_failed',check=private_check))
    if alternate and not wants_proxy:
        alternate_check = await check_draft(CheckInput(address=alternate,open_behavior=incoming.open_behavior,custom_enabled=bool(incoming.custom and incoming.custom.enabled),connection=probe_connection),parent_origin=records()['stella'].get('private',parent_origin))
        if not alternate_check['can_save']:
            raise HTTPException(422,dict(code='website_check_failed',check=alternate_check))
    checked = await check_draft(CheckInput(address=probe_address,open_behavior=incoming.open_behavior,custom_enabled=bool(incoming.custom and incoming.custom.enabled),connection=probe_connection),parent_origin=parent_origin,evidence=evidence,credential_headers=headers,approved_target=pin)
    if legacy_target: checked['normalized_url']=normalize_url(incoming.address)
    if not checked['can_save']: raise HTTPException(422,dict(code='website_check_failed',check=checked))
    prepared = None
    alternate_prepared = None
    alternate_reuse = False
    if wants_proxy and alternate:
        from app.services.website_mapping import prepare_alternate
        alternate_prepared, alternate_reuse = await prepare_alternate(alternate, connection, before, old_alternate_target,
            parent_origin=records()['stella'].get('private',parent_origin),custom_enabled=bool(incoming.custom.enabled if incoming.custom is not None else same_identity and before and (before.get('injection',{}).get('active') or {}).get('enabled')),name=incoming.name)
    safe_reuse = False
    if wants_proxy:
        parsed = urlsplit(checked['normalized_url'])
        root = old_target['upstream_url'] if legacy_target else parsed.scheme + '://' + parsed.netloc + '/'
        try:
            addresses = [safe_address(a) for a in await bounded_dns(proxy._preview_addresses,root)]
            if set(addresses) != set(evidence.get('allowed_ips',[])): raise ValueError('检测之后 DNS 发生变化')
            prepared = proxy.TargetInput(name=incoming.name or checked['name_suggestion'],upstream_url=root,allowed_ips=addresses,headers=headers,controlled=old_target['controlled'] if legacy_target else False).model_dump()
        except (OSError,ValueError,TimeoutError,ProbeFailure):
            checked.update(can_save=False,issues=checked['issues']+['提交前目标解析失败或已变更'])
            raise HTTPException(422,dict(code='website_check_failed',check=checked))
        # Compute before entering the mutating transaction. In particular a
        # retained header-free proxy must never fall through to target creation.
        safe_reuse = old_target and old_target['headers'] == prepared['headers'] and old_target['controlled'] == prepared['controlled'] and old_target['upstream_url'] == prepared['upstream_url'] and set(old_target['allowed_ips']) == set(prepared['allowed_ips'])
        if retained_proxy and not safe_reuse:
            raise HTTPException(422,'原目标授权与检测结果不同，请明确配置连接')
    custom = incoming.custom.model_dump() | {'csp_policy':'reject'} if incoming.custom else None
    if custom:
        problems = await asyncio.to_thread(injection.errors,custom,{'mode':'isolated_proxy' if prepared else 'iframe','connection':connection.model_dump(exclude={'token'})},prepared)
        problems += css_errors(custom['css'])
        if problems:
            checked.update(can_save=False,issues=checked['issues']+problems)
            raise HTTPException(422,dict(code='website_check_failed',check=checked))
    def persist_checked(db, mid=mid):
        with store.edit(db) as config:
            result = retry_result(config,slot,digest,incoming.idempotency_key) if incoming.idempotency_key else None
            if result is not None: return result
            if incoming.expected_revision is not None and incoming.expected_revision != config.get('navigation_revision',0):
                raise HTTPException(409,'网站编辑版本已改变，请重新读取并保留当前草稿')
            from app.services.access_entries import current as access_snapshot, read as read_access
            snapshot = access_snapshot()
            if snapshot is not None and read_access(db)['revision'] != snapshot['revision']:
                raise HTTPException(409,'检测期间内外网设置已改变，请重新检查')
            if old_target and config['targets'].get(old_target['id']) != old_target: raise HTTPException(409,'检测期间目标已变更，请重新读取')
            if old_alternate_target and config['targets'].get(old_alternate_target['id']) != old_alternate_target: raise HTTPException(409,'检测期间其他入口目标已变更，请重新读取')
            if mid and config['modules'].get(mid) != before: raise HTTPException(409,'检测期间网站已变更，请重新读取')
            if before and ([(index,entry) for index,entry in enumerate(config['navigation']) if entry['id'] == mid] != navigation_before or store.display_module(before,config) != display_before):
                raise HTTPException(409,'检测期间网站导航显示已变更，请重新读取')
            if mid is None and len(config['modules']) >= 128: raise HTTPException(422,'模块数量超过限制')
            is_new = mid is None
            mid = mid or uuid4().hex
            data = store.ModuleInput(name=incoming.name or (display_before and display_before['name']) or checked['name_suggestion'] or '网站', icon=incoming.icon,
                                     browser_url=checked['normalized_url'], mode='link' if incoming.open_behavior=='external' else 'iframe',
                                     enabled=before['enabled'] if before else True,keep_alive=incoming.keep_alive).model_dump()
            data.update(template_id=incoming.template_id if 'template_id' in incoming.model_fields_set else (before or {}).get('template_id'),
                        private_address=entry['private_address'],entry_policy=entry['entry_policy'],
                        access_adapter=access_adapter,
                        connection=public_connection(connection,headers),
                        background=incoming.background if 'background' in incoming.model_fields_set else (before or {}).get('background','solid'),
                        request_policy=request_policy)
            if 'address_mode' in incoming.model_fields_set or (before and 'address_mode' in before):
                data['address_mode'] = address_mode
            if mapping_configured: data.update(alternate_address=alternate, mapping_configured=True)
            if before and before.get('migration'): data['migration'] = copy.deepcopy(before['migration'])
            data.update(id=mid,origin=store.derived_origin(mid,data),injection=copy.deepcopy(before['injection']) if before else dict(draft=None,active=None,previous=None))
            old_url = (before.get('browser_url') or (old_target and old_target['upstream_url'])) if before else None
            identity_changed = bool(old_url and origin(old_url) != origin(data['browser_url']))
            versions = data['injection']
            bindings = config.setdefault('website_version_origins',{}).setdefault(mid,{})
            if identity_changed:
                retired = [copy.deepcopy(v) for v in (versions['active'],versions['previous']) if v]
                config.setdefault('website_retired_versions',{})[mid] = retired
                for version in retired: bindings.setdefault(version['version'],old_url)
                if versions['active']:
                    versions['previous'] = versions['active']
                versions['active'] = None
                if not incoming.preserve_saved_draft and (versions['draft'] or versions['previous']):
                    versions['draft'] = {k:v for k,v in (versions['draft'] or versions['previous']).items() if k not in {'version','source_origin'}} | {'enabled':False,'csp_policy':'reject'}
            if prepared:
                # Reuse only the exact checked snapshot, including credential and CSP authority.
                tid = old_target['id'] if safe_reuse else uuid4().hex
                if not safe_reuse:
                    if len(config['targets']) >= 128: raise HTTPException(422,'目标数量超过限制')
                    config['targets'][tid] = prepared | {'id':tid}
                parsed = urlsplit(data['browser_url'])
                initial = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')
                data.update(mode='isolated_proxy',target_id=tid,initial_path=before.get('initial_path','/') if legacy_target or retained_proxy else initial)
                config.setdefault('website_target_authority',{})[tid]=target_fingerprint(config['targets'][tid])
            if alternate_prepared:
                from app.services.website_mapping import UpstreamBinding, initial_path
                alternate_tid = old_alternate_target['id'] if alternate_reuse else uuid4().hex
                if not alternate_reuse:
                    if len(config['targets']) >= 128: raise HTTPException(422,'目标数量超过限制')
                    config['targets'][alternate_tid] = alternate_prepared | {'id':alternate_tid}
                data['alternate_binding'] = UpstreamBinding(target_id=alternate_tid,initial_path=initial_path(alternate)).model_dump()
                config.setdefault('website_target_authority',{})[alternate_tid]=target_fingerprint(config['targets'][alternate_tid])
            if incoming.open_behavior == 'external' and versions['active'] and (not before or before['mode'] != 'link'):
                versions['previous'] = versions['active']
                versions['active'] = None
            if custom:
                if not incoming.preserve_saved_draft: versions['draft'] = custom
                if custom['enabled']:
                    if versions['active']: versions['previous'] = versions['active']
                    versions['active'] = custom | {'version':uuid4().hex}
                    bindings[versions['active']['version']] = data['browser_url']
                elif versions['active'] or custom['css'] or custom['js'] or incoming.preserve_saved_draft:
                    # One website editor reads the applied snapshot, including disabled
                    # or explicitly empty code saved while retaining a historical draft.
                    # A historical draft alone must never masquerade as applied code.
                    if versions['active']: versions['previous'] = versions['active']
                    versions['active'] = custom | {'version':uuid4().hex}
                    bindings[versions['active']['version']] = data['browser_url']
            elif wants_proxy and incoming.open_behavior == 'embedded' and not identity_changed and before and before['mode'] == 'isolated_proxy' and versions['active']:
                # Omitted custom means preserve a same-identity active version, not silently disable it.
                if checked['injection']['status'] != 'supported': raise HTTPException(422,dict(code='website_check_failed',check=checked | {'can_save':False}))
            if before and any(data.get(k) != before.get(k) for k in ('browser_url','mode','target_id','initial_path','origin','connection','request_policy','alternate_address','alternate_binding','mapping_configured','private_address','entry_policy')):
                for key in ('tickets','grants'):
                    config[key] = {k:v for k,v in config[key].items() if v['id'] != mid}
            keep_versions = {v['version'] for v in (versions['active'],versions['previous']) if v} | {v['version'] for v in config.get('website_retired_versions',{}).get(mid,[])}
            config['website_version_origins'][mid] = {key:value for key,value in bindings.items() if key in keep_versions}
            config['modules'][mid] = data
            nav = next((e for e in config['navigation'] if e['id'] == mid),None)
            if nav is None:
                nav = dict(id=mid); config['navigation'].append(nav)
            nav.update(title=data['name'],icon=data['icon'],visible=incoming.visible)
            if incoming.idempotency_key:
                keys = {k:v for k,v in config.get('website_save_keys',{}).items() if v['expires'] > time.time()}
                if len(keys) >= 128: keys.pop(min(keys,key=lambda k:keys[k]['expires']))
                keys[slot] = dict(id=mid,digest=digest,module_digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),check=checked,expires=time.time()+86400,navigation_revision=config.get('navigation_revision',0)+1)
                config['website_save_keys'] = keys
            store.record_change(db,action='integration.create' if is_new else 'integration.update',actor_id=actor_id,resource_id=mid,changed_fields=['name','icon','navigation','visible'])
            from app.public_website import public_website_result
            result = public_website_result(data, checked)
        return result | {'navigation':store.navigation_projection(config),'idempotency_key':incoming.idempotency_key}

    return await run_in_threadpool(_database_phase, bind, persist_checked)
