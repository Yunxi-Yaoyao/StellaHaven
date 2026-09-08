"""External connections only. Never installs, starts, or changes upstream services."""
import ipaddress
import json
import socket
from urllib.parse import urlsplit
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.repositories import config as config_repo


def validate_url(value: str) -> str:
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment or p.query:
        raise ValueError('使用完整 http/https URL，不允许账号、查询参数或片段')
    if any(ord(c) < 33 for c in value) or '\\' in value or any(x in p.path.split('/') for x in ('.', '..')) or '%' in p.path:
        raise ValueError('URL 包含不安全字符')
    host = p.hostname.lower().rstrip('.')
    if host in ('metadata.google.internal', 'metadata', 'instance-data'):
        raise ValueError('不允许元数据服务')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_link_local or address.is_unspecified or address.is_multicast):
        raise ValueError('不允许元数据/链路本地地址')
    if (host == 'localhost' or (address and address.is_loopback)) and (p.port or (443 if p.scheme == 'https' else 80)) != 5244:
        raise ValueError('回环地址仅允许已批准的 OpenList 5244 端口；其他服务请使用明确的 LAN 地址')
    _ = p.port  # validate port
    return value.rstrip('/')


class Connection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    browser_url: str
    upstream_url: str = ''
    alternate_browser_url: str = ''
    use_proxy: bool = False
    auth_mode: Literal['manual', 'token', 'oidc'] = 'manual'
    token: str | None = Field(default=None, max_length=8192, repr=False)
    clear_token: bool = False

    @field_validator('browser_url', 'upstream_url', 'alternate_browser_url')
    @classmethod
    def valid_url(cls, value, info):
        if not value and info.field_name != 'browser_url':
            return value
        return validate_url(value)

    @field_validator('token')
    @classmethod
    def valid_token(cls, value):
        if value and any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError('Token 必须是不含换行的 ASCII 字符串')
        return value


class DriveConnection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    service_url: str
    auth_mode: Literal['manual', 'token'] = 'manual'
    token: str | None = Field(default=None, max_length=8192, repr=False)
    clear_token: bool = False

    @field_validator('service_url')
    @classmethod
    def valid_service(cls, value):
        return validate_url(value)

    def as_connection(self):
        # Browser iframe path is application-owned; callers only configure the backend target.
        return Connection(browser_url=self.service_url, upstream_url=self.service_url,
                          use_proxy=True, auth_mode=self.auth_mode, token=self.token,
                          clear_token=self.clear_token)


def masked_drive(cfg):
    return {'service_url': cfg.upstream_url or cfg.browser_url,
            'auth_mode': cfg.auth_mode, 'has_token': bool(cfg.token)}


DEFAULTS = {
    'drive': dict(browser_url='https://stella.xiya.live/drive/openlist', upstream_url='http://127.0.0.1:5244/drive/openlist', use_proxy=True, auth_mode='manual'),
    'gallery': dict(browser_url='https://immich.xiya.live', alternate_browser_url='https://immich.yunxi.life', auth_mode='oidc'),
}


def load(db, kind):
    raw = config_repo.get(db, f'external_{kind}_connection')
    return Connection(**(json.loads(raw) if raw else DEFAULTS[kind]))


def masked(cfg):
    return {**cfg.model_dump(exclude={'token', 'clear_token'}), 'has_token': bool(cfg.token)}


def merge(db, kind, incoming):
    old = load(db, kind)
    cfg = incoming.model_copy(deep=True)
    cfg.token = '' if incoming.clear_token else (incoming.token if incoming.token is not None else old.token)
    cfg.clear_token = False
    if kind == 'gallery' and cfg.use_proxy:
        raise ValueError('Immich 使用浏览器直连，不支持子路径反代')
    if kind == 'gallery' and cfg.auth_mode == 'token':
        raise ValueError('Immich 网页使用手动登录或已有 OIDC，不使用 API key 登录')
    if kind == 'drive' and cfg.auth_mode == 'oidc':
        raise ValueError('OpenList 请选择手动登录或 Token')
    if cfg.auth_mode == 'token' and not cfg.token:
        raise ValueError('Token 登录必须填写 Token，或改为在原服务登录')
    return cfg


def save(db, kind, incoming):
    cfg = merge(db, kind, incoming)
    config_repo.put(db, f'external_{kind}_connection', cfg.model_dump_json())
    return masked(cfg)


def endpoint(cfg, path):
    return (cfg.upstream_url or cfg.browser_url).rstrip('/') + '/' + path.lstrip('/')


def check_resolved(url):
    """Reject metadata destinations also when expressed through DNS aliases."""
    p = urlsplit(validate_url(url))
    for entry in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM):
        addr = ipaddress.ip_address(entry[4][0])
        if addr.is_link_local or addr.is_unspecified or addr.is_multicast or (addr.is_loopback and (p.port or 80) != 5244):
            raise ValueError('目标解析到未批准的本机或元数据地址')


async def probe(kind, cfg):
    url = endpoint(cfg, 'api/public/settings' if kind == 'drive' else 'api/server/ping')
    warning = '服务器连通不代表浏览器可嵌入；请检查 HTTPS、CSP frame-ancestors、X-Frame-Options 和第三方 Cookie。'
    try:
        import asyncio
        await asyncio.wait_for(asyncio.to_thread(check_resolved, url), 5)
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4), follow_redirects=False, trust_env=False) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            ok = data.get('code') == 200 if kind == 'drive' else data.get('res') == 'pong'
            if not ok:
                return {'ok': False, 'message': '服务返回非预期响应（检查基础路径和服务类型）', 'warning': warning}
            if kind == 'drive' and cfg.auth_mode == 'token':
                if not cfg.token:
                    return {'ok': False, 'message': 'Token 模式尚未配置 Token', 'warning': warning}
                auth = await client.get(endpoint(cfg, 'api/me'), headers={'Authorization': cfg.token})
                if auth.status_code != 200 or auth.json().get('code') != 200:
                    return {'ok': False, 'message': '服务可达，但 Token 验证失败', 'warning': warning}
            return {'ok': True, 'message': '连接成功' + ('，Token 有效' if kind == 'drive' and cfg.auth_mode == 'token' else ''), 'warning': ''}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        message = '认证被拒绝，检查登录方式/凭据' if code in (401, 403) else '服务路径不存在，检查基础路径' if code == 404 else f'上游返回 HTTP {code}'
        return {'ok': False, 'message': message, 'warning': warning}
    except httpx.TimeoutException:
        return {'ok': False, 'message': '连接超时，检查地址、端口与网络连通性', 'warning': warning}
    except (httpx.HTTPError, ValueError, OSError, TimeoutError):
        return {'ok': False, 'message': '无法连接或响应格式错误，检查协议、证书及服务类型', 'warning': warning}
