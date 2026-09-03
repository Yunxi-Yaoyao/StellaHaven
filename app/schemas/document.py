from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class DocumentCreate(BaseModel):
    title: str
    file_path: str
    workspace_id: UUID
    parent_id: UUID | None = None
    content: str | None = None  # 正文；传了服务端会自动算 content_hash
    frontmatter: dict | None = None
    is_folder: bool = False
    visibility: str = "private"
    is_pinned: bool = False
    is_favorite: bool = False
    status: str = "draft"
    word_count: int | None = None
    content_hash: str | None = None  # 兼容旧调用；有 content 时被服务端覆盖


class DocumentUpdate(BaseModel):
    updated_at: datetime
    title: str | None = None
    content: str | None = None  # 传了 → 服务端重算 content_hash
    content_hash: str | None = None
    frontmatter: dict | None = None
    is_folder: bool | None = None
    visibility: str | None = None
    is_pinned: bool | None = None
    is_favorite: bool | None = None
    status: str | None = None
    word_count: int | None = None
    parent_id: UUID | None = None


class DocumentListItem(BaseModel):
    """列表/树用摘要：不含正文。目录树只需要元数据，正文走 /documents/{id} 单篇取"""
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


class DocumentRead(DocumentListItem):
    """单篇详情 = 摘要 + 正文"""
    content: str | None = None  # 正文


class DraftRead(BaseModel):
    """草稿槽内容——只在「查看草稿」时单独取"""
    content: str
    updated_at: datetime
    device: str | None


