"""Generic transport/auth DTOs; secrets live only in backend target records."""
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from fastapi import HTTPException


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transport: Literal['auto','proxy','direct'] = 'auto'
    auth_mode: Literal['original','header','oidc'] = 'original'
    header_name: str = 'Authorization'
    token: str | None = Field(default=None, max_length=8192, repr=False)
    clear_token: bool = False
    injection_delivery: Literal['proxy','loader'] = 'proxy'

    @field_validator('header_name')
    @classmethod
    def header(cls, value):
        names = {'authorization':'Authorization', 'x-api-key':'X-API-Key', 'x-auth-token':'X-Auth-Token'}
        if value.lower() not in names: raise ValueError('不支持的凭据头')
        return names[value.lower()]

    @field_validator('token')
    @classmethod
    def secret(cls, value):
        if value is not None and (not value or any(ord(c)<32 or ord(c)>126 for c in value)):
            raise ValueError('凭据必须是不含换行的 ASCII')
        return value

    @model_validator(mode='after')
    def compatible(self):
        if self.auth_mode == 'header' and (self.transport == 'direct' or self.injection_delivery == 'loader'):
            raise ValueError('凭据头只能由后端代理发送')
        if self.transport == 'proxy' and self.injection_delivery == 'loader':
            raise ValueError('代理使用 proxy 注入交付')
        if self.transport == 'direct' and self.injection_delivery != 'loader':
            raise ValueError('直连注入使用 loader')
        return self


class RequestPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    management_prefixes: list[str] = Field(default_factory=list, max_length=64)
    read_post_paths: list[str] = Field(default_factory=list, max_length=64)
    protect_other_writes: bool = False

    @field_validator('management_prefixes','read_post_paths')
    @classmethod
    def paths(cls, values):
        import re
        for value in values:
            if len(value)>256 or not re.fullmatch(r'/[A-Za-z0-9_./~-]*', value) or '//' in value or any(p in {'.','..'} for p in value.split('/')):
                raise ValueError('权限路径须为不含编码/查询的绝对路径')
        return list(dict.fromkeys(v.rstrip('/') or '/' for v in values))


def effective_connection(before=None, target=None):
    if before and before.get('connection'):
        return ConnectionInput(**{k:v for k,v in before['connection'].items() if k in ConnectionInput.model_fields})
    connection = ConnectionInput(transport='proxy' if before and before.get('mode')=='isolated_proxy' else 'auto')
    if target and target.get('headers'):
        for name in target['headers']:
            if name.lower() in {'authorization','x-api-key','x-auth-token'}:
                connection.auth_mode='header'; connection.header_name=ConnectionInput.header(name); break
    return connection


def preserve_legacy_target(before, target, address, connection):
    from app.services.website_check import normalize_url
    if not before or not target or before.get('connection') or before.get('mode')!='isolated_proxy': return False
    if normalize_url(before['browser_url']) != normalize_url(address) or connection.token is not None or connection.clear_token: return False
    return connection.model_dump(exclude={'token','clear_token'}) == effective_connection(before,target).model_dump(exclude={'token','clear_token'})


def credential_headers(connection, address, before=None, old_target=None):
    from app.services.website_check import normalize_url
    if connection.auth_mode != 'header': return {}
    token = None if connection.clear_token else connection.token
    if token is None and not connection.clear_token and before and old_target:
        if normalize_url(before['browser_url']) != normalize_url(address):
            raise HTTPException(422,'地址已改变：请明确填写凭据，不向新地址发送已保存凭据')
        token = old_target.get('headers',{}).get(connection.header_name.lower())
    if not token: raise HTTPException(422,'凭据头登录需要有效凭据；清除后请选择原站登录')
    return {connection.header_name.lower(): token}


def public_connection(connection, headers):
    return connection.model_dump(exclude={'token','clear_token'}) | {'has_token':bool(headers)}
