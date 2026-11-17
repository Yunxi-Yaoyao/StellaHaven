"""Versioned, bounded metadata protocol; file bytes use raw HTTP streams."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class FileRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    protocol: Literal[1] = 1
    request_key: UUID
    node_id: int = Field(gt=0)
    root: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    op: Literal['list', 'preview', 'download', 'upload', 'edit', 'create', 'mkdir', 'rename', 'copy', 'move']
    path: str = Field(default='', max_length=4096)
    hidden: bool = False
    sort: Literal['name', 'size', 'mtime'] = 'name'
    descending: bool = False
    limit: int = Field(default=2000, ge=1, le=2000)

    destination: str | None = Field(default=None, max_length=4096)
    etag: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    size: int | None = Field(default=None, ge=0, le=32 * 1024 * 1024)
    sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def operation_fields(self):
        if self.op != 'list' and not self.path:
            raise ValueError('path_required')
        if self.op in ('rename', 'copy', 'move'):
            if not self.destination:
                raise ValueError('destination_required')
            self.safe_path(self.destination)
        elif self.destination is not None:
            raise ValueError('unexpected_destination')
        if self.op in ('upload', 'edit'):
            if self.size is None or self.sha256 is None:
                raise ValueError('manifest_required')
            if self.op == 'edit' and (self.etag is None or self.size > 256 * 1024):
                raise ValueError('edit_manifest_invalid')
        elif any(x is not None for x in (self.size, self.sha256, self.etag)):
            raise ValueError('unexpected_manifest')
        return self

    @field_validator('path')
    @classmethod
    def safe_path(cls, value):
        if value and (any(x in ('', '.', '..') or len(x.encode()) > 255 for x in value.split('/')) or len(value.split('/')) > 64):
            raise ValueError('invalid_path')
        if '\\' in value or '\x00' in value:
            raise ValueError('invalid_path')
        return value

class StrictAgentConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('enabled', 'write', mode='before', check_fields=False)
    @classmethod
    def strict_boolean(cls, value):
        # Literal[True/False] alone accepts integer 1/0 in Pydantic.
        if type(value) is not bool:
            raise ValueError('boolean_required')
        return value


class AgentSystemRoot(StrictAgentConfig):
    path: Literal['/']
    write: Literal[True]


class AgentSystemRoots(BaseModel):
    model_config = ConfigDict(extra='forbid')
    system: AgentSystemRoot


class AgentEmptyRoots(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AgentFilesEnabled(StrictAgentConfig):
    enabled: Literal[True]
    roots: AgentSystemRoots
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')


class AgentFilesDisabled(StrictAgentConfig):
    enabled: Literal[False]
    roots: AgentEmptyRoots
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')


AgentFilesConfig = AgentFilesEnabled | AgentFilesDisabled


class AgentHello(BaseModel):
    model_config = ConfigDict(extra='forbid')
    protocol: Literal[1] = 1
    roots: dict[str, bool] = Field(default_factory=dict, max_length=32)

class FileResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lease: str = Field(min_length=32, max_length=64)
    result: dict = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=64)
