"""Closed, secret-free report channel DTOs; install credentials stay separate."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ChannelEntry(Closed):
    entry_id: Literal['public','private']
    origin: str = Field(max_length=256)

class ChannelWrite(Closed):
    revision: int = Field(ge=0, strict=True)
    node_ids: list[StrictInt] = Field(min_length=1, max_length=500)
    mode: Literal['default','fixed','auto']
    entry_id: Literal['public','private'] | None = None

    @model_validator(mode='after')
    def valid_selection(self):
        if any(type(n) is not int or n < 1 for n in self.node_ids) or len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError('节点选择必须唯一且有效')
        if (self.mode == 'fixed') != (self.entry_id is not None):
            raise ValueError('仅固定策略需要入口')
        return self

class ChannelConfig(Closed):
    revision: int = Field(ge=0)
    epoch: str = Field(max_length=64)
    nonce: str = Field(pattern=r'^[a-f0-9]{64}$')
    center_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    token_binding: str = Field(pattern=r'^[a-f0-9]{64}$')
    node_id: int
    mode: Literal['default','fixed','auto']
    selected_entry_id: Literal['public','private']
    entries: list[ChannelEntry] = Field(min_length=1, max_length=2)

class ChannelReceipt(Closed):
    revision: int = Field(ge=0)
    epoch: str = Field(max_length=64)
    nonce: str = Field(pattern=r'^[a-f0-9]{64}$')
    origin: str = Field(max_length=256)
    center_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    sequence: int = Field(ge=1, strict=True)
    state: Literal['applied','failed']
    error: Literal['probe_failed','invalid_config'] | None = None

class ChannelProbe(Closed):
    center_id: str
    node_id: int
    token_binding: str
    origin: str

class ChannelReportAck(Closed):
    ok: Literal[True]
    node_id: int
    status: str
    monitors_version: int
    channel_revision: int

class ChannelNode(Closed):
    node_id: int
    name: str
    mode: Literal['default','fixed','auto']
    entry_id: Literal['public','private'] | None
    revision: int
    state: Literal['pending','applied','failed']
    actual_origin: str | None = None
    http_ms: float | None = None
    http_origin: str | None = None
    http_status: Literal['ok','error'] | None = None
    sampled_at: datetime | None = None
    error: Literal['probe_failed','invalid_config'] | None = None
    online: bool

class ChannelRead(Closed):
    revision: int
    default_entry_id: Literal['public'] = 'public'
    entries: list[ChannelEntry]
    nodes: list[ChannelNode]
