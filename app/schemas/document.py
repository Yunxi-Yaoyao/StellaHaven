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

    model_config = {"from_attributes": True}


