"""Owner-scoped inert snapshots in integrations_v1, never runtime bindings.

Only explicit portable fields cross this boundary. No targets, grants, headers,
addresses or saved credential state can be exported. Read-POST exemptions are
not portable authority: new copies require management authorization for writes.
"""
import re
import hashlib
import json
import time
from typing import Literal
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services import integrations as store
from app.services.website_settings import CustomInput
from app.services.website_connection import ConnectionInput, RequestPolicy
from app.services.website_templates import catalog

MAX_TEMPLATES = 128


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    draft: dict
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('请输入简短的模板名称')
        return value


class PortableDraft(BaseModel):
    model_config = ConfigDict(extra='ignore')
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str = 'globe'
    open_behavior: Literal['embedded','external'] = 'embedded'
    keep_alive: bool = False
    background: Literal['solid','home'] = 'solid'
    custom: CustomInput = Field(default_factory=CustomInput)

    @field_validator('name', mode='before')
    @classmethod
    def optional_name(cls, value):
        return None if isinstance(value,str) and not value.strip() else value

    @field_validator('icon')
    @classmethod
    def valid_icon(cls, value):
        if value not in store.ICONS: raise ValueError('不支持的图标')
        return value


def portable_draft(raw):
    # Build rather than subtract secrets; additions to website DTOs stay private.
    result = PortableDraft.model_validate(raw).model_dump(exclude_none=True)
    connection = raw.get('connection') or {}
    safe_connection = {k: connection[k] for k in ('transport','auth_mode','header_name','injection_delivery') if k in connection}
    result['connection'] = ConnectionInput(**safe_connection).model_dump(exclude={'token','clear_token'})
    policy = RequestPolicy.model_validate({k:v for k,v in (raw.get('request_policy') or {}).items() if k in RequestPolicy.model_fields})
    result['request_policy'] = dict(management_prefixes=policy.management_prefixes, read_post_paths=[], protect_other_writes=True)
    # Known supplied secrets must not survive embedded in editable code either.
    token = connection.get('token')
    if token and any(token in result['custom'][key] for key in ('css','js')):
        raise HTTPException(422, '代码包含凭据，请移除后再存为模板')
    return result


def public_record(record):
    return dict(id=record['id'], name=record['name'], provenance='user',
                description='你的独立配置与代码副本；不含网站地址和凭据，使用前请填写新地址。',
                draft=portable_draft(record['draft']))


def list_templates(db, owner_id):
    records = store.state(db).get('website_templates', {})
    return catalog() + [public_record(record) for record in records.values() if record.get('owner_id') == str(owner_id)]


def save_template(db, incoming, owner_id):
    draft = portable_draft(incoming.draft)
    digest = hashlib.sha256(json.dumps(dict(name=incoming.name, draft=draft), sort_keys=True).encode()).hexdigest()
    slot = str(owner_id) + ':' + (incoming.idempotency_key or '')
    with store.edit(db) as state:
        records = state.setdefault('website_templates', {})
        # Same bounded, one-day operation receipts as website saves. Check only
        # after edit has locked and refreshed the registry, including at capacity.
        keys = {k:v for k,v in state.get('website_template_save_keys', {}).items() if v['expires'] > time.time()}
        previous = keys.get(slot) if incoming.idempotency_key else None
        if previous:
            if previous['digest'] != digest: raise HTTPException(409, '幂等键已用于不同的模板草稿')
            record = records.get(previous['id'])
            if not record or record.get('owner_id') != str(owner_id):
                raise HTTPException(409, '已保存的模板随后已删除，请重新读取')
            return public_record(record)
        if len(records) >= MAX_TEMPLATES: raise HTTPException(422, '模板数量已达 128 个，请先删除不用的模板')
        tid = 'user_' + uuid4().hex
        record = dict(id=tid, name=incoming.name, owner_id=str(owner_id), draft=draft)
        records[tid] = record
        if incoming.idempotency_key:
            if len(keys) >= 128: keys.pop(min(keys, key=lambda k:keys[k]['expires']))
            keys[slot] = dict(id=tid, digest=digest, expires=time.time()+86400)
            state['website_template_save_keys'] = keys
    return public_record(record)


def delete_template(db, tid, owner_id):
    if not re.fullmatch(r'user_[0-9a-f]{32}', tid): raise HTTPException(404, '模板不存在或不可删除')
    with store.edit(db) as state:
        records = state.get('website_templates', {})
        if tid not in records or records[tid].get('owner_id') != str(owner_id):
            raise HTTPException(404, '模板不存在或不可删除')
        del records[tid]
