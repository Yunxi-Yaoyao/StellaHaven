"""Bounded management telemetry; never arbitrary agent JSON in public output."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ReportTransaction(Record):
    entry_id: Literal['public','private'] | None = None
    origin: str = Field(max_length=300)
    duration_ms: float = Field(ge=0, le=120000)
    status: Literal['ok','error']
    http_status: int | None = Field(default=None, ge=100, le=599)
    error: Literal['http','timeout','transport','invalid_response'] | None = None
    sampled_at: AwareDatetime

    @model_validator(mode='after')
    def coherent(self):
        from urllib.parse import urlsplit
        p = urlsplit(self.origin)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):
            raise ValueError('exact control origin required')
        if self.status == 'ok' and (self.error is not None or self.http_status is None or not 200 <= self.http_status < 300):
            raise ValueError('inconsistent success')
        if self.status == 'error' and self.error is None:
            raise ValueError('missing error class')
        return self


class EntryIPSample(Record):
    ip: str = Field(max_length=64)
    family: Literal[4,6]
    status: Literal['up','down','unavailable']
    latency_ms: float | None = Field(default=None, ge=0, le=60000)
    loss_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode='after')
    def numeric(self):
        import ipaddress
        if ipaddress.ip_address(self.ip).version != self.family:
            raise ValueError('family mismatch')
        if self.status == 'up' and (self.latency_ms is None or self.loss_pct is None or self.loss_pct >= 100):
            raise ValueError('success requires actual measurement')
        return self


class EntrySample(Record):
    entry_id: Literal['public','private']
    version: str = Field(pattern=r'^[0-9a-f]{24}$')
    hostname: str = Field(min_length=1,max_length=253)
    sampled_at: AwareDatetime
    status: Literal['complete','dns_error','dns_timeout','outside_scope','too_many_ips','budget_exceeded','unavailable']
    results: list[EntryIPSample] = Field(default_factory=list, max_length=4)


class ControlChannel(Record):
    report: ReportTransaction | None = None
    icmp: list[EntrySample] = Field(default_factory=list, max_length=4)


class EntryDefinition(Record):
    entry_id: Literal['public','private']
    origin: str
    hostname: str
    version: str


class EntryManifest(Record):
    icmp_available: bool = False
    entries: list[EntryDefinition] = Field(default_factory=list,max_length=4)
    interval: Literal[60] = 60
    max_ips: Literal[4] = 4
    deadline_seconds: Literal[12] = 12
    # Internal None denotes truly absent targets. Omit it on the wire so the
    # Agent can reject explicit raw null without losing public-scope compatibility.
    targets: list[str] | None = Field(default=None, exclude_if=lambda value: value is None)
    approved_ranges: list[str] = Field(default_factory=list)
