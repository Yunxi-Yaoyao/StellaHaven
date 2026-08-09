from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class DocumentCreate(BaseModel):
    title: str
    file_path: str
    workspace_id: UUID
    parent_id: UUID | None = None
    frontmatter: dict | None = None
    is_folder: bool = False
    visibility: str = "private"
    is_pinned: bool = False
    is_favorite: bool = False
    status: str = "draft"
    word_count: int | None = None
    content_hash: str


class DocumentUpdate(BaseModel):
    updated_at: datetime
    title: str | None = None
    content_hash: str | None = None
    frontmatter: dict | None = None
    is_folder: bool | None = None
    visibility: str | None = None
    is_pinned: bool | None = None
    is_favorite: bool | None = None
    status: str | None = None
    word_count: int | None = None
    parent_id: UUID | None = None


class DocumentRead(BaseModel):
    id: UUID
    title: str
    file_path: str
    workspace_id: UUID
    parent_id: UUID | None
    frontmatter: dict | None
    is_folder: bool
    visibility: str
    is_pinned: bool
    is_favorite: bool
    status: str
    word_count: int | None
    content_hash: str
    created_at: datetime
    updated_at: datetime
    # 草稿元信息（内容不随文档返回，要看走 /documents/{id}/draft）
    draft_updated_at: datetime | None = None
    draft_device: str | None = None
    has_draft: bool = False  # 由 router 按 10 分钟惰性规则算好挂上去

    model_config = {"from_attributes": True}


class DraftRead(BaseModel):
    """草稿槽内容——只在「查看草稿」时单独取"""
    content: str
    updated_at: datetime
    device: str | None


