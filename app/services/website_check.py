"""Anonymous, bounded draft GET; never receives a database or owner credentials."""
import asyncio
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from app.services import integrations_proxy as proxy
from app.services.website_connection import ConnectionInput

MAX_BODY = 512 * 1024

# Process-wide capacity, also safe across multiple event loops. Timed-out DNS
# work retains its slot until the OS resolver actually finishes. No unbounded queue.
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
DNS_POOL = ThreadPoolExecutor(max_workers=4,thread_name_prefix='website-dns')
DNS_SLOTS = BoundedSemaphore(4)
PROBE_SLOTS = BoundedSemaphore(4)

async def bounded_dns(function, value):
    if not DNS_SLOTS.acquire(blocking=False): raise ProbeFailure('busy','域名检测繁忙，请稍后重试')
    try: future = DNS_POOL.submit(function,value)
    except BaseException:
        DNS_SLOTS.release(); raise
    future.add_done_callback(lambda _: DNS_SLOTS.release())
    return await asyncio.wait_for(asyncio.wrap_future(future),3)

async def resolve_probe(target):
    try: return await bounded_dns(proxy.resolve,target)
    except TimeoutError as exc: raise ProbeFailure('timeout','域名解析超过三秒预算') from exc

def safe_address(value):
    import ipaddress
    value = proxy.allowed_address(value)
    ip = ipaddress.ip_address(value)
    private = any(ip in net for net in (ipaddress.ip_network('10.0.0.0/8'),ipaddress.ip_network('172.16.0.0/12'),ipaddress.ip_network('192.168.0.0/16'),ipaddress.ip_network('fc00::/7')) if ip.version == net.version)
    if not (ip.is_global or ip.is_loopback or private): raise ValueError('禁止特殊用途/保留网络')
    return value

class CheckInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(min_length=1, max_length=2048)
    open_behavior: Literal['embedded', 'external'] = 'embedded'
    custom_enabled: bool = False
    connection: ConnectionInput | None = None
    module_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')

class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ''
        self.meta_csp = False

    def handle_starttag(self, tag, attrs):
        if tag == 'title': self.in_title = True
        if tag == 'meta' and (dict(attrs).get('http-equiv') or '').strip().lower() == 'content-security-policy': self.meta_csp = True

    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False

    def handle_data(self, data):
        if self.in_title: self.title += data

def origin(url):
    p = urlsplit(url)
    return p.scheme.lower(), (p.hostname or '').lower(), p.port or (443 if p.scheme == 'https' else 80)

def source_matches(source, parent, document):
    if source == "'self'": return origin(parent) == origin(document)
    if source == "'none'": return False
    if source == '*': return True
    if source in {'http:', 'https:'}:
        return urlsplit(parent).scheme == source[:-1] or (source == 'http:' and urlsplit(parent).scheme == 'https')
    # Unknown syntax is not treated as a successful match. Path restrictions are
    # ignored by frame-ancestors in browsers; other unsupported forms stay unknown.
    import re
    match = re.fullmatch(r'(?:(https?)://)?(\*\.)?([a-zA-Z0-9.-]+)(?::(\*|[0-9]+))?(?:/[^\s]*)?', source)
    if not match: return None
    scheme, wildcard, host, port = match.groups()
    if port and port != '*' and (len(port)>5 or not 1<=int(port)<=65535): return None
    scheme = scheme or urlsplit(document).scheme
    ps, ph, pp = origin(parent)
    scheme_ok = ps == scheme or (scheme == 'http' and ps == 'https')
    host_ok = ph.endswith('.' + host.lower()) if wildcard else ph == host.lower()
    port_ok = port == '*' or pp == (int(port) if port else (443 if ps == 'https' else 80))
    # CSP3's HTTP default-port secure upgrade (frozen 2016 WD §6.6.1.6).
    # https:80 is not an HTTP upgrade; non-default ports never map to 443.
    # https://www.w3.org/TR/2016/WD-CSP3-20160913/#match-url-to-source-expression
    if port and port != '*' and int(port) == 80 and scheme == 'http' and ps == 'https' and pp == 443:
        port_ok = True
    return scheme_ok and host_ok and port_ok

def evaluate_embedding(headers, document_url, parent_origin):
    policies = [part for value in headers.get_list('content-security-policy') for part in value.split(',')]
    results = []
    for policy in policies:
        for directive in policy.split(';'):
            words = directive.strip().split()
            if words and words[0].lower() == 'frame-ancestors':
                matches = [source_matches(v, parent_origin, document_url) for v in words[1:]]
                results.append(True if True in matches else (None if None in matches else False))
                break  # Only first duplicate directive in this policy is effective.
    if results:
        status = 'blocked' if False in results else ('unknown' if None in results else 'allowed')
        code = 'csp_frame_ancestors'
    else:
        xfo = [part.strip().upper() for value in headers.get_list('x-frame-options') for part in value.split(',')]
        if not xfo: status, code = 'allowed', 'no_observed_restriction'
        elif set(xfo) == {'DENY'}: status, code = 'blocked', 'xfo_deny'
        elif set(xfo) == {'SAMEORIGIN'}:
            status, code = ('allowed' if origin(parent_origin) == origin(document_url) else 'blocked'), 'xfo_sameorigin'
        else: status, code = 'unknown', 'xfo_unknown'
    reasons = {'blocked':'目标响应策略禁止在 Stella 内嵌入', 'allowed':'未发现响应策略阻断，浏览器内容及登录仍需验证', 'unknown':'响应策略无法可靠判断，浏览器状态尚未确认'}
    return dict(status=status, reason_code=code, reason=reasons[status])

def frame_help(url):
    known = urlsplit(url).hostname == 'quota.xiya.live'
    return dict(title='在额度服务配置允许嵌入' if known else '在目标网站配置允许嵌入',
                location='/etc/nginx/conf.d/quota.conf' if known else None,
                instructions=(["在服务本机 /etc/nginx/conf.d/quota.conf 及部署源 quota-monitor/deploy/quota.conf 取消 DENY，把 frame-ancestors 精确允许 https://stella.xiya.live，保留其他 CSP、LAN 监听/ACL、凭据与额度数据。", '完成后重新检测；Stella 不会修改目标服务。'] if known else
                              ['由原站部署人员检查反向代理或应用的 CSP frame-ancestors 与 X-Frame-Options，精确允许 Stella origin，保留其他安全策略。', '无权修改原站时请选择新窗口打开；不要全局清除 CSP。']), external_url=None)

class ProbeFailure(Exception):
    def __init__(self, code, reason, blocked=False):
        self.code, self.reason, self.blocked = code, reason, blocked

def normalize_url(value):
    from urllib.parse import urlunsplit
    import ipaddress
    import re
    if any(ord(c) < 33 or ord(c) == 127 for c in value) or '\\' in value: raise ValueError('不安全地址')
    if '://' not in value:
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value) and not re.match(r'^[^/:]+:[0-9]+(?:[/?#]|$)', value): raise ValueError('不支持的协议')
        value = 'https://' + value
    p = urlsplit(value)
    if p.scheme not in {'http','https'} or not p.hostname or p.username is not None or p.password is not None: raise ValueError('不合法的网站 URL')
    if p.port == 0: raise ValueError('不安全端口')
    host = p.hostname.lower().rstrip('.').encode('idna').decode('ascii')
    if host in {'metadata.google.internal','metadata','instance-data'}: raise ValueError('禁止元数据主机')
    try: ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')): raise ValueError('非法主机名')
    else: safe_address(host)
    authority = '[' + host + ']' if ':' in host else host
    if p.port is not None: authority += ':' + str(p.port)
    path = p.path or '/'
    proxy.request_path(path + ('?' + p.query if p.query else ''))
    return urlunsplit((p.scheme.lower(), authority, path, p.query, p.fragment))

def failure_result(url, incoming, code, reason, blocked=False):
    return dict(normalized_url=url, name_suggestion=urlsplit(url).hostname or '',
                access=dict(status='blocked' if blocked else 'unknown', http_status=None),
                embedding=dict(status='blocked' if blocked else 'unknown', reason_code=code, reason=reason),
                injection=dict(status='unsupported' if blocked else 'unknown', reason=reason),
                help=frame_help(url) if urlsplit(url).hostname == 'quota.xiya.live' else None, can_save=not blocked and incoming.open_behavior == 'external' and not incoming.custom_enabled,
                recommended_behavior='external', issues=[reason])

async def _check_draft(incoming: CheckInput, *, parent_origin: str, evidence=None, credential_headers=None, approved_target=None) -> dict:
    import httpx
    import socket
    from urllib.parse import urljoin
    from fastapi import HTTPException
    try: normalized = normalize_url(incoming.address)
    except (ValueError, HTTPException):
        return failure_result('', incoming, 'unsafe_address', '地址不合法或属于禁止的元数据/保留目的地', True)
    async def fetch():
        url = normalized
        for redirects in range(4):
            try: url = normalize_url(url)
            except (ValueError, HTTPException) as exc:
                raise ProbeFailure('unsafe_address', '重定向目的地不安全，已阻断', True) from exc
            p = urlsplit(url)
            root = p.scheme + '://' + p.netloc + '/'
            try:
                addresses = [safe_address(a) for a in await bounded_dns(proxy._preview_addresses,root)]
            except socket.gaierror as exc: raise ProbeFailure('dns_failed', '域名解析失败，浏览器状态未知') from exc
            except ValueError as exc: raise ProbeFailure('unsafe_address', '域名解析含禁止目的地', True) from exc
            if approved_target and (origin(root)!=origin(approved_target['upstream_url']) or set(addresses)!=set(approved_target['allowed_ips'])):
                raise ProbeFailure('dns_pin_failed','解析地址已变更，未发送保存的凭据；请核对目标后重新配置',True)
            target = dict(upstream_url=root, allowed_ips=addresses, headers=credential_headers or {}, controlled=False)
            client = response = None
            try:
                path = p.path or '/'
                if p.query: path += '?' + p.query
                client, response = await proxy.open_response(target, path, headers={'Accept-Encoding':'identity'},resolve_async=resolve_probe)
                if response.status_code in {301,302,303,307,308}:
                    if credential_headers: raise ProbeFailure('credential_redirect', '凭据检测不跟随跳转，请在浏览器确认登录')
                    location = response.headers.get('location')
                    if not location: raise ProbeFailure('redirect_unknown', '跳转响应缺少目标，浏览器状态未知')
                    if redirects == 3: raise ProbeFailure('redirect_limit', '超过三次跳转，检测已停止')
                    url = urljoin(url, location)
                    continue
                if response.headers.get('content-encoding','identity').lower() not in {'','identity'}:
                    raise ProbeFailure('encoding_unknown', '压缩响应无法在检测体积预算内可靠判断')
                body = bytearray()
                async for chunk in response.aiter_raw(chunk_size=16384):
                    if len(body) + len(chunk) > MAX_BODY: raise ProbeFailure('body_limit', '响应体超过 512 KiB 检测限制')
                    body.extend(chunk)
                charset = (response.charset_encoding or 'utf-8').lower()
                text_valid = charset in {'utf-8','utf8','us-ascii'}
                try: decoded = body.decode('utf-8')
                except UnicodeDecodeError:
                    text_valid = False; decoded = body.decode('utf-8',errors='replace')
                document = Document(); document.feed(decoded)
                embedding = evaluate_embedding(response.headers, url, parent_origin)
                http_status = response.status_code
                access = 'login_required' if http_status == 401 else ('blocked' if http_status == 403 else ('reachable' if 200 <= http_status < 300 else 'unknown'))
                import re
                if redirects and re.search(r'/(?:login|signin|oauth|authorize)(?:/|$)', p.path, re.I): access = 'login_required'
                html = response.headers.get('content-type','').split(';')[0].lower() == 'text/html'
                supported = html and text_valid and http_status == 200 and access == 'reachable' and origin(url) == origin(normalized) and not (response.headers.get_list('content-security-policy') or response.headers.get_list('x-frame-options') or document.meta_csp)
                if urlsplit(parent_origin).scheme == 'https' and p.scheme == 'http' and embedding['status'] == 'allowed':
                    if (not incoming.connection or (incoming.connection.transport != 'direct' and incoming.connection.injection_delivery != 'loader')) and (incoming.custom_enabled or (incoming.connection and incoming.connection.transport == 'proxy')) and incoming.open_behavior == 'embedded' and supported:
                        # The save constructs an HTTPS isolated origin with a freshly
                        # DNS-pinned, uncontrolled, header-free target. Browser delivery
                        # is not a direct HTTP frame; upstream policies are never stripped.
                        embedding = dict(status='allowed',reason_code='isolated_https_proxy',reason='将通过 HTTPS 隔离代理交付；浏览器内容及登录仍需验证')
                    else:
                        embedding = dict(status='blocked',reason_code='mixed_content',reason='HTTPS Stella 不能直接嵌入 HTTP 混合内容')
                if not html and embedding['status'] == 'allowed': embedding = dict(status='unknown', reason_code='not_html', reason='非 HTML 响应，浏览器呈现尚未确认')
                can_save = incoming.open_behavior == 'external' or (embedding['status'] == 'allowed' and access == 'reachable')
                loader = bool(incoming.connection and incoming.connection.injection_delivery == 'loader' and incoming.connection.transport != 'proxy')
                if incoming.custom_enabled and ((not supported and not loader) or incoming.open_behavior == 'external'): can_save = False
                loader_seen = bool(incoming.module_id and '/website-assets/'+incoming.module_id+'.js' in decoded)
                issues = [] if access == 'reachable' else ['服务器返回认证/拒绝或错误响应；不能确认原站登录与浏览器内容']
                if embedding['status'] != 'allowed': issues.append(embedding['reason'])
                if evidence is not None: evidence.update(allowed_ips=addresses,upstream_url=root)
                return dict(normalized_url=normalized, name_suggestion=' '.join(document.title.split())[:100] or urlsplit(normalized).hostname,
                            access=dict(status=access, http_status=http_status), embedding=embedding,
                            injection=dict(status=('supported' if loader_seen else 'loader_required') if loader else ('supported' if supported else 'unsupported'), reason=('已观察到模块加载器，浏览器状态仍未验证' if loader_seen else '需在原站安装此模块的经典脚本加载器；可先保存代码') if loader else '匿名 HTML 未发现 CSP/XFO/meta 限制；仍需隔离页面浏览器验证' if supported else '原站策略、认证、响应类型或跨站跳转不支持安全注入；不自动清除 CSP'),
                            help=frame_help(normalized) if embedding['status'] != 'allowed' else None,
                            can_save=can_save, recommended_behavior='external' if embedding['status'] != 'allowed' else incoming.open_behavior, issues=issues)
            finally:
                if response is not None: await response.aclose()
                if client is not None: await client.aclose()
    try: return await asyncio.wait_for(fetch(), 8)
    except ProbeFailure as exc: return failure_result(normalized, incoming, exc.code, exc.reason, exc.blocked)
    except TimeoutError: return failure_result(normalized, incoming, 'timeout', '检测超过八秒预算，浏览器状态未知')
    except HTTPException: return failure_result(normalized, incoming, 'dns_pin_failed', 'DNS 已变更或解析不属于固定地址，已阻断', True)
    except httpx.HTTPError as exc:
        certificate = 'CERTIFICATE_VERIFY_FAILED' in str(exc)
        return failure_result(normalized, incoming, 'certificate_failed' if certificate else 'connection_failed', '证书验证失败；不会关闭 TLS 验证' if certificate else '上游连接失败，浏览器状态未知')
    except OSError: return failure_result(normalized, incoming, 'connection_failed', '上游连接失败，浏览器状态未知')

async def check_draft(incoming: CheckInput, *, parent_origin: str, evidence=None, credential_headers=None, approved_target=None) -> dict:
    from fastapi import HTTPException
    try: normalized = normalize_url(incoming.address)
    except (ValueError,HTTPException): return failure_result('',incoming,'unsafe_address','地址不合法或属于禁止目的地',True)
    if not PROBE_SLOTS.acquire(blocking=False): return failure_result(normalized,incoming,'busy','网站检测繁忙，请稍后重试')
    try: return await _check_draft(incoming,parent_origin=parent_origin,evidence=evidence,credential_headers=credential_headers,approved_target=approved_target)
    finally: PROBE_SLOTS.release()


async def check_saved_draft(db, incoming, *, parent_origin):
    import copy
    from fastapi import HTTPException
    from app.services import integrations as store
    from app.services.website_connection import effective_connection, credential_headers, preserve_legacy_target
    config=store.state(db)
    before=copy.deepcopy(config['modules'].get(incoming.module_id)) if incoming.module_id else None
    if incoming.module_id and before is None: raise HTTPException(404,'模块不存在')
    target=copy.deepcopy(config['targets'].get(before.get('target_id'))) if before else None
    connection=incoming.connection or effective_connection(before,target)
    if connection.auth_mode == 'header' and incoming.open_behavior == 'external':
        raise HTTPException(422,'凭据头认证需要隔离代理嵌入；外部打开请使用原站登录')
    preserve=preserve_legacy_target(before,target,incoming.address,connection)
    headers=copy.deepcopy(target['headers']) if preserve else credential_headers(connection,incoming.address,before,target)
    pin=target if target and (preserve or (headers and connection.token is None and not connection.clear_token)) else None
    address=target['upstream_url'].rstrip('/')+before.get('initial_path','/') if preserve else incoming.address
    db.rollback()
    result=await check_draft(incoming.model_copy(update={'connection':connection,'address':address}),parent_origin=parent_origin,credential_headers=headers,approved_target=pin)
    if preserve: result['normalized_url']=normalize_url(incoming.address)
    if before:
        after=store.state(db)
        if after['modules'].get(incoming.module_id)!=before or (target and after['targets'].get(target['id'])!=target):
            db.rollback()
            raise HTTPException(409,'检测期间网站或凭据已变更，请重新读取')
    db.rollback()
    return result
