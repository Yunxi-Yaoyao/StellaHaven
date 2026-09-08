"""Opt-in administrator comparison only; never switches collectors or graphs."""
import ipaddress
import math
import socket
import time
from datetime import timezone
import httpx
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Node, NodeSysMetric
from app.services.prometheus_metrics import PrometheusMetrics, PrometheusError
from app.repositories import config as config_repo
from app.routers.auth import admin_user

router = APIRouter(tags=['prometheus'], dependencies=[Depends(admin_user)])
CONFIG_KEY = 'prometheus_connection'


def _safe_address(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast or address.is_reserved:
        raise ValueError('Loopback, metadata, and special-use destinations are not permitted')
    return str(address)


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job: str = Field(min_length=1, max_length=512)
    instance: str = Field(min_length=1, max_length=512)

    @field_validator('job', 'instance')
    @classmethod
    def label(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Nonempty labels without control characters required')
        return value


class PrometheusConnection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    url: str | None = Field(default=None, max_length=2048)
    nodes: dict[str, Target] = Field(default_factory=dict, max_length=256)

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        if value is None:
            return value
        p = urlsplit(value)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username is not None
                or p.password is not None or '?' in value or '#' in value
                or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value
                or '%' in value or any(s in ('.', '..') for s in p.path.split('/'))):
            raise ValueError('Safe HTTP(S) URL without credentials/query/fragment required')
        if p.port == 0:
            raise ValueError('Invalid port')
        host = p.hostname.lower().rstrip('.')
        if host in ('localhost', 'metadata', 'metadata.google.internal', 'instance-data') or host.endswith('.localhost'):
            raise ValueError('Localhost and metadata destinations are not permitted')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not all(c.isascii() and (c.isalnum() or c in '.-') for c in host):
                raise ValueError('Invalid hostname')
        else:
            _safe_address(host)
        return value

    @field_validator('nodes')
    @classmethod
    def valid_ids(cls, nodes):
        if any(not key.isascii() or not key.isdecimal() or key.startswith('0') or len(key) > 10 or int(key) > 2147483647 for key in nodes):
            raise ValueError('Node keys must be canonical positive integer IDs')
        return nodes

    @model_validator(mode='after')
    def opted_in(self):
        if self.enabled and (not self.url or not self.nodes):
            raise ValueError('Enabling requires URL and explicit node mappings')
        return self


def _load(db):
    raw = config_repo.get(db, CONFIG_KEY)
    if raw is None:
        return PrometheusConnection()
    try:
        return PrometheusConnection.model_validate_json(raw)
    except ValueError:
        raise HTTPException(409, 'Invalid stored Prometheus configuration') from None


@router.get('/config/prometheus', response_model=PrometheusConnection)
def get_connection(db: Session = Depends(get_db)):
    return _load(db)


@router.put('/config/prometheus', response_model=PrometheusConnection)
def put_connection(data: PrometheusConnection, db: Session = Depends(get_db)):
    ids = [int(key) for key in data.nodes]
    existing = {row[0] for row in db.query(Node.id).filter(Node.id.in_(ids), Node.status != 'removed').all()} if ids else set()
    if set(ids) != existing:
        raise HTTPException(422, 'All mappings must reference existing, non-removed nodes')
    config_repo.put(db, CONFIG_KEY, data.model_dump_json())
    return data


class PinnedTransport(httpx.BaseTransport):
    """Resolve once, reject unsafe answers, pin TCP IP but retain Host/TLS SNI.

    DNS names and explicit LAN IPs are allowed; redirects and env proxies are not.
    Validation plus a later unpinned connection would allow DNS rebinding.
    """
    def __init__(self, url):
        p = urlsplit(PrometheusConnection.safe_url(url))
        self.host = p.hostname
        self.port = p.port or (443 if p.scheme == 'https' else 80)
        answers = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        addresses = [_safe_address(answer[4][0]) for answer in answers]
        if not addresses:
            raise ValueError('No destination addresses')
        self.address = addresses[0]
        self.inner = httpx.HTTPTransport(retries=0, trust_env=False, limits=httpx.Limits(max_connections=2))

    def handle_request(self, request):
        if request.url.host != self.host or (request.url.port or (443 if request.url.scheme == 'https' else 80)) != self.port:
            raise ValueError('Unexpected upstream destination')
        pinned = httpx.Request(request.method, request.url.copy_with(host=self.address),
                               headers=request.headers, content=request.content,
                               extensions={**request.extensions, 'sni_hostname': self.host})
        return self.inner.handle_request(pinned)

    def close(self):
        self.inner.close()


def _timestamp(value):
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()


@router.get('/nodes/{node_id}/metrics-comparison')
def compare_metrics(node_id: int, db: Session = Depends(get_db)):
    """Synchronous route runs DB/DNS/adapter I/O in FastAPI's worker pool.

    Fixed eleven bounded adapter queries; no browser PromQL or range parameters.
    Merely reading does not persist configuration, observations, or status.
    """
    node = db.get(Node, node_id)
    if node is None or node.status == 'removed':
        raise HTTPException(404, 'Node not found')
    cfg = _load(db)
    if not cfg.enabled:
        raise HTTPException(409, 'Prometheus comparison is not enabled')
    target = cfg.nodes.get(str(node_id))
    if target is None:
        raise HTTPException(409, 'Node has no explicit Prometheus mapping')
    rows = db.query(NodeSysMetric).filter(NodeSysMetric.node_id == node_id).order_by(NodeSysMetric.ts.desc()).limit(2).all()
    latest = rows[0] if rows else None
    legacy = {
        'source': 'legacy',
        'latestSys': None if latest is None else {
            'timestamp': _timestamp(latest.ts), 'cpuPct': latest.cpu_pct,
            'memoryPct': latest.mem_pct, 'diskPct': latest.disk_pct,
        },
        'sysSampleSpacingSeconds': (_timestamp(rows[0].ts)-_timestamp(rows[1].ts)) if len(rows) == 2 else None,
        'expectedSysIntervalSeconds': 60, 'trafficIntervalSeconds': 5,
    }
    try:
        with PrometheusMetrics(cfg.url, allowed_targets={(target.job, target.instance)},
                               transport=PinnedTransport(cfg.url)) as adapter:
            snapshot = adapter.snapshot(target.job, target.instance)
            spacing = adapter.sample_spacing(target.job, target.instance)
    except (PrometheusError, httpx.HTTPError, OSError, ValueError, KeyError, TypeError, IndexError):
        raise HTTPException(502, 'Prometheus comparison unavailable; check connection and upstream response') from None
    intervals = spacing['spacingSeconds']
    cadence_matches = bool(intervals) and all(math.isfinite(v) and v == 5 for v in intervals)
    reason = ('insufficient_raw_samples' if not intervals else
              'sample_spacing_not_5s' if not cadence_matches else
              'prometheus_not_fresh' if snapshot.get('freshness') != 'up' else
              'rate_window_and_metric_semantics_differ')
    return {
        'nodeId': node_id, 'comparedAt': time.time(), 'legacy': legacy,
        'prometheus': {'snapshot': snapshot, 'sampleSpacing': spacing},
        'equivalence': {'status': 'not_equivalent', 'reason': reason,
                        'requiredSpacingSeconds': 5, 'cadenceMatches': cadence_matches,
                        'note': 'Raw up scrape cadence only; Prometheus rates use a 1m window, legacy traffic uses 5s deltas and system metrics nominally 60s. No graph/source switch.'},
    }
