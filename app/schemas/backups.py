"""Frozen Backup Center HTTP types; no arbitrary configuration/content dictionary."""
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.backup_diagnostics import ReasonCode, FailedStage

Scope = Literal['settings', 'all']


class Config(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(default=0, ge=0)
    enabled: bool = False
    scope: Scope = 'settings'
    directory: str = Field(default='', max_length=4096)
    frequency: Literal['daily', 'weekly'] = 'daily'
    time: str = Field(default='03:00', pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone: str = 'Asia/Shanghai'
    weekday: int = Field(default=0, ge=0, le=6)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('unknown IANA timezone') from None
        return value

    @field_validator('directory')
    @classmethod
    def valid_directory(cls, value):
        if value and (not value.startswith('/') or value == '/' or '\\' in value or any(ord(c) < 32 for c in value)
                      or '..' in value.split('/') or str(PurePosixPath(value)) != value):
            raise ValueError('directory must be an exact absolute server path')
        return value


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=0)
    enabled: bool | None = None
    scope: Scope | None = None
    directory: str | None = None
    frequency: Literal['daily', 'weekly'] | None = None
    time: str | None = None
    timezone: str | None = None
    weekday: int | None = None


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    scope: Scope


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirm: str = Field(min_length=1, max_length=200)


class Job(BaseModel):
    id: str
    kind: Literal['backup', 'verify', 'restore']
    scope: Scope
    state: Literal['queued', 'running', 'succeeded', 'failed', 'interrupted']
    stage: str
    error: str | None = None
    record_id: str | None = None
    # Null means an older job has no trustworthy diagnostic; never infer one.
    reason_code: ReasonCode | None = None
    failed_stage: FailedStage | None = None


class Record(BaseModel):
    id: str
    filename: str
    scope: Scope
    created_at: str
    bytes: int
    sha256: str
    verified: bool


class Storage(BaseModel):
    node: str
    available: bool
    free_bytes: int | None
    error: str | None
    # Missing default is provisioned only by an explicit/due backup, never GET.
    can_initialize_default: bool = False


class Capabilities(BaseModel):
    settings_restore: bool = True
    full_restore: Literal['maintenance_cli'] = 'maintenance_cli'


class Status(BaseModel):
    config: Config
    records: list[Record]
    job: Job | None
    storage: Storage
    next_run: str | None
    capabilities: Capabilities


class Crop(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    cx: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    cy: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    w: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)
    h: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)


class HomePreferences(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    theme: Literal['daybreak', 'nightfall', 'classic'] = 'daybreak'
    particles: Literal['stars', 'motes', 'sakura', 'off'] = 'stars'
    bgImage: str = Field(default='', max_length=220)
    bgCrop: Crop = Field(default_factory=Crop)
    siteTitle: str = Field(default='StellaHaven', max_length=120)
    signature: str = Field(default='', max_length=512)
    meetDate: str = Field(default='2026-05-31', pattern=r'^\d{4}-\d{2}-\d{2}$')
    live2d: bool = True
    avatar: str = Field(default='/avatar.png', max_length=220)

    @field_validator('meetDate')
    @classmethod
    def valid_date(cls, value):
        from datetime import date
        date.fromisoformat(value)
        return value

    @field_validator('bgImage', 'avatar')
    @classmethod
    def media_url(cls, value, info):
        import re
        group = 'homebg' if info.field_name == 'bgImage' else 'avatars'
        if value == '' or (info.field_name == 'avatar' and value == '/avatar.png'):
            return value
        if '..' in value or not re.fullmatch(r'/assets/' + group + r'/[A-Za-z0-9][A-Za-z0-9_.-]*', value):
            raise ValueError('audited local configuration resource required')
        return value

    @field_validator('siteTitle', 'signature')
    @classmethod
    def plain_text(cls, value):
        if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
            raise ValueError('plain presentation text required')
        return value


class LayoutPreferences(BaseModel):
    """Nine audited presentation choices, never arbitrary localStorage or note data."""
    model_config = ConfigDict(extra='forbid', strict=True)
    backgroundQuality: Literal['original', 'compressed1', 'compressed2'] = 'compressed1'
    sidebarFold: bool = False
    serversFold: bool = False
    toolsOpen: bool = False
    worldMapCollapsed: bool = False
    monitorMode: Literal['chart', 'simple'] = 'chart'
    noteEditMode: Literal['rich', 'markdown'] = 'rich'
    listFold: bool = False
    driveBackground: Literal['solid', 'image'] = 'solid'


PaletteToken = Literal[
    'bg-base', 'bg-panel', 'bg-raised', 'bg-sidebar', 'text-hi', 'text-lo', 'text-faint',
    'accent', 'accent-dim', 'pink', 'warm', 'selected-bg', 'selected-border',
    'button-top', 'button-bottom', 'button-border', 'success', 'warning', 'danger',
    'control-border', 'control-bg', 'control-hover', 'metric-cpu', 'metric-memory', 'metric-disk',
    'metric-cpu-start', 'metric-memory-start', 'metric-disk-start',
]


class CustomAppearance(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: Literal[1]
    base: Literal['A', 'B']
    overrides: dict[PaletteToken, Annotated[str, Field(pattern=r'^#[0-9A-Fa-f]{6}$')]] = Field(max_length=28)

    @field_validator('version', mode='before')
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('unsupported custom palette version')
        return value

    @field_validator('overrides')
    @classmethod
    def hex_colors(cls, values):
        import re
        if any(not re.fullmatch(r'#[0-9A-Fa-f]{6}', value) for value in values.values()):
            raise ValueError('six digit opaque hex colors required')
        return {key: value.upper() for key, value in values.items()}


class AppearancePreferences(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    appearance: Literal['A', 'B', 'custom'] = 'A'
    customAppearance: CustomAppearance | None = None

    @model_validator(mode='after')
    def custom_requires_palette(self):
        if self.appearance == 'custom' and self.customAppearance is None:
            raise ValueError('custom appearance requires a palette')
        return self


class ClientPreferences(AppearancePreferences):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(default=0, ge=0)

    home: HomePreferences = Field(default_factory=HomePreferences)
    ui: LayoutPreferences = Field(default_factory=LayoutPreferences)


class ClientPreferencesWrite(AppearancePreferences):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=0)
    appearance: Literal['A', 'B', 'custom']
    home: HomePreferences
    ui: LayoutPreferences = Field(default_factory=LayoutPreferences)
