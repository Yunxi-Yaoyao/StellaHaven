"""Single-owner integrations in PostgreSQL AppConfig; no user/visibility tables."""
import copy
import json
from typing import Any
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.config import AppConfig
from app.services.backup_health import record_change

KEY = 'integrations_v1'
IMMICH_HOSTS = {'immich.xiya.live', 'immich.yunxi.life'}
BUILTINS = [
    dict(id='home', title='首页', icon='home', route='/'),
    dict(id='notes', title='笔记', icon='file-text', route='/notes'),
    dict(id='gallery', title='图库', icon='image', route='/gallery'),
    dict(id='drive', title='网盘', icon='hard-drive', route='/drive'),
    dict(id='status', title='服务器', icon='server', route='/status'),
    dict(id='settings', title='设置', icon='settings', route='/settings'),
]
ICONS = {'note','drive','box','home','file-text','image','hard-drive','server','settings','globe','link','folder','book','activity','cloud','star','code','external-link','monitor','music','video','database','terminal','grid','heart','calendar','bookmark','layers','cpu','search'}


def browser_url(value):
    try:
        p = urlsplit(value)
        if p.scheme not in {'http','https'} or not p.hostname or p.username is not None or p.password is not None:
            raise ValueError('完整 http/https URL，不允许账号密码')
        _ = p.port
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or '\\' in value:
            raise ValueError('URL 包含不安全字符')
    except (ValueError, TypeError) as exc:
        raise ValueError('不合法的网站 URL') from exc
    return value


class ModuleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    icon: str = 'globe'
    mode: str = 'iframe'
    adapter: str = 'generic'
    browser_url: str = ''
    target_id: str | None = None
    initial_path: str = '/'
    enabled: bool = True
    keep_alive: bool = Field(default=False, strict=True)

    @field_validator('browser_url')
    @classmethod
    def url(cls, value):
        return browser_url(value) if value else value

    @field_validator('icon')
    @classmethod
    def icon_valid(cls, value):
        if value not in ICONS:
            raise ValueError('不支持的图标')
        return value

    @field_validator('mode')
    @classmethod
    def mode_valid(cls, value):
        if value not in {'iframe','link','openlist','isolated_proxy'}:
            raise ValueError('不支持的接入模式')
        return value

    @field_validator('adapter')
    @classmethod
    def adapter_valid(cls, value):
        if value not in {'generic','openlist','immich'}:
            raise ValueError('不支持的服务模板')
        return value

    @field_validator('initial_path')
    @classmethod
    def path_valid(cls, value):
        if not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c)<32 for c in value):
            raise ValueError('起始路径必须是 origin 内路径')
        return value


class NavigationEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    title: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = None
    visible: bool = True

    @field_validator('icon')
    @classmethod
    def icon_valid(cls, value):
        if value is not None and value not in ICONS:
            raise ValueError('不支持的图标')
        return value


class NavigationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entries: list[NavigationEntry] = Field(default_factory=list, max_length=200)
    reset: bool = False


def empty_state() -> dict[str, Any]:
    return dict(modules={}, targets={}, navigation=[], tickets={}, grants={})


def state(db) -> dict[str, Any]:
    row = db.get(AppConfig, KEY)
    return json.loads(row.value) if row else empty_state()


@contextmanager
def edit(db):
    # Seed + lock in one transaction: concurrent navigation/module/grant writes cannot overwrite.
    db.execute(insert(AppConfig).values(key=KEY, value=json.dumps(empty_state())).on_conflict_do_nothing(index_elements=['key']))
    row = db.execute(select(AppConfig).where(AppConfig.key == KEY).with_for_update().execution_options(populate_existing=True)).scalar_one()
    value = json.loads(row.value)
    try:
        yield value
        row.value = json.dumps(value, ensure_ascii=False)
        db.commit()
    except BaseException:
        db.rollback()
        raise


def get_module(db, mid):
    module = state(db)['modules'].get(mid)
    if module is None:
        raise HTTPException(404, '模块不存在')
    return module


def present(module):
    result = copy.deepcopy(module)
    result.setdefault('keep_alive', False)
    result['route'] = '/apps/' + module['id']
    adapter = module.get('adapter', 'generic')
    managed = '/settings?section=navigation&module=' + ('drive' if adapter=='openlist' else 'gallery') if adapter in {'openlist','immich'} else None
    result['capabilities'] = {'injection': module['mode']=='isolated_proxy' and adapter=='generic',
                              'browser_status': 'unobservable', 'managed_settings': managed}
    return result


def check_module(value, config):
    if value['mode'] in {'iframe','link'} and not value['browser_url'] and value['adapter'] != 'immich':
        raise HTTPException(422, '此接法需要网站 URL')
    if value['mode'] == 'isolated_proxy' and value['target_id'] not in config['targets']:
        raise HTTPException(422, '请选择已批准的固定上游')
    if value['adapter']=='immich' and value['mode']=='openlist':
        raise HTTPException(422, 'Immich 不支持兼容子路径代理')
    if value['adapter']=='immich' and value['mode']=='isolated_proxy':
        p=urlsplit(value['browser_url'])
        if p.scheme!='https' or p.hostname not in IMMICH_HOSTS or p.port is not None or p.path not in {'','/'} or p.query or p.fragment:
            raise HTTPException(422,'Immich 代理只接管已批准的现有 HTTPS 根域名，保留 OIDC 回调')
        if not config['targets'][value['target_id']]['controlled']:
            raise HTTPException(422,'Immich 域名接管需要受控上游')


def create_module(db, incoming, actor_id):
    value = incoming.model_dump()
    with edit(db) as config:
        check_module(value, config)
        if len(config['modules']) >= 128:
            raise HTTPException(422, '模块数量超过限制')
        mid = uuid4().hex
        value.update(id=mid, origin=f'https://app-{mid}.xiya.live', injection=dict(draft=None,active=None,previous=None))
        if value['adapter']=='immich' and value['mode']=='isolated_proxy':
            value['origin']=value['browser_url'].rstrip('/')
            if any(m['origin']==value['origin'] for m in config['modules'].values()):
                raise HTTPException(409,'此 Immich 域名已有模块')
        config['modules'][mid] = value
        record_change(db,action='integration.create',actor_id=actor_id,resource_id=mid,changed_fields=['name','icon','mode','target','enabled'])
    return present(value)


def patch_module(db, mid, patch, actor_id):
    if set(patch) - set(ModuleInput.model_fields):
        raise HTTPException(422, '包含不可修改的字段')
    with edit(db) as config:
        value = config['modules'].get(mid)
        if value is None:
            raise HTTPException(404, '模块不存在')
        try:
            merged = ModuleInput(**({k:value[k] for k in ModuleInput.model_fields if k in value} | patch)).model_dump()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        check_module(merged, config)
        value.update(merged)
        record_change(db,action='integration.update',actor_id=actor_id,resource_id=mid,changed_fields=[('target' if k=='target_id' else k) for k in patch])
    return present(value)


def delete_module(db, mid, actor_id):
    with edit(db) as config:
        if mid not in config['modules']:
            raise HTTPException(404, '模块不存在')
        del config['modules'][mid]
        config['navigation'] = [e for e in config['navigation'] if e['id'] != mid]
        for key in ('tickets','grants'):
            config[key] = {k:v for k,v in config[key].items() if v['id']!=mid}
        record_change(db,action='integration.delete',actor_id=actor_id,resource_id=mid,changed_fields=['navigation'])


def navigation(db):
    config = state(db)
    defaults = {e['id']:dict(e, visible=True,builtin=True) for e in BUILTINS}
    defaults.update({mid:dict(id=mid,title=m['name'],icon=m['icon'],visible=m['enabled'],route='/apps/'+mid,builtin=False) for mid,m in config['modules'].items()})
    entries = []
    for override in config['navigation']:
        default = defaults.pop(override['id'], None)
        if default:
            entries.append(default | {k:v for k,v in override.items() if v is not None})
    entries.extend(defaults.values())
    return dict(entries=entries, settings_route='/settings')


def save_navigation(db, incoming, actor_id):
    with edit(db) as config:
        allowed = {b['id'] for b in BUILTINS} | set(config['modules'])
        ids = [e.id for e in incoming.entries]
        if len(ids)!=len(set(ids)) or not set(ids)<=allowed:
            raise HTTPException(422, '导航包含未知或重复 ID')
        config['navigation'] = [] if incoming.reset else [e.model_dump() for e in incoming.entries]
        record_change(db,action='navigation.update',actor_id=actor_id,changed_fields=['navigation','order','visible','title','icon'])
    return navigation(db)
