"""Offline syntax only. Shared by DTOs, services, status and MTR dispatch."""
from dataclasses import dataclass
import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Target:
    value: str
    host: str
    port: int | None


def host_name(value: str) -> str:
    if "%" in value:
        raise ValueError("目标 IP 不接受接口作用域后缀")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not value or any(c in value for c in ':[]/%@\\'):
        raise ValueError('目标主机无效，请填写有效 IP 或主机名')
    try:
        ascii_host = value.encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise ValueError('目标主机无效，请填写有效 IP 或主机名') from None
    labels = ascii_host.rstrip('.').split('.')
    if (len(ascii_host) > 253 or not any(c.isalpha() for c in ascii_host)
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in labels)):
        raise ValueError('目标主机无效，请填写有效 IP 或主机名（不能是裸数字）')
    return ascii_host


def parse_target(kind: str, value: str) -> Target:
    if (not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError('目标不能含控制字符')
    value = value.strip().replace('：', ':')
    if not value or len(value) > 256 or any(c.isspace() for c in value) or '\\' in value:
        raise ValueError('目标不能为空或含空白、反斜线，且最多 256 字符')
    if kind == 'ping':
        host = host_name(value)
        return Target(host, host, None)
    if kind in ('tcp', 'udp'):
        match = re.fullmatch(r'(\[[^\[\]]+\]|[^:]+):([0-9]+)', value)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise ValueError('TCP/UDP 需要主机:1–65535端口；IPv6 使用 [地址]:端口')
        raw_host = match[1]
        if raw_host.startswith('['):
            if '%' in raw_host:
                raise ValueError('目标 IP 不接受接口作用域后缀')
            try:
                host = str(ipaddress.IPv6Address(raw_host[1:-1]))
            except ValueError:
                raise ValueError('IPv6 地址无效') from None
        else:
            host = host_name(raw_host)
        port = int(match[2])
        return Target(f'{"["+host+"]" if ":" in host else host}:{port}', host, port)
    if kind not in ('http', 'https'):
        raise ValueError('监控类型不正确')
    try:
        url = urlsplit(value)
        if (url.scheme != kind or not value.lower().startswith(kind+'://') or not url.netloc
                or url.username is not None or url.password is not None or url.netloc.endswith(':')):
            raise ValueError()
        # Brackets are supported only for IPv6, never IPvFuture-to-DNS
        # reinterpretation through urlsplit().hostname and authority rebuilding.
        if url.netloc.startswith('['):
            literal = url.netloc[1:url.netloc.index(']')]
            if '%' in literal:
                raise ValueError()
            ipaddress.IPv6Address(literal)
        host = host_name(url.hostname or '')
        port = url.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        authority = f'[{host}]' if ':' in host else host
        authority += ':'+str(port) if port is not None else ''
        normalized = url._replace(netloc=authority).geturl()
        return Target(normalized, host, port or (443 if kind == 'https' else 80))
    except ValueError:
        raise ValueError('请填写协议匹配的 HTTP(S) URL、有效主机及端口，不含账号密码') from None


def parse_stored_target(kind: str, value: str) -> Target:
    """Read/dispatch adapter for retained pre-URL HTTP(S) definitions only.

    Never use for create/update admission. The old worker prepended the monitor
    scheme to host[:port][/path]; retain that meaning without rewriting the row.
    A malformed URL is not a bare authority: do not strip/repair its scheme,
    credentials, whitespace, or network-path prefix. Reuse strict validation
    after the narrowly recognized legacy shape, including host and port checks.
    """
    try:
        return parse_target(kind, value)
    except ValueError:
        if (kind not in ('http', 'https') or not isinstance(value, str)
                or value != value.strip() or any(c.isspace() for c in value)
                or not re.fullmatch(r'(?:\[[^\[\]]+\]|[^:/?#]+)(?::[0-9]+)?(?:/.*)?', value)):
            raise
    return parse_target(kind, f'{kind}://{value}')
