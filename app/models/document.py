from datetime import datetime
from sqlalchemy import ForeignKey, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.models import Base, Mapped, mapped_column, UUID, uuid4


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(nullable=False)
    file_path: Mapped[str] = mapped_column(nullable=False)  # 纯逻辑路径，展示用
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 正文，进 DB
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 回收站标记
    frontmatter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_folder: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(default="private")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(default="draft")
    word_count: Mapped[int | None] = mapped_column(nullable=True)
    content_hash: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # updated_at 只代表「正文最后保存时间」——由 repo 显式赋值，不用 onupdate 魔法
    # （onupdate 会在草稿同步时也刷新它，导致编辑器手里的乐观锁令牌失效 → 保存必 409）
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 最近查看戳
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), nullable=True)

    # 草稿槽：每文档一格，覆写不追加。手动保存时清空。
    draft_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    draft_device: Mapped[str | None] = mapped_column(nullable=True)
