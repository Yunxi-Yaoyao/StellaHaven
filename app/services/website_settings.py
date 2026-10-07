"""Unified website saves using the existing single-owner AppConfig transaction."""
import copy
import hashlib
import json
import time
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi import HTTPException
from app.services import integrations as store
from app.services.website_check import CheckInput, check_draft, normalize_url, origin, bounded_dns, safe_address, ProbeFailure
from app.services import integrations_proxy as proxy, integrations_injection as injection
import asyncio
from urllib.parse import urlsplit

from app.services.website_connection import ConnectionInput, RequestPolicy, effective_connection, credential_headers, public_connection

NAVIGATION_ICONS = {'home','note','image','drive','server','settings','globe','link','book','folder','terminal','star','activity','box'}

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

class WebsiteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(min_length=1,max_length=2048)
    name: str | None = Field(default=None,min_length=1,max_length=100)
    icon: str = 'globe'
    visible: bool = True
    keep_alive: bool = False
    open_behavior: Literal['embedded','external'] = 'embedded'
    custom: CustomInput | None = None
    template_id: Literal['openlist','immich'] | None = None
    connection: ConnectionInput | None = None
    background: Literal['solid','home'] = 'solid'
    request_policy: RequestPolicy | None = None
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=128,pattern=r'^[A-Za-z0-9_.:-]+$')

    @field_validator('icon')
    @classmethod
    def valid_icon(cls, value):
        # Legacy values need module context before deciding retention vs change.
        if value not in store.ICONS: raise ValueError('不支持的图标')
        return value

def fingerprint(incoming, *, patch=False):
    body = incoming.model_dump(exclude={'idempotency_key'})
    if patch: body['provided_fields'] = sorted(incoming.model_fields_set - {'idempotency_key'})
    try: body['address'] = normalize_url(body['address'])
    except (ValueError,HTTPException): pass
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def retry_result(config, slot, digest):
    entry = config.get('website_save_keys',{}).get(slot)
    if not entry or entry['expires'] <= time.time(): return None
    if entry['digest'] != digest: raise HTTPException(409,'幂等键已用于不同的网站草稿')
    module = config['modules'].get(entry['id'])
    if module is None or hashlib.sha256(json.dumps(module,sort_keys=True).encode()).hexdigest() != entry['module_digest']:
        raise HTTPException(409,'已保存的网站随后发生变更，请重新读取后保存')
    return store.present(module) | {'check':copy.deepcopy(entry['check'])}

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

async def save_website(db, incoming, actor_id, *, parent_origin, mid=None):
    if mid is None and incoming.idempotency_key is None: raise HTTPException(422,'新增网站需要 idempotency_key')
    digest = fingerprint(incoming,patch=mid is not None)
    slot = str(actor_id) + ':' + (mid or 'create') + ':' + (incoming.idempotency_key or '')
    config = store.state(db)
    result = retry_result(config,slot,digest) if incoming.idempotency_key else None
    before = copy.deepcopy(config['modules'].get(mid)) if mid else None
    display_before = store.display_module(before,config) if before else None
    old_target = copy.deepcopy(config['targets'].get(before.get('target_id'))) if before else None
    if before:
        override = next((e for e in config['navigation'] if e['id']==mid),{})
        defaults = dict(name=display_before['name'],icon=display_before['icon'],keep_alive=before.get('keep_alive',False),visible=override.get('visible',before['enabled']),open_behavior='external' if before['mode']=='link' else 'embedded')
        incoming = incoming.model_copy(update={key:value for key,value in defaults.items() if key not in incoming.model_fields_set})
    db.rollback()  # Release read connection before bounded external I/O.
    if result is not None: return result
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
    headers = copy.deepcopy(old_target['headers']) if legacy_target else credential_headers(connection,incoming.address,before,old_target)
    same_identity = bool(before and origin(before['browser_url']) == origin(normalize_url(incoming.address)))
    wants_proxy = incoming.open_behavior == 'embedded' and connection.transport != 'direct' and connection.injection_delivery != 'loader' and (
        connection.transport == 'proxy' or connection.auth_mode == 'header' or bool(incoming.custom and incoming.custom.enabled) or
        (same_identity and before['mode'] == 'isolated_proxy'))
    evidence = {}
    pin=old_target if old_target and (legacy_target or (headers and connection.token is None and not connection.clear_token)) else None
    probe_address=old_target['upstream_url'].rstrip('/')+before.get('initial_path','/') if legacy_target else incoming.address
    checked = await check_draft(CheckInput(address=probe_address,open_behavior=incoming.open_behavior,custom_enabled=bool(incoming.custom and incoming.custom.enabled),connection=connection),parent_origin=parent_origin,evidence=evidence,credential_headers=headers,approved_target=pin)
    if legacy_target: checked['normalized_url']=normalize_url(incoming.address)
    if not checked['can_save']: raise HTTPException(422,dict(code='website_check_failed',check=checked))
    prepared = None
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
    custom = incoming.custom.model_dump() | {'csp_policy':'reject'} if incoming.custom else None
    if custom:
        problems = await asyncio.to_thread(injection.errors,custom,{'mode':'isolated_proxy' if prepared else 'iframe','connection':connection.model_dump(exclude={'token'})},prepared)
        problems += css_errors(custom['css'])
        if problems:
            checked.update(can_save=False,issues=checked['issues']+problems)
            raise HTTPException(422,dict(code='website_check_failed',check=checked))
    with store.edit(db) as config:
        result = retry_result(config,slot,digest) if incoming.idempotency_key else None
        if result is not None: return result
        if old_target and config['targets'].get(old_target['id']) != old_target: raise HTTPException(409,'检测期间目标已变更，请重新读取')
        if mid and config['modules'].get(mid) != before: raise HTTPException(409,'检测期间网站已变更，请重新读取')
        if before and store.display_module(before,config) != display_before:
            raise HTTPException(409,'检测期间网站导航显示已变更，请重新读取')
        if mid is None and len(config['modules']) >= 128: raise HTTPException(422,'模块数量超过限制')
        is_new = mid is None
        mid = mid or uuid4().hex
        data = store.ModuleInput(name=incoming.name or (display_before and display_before['name']) or checked['name_suggestion'] or '网站', icon=incoming.icon,
                                 browser_url=checked['normalized_url'], mode='link' if incoming.open_behavior=='external' else 'iframe',
                                 enabled=before['enabled'] if before else True,keep_alive=incoming.keep_alive).model_dump()
        data.update(template_id=incoming.template_id if 'template_id' in incoming.model_fields_set else (before or {}).get('template_id'),
                    connection=public_connection(connection,headers),
                    background=incoming.background if 'background' in incoming.model_fields_set else (before or {}).get('background','solid'),
                    request_policy=incoming.request_policy.model_dump() if incoming.request_policy else copy.deepcopy((before or {}).get('request_policy',RequestPolicy().model_dump())))
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
            if versions['draft'] or versions['previous']:
                versions['draft'] = {k:v for k,v in (versions['draft'] or versions['previous']).items() if k not in {'version','source_origin'}} | {'enabled':False,'csp_policy':'reject'}
        if prepared:
            # Reuse only the exact checked snapshot, including credential and CSP authority.
            safe_reuse = old_target and old_target['headers'] == prepared['headers'] and old_target['controlled'] == prepared['controlled'] and old_target['upstream_url'] == prepared['upstream_url'] and set(old_target['allowed_ips']) == set(prepared['allowed_ips'])
            tid = old_target['id'] if safe_reuse else uuid4().hex
            if not safe_reuse:
                if len(config['targets']) >= 128: raise HTTPException(422,'目标数量超过限制')
                config['targets'][tid] = prepared | {'id':tid}
            parsed = urlsplit(data['browser_url'])
            initial = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')
            data.update(mode='isolated_proxy',target_id=tid,initial_path=before.get('initial_path','/') if legacy_target else initial)
        if incoming.open_behavior == 'external' and versions['active']:
            versions['previous'] = versions['active']
            versions['active'] = None
        if custom:
            versions['draft'] = custom
            if custom['enabled']:
                if versions['active']: versions['previous'] = versions['active']
                versions['active'] = custom | {'version':uuid4().hex}
                bindings[versions['active']['version']] = data['browser_url']
            elif versions['active']:
                versions['previous'] = versions['active']
                versions['active'] = custom | {'version':uuid4().hex}
                bindings[versions['active']['version']] = data['browser_url']
        elif wants_proxy and incoming.open_behavior == 'embedded' and not identity_changed and before and before['mode'] == 'isolated_proxy' and versions['active']:
            # Omitted custom means preserve a same-identity active version, not silently disable it.
            if checked['injection']['status'] != 'supported': raise HTTPException(422,dict(code='website_check_failed',check=checked | {'can_save':False}))
        if before and any(data[k] != before.get(k) for k in ('browser_url','mode','target_id','initial_path','origin','connection','request_policy')):
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
            keys[slot] = dict(id=mid,digest=digest,module_digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),check=checked,expires=time.time()+86400)
            config['website_save_keys'] = keys
        store.record_change(db,action='integration.create' if is_new else 'integration.update',actor_id=actor_id,resource_id=mid,changed_fields=['name','icon','navigation','visible'])
        result = store.present(data) | {'check':checked}
    return result
