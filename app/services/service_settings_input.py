"""Frozen service editor input: no upstream identity/registry fields accepted."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services import external_services as external
from app.services.integrations import ICONS
from app.services.integrations_injection import InjectionInput


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class GalleryConnection(StrictInput):
    browser_url: str
    upstream_url: str = ''
    alternate_browser_url: str = ''
    auth_mode: Literal['manual', 'oidc'] = 'manual'

    @field_validator('browser_url', 'upstream_url', 'alternate_browser_url')
    @classmethod
    def url(cls, value, info):
        return external.validate_url(value) if value or info.field_name == 'browser_url' else ''

    def as_connection(self):
        return external.Connection(**self.model_dump(), use_proxy=False)


class DriveAppearance(StrictInput):
    theme: Literal['stella', 'original']
    simplified: bool = Field(strict=True)


class GalleryAppearance(StrictInput):
    logo: Literal['stella', 'original']


class CustomInput(InjectionInput):
    csp_policy: Literal['reject'] = 'reject'


class SettingsInput(StrictInput):
    name: str = Field(min_length=1, max_length=100)
    icon: str
    visible: bool = Field(strict=True)
    connection: dict = Field(repr=False)
    appearance: dict
    custom: CustomInput | None = None

    @field_validator('name')
    @classmethod
    def name_valid(cls, value):
        if not value.strip(): raise ValueError('名称不可为空白')
        return value

    @field_validator('icon')
    @classmethod
    def icon_valid(cls, value):
        if value not in ICONS: raise ValueError('不支持的图标')
        return value


def connection_input(site, value):
    model = external.DriveConnection if site == 'drive' else GalleryConnection
    return model.model_validate(value).as_connection()
