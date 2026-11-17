"""Owner-selected roles, CAS updates and safe per-target pause."""
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from typing import Literal

class NodeMonitoringPolicyWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0, strict=True)
    enabled: StrictBool
    source_node_id: int | None = Field(default=None, ge=1, strict=True)
    host_node_id: int | None = Field(default=None, ge=1, strict=True)
    interval: int = Field(default=60, ge=60, le=3600, strict=True)

class NodeMonitoringPause(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suppressed: StrictBool

class ManagedNodeMonitor(BaseModel):
    target_node_id: int
    source_node_id: int
    monitor_id: int
    suppressed: bool
    exists: bool
    paused: bool

class DeferredNodeMonitor(BaseModel):
    node_id: int
    reason: str

class NodeMonitoringPolicyRead(NodeMonitoringPolicyWrite):
    managed: list[ManagedNodeMonitor]
    pending: list[DeferredNodeMonitor]
    source_ready: bool
    source_scope: list[str] | None
    source_test_targets: list['ProbeTestTarget'] = Field(default_factory=list)

class ProbeTestTarget(BaseModel):
    type: Literal['ping', 'tcp']
    target: str = Field(min_length=1, max_length=256)
    description: str = Field(max_length=128)
