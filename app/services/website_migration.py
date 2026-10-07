"""Operator-only, reversible single-transaction legacy → generic migration.

Call migrate_legacy(db, approved_ips=[...]) after DNS-only approval of the exact
legacy drive upstream. No HTTP, service configuration, storage or account writes.
Rollback refuses intervening registry edits; deploy the legacy release with it.
"""
import copy
import hashlib
import json
from uuid import uuid4
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.config import AppConfig
from app.services import integrations as store, builtin_injection as builtin, external_services as external, service_appearance as appearance
from app.services.website_templates import catalog, export_code
from app.services.website_check import normalize_url
from app.services.integrations_proxy import TargetInput
from app.services.website_connection import ConnectionInput, public_connection

MARKER = 'website_migration_v1'
LEGACY_BUILTINS = [dict(id='home',title='首页',icon='home'),dict(id='notes',title='笔记',icon='file-text'),dict(id='gallery',title='图库',icon='image'),dict(id='drive',title='网盘',icon='hard-drive'),dict(id='status',title='服务器',icon='server'),dict(id='settings',title='设置',icon='settings')]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


def exact_legacy_signatures():
    from app.services.drive import OPENLIST_THEME_CSS, OPENLIST_THEME_JS
    return {'style':[digest_text(OPENLIST_THEME_CSS)], 'script':[digest_text(OPENLIST_THEME_JS)]}


def digest_text(value):
    return hashlib.sha256(value.strip().encode('utf-8')).hexdigest()


def migrate_legacy(db, *, approved_ips, actor_id, main_origin='https://stella.xiya.live'):
    defaults = {store.KEY:store.empty_state(),builtin.KEY:builtin.empty_state(),appearance.KEY:appearance.DEFAULTS,
                'external_drive_connection':external.DEFAULTS['drive'],'external_gallery_connection':external.DEFAULTS['gallery']}
    try:
        rows = {}
        for key in sorted(defaults):
            db.execute(insert(AppConfig).values(key=key,value=json.dumps(defaults[key])).on_conflict_do_nothing(index_elements=['key']))
            rows[key] = db.execute(select(AppConfig).where(AppConfig.key==key).with_for_update().execution_options(populate_existing=True)).scalar_one()
        registry = json.loads(rows[store.KEY].value)
        if MARKER in registry:
            db.rollback()
            return copy.deepcopy(registry.get('legacy_routes',{}))
        before = copy.deepcopy(registry)
        values = {k:json.loads(row.value) for k,row in rows.items()}
        templates = {t['id']:t['draft'] for t in catalog(main_origin=main_origin)}
        defaults_nav = {e['id']:dict(e,visible=True) for e in LEGACY_BUILTINS}
        defaults_nav.update({mid:dict(id=mid,title=m['name'],icon=m['icon'],visible=m['enabled']) for mid,m in registry['modules'].items()})
        navigation = []
        for entry in registry['navigation']:
            if entry['id'] in defaults_nav:
                navigation.append(defaults_nav.pop(entry['id']) | {k:v for k,v in entry.items() if v is not None})
        navigation.extend(defaults_nav.values())
        aliases = {}; removed = set()
        for site, template_id in [('drive','openlist'),('gallery','immich')]:
            legacy = [m for m in registry['modules'].values() if m.get('adapter')==template_id]
            if len(legacy)>1: raise HTTPException(409,'多个遗留专用模块需要先显式核对，未做任何迁移')
            old = legacy[0] if legacy else None
            entry = next(e for e in navigation if e['id']==site)
            if old:
                # Avoid duplicate old adapter entries; preserve its snapshots.
                removed.add(old['id'])
            # Validate the exported URL/token with generic validators below, not the
            # retired singleton's loopback:5244-only URL constraint.
            cfg = external.Connection.model_construct(**values['external_'+site+'_connection'])
            address = normalize_url((cfg.upstream_url or cfg.browser_url) if site=='drive' else cfg.browser_url)
            parsed = urlsplit(address)
            mid = uuid4().hex
            aliases[site] = mid
            connection = ConnectionInput(**templates[template_id]['connection'])
            headers = {}
            if site=='drive' and cfg.auth_mode=='token':
                if not cfg.token: raise HTTPException(422,'遗留凭据缺失，迁移已回滚')
                connection.auth_mode='header'; headers={'authorization':cfg.token}
            active = values[builtin.KEY][site]['active']
            visual = appearance.DEFAULTS[site] | values[appearance.KEY].get(site,{})
            code = export_code(site,visual,active,main_origin=main_origin) | {'csp_policy':'reject'}
            version = code | {'version':uuid4().hex}
            module = store.ModuleInput(name=entry['title'],icon=entry['icon'],browser_url=address,mode='isolated_proxy' if site=='drive' else 'iframe').model_dump()
            module.update(id=mid,template_id=template_id,origin=store.derived_origin(mid,module),connection=public_connection(connection,headers),background=templates[template_id]['background'],request_policy=templates[template_id]['request_policy'],
                          injection=dict(active=version,draft=copy.deepcopy(code),previous=None),
                          migration=dict(legacy_route=site,legacy_injection=copy.deepcopy(values[builtin.KEY][site]),legacy_module=copy.deepcopy(old)))
            if site=='drive':
                tid = uuid4().hex
                target = TargetInput(name=entry['title'],upstream_url=parsed.scheme+'://'+parsed.netloc+'/',allowed_ips=approved_ips,headers=headers,controlled=False).model_dump() | {'id':tid}
                registry['targets'][tid]=target
                module.update(target_id=tid,initial_path=parsed.path or '/')
                module['migration']['exact_legacy_sha256']=exact_legacy_signatures()
            registry['modules'][mid]=module
            registry.setdefault('website_version_origins',{})[mid]={version['version']:address}
            entry['id']=mid
        for old_id in removed: registry['modules'].pop(old_id,None)
        registry['navigation']=[e for e in navigation if e['id'] not in removed]
        for key in ('tickets','grants'):
            registry[key]={k:v for k,v in registry[key].items() if v['id'] not in removed}
        registry['legacy_routes']=aliases
        registry[MARKER]={'before':before,'after_digest':digest(registry)}
        rows[store.KEY].value=json.dumps(registry,ensure_ascii=False)
        store.record_change(db,action='integration.update',actor_id=actor_id,changed_fields=['navigation','injection','target'])
        db.commit()
        return copy.deepcopy(aliases)
    except BaseException:
        db.rollback(); raise


def rollback_legacy(db):
    with store.edit(db) as registry:
        marker=registry.get(MARKER)
        if not marker: raise HTTPException(409,'没有通用网站迁移快照')
        if digest({k:v for k,v in registry.items() if k!=MARKER}) != marker['after_digest']:
            raise HTTPException(409,'迁移后网站已修改；保留变更，拒绝覆盖回退')
        before=copy.deepcopy(marker['before'])
        registry.clear(); registry.update(before)


def require_unmigrated(db):
    if MARKER in store.state(db): raise HTTPException(410,'遗留服务入口已迁移；请使用通用网站模块')
