"""Explicit owner-applied entry selection; deployment trust is never UI-writable.

One immutable request snapshot is used by launch/check/host/ACK/OIDC consumers.
Saving never writes environment, DNS, TLS, callbacks or upstream credentials.
"""
import hashlib
import json
from contextlib import contextmanager, asynccontextmanager
from types import MappingProxyType
from contextvars import ContextVar
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from fastapi import HTTPException
from app.models.config import AppConfig

KEY = 'access_entries.v1'
_snapshot = ContextVar('stella_access_entries', default=None)

class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    enabled: bool  # Legacy wire/storage field; no longer gates same-entry selection.
    public_origin: str = Field(max_length=300)
    private_origin: str | None = Field(default=None, max_length=300)

    @field_validator('public_origin','private_origin')
    @classmethod
    def exact_origin(cls,value):
        if value is not None:
            from app.services.entry_registry import _origin
            _origin(value)
        return value

class ApplyInput(Settings):
    checked_digest: str = Field(pattern=r'^[0-9a-f]{64}$')


def pinned_owner(db):
    from app.services.admin_security import read_state
    from uuid import UUID
    import os
    _, identity = read_state(db)
    try:
        owner = str(UUID(identity.get('owner_id','')))
        if os.getenv('STELLA_OWNER_ID') and os.getenv('STELLA_OWNER_ID') != owner:
            raise ValueError()
        return owner
    except (ValueError,TypeError,AttributeError):
        raise HTTPException(503,'内外网设置需要已固定的管理身份')


def bootstrap():
    from app.services.entry_registry import records
    pair = records()['stella']
    # An absent owner override inherits deployment capabilities, without a GET write.
    # Persisted null remains an explicit opt-out and is handled by read(), not here.
    return dict(revision=0,enabled=False,public_origin=pair['public'],private_origin=pair.get('private'))


def read(db,actor=None):
    row = db.get(AppConfig,KEY,populate_existing=True)
    if actor is not None and str(actor) != pinned_owner(db):
        raise HTTPException(403,'仅空间所有者可管理内外网设置')
    if row is None:
        return bootstrap()
    try:
        value = json.loads(row.value)
        if set(value) != {'owner_id','settings'} or value['owner_id'] != pinned_owner(db):
            raise ValueError()
        return Settings.model_validate(value['settings']).model_dump()
    except (ValueError,KeyError,TypeError):
        raise HTTPException(503,'内外网设置无效，请修复已保存配置')


def _read_snapshot(factory):
    # Session construction, checkout, read and close belong to one worker.
    with factory() as db:
        return MappingProxyType(read(db))


@asynccontextmanager
async def async_request_snapshot(factory):
    from starlette.concurrency import run_in_threadpool
    value = await run_in_threadpool(_read_snapshot, factory)
    # ContextVar tokens must be set/reset on the requesting task, not the worker.
    token = _snapshot.set(value)
    try:
        yield value
    finally:
        _snapshot.reset(token)


@contextmanager
def request_snapshot(factory):
    value = _read_snapshot(factory)
    token = _snapshot.set(value)
    try:
        yield value
    finally:
        _snapshot.reset(token)


def current():
    return _snapshot.get()


def lane(source, *, policy='follow'):
    from app.services.entry_registry import parent_context
    deployed_lane = parent_context(source)
    value = current()
    if value is None:
        return 'public' if policy == 'public' else deployed_lane
    # The retired global switch must not send a known private entry to public.
    # Keep reading its stored value without rewriting owner data on GET.
    if policy == 'public':
        return 'public'
    if source == value['public_origin']:
        return 'public'
    if source == value['private_origin']:
        return 'private'
    raise HTTPException(409,'当前入口未匹配已应用设置；请从配置的主站进入，不会自动回退公网')


def summary(db,actor):
    value = read(db,actor)
    from app.services.entry_registry import records
    from app.services import integrations
    from app.services.oidc import resolve_issuer
    # Stable issuer is deployment-owned and deliberately not editable here.
    from urllib.parse import urlsplit
    try:
        issuer = resolve_issuer(urlsplit(value['public_origin']).netloc)
    except HTTPException:
        issuer = None  # entry setup must remain usable before OIDC deployment
    websites = []
    for item in integrations.state(db)['modules'].values():
        pair = records().get(item['id'],{})
        websites.append(dict(id=item['id'],name=item['name'],mode=item['mode'],
                             public_address=pair.get('public') if item['mode']=='isolated_proxy' else item['browser_url'],
                             private_address=pair.get('private') if item['mode']=='isolated_proxy' else item.get('private_address') or pair.get('private'),
                             entry_policy=item.get('entry_policy','follow'),template_id=item.get('template_id'),
                             access_adapter=item.get('access_adapter','auto')))
    return dict(settings=value,issuer=issuer,deployed=records()['stella'],websites=websites)


def check(db,incoming,actor):
    current_value = read(db,actor)
    if incoming.revision != current_value['revision']:
        raise HTTPException(409,'设置已在其他窗口更新，请回读后重新检查')
    from app.services.entry_registry import records
    from app.services.request_security import trusted_origins
    deployed = records()
    pair = deployed['stella']
    checks = []
    for name,field in [('公网主站','public'),('内网主站','private')]:
        value = getattr(incoming,field+'_origin')
        ok = value is not None and value == pair.get(field) and value in trusted_origins()
        required = field == 'public' or incoming.private_origin is not None
        checks.append(dict(name=name,status='configured' if ok else 'pending' if required else 'unused',
                           reason='已部署精确入口与主站权限一致；未检测网络' if ok else '待部署：需要对应的主站入口、HTTPS 与精确来源许可' if required else '未配置内网主站地址'))
    if incoming.private_origin is not None and incoming.public_origin == incoming.private_origin:
        checks.append(dict(name='入口区分',status='pending',reason='公网与内网主站不能相同'))
    data = incoming.model_dump(exclude={'checked_digest'})
    # Binding includes exact deployment capabilities. A deployment change between
    # checking and applying cannot reuse an old confirmation.
    digest = hashlib.sha256(json.dumps([data,deployed,sorted(trusted_origins())],sort_keys=True).encode()).hexdigest()
    return dict(can_apply=not any(c['status']=='pending' for c in checks),digest=digest,checks=checks,
                network=dict(dns='unknown',tls='unknown',browser='unknown'),
                behavior='已配置内网地址的网站默认跟随当前 Stella 入口；普通网站无内网地址时使用原地址，已打开页面不变')


def apply(db,incoming,actor):
    try:
        # Serialize absent-row creation as well as updates; no migration/table.
        if db.get_bind().dialect.name == 'postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(1836289018)'))
        row = db.execute(select(AppConfig).where(AppConfig.key==KEY).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        result = check(db,incoming,actor)
        if not result['can_apply']:
            raise HTTPException(422,'入口尚未部署；请完成检查中列出的部署能力')
        if result['digest'] != incoming.checked_digest:
            raise HTTPException(409,'检查与应用内容不一致，请重新检查')
        value = incoming.model_dump(exclude={'checked_digest'})
        value['revision'] += 1
        stored = json.dumps(dict(owner_id=str(actor),settings=value),ensure_ascii=False)
        if row is None:
            db.add(AppConfig(key=KEY,value=stored))
        else:
            row.value = stored
        db.flush()
        from app.services.entry_monitor_groups import reconcile
        reconcile(db)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return summary(db,actor)
