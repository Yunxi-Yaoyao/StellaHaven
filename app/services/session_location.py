"""Opt-in stored-IP lookup: public IP is disclosed only to fixed ipinfo.io.

Call with await, after releasing the DB transaction. Two-second cooperative
async cancellation covers client/stream cleanup, not an OS-level DNS deadline.
No background tasks; a bounded admission set limits concurrent outbound work.
"""
import asyncio
from collections import OrderedDict
from ipaddress import ip_address
import json
from threading import Lock
from time import monotonic

import httpx

_cache = OrderedDict()
_inflight = set()
_lock = Lock()
TTL = 3600
MAX_ENTRIES = 512
MAX_INFLIGHT = 16


async def lookup_location(value: str) -> str | None:
    try:
        addr = ip_address(value)
    except ValueError:
        return None
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return '局域网'
    if not addr.is_global:
        return None
    ip = str(addr)
    # Only short state operations under the lock; never hold it over await.
    with _lock:
        cached = _cache.get(ip)
        if cached and cached[0] > monotonic():
            _cache.move_to_end(ip)
            return cached[1]
        # Duplicate/overload callers fail closed without creating waiter tasks
        # or poisoning the result of an already admitted lookup.
        if ip in _inflight or len(_inflight) >= MAX_INFLIGHT:
            return None
        _inflight.add(ip)
    location = None
    try:
        try:
            async with asyncio.timeout(2.0):
                async with httpx.AsyncClient(timeout=2.0, follow_redirects=False,
                                             trust_env=False) as client:
                    async with client.stream('GET', f'https://ipinfo.io/{ip}/json') as response:
                        if response.status_code == 200:
                            raw = bytearray()
                            async for chunk in response.aiter_bytes():
                                if len(raw) + len(chunk) > 8192:
                                    break
                                raw.extend(chunk)
                            else:
                                data = json.loads(raw)
                                if isinstance(data, dict):
                                    parts = [data.get(k) for k in ('country', 'region', 'city')]
                                    parts = list(dict.fromkeys(p.strip()[:80] for p in parts
                                                              if isinstance(p, str) and p.strip()))
                                    location = ' · '.join(parts) or None
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
            location = None
        with _lock:
            _cache[ip] = (monotonic() + TTL, location)
            _cache.move_to_end(ip)
            while len(_cache) > MAX_ENTRIES:
                _cache.popitem(last=False)
        return location
    finally:
        # External cancellation propagates; no orphan task or stuck admission.
        with _lock:
            _inflight.discard(ip)
