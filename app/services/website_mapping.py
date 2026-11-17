"""Typed website upstream mapping, separate from trusted browser Host entries."""
import ipaddress
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator


def address_kind(value):
    from app.services.website_check import normalize_url
    host = urlsplit(normalize_url(value)).hostname or ''
    try:
        ipaddress.ip_address(host)
        return 'ip'
    except ValueError:
        # Avoid ambiguous historical inet_aton spellings such as 1 / 127.1.
        if all(part.isdecimal() for part in host.split('.')):
            raise ValueError('请填写完整 IP 地址')
        return 'domain'


class WebsiteMappingInput(BaseModel):
    address_mode: Literal['ip', 'domain'] | None = None
    alternate_address: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode='after')
    def mapping_addresses(self):
        from app.services.website_check import normalize_url
        address = getattr(self, 'address', None)
        for value in (address, self.alternate_address):
            if value is not None and (self.address_mode is not None or value == self.alternate_address):
                kind = address_kind(value)
                if self.address_mode is not None and kind != self.address_mode:
                    raise ValueError('地址与所选 IP / 域名模式不符')
                normalize_url(value)
        return self


def mapping_values(incoming, before=None):
    """Omitted fields retain old values; null clears; empty URLs are invalid DTOs."""
    from fastapi import HTTPException
    from app.services.website_check import normalize_url
    before = before or {}
    mode = incoming.address_mode if 'address_mode' in incoming.model_fields_set else before.get('address_mode')
    configured = 'alternate_address' in incoming.model_fields_set or before.get('mapping_configured',False)
    alternate = incoming.alternate_address if 'alternate_address' in incoming.model_fields_set else before.get('alternate_address') if configured else None
    try:
        if mode is not None:
            if mode not in {'ip','domain'}: raise ValueError('Invalid mode')
            if any(address_kind(address) != mode for address in (incoming.address,alternate) if address is not None):
                raise ValueError('Mode mismatch')
        if alternate is not None: alternate = normalize_url(alternate)
    except ValueError:
        raise HTTPException(422,'地址与所选 IP / 域名模式不符，或地址无效') from None
    return mode, alternate, configured


def initial_path(address):
    parsed = urlsplit(address)
    return (parsed.path or '/') + ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')


class UpstreamBinding(BaseModel):
    """Internal persisted JSON DTO; never accepted by a public write route."""
    model_config = ConfigDict(extra='forbid', strict=True)
    target_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    initial_path: str = Field(min_length=1, max_length=2048)

    @model_validator(mode='after')
    def safe_path(self):
        from app.services.integrations_proxy import request_path
        request_path(self.initial_path)
        return self


def proxy_projection(module, target_origin):
    """Select by exact registered browser origin, not an arbitrary upstream URL."""
    from app.services.entry_registry import records, parent_for_module
    parent_for_module(module, target_origin)  # exact existing trust boundary
    pair = records().get(module['id'], {'public':module['origin']})
    if target_origin == pair.get('private') and module.get('alternate_address') and module.get('mapping_configured'):
        from fastapi import HTTPException
        try:
            binding = UpstreamBinding.model_validate(module.get('alternate_binding')).model_dump()
        except ValueError:
            raise HTTPException(403, '网站其他入口上游未绑定，请重新保存') from None
        return dict(module, **binding, origin=target_origin)
    return dict(module, origin=target_origin)


async def prepare_alternate(address, connection, before, old_target, *, parent_origin, custom_enabled, name):
    from app.services import integrations_proxy as proxy
    from app.services.website_check import CheckInput, check_draft, normalize_url, bounded_dns, safe_address, ProbeFailure
    from app.services.website_connection import credential_headers
    from fastapi import HTTPException
    # credential_headers may only reuse the exact independently saved URL.
    prior = dict(before, browser_url=before.get('alternate_address')) if before and before.get('mapping_configured') and before.get('alternate_address') else None
    same = bool(prior and normalize_url(prior['browser_url']) == normalize_url(address))
    if same and old_target is None:
        raise HTTPException(422, '原其他入口目标缺失，请重新读取并明确配置连接')
    if same:
        fields = set(proxy.TargetInput.model_fields)
        try:
            if not fields <= old_target.keys() or old_target.get('id') != before.get('alternate_binding',{}).get('target_id'):
                raise ValueError('Invalid saved target')
            proxy.TargetInput.model_validate({field:old_target[field] for field in fields},strict=True)
        except (ValueError,TypeError):
            raise HTTPException(422, '原其他入口目标无效，请重新读取并明确配置连接') from None
    headers = credential_headers(connection,address,prior,old_target)
    pin = old_target if same else None
    evidence = {}
    checked = await check_draft(CheckInput(address=address,connection=connection.model_copy(update={'transport':'proxy','injection_delivery':'proxy'}),custom_enabled=custom_enabled),
                                parent_origin=parent_origin,evidence=evidence,credential_headers=headers,approved_target=pin)
    if not checked['can_save']:
        raise HTTPException(422,dict(code='website_check_failed',check=checked))
    parsed = urlsplit(checked['normalized_url'])
    root = parsed.scheme+'://'+parsed.netloc+'/'
    try:
        ips = [safe_address(ip) for ip in await bounded_dns(proxy._preview_addresses,root)]
        if set(ips) != set(evidence.get('allowed_ips', [])): raise ValueError('DNS drift')
        prepared = proxy.TargetInput(name=name or checked['name_suggestion'],upstream_url=root,allowed_ips=ips,headers=headers,
                                     controlled=old_target.get('controlled',False) if same else False).model_dump()
    except (ValueError,OSError,TimeoutError,ProbeFailure):
        raise HTTPException(422,'其他入口提交前目标解析失败或已变更') from None
    reusable = bool(old_target and all(old_target.get(key)==prepared[key] for key in ('upstream_url','headers','controlled'))
                    and set(old_target.get('allowed_ips',[]))==set(prepared['allowed_ips']))
    return prepared, reusable
