"""Compile exact, operator-reviewed private OAuth launch response adapters.

This is a response URL adapter, not an OIDC issuer/discovery rewrite. Generated
locations are included inside the private service vhost only. No wildcard body
replacement, cookie/domain changes or credential forwarding are introduced.
"""
import ipaddress
import re
from urllib.parse import urlsplit


def origin(value):
    if not re.fullmatch(r'https://[a-z0-9.-]+(?::[0-9]+)?', value):
        raise ValueError('Exact HTTPS origin required')
    u = urlsplit(value)
    if not u.hostname or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', s) for s in u.hostname.split('.')):
        raise ValueError('Invalid origin')
    if u.port is not None and not 0 < u.port < 65536:
        raise ValueError('Invalid port')
    return value


def render(rule):
    if set(rule) != {'service_id','path','upstream','public_authorization','private_authorization','response_key'}:
        raise ValueError('Explicit rule fields required')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', rule['service_id']):
        raise ValueError('Invalid service ID')
    if not re.fullmatch(r'/[a-zA-Z0-9_/-]+', rule['path']) or '..' in rule['path']:
        raise ValueError('Exact source endpoint required')
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,63}',rule['response_key']):
        raise ValueError('Invalid response key')
    upstream=urlsplit(rule['upstream'])
    if upstream.scheme != 'http' or upstream.hostname != '127.0.0.1' or not upstream.port or upstream.path or upstream.query or upstream.fragment or upstream.username:
        raise ValueError('Pinned local upstream only')
    endpoints=[]
    for field in ['public_authorization','private_authorization']:
        u=urlsplit(rule[field]);origin(u.scheme+'://'+u.netloc)
        if u.query or u.fragment or not re.fullmatch(r'/[a-zA-Z0-9_/-]+',u.path) or '..' in u.path:
            raise ValueError('Exact authorization endpoint required')
        endpoints.append(rule[field])
    if endpoints[0]==endpoints[1]:raise ValueError('Distinct endpoints required')
    key=rule['response_key']
    lines=[f'# private login adapter: {rule["service_id"]}',f'location = {rule["path"]} {{',
        f'    proxy_pass {rule["upstream"]};','    proxy_http_version 1.1;',
        '    proxy_set_header Host $host;','    proxy_set_header X-Forwarded-Host $host;',
        '    proxy_set_header X-Forwarded-Proto https;','    proxy_set_header X-Forwarded-For $remote_addr;',
        '    proxy_set_header Accept-Encoding "";','    proxy_buffering on;',
        '    proxy_connect_timeout 5s;','    proxy_read_timeout 30s;',
        '    proxy_hide_header ETag;','    proxy_hide_header Last-Modified;',
        '    proxy_hide_header Cache-Control;','    add_header Cache-Control "no-store" always;',
        '    sub_filter_types application/json;','    sub_filter_once off;']
    # Controlled providers serialize a URL field in either compact or spaced JSON.
    # Only this field's exact authorization URL prefix changes; query bytes remain.
    for gap in ['', ' ']:
        src=f'"{key}":{gap}"{endpoints[0]}?'
        dst=f'"{key}":{gap}"{endpoints[1]}?'
        lines.append(f"    sub_filter '{src}' '{dst}';")
    lines += ['}', '']
    return '\n'.join(lines)
