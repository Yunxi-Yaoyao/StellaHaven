"""Closed, bounded native navigation contract. Array order is authoritative."""
from typing import Literal
from uuid import UUID
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import re

class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')

Color = str

def color(v):
    if v is not None and not re.fullmatch(r'#(?:[\da-fA-F]{3}|[\da-fA-F]{4}|[\da-fA-F]{6}|[\da-fA-F]{8})',v):
        raise ValueError('颜色必须是三、四、六或八位十六进制值')
    return v

def media_url(v):
    if not v: return v
    if re.fullmatch(r'/nav-assets/[0-9a-f-]{36}',v): return v
    if re.fullmatch(r'/assets/homebg/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,200}',v) and '..' not in v: return v
    if v=='/assets/default-background.webp': return v
    p = urlsplit(v)
    if p.scheme not in {'https','http'} or not p.hostname or p.username is not None or p.password is not None or '\\' in v or any(ord(c)<33 or ord(c)==127 for c in v):
        raise ValueError('需要不含凭据的完整 http/https 地址或本账号素材')
    _ = p.port
    return v

class Style(Closed):
    layout: Literal['icon','info'] | None = None
    textColor: str | None = None
    hideTitle: bool | None = Field(None, strict=True)
    hideDescription: bool | None = Field(None, strict=True)
    _color = field_validator('textColor')(color)

class Icon(Closed):
    itemType: Literal[1,2,3] = 2
    src: str = Field('',max_length=2048)
    text: str = Field('',max_length=24)
    backgroundColor: str | None = None
    _src = field_validator('src')(media_url)
    _color = field_validator('backgroundColor')(color)

class Card(Closed):
    id: UUID
    title: str = Field(min_length=1,max_length=120)
    url: str = Field('',max_length=2048)
    lanUrl: str = Field('',max_length=2048)
    description: str = Field('',max_length=2000)
    icon: Icon | None = None
    openMethod: Literal[1,2] = 2  # 1 current tab, 2 new tab; legacy iframe explicitly flagged in preview
    module_id: str | None = Field(None,max_length=80)
    _urls = field_validator('url','lanUrl')(media_url)
    @model_validator(mode='after')
    def destination(self):
        if not (self.url or self.lanUrl or self.module_id): raise ValueError('网站需要目标地址')
        if self.module_id and not re.fullmatch(r'[a-zA-Z0-9_-]+',self.module_id): raise ValueError('模块引用无效')
        return self

class Group(Closed):
    id: UUID
    title: str = Field(min_length=1,max_length=100)
    description: str = Field('',max_length=500)
    icon: str = Field('',max_length=24)
    style: Style | None = None
    items: list[Card] = Field(default_factory=list,max_length=500)

class Engine(Closed):
    id: UUID
    title: str = Field(min_length=1,max_length=40)
    url: str = Field(min_length=1,max_length=2048)
    icon: str = Field('',max_length=2048)
    _icon = field_validator('icon')(media_url)
    @field_validator('url')
    @classmethod
    def template(cls,v):
        if '{query}' not in v: raise ValueError('引擎地址需要 {query} 占位')
        return media_url(v)

class Preferences(Closed):
    layout: Literal['icon','info'] = 'icon'
    textColor: str | None = None
    hideTitle: bool = Field(False,strict=True)
    hideDescription: bool = Field(False,strict=True)
    title: str = Field('导航',max_length=100)
    titleImage: str = Field('',max_length=2048)
    showTitle: bool = Field(False,strict=True)
    clock: bool = Field(False,strict=True)
    seconds: bool = Field(False,strict=True)
    clockColor: str | None = None
    search: bool = Field(True,strict=True)
    searchIcons: bool = Field(True,strict=True)
    searchBackground: str | None = None
    searchBorder: str | None = None
    searchText: str | None = None
    engines: list[Engine] = Field(default_factory=list,max_length=20)
    defaultEngine: UUID | None = None
    newWindowOpen: bool = Field(True,strict=True)
    background: Literal['none','home','custom'] = 'none'
    backgroundUrl: str = Field('',max_length=2048)
    blur: int = Field(0,ge=0,le=30,strict=True)
    mask: float = Field(0.35,ge=0,le=1)
    width: int = Field(1400,ge=1,le=2400,strict=True)
    widthUnit: Literal['px','%'] = 'px'
    marginX: int = Field(0,ge=0,le=200,strict=True)
    marginTop: float = Field(0,ge=0,le=100)
    marginBottom: float = Field(0,ge=0,le=100)
    gap: int = Field(16,ge=4,le=40,strict=True)
    padding: int = Field(24,ge=8,le=80,strict=True)
    networkButton: bool = Field(True,strict=True)
    _colors = field_validator('textColor','clockColor','searchBackground','searchBorder','searchText')(color)
    _media = field_validator('backgroundUrl','titleImage')(media_url)
    @model_validator(mode='after')
    def ranges(self):
        if self.widthUnit=='%' and self.width>100: raise ValueError('百分比宽度不能超过100')
        if self.defaultEngine is not None and self.defaultEngine not in {e.id for e in self.engines}: raise ValueError('默认引擎不存在')
        return self

class NavData(Closed):
    groups: list[Group] = Field(default_factory=list,max_length=100)
    preferences: Preferences = Field(default_factory=Preferences)
    @model_validator(mode='after')
    def unique(self):
        ids=[str(g.id) for g in self.groups]+[str(i.id) for g in self.groups for i in g.items]+[str(e.id) for e in self.preferences.engines]
        if len(ids)!=len(set(ids)) or sum(len(g.items) for g in self.groups)>2000: raise ValueError('标识重复或超过网站数量上限')
        return self

class Write(Closed):
    revision: int = Field(ge=0,strict=True)
    mutation_id: UUID
    data: NavData
